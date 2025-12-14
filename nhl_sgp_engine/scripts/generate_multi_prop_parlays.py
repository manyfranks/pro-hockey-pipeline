#!/usr/bin/env python3
"""
Multi-Prop Parlay Generator

Production script using the CORRECT architecture per MULTI_LEAGUE_ARCHITECTURE.md:
1. Fetches ALL prop types from Odds API (points, goals, assists, SOG, blocks)
2. Uses NHLDataProvider (NHL API) as PRIMARY data source
3. Uses Pipeline as SUPPLEMENTAL context (is_scoreable, rank, line deployment)
4. Generates parlays across all prop types

This replaces generate_daily_parlays.py which was too pipeline-dependent.
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
from nhl_sgp_engine.providers.context_builder import PropContextBuilder
from nhl_sgp_engine.database.sgp_db_manager import NHLSGPDBManager
from nhl_sgp_engine.edge_detection.edge_calculator import EdgeCalculator
from nhl_sgp_engine.config.settings import DATA_DIR
from nhl_sgp_engine.config.markets import PRODUCTION_MARKETS, MARKET_TO_STAT_TYPE


# NHL Team abbreviations
NHL_TEAM_ABBREVS = {
    'Anaheim Ducks': 'ANA', 'Boston Bruins': 'BOS', 'Buffalo Sabres': 'BUF',
    'Calgary Flames': 'CGY', 'Carolina Hurricanes': 'CAR', 'Chicago Blackhawks': 'CHI',
    'Colorado Avalanche': 'COL', 'Columbus Blue Jackets': 'CBJ', 'Dallas Stars': 'DAL',
    'Detroit Red Wings': 'DET', 'Edmonton Oilers': 'EDM', 'Florida Panthers': 'FLA',
    'Los Angeles Kings': 'LAK', 'Minnesota Wild': 'MIN', 'Montréal Canadiens': 'MTL',
    'Montreal Canadiens': 'MTL', 'Nashville Predators': 'NSH', 'New Jersey Devils': 'NJD',
    'New York Islanders': 'NYI', 'New York Rangers': 'NYR', 'Ottawa Senators': 'OTT',
    'Philadelphia Flyers': 'PHI', 'Pittsburgh Penguins': 'PIT', 'San Jose Sharks': 'SJS',
    'Seattle Kraken': 'SEA', 'St. Louis Blues': 'STL', 'Tampa Bay Lightning': 'TBL',
    'Toronto Maple Leafs': 'TOR', 'Utah Hockey Club': 'UTA', 'Utah Mammoth': 'UTA',
    'Vancouver Canucks': 'VAN', 'Vegas Golden Knights': 'VGK', 'Washington Capitals': 'WSH',
    'Winnipeg Jets': 'WPG',
}


def get_team_abbrev(team_name: str) -> str:
    """Convert full team name to abbreviation."""
    return NHL_TEAM_ABBREVS.get(team_name, team_name[:3].upper())


@dataclass
class QualifiedProp:
    """A prop that passed filters."""
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
    # NHL API data
    season_avg: float
    recent_avg: float
    trend_pct: float
    # Pipeline data (if available)
    pipeline_score: Optional[float]
    pipeline_rank: Optional[int]
    is_scoreable: Optional[bool]
    line_number: Optional[int]
    pp_unit: Optional[int]
    # Game context
    game_id: str
    opponent: str
    is_home: bool
    # Data source flags
    has_nhl_api_data: bool
    has_pipeline_data: bool


def should_surface_prop(
    edge_pct: float,
    stat_type: str,
    has_pipeline_data: bool,
    is_scoreable: Optional[bool],
    pipeline_rank: Optional[int],
) -> Tuple[bool, str]:
    """
    Apply production filters based on prop type and data availability.

    Different criteria for:
    - Points: Use validated pipeline filters (5-8% edge, scoreable, rank 11-50)
    - Other props: Use NHL API data only (minimum edge threshold)
    """
    # Universal minimum edge
    if edge_pct < 3.0:
        return False, f"edge={edge_pct:.1f}% (below 3% minimum)"

    # POINTS: Use validated pipeline filters
    if stat_type == 'points':
        if edge_pct < 5.0:
            return False, f"edge={edge_pct:.1f}% (below 5% for points)"
        if edge_pct > 8.0:
            return False, f"edge={edge_pct:.1f}% (above 8% for points)"

        if has_pipeline_data:
            if not is_scoreable:
                return False, "not scoreable (points filter)"
            if pipeline_rank is not None:
                if pipeline_rank <= 10:
                    return False, f"rank={pipeline_rank} (top 10 overvalued)"
                if pipeline_rank > 50:
                    return False, f"rank={pipeline_rank} (below rank 50)"

        return True, "passes points filters"

    # SOG: Different criteria (NHL API only)
    elif stat_type == 'shots_on_goal':
        if edge_pct < 5.0:
            return False, f"edge={edge_pct:.1f}% (below 5% for SOG)"
        if edge_pct > 15.0:
            return False, f"edge={edge_pct:.1f}% (above 15% for SOG - likely false positive)"
        return True, "passes SOG filters"

    # GOALS/ASSISTS: More conservative (not validated)
    elif stat_type in ['goals', 'assists']:
        if edge_pct < 8.0:
            return False, f"edge={edge_pct:.1f}% (below 8% for {stat_type})"
        return True, f"passes {stat_type} filters"

    # OTHER: Conservative default
    else:
        if edge_pct < 5.0:
            return False, f"edge={edge_pct:.1f}% (below 5% default)"
        return True, "passes default filters"


def generate_multi_prop_parlays(
    game_date: date = None,
    dry_run: bool = False,
    markets: List[str] = None,
    max_legs_per_parlay: int = 3,
):
    """
    Generate parlay recommendations using ALL prop types.

    Uses the CORRECT architecture:
    - NHL API as PRIMARY data source
    - Pipeline as SUPPLEMENTAL context
    """
    game_date = game_date or date.today()
    date_str = game_date.strftime('%Y-%m-%d')
    markets = markets or ['player_points', 'player_shots_on_goal']

    print(f"\n{'='*70}")
    print(f"NHL SGP ENGINE - MULTI-PROP PARLAY GENERATOR")
    print(f"{'='*70}")
    print(f"Date: {date_str}")
    print(f"Markets: {markets}")
    print(f"Dry run: {dry_run}")
    print(f"Architecture: NHL API (PRIMARY) + Pipeline (SUPPLEMENTAL)")
    print(f"{'='*70}\n")

    # Initialize components
    odds_client = OddsAPIClient()
    context_builder = PropContextBuilder()
    calculator = EdgeCalculator()
    sgp_db = NHLSGPDBManager()

    # Get today's events from Odds API
    print(f"Fetching odds from Odds API...")
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
    stats = {
        'total_props': 0,
        'with_nhl_data': 0,
        'with_pipeline_data': 0,
        'qualified': 0,
    }
    rejected_by_stat = defaultdict(lambda: defaultdict(int))

    for event in events:
        event_id = event.get('id')
        home_team = event.get('home_team', '')
        away_team = event.get('away_team', '')
        home_abbrev = get_team_abbrev(home_team)
        away_abbrev = get_team_abbrev(away_team)

        print(f"\n--- {away_team} @ {home_team} ---")

        # Fetch ALL prop types
        try:
            event_odds = odds_client.get_event_odds(event_id, markets=markets)
            props = odds_client.parse_player_props(event_odds, market_keys=markets)
        except Exception as e:
            print(f"  Error fetching props: {e}")
            continue

        if not props:
            print(f"  No player props found")
            continue

        print(f"  Found {len(props)} player props across {len(markets)} markets")

        # Deduplicate by player + stat_type + line
        seen_props = set()

        for prop in props:
            stats['total_props'] += 1
            player_name = prop.player_name
            stat_type = prop.stat_type
            line = prop.line

            # Dedup key
            prop_key = f"{player_name}_{stat_type}_{line}"
            if prop_key in seen_props:
                continue
            seen_props.add(prop_key)

            # Determine team context
            team = None  # Let context builder figure it out
            opponent = None
            is_home = None

            # Build context using NHL API (PRIMARY) + Pipeline (SUPPLEMENTAL)
            ctx = context_builder.build_context(
                player_name=player_name,
                stat_type=stat_type,
                line=line,
                game_date=game_date,
                event_id=event_id,
                team=team,
                opponent=opponent,
                is_home=is_home,
                use_pipeline=True,  # Try to get pipeline data if available
            )

            if not ctx or not ctx.has_nhl_api_data:
                rejected_by_stat[stat_type]['no_nhl_api_data'] += 1
                continue

            stats['with_nhl_data'] += 1
            if ctx.has_pipeline_data:
                stats['with_pipeline_data'] += 1

            # Calculate edge
            over_odds = prop.over_price or -110
            under_odds = prop.under_price or -110

            edge_result = calculator.calculate_edge(ctx, over_odds, under_odds)

            # Apply filters based on prop type
            passes, reason = should_surface_prop(
                edge_pct=edge_result.edge_pct,
                stat_type=stat_type,
                has_pipeline_data=ctx.has_pipeline_data,
                is_scoreable=ctx.is_scoreable,
                pipeline_rank=ctx.pipeline_rank,
            )

            if not passes:
                # Simplify rejection reason
                if 'edge=' in reason:
                    rejection_key = 'edge_out_of_range'
                elif 'rank=' in reason:
                    rejection_key = 'rank_out_of_range'
                else:
                    rejection_key = reason.split('(')[0].strip()
                rejected_by_stat[stat_type][rejection_key] += 1
                continue

            stats['qualified'] += 1

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
                season_avg=float(ctx.season_avg or 0),
                recent_avg=float(ctx.recent_avg or 0),
                trend_pct=float(ctx.trend_pct or 0),
                pipeline_score=float(ctx.pipeline_score) if ctx.pipeline_score else None,
                pipeline_rank=ctx.pipeline_rank,
                is_scoreable=ctx.is_scoreable,
                line_number=ctx.line_number,
                pp_unit=ctx.pp_unit,
                game_id=event_id,
                opponent=ctx.opponent,
                is_home=ctx.is_home,
                has_nhl_api_data=ctx.has_nhl_api_data,
                has_pipeline_data=ctx.has_pipeline_data,
            )

            game_key = f"{away_abbrev}@{home_abbrev}"
            all_qualified_props[game_key].append(qualified)

            pipeline_marker = " [+PIPELINE]" if ctx.has_pipeline_data else " [NHL API]"
            print(f"  ✓ {player_name} {stat_type} {edge_result.direction.upper()} {line} | "
                  f"Edge: {edge_result.edge_pct:.1f}%{pipeline_marker}")

    # Summary
    print(f"\n{'='*70}")
    print(f"PROCESSING SUMMARY")
    print(f"{'='*70}")
    print(f"Total props evaluated: {stats['total_props']}")
    print(f"With NHL API data: {stats['with_nhl_data']}")
    print(f"With Pipeline data: {stats['with_pipeline_data']}")
    print(f"Qualified: {stats['qualified']}")

    print(f"\n--- Rejections by Stat Type ---")
    for stat_type, reasons in rejected_by_stat.items():
        total = sum(reasons.values())
        print(f"  {stat_type}: {total} rejected")
        for reason, count in sorted(reasons.items(), key=lambda x: -x[1])[:3]:
            print(f"    - {reason}: {count}")

    # Build parlays
    print(f"\n{'='*70}")
    print("PARLAY RECOMMENDATIONS")
    print(f"{'='*70}")

    parlays_generated = []

    for game_key, props in all_qualified_props.items():
        if len(props) < 2:
            print(f"\n{game_key}: Only {len(props)} qualifying prop(s), skipping")
            continue

        # Sort by edge
        props.sort(key=lambda x: x.edge_pct, reverse=True)

        # Build parlay with top props (preferring diverse stat types)
        parlay_legs = []
        stat_types_used = set()

        for prop in props:
            # Try to get diverse stat types
            if prop.stat_type not in stat_types_used or len(parlay_legs) < 2:
                parlay_legs.append(prop)
                stat_types_used.add(prop.stat_type)
            if len(parlay_legs) >= max_legs_per_parlay:
                break

        # Calculate combined odds
        combined_prob = 1.0
        for leg in parlay_legs:
            if leg.odds > 0:
                prob = 100 / (leg.odds + 100)
            else:
                prob = abs(leg.odds) / (abs(leg.odds) + 100)
            combined_prob *= prob

        combined_odds = int(100 * (1 - combined_prob) / combined_prob) if combined_prob < 0.5 else int(-100 * combined_prob / (1 - combined_prob))

        avg_edge = sum(leg.edge_pct for leg in parlay_legs) / len(parlay_legs)

        print(f"\n{game_key} - MULTI-PROP PARLAY")
        print(f"  Combined odds: +{combined_odds}" if combined_odds > 0 else f"  Combined odds: {combined_odds}")
        print(f"  Average edge: {avg_edge:.1f}%")
        print(f"  Stat types: {', '.join(stat_types_used)}")
        print(f"  Legs:")
        for i, leg in enumerate(parlay_legs, 1):
            source = "NHL+Pipeline" if leg.has_pipeline_data else "NHL API"
            print(f"    {i}. {leg.player_name} {leg.stat_type} {leg.direction.upper()} {leg.line}")
            print(f"       Edge: {leg.edge_pct:.1f}% | Source: {source}")

        parlays_generated.append({
            'game': game_key,
            'legs': len(parlay_legs),
            'combined_odds': combined_odds,
            'avg_edge': avg_edge,
            'stat_types': list(stat_types_used),
        })

    # Save summary
    summary = {
        'generated_at': datetime.now().isoformat(),
        'game_date': date_str,
        'markets': markets,
        'stats': stats,
        'parlays': parlays_generated,
    }

    output_file = DATA_DIR / f"multi_prop_parlays_{date_str}.json"
    with open(output_file, 'w') as f:
        json.dump(summary, f, indent=2, default=str)

    print(f"\n{'='*70}")
    print(f"COMPLETE")
    print(f"{'='*70}")
    print(f"Parlays generated: {len(parlays_generated)}")
    print(f"Summary saved to: {output_file}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description='Generate multi-prop NHL SGP parlays')
    parser.add_argument('--date', help='Date (YYYY-MM-DD)')
    parser.add_argument('--dry-run', action='store_true', help='Do not save to database')
    parser.add_argument('--markets', nargs='+', default=['player_points', 'player_shots_on_goal'],
                       help='Markets to include')

    args = parser.parse_args()

    game_date = None
    if args.date:
        game_date = datetime.strptime(args.date, '%Y-%m-%d').date()

    generate_multi_prop_parlays(
        game_date=game_date,
        dry_run=args.dry_run,
        markets=args.markets,
    )
