#!/usr/bin/env python3
"""
Daily Parlay Generator

Production script to:
1. Fetch today's odds from Odds API
2. Enrich with pipeline predictions
3. Calculate edges and apply filters
4. Generate parlay recommendations
5. Store in database

Run daily before games start.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import json
import uuid
from datetime import datetime, date
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, asdict
from collections import defaultdict

from nhl_sgp_engine.providers.odds_api_client import OddsAPIClient
from nhl_sgp_engine.providers.pipeline_adapter import PipelineAdapter
from nhl_sgp_engine.database.sgp_db_manager import NHLSGPDBManager
from nhl_sgp_engine.edge_detection.edge_calculator import EdgeCalculator
from nhl_sgp_engine.config.settings import DATA_DIR


# NHL Team name to abbreviation mapping
NHL_TEAM_ABBREVS = {
    'Anaheim Ducks': 'ANA',
    'Arizona Coyotes': 'ARI',
    'Boston Bruins': 'BOS',
    'Buffalo Sabres': 'BUF',
    'Calgary Flames': 'CGY',
    'Carolina Hurricanes': 'CAR',
    'Chicago Blackhawks': 'CHI',
    'Colorado Avalanche': 'COL',
    'Columbus Blue Jackets': 'CBJ',
    'Dallas Stars': 'DAL',
    'Detroit Red Wings': 'DET',
    'Edmonton Oilers': 'EDM',
    'Florida Panthers': 'FLA',
    'Los Angeles Kings': 'LAK',
    'Minnesota Wild': 'MIN',
    'Montréal Canadiens': 'MTL',
    'Montreal Canadiens': 'MTL',
    'Nashville Predators': 'NSH',
    'New Jersey Devils': 'NJD',
    'New York Islanders': 'NYI',
    'New York Rangers': 'NYR',
    'Ottawa Senators': 'OTT',
    'Philadelphia Flyers': 'PHI',
    'Pittsburgh Penguins': 'PIT',
    'San Jose Sharks': 'SJS',
    'Seattle Kraken': 'SEA',
    'St. Louis Blues': 'STL',
    'Tampa Bay Lightning': 'TBL',
    'Toronto Maple Leafs': 'TOR',
    'Utah Hockey Club': 'UTA',
    'Utah Mammoth': 'UTA',
    'Vancouver Canucks': 'VAN',
    'Vegas Golden Knights': 'VGK',
    'Washington Capitals': 'WSH',
    'Winnipeg Jets': 'WPG',
}


def get_team_abbrev(team_name: str) -> str:
    """Convert full team name to 3-letter abbreviation."""
    return NHL_TEAM_ABBREVS.get(team_name, team_name[:3].upper())


@dataclass
class QualifiedProp:
    """A prop that passed production filters."""
    player_name: str
    player_id: int
    team: str
    position: str
    stat_type: str
    line: float
    direction: str
    odds: int
    edge_pct: float
    confidence: float
    model_probability: float
    market_probability: float
    primary_reason: str
    supporting_reasons: List[str]
    risk_factors: List[str]
    signals: Dict

    # Pipeline context
    pipeline_score: float
    pipeline_rank: int
    is_scoreable: bool
    line_number: Optional[int]
    pp_unit: Optional[int]

    # Game context
    game_id: str
    opponent: str
    is_home: bool


def should_surface_prop(
    edge_pct: float,
    stat_type: str,
    is_scoreable: bool,
    pipeline_rank: int,
) -> Tuple[bool, str]:
    """
    Apply production filters based on validated backtest results.

    Returns:
        Tuple of (passes_filter, reason)
    """
    # Filter 1: Points only (58.9% vs 7.4% for goals)
    if stat_type != 'points':
        return False, f"stat_type={stat_type} (only points validated)"

    # Filter 2: 5-8% edge bucket (58.9% hit rate, +9.0% ROI)
    if edge_pct < 5.0:
        return False, f"edge={edge_pct:.1f}% (below 5% minimum)"
    if edge_pct > 8.0:
        return False, f"edge={edge_pct:.1f}% (above 8% - lower hit rate)"

    # Filter 3: Scoreable players (58.4% vs 37.8%)
    if not is_scoreable:
        return False, "not scoreable (37.8% hit rate)"

    # Filter 4: Rank 11-50 (68.6% for 11-25, 56.5% for 26-50)
    # AVOID Top 10 (34.6% - market prices correctly)
    if pipeline_rank is None:
        return False, "no pipeline rank"
    if pipeline_rank <= 10:
        return False, f"rank={pipeline_rank} (top 10 overvalued by market)"
    if pipeline_rank > 50:
        return False, f"rank={pipeline_rank} (below rank 50 threshold)"

    return True, "passes all filters"


def calculate_parlay_odds(legs: List[QualifiedProp]) -> int:
    """Calculate combined American odds for a parlay."""
    if not legs:
        return 0

    combined_prob = 1.0
    for leg in legs:
        # Convert American odds to probability
        if leg.odds > 0:
            prob = 100 / (leg.odds + 100)
        else:
            prob = abs(leg.odds) / (abs(leg.odds) + 100)
        combined_prob *= prob

    # Convert back to American odds
    if combined_prob >= 0.5:
        return int(-100 * combined_prob / (1 - combined_prob))
    else:
        return int(100 * (1 - combined_prob) / combined_prob)


def generate_thesis(legs: List[QualifiedProp], game_context: Dict) -> str:
    """Generate narrative thesis for a parlay."""
    if not legs:
        return ""

    # Get common themes
    reasons = [leg.primary_reason for leg in legs]
    avg_edge = sum(leg.edge_pct for leg in legs) / len(legs)
    avg_rank = sum(leg.pipeline_rank for leg in legs) / len(legs)

    home_team = game_context.get('home_team', '')
    away_team = game_context.get('away_team', '')

    thesis_parts = [
        f"Pipeline-ranked players (avg rank {avg_rank:.0f}) with 5-8% edge.",
        f"Average edge: {avg_edge:.1f}%.",
    ]

    # Add specific player insights
    for leg in legs[:2]:
        thesis_parts.append(f"{leg.player_name}: {leg.primary_reason}")

    return " ".join(thesis_parts)


def generate_daily_parlays(
    game_date: date = None,
    dry_run: bool = False,
    max_legs_per_parlay: int = 3,
):
    """
    Generate parlay recommendations for a specific date.

    Args:
        game_date: Date to generate for (default: today)
        dry_run: If True, don't save to database
        max_legs_per_parlay: Maximum legs per parlay
    """
    game_date = game_date or date.today()
    date_str = game_date.strftime('%Y-%m-%d')

    print(f"\n{'='*70}")
    print(f"NHL SGP ENGINE - DAILY PARLAY GENERATOR")
    print(f"{'='*70}")
    print(f"Date: {date_str}")
    print(f"Dry run: {dry_run}")
    print(f"{'='*70}\n")

    # Initialize components
    odds_client = OddsAPIClient()
    pipeline = PipelineAdapter()
    calculator = EdgeCalculator()
    sgp_db = NHLSGPDBManager()

    # Get pipeline predictions for today
    predictions = pipeline.get_predictions_for_date(game_date)
    if not predictions:
        print(f"No pipeline predictions for {date_str}")
        return

    print(f"Found {len(predictions)} pipeline predictions")

    # Get today's events from Odds API
    print(f"\nFetching odds from Odds API...")
    try:
        events = odds_client.get_current_events()
    except Exception as e:
        print(f"Error fetching events: {e}")
        return

    if not events:
        print("No events found")
        return

    print(f"Found {len(events)} events")

    # Process each game
    all_qualified_props: Dict[str, List[QualifiedProp]] = defaultdict(list)
    rejected_stats = defaultdict(int)

    for event in events:
        event_id = event.get('id')
        home_team = event.get('home_team', '')
        away_team = event.get('away_team', '')

        print(f"\n--- {away_team} @ {home_team} ---")

        # Fetch player props for this event
        try:
            event_odds = odds_client.get_event_odds(event_id, markets=['player_points'])
            props = odds_client.parse_player_props(event_odds, market_keys=['player_points'])
        except Exception as e:
            print(f"  Error fetching props: {e}")
            continue

        if not props:
            print(f"  No player props found")
            continue

        print(f"  Found {len(props)} player props")

        # Evaluate each prop
        for prop in props:
            player_name = prop.player_name
            stat_type = prop.stat_type
            line = prop.line

            # Get pipeline context
            ctx = pipeline.enrich_prop_context(
                player_name=player_name,
                stat_type=stat_type,
                line=line,
                game_date=game_date,
                event_id=event_id,
            )

            # Skip if no pipeline context
            if ctx.pipeline_score is None:
                rejected_stats['no_pipeline_context'] += 1
                continue

            # Calculate edge
            over_odds = prop.over_price or -110
            under_odds = prop.under_price or -110

            edge_result = calculator.calculate_edge(ctx, over_odds, under_odds)

            # Get scoreable status
            pred_ctx = pipeline.get_prediction_context(player_name, game_date)
            is_scoreable = pred_ctx.get('is_scoreable', False) if pred_ctx else False
            pipeline_rank = ctx.pipeline_rank or 999

            # Apply production filters
            passes, reason = should_surface_prop(
                edge_pct=edge_result.edge_pct,
                stat_type=stat_type,
                is_scoreable=is_scoreable,
                pipeline_rank=pipeline_rank,
            )

            if not passes:
                # Group rejections by category for cleaner summary
                if 'edge=' in reason:
                    if 'below 5%' in reason:
                        rejected_stats['edge below 5%'] += 1
                    elif 'above 8%' in reason:
                        rejected_stats['edge above 8%'] += 1
                    else:
                        rejected_stats['edge out of range'] += 1
                elif 'rank=' in reason:
                    if 'top 10' in reason:
                        rejected_stats['rank 1-10 (market prices correctly)'] += 1
                    elif 'below rank 50' in reason:
                        rejected_stats['rank 51+ (low priority)'] += 1
                    else:
                        rejected_stats['rank out of range'] += 1
                else:
                    rejected_stats[reason.split('(')[0].strip()] += 1
                continue

            # Create qualified prop
            qualified = QualifiedProp(
                player_name=player_name,
                player_id=ctx.player_id,
                team=ctx.team,
                position=ctx.position,
                stat_type=stat_type,
                line=line,
                direction=edge_result.direction,
                odds=over_odds if edge_result.direction == 'over' else under_odds,
                edge_pct=edge_result.edge_pct,
                confidence=edge_result.confidence,
                model_probability=edge_result.model_probability,
                market_probability=edge_result.market_probability,
                primary_reason=edge_result.primary_reason,
                supporting_reasons=edge_result.supporting_reasons,
                risk_factors=edge_result.risk_factors,
                signals=edge_result.signals,
                pipeline_score=float(ctx.pipeline_score),
                pipeline_rank=pipeline_rank,
                is_scoreable=is_scoreable,
                line_number=ctx.line_number,
                pp_unit=ctx.pp_unit,
                game_id=event_id,
                opponent=ctx.opponent,
                is_home=ctx.is_home,
            )

            game_key = f"{away_team}@{home_team}"

            # Deduplicate by player + stat_type + line + direction (multiple bookmakers)
            prop_key = f"{player_name}_{stat_type}_{line}_{edge_result.direction}"
            existing = next(
                (p for p in all_qualified_props[game_key]
                 if f"{p.player_name}_{p.stat_type}_{p.line}_{p.direction}" == prop_key),
                None
            )

            if existing:
                # Keep prop with better odds
                if qualified.odds > existing.odds:
                    all_qualified_props[game_key].remove(existing)
                    all_qualified_props[game_key].append(qualified)
            else:
                all_qualified_props[game_key].append(qualified)
                print(f"  ✓ {player_name} {stat_type} {edge_result.direction.upper()} {line} | "
                      f"Edge: {edge_result.edge_pct:.1f}% | Rank: {pipeline_rank}")

    # Summary of rejections
    print(f"\n--- Filter Summary ---")
    for reason, count in sorted(rejected_stats.items(), key=lambda x: -x[1]):
        print(f"  {reason}: {count}")

    # Build parlays
    print(f"\n{'='*70}")
    print("PARLAY RECOMMENDATIONS")
    print(f"{'='*70}")

    parlays_generated = []

    for game_key, props in all_qualified_props.items():
        if not props:
            continue

        # Sort by pipeline rank (lower = better)
        props.sort(key=lambda x: x.pipeline_rank)

        # Take top props for parlay
        parlay_legs = props[:max_legs_per_parlay]

        if len(parlay_legs) < 2:
            print(f"\n{game_key}: Only {len(parlay_legs)} qualifying prop(s), skipping parlay")
            continue

        # Calculate combined odds
        combined_odds = calculate_parlay_odds(parlay_legs)
        implied_prob = 1 / (1 + combined_odds/100) if combined_odds > 0 else abs(combined_odds) / (abs(combined_odds) + 100)

        # Generate thesis
        away, home = game_key.split('@')
        thesis = generate_thesis(parlay_legs, {'home_team': home, 'away_team': away})

        print(f"\n{game_key} - PRIMARY PARLAY")
        print(f"  Combined odds: +{combined_odds}" if combined_odds > 0 else f"  Combined odds: {combined_odds}")
        print(f"  Legs:")
        for i, leg in enumerate(parlay_legs, 1):
            print(f"    {i}. {leg.player_name} points {leg.direction.upper()} {leg.line}")
            print(f"       Edge: {leg.edge_pct:.1f}% | Rank: {leg.pipeline_rank} | {leg.primary_reason[:50]}...")
        print(f"  Thesis: {thesis[:100]}...")

        # Prepare parlay record
        parlay_record = {
            'id': uuid.uuid4(),
            'parlay_type': 'primary',
            'game_id': parlay_legs[0].game_id,
            'game_date': game_date,
            'home_team': get_team_abbrev(home.strip()),
            'away_team': get_team_abbrev(away.strip()),
            'game_slot': 'EVENING',  # Default
            'total_legs': len(parlay_legs),
            'combined_odds': combined_odds,
            'implied_probability': implied_prob,
            'thesis': thesis,
            'season': 2025,
            'season_type': 'regular',
        }

        leg_records = []
        for i, leg in enumerate(parlay_legs, 1):
            leg_records.append({
                'leg_number': i,
                'player_name': leg.player_name,
                'player_id': leg.player_id,
                'team': leg.team,
                'position': leg.position,
                'stat_type': leg.stat_type,
                'line': leg.line,
                'direction': leg.direction,
                'odds': leg.odds,
                'edge_pct': leg.edge_pct,
                'confidence': leg.confidence,
                'model_probability': leg.model_probability,
                'market_probability': leg.market_probability,
                'primary_reason': leg.primary_reason,
                'supporting_reasons': leg.supporting_reasons,
                'risk_factors': leg.risk_factors,
                'signals': leg.signals,
                'pipeline_score': leg.pipeline_score,
                'pipeline_confidence': 'high' if leg.pipeline_rank <= 25 else 'medium',
                'pipeline_rank': leg.pipeline_rank,
            })

        parlays_generated.append({
            'parlay': parlay_record,
            'legs': leg_records,
        })

    # Save to database
    if not dry_run and parlays_generated:
        print(f"\n--- Saving to Database ---")
        for pg in parlays_generated:
            try:
                parlay_id = sgp_db.upsert_parlay(pg['parlay'])
                sgp_db.upsert_legs(parlay_id, pg['legs'])
                print(f"  Saved parlay {parlay_id[:8]}...")
            except Exception as e:
                print(f"  Error saving parlay: {e}")

    # Save summary
    summary = {
        'generated_at': datetime.now().isoformat(),
        'game_date': date_str,
        'total_props_evaluated': sum(len(p) for p in all_qualified_props.values()),
        'qualified_props': sum(len(p) for p in all_qualified_props.values()),
        'parlays_generated': len(parlays_generated),
        'rejection_summary': dict(rejected_stats),
        'parlays': [
            {
                'game': f"{p['parlay']['away_team']}@{p['parlay']['home_team']}",
                'legs': len(p['legs']),
                'combined_odds': p['parlay']['combined_odds'],
            }
            for p in parlays_generated
        ],
    }

    output_file = DATA_DIR / f"daily_parlays_{date_str}.json"
    with open(output_file, 'w') as f:
        json.dump(summary, f, indent=2, default=str)

    print(f"\n{'='*70}")
    print(f"COMPLETE")
    print(f"{'='*70}")
    print(f"Parlays generated: {len(parlays_generated)}")
    print(f"Summary saved to: {output_file}")

    return parlays_generated


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description='Generate daily NHL SGP parlays')
    parser.add_argument('--date', help='Date to generate for (YYYY-MM-DD)')
    parser.add_argument('--dry-run', action='store_true', help='Do not save to database')
    parser.add_argument('--max-legs', type=int, default=3, help='Max legs per parlay')

    args = parser.parse_args()

    game_date = None
    if args.date:
        game_date = datetime.strptime(args.date, '%Y-%m-%d').date()

    generate_daily_parlays(
        game_date=game_date,
        dry_run=args.dry_run,
        max_legs_per_parlay=args.max_legs,
    )
