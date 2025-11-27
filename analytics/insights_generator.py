# nhl_isolated/analytics/insights_generator.py
"""
NHL Post-Prediction Insights Generator - Phase 0 (Rule-Based)

Generates actionable insights from NHL predictions including:
- Parlay recommendations (Conservative, Balanced, Aggressive)
- Player hot streak analysis
- Goalie cold streak identification
- Matchup-based opportunities
- Game stacking opportunities

Modeled after NCAAF find_parlay_edges.py and cherry_pick_v2_scorer.py patterns.
"""

import json
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass, field, asdict
from collections import defaultdict

from utilities.logger import get_logger

logger = get_logger('insights')


# ============================================================================
# Data Classes for Structured Insights
# ============================================================================

@dataclass
class PlayerInsight:
    """Individual player insight with supporting data."""
    player_id: int
    player_name: str
    team: str
    insight_type: str  # hot_streak, elite_opportunity, pp_specialist, etc.
    headline: str
    details: str
    confidence: str
    supporting_stats: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ParlayLeg:
    """Single leg of a parlay recommendation."""
    player_id: int
    player_name: str
    team: str
    opponent: str
    game_id: int
    final_score: float
    confidence: str
    line_number: int
    pp_unit: int
    point_streak: int
    recent_ppg: float


@dataclass
class ParlayRecommendation:
    """Parlay recommendation with multiple legs."""
    parlay_type: str  # conservative, balanced, aggressive, moonshot
    legs: List[ParlayLeg]
    combined_confidence: str
    rationale: str
    estimated_hit_probability: float  # Based on historical data


@dataclass
class GoalieInsight:
    """Goalie-specific insight (cold streak, vulnerability, etc.)."""
    goalie_id: int
    goalie_name: str
    team: str
    insight_type: str  # cold_streak, high_gaa, low_sv_pct
    headline: str
    details: str
    gaa: float
    sv_pct: float
    quality_tier: str


@dataclass
class MatchupInsight:
    """Game-level matchup insight."""
    game_id: int
    home_team: str
    away_team: str
    insight_type: str  # goalie_mismatch, high_scoring_potential, stack_opportunity
    headline: str
    details: str
    featured_players: List[str]


@dataclass
class InsightsReport:
    """Complete insights report for a prediction date."""
    analysis_date: str
    generated_at: str
    total_predictions: int

    # Player insights
    hot_streaks: List[PlayerInsight]
    elite_opportunities: List[PlayerInsight]
    pp_specialists: List[PlayerInsight]

    # Goalie insights
    goalie_vulnerabilities: List[GoalieInsight]

    # Matchup insights
    matchup_highlights: List[MatchupInsight]

    # Parlay recommendations
    parlays: Dict[str, ParlayRecommendation]

    # Top picks summary
    top_5_picks: List[Dict[str, Any]]
    picks_6_to_10: List[Dict[str, Any]]

    # System performance (if settlement data available)
    recent_performance: Optional[Dict[str, Any]] = None


# ============================================================================
# Insights Generator Class
# ============================================================================

class NHLInsightsGenerator:
    """
    Generates rule-based insights from NHL predictions.

    Usage:
        generator = NHLInsightsGenerator()
        report = generator.generate_insights(predictions)
        generator.print_report(report)
    """

    # Thresholds for insight detection
    HOT_STREAK_THRESHOLD = 3  # Consecutive games with a point
    ELITE_PPG_THRESHOLD = 1.2  # Recent PPG to be considered "hot"
    COLD_GOALIE_GAA_THRESHOLD = 3.2  # GAA above this is "cold"
    COLD_GOALIE_SV_PCT_THRESHOLD = 0.890  # SV% below this is struggling

    # Position mappings for diversity
    POSITION_GROUPS = {
        'C': 'center',
        'L': 'wing',
        'R': 'wing',
        'LW': 'wing',
        'RW': 'wing',
        'D': 'defense',
    }

    def __init__(self, db_manager=None):
        """Initialize insights generator."""
        self.db = db_manager

    def generate_insights(
        self,
        predictions: List[Dict],
        include_settlement_analysis: bool = True,
        lookback_days: int = 5
    ) -> InsightsReport:
        """
        Generate comprehensive insights from predictions.

        Args:
            predictions: List of player prediction dictionaries
            include_settlement_analysis: Include recent performance metrics
            lookback_days: Days to look back for settlement analysis

        Returns:
            InsightsReport with all generated insights
        """
        if not predictions:
            logger.warning("No predictions provided for insights generation")
            return self._empty_report()

        # Sort by final_score descending
        sorted_preds = sorted(predictions, key=lambda x: x.get('final_score', 0), reverse=True)

        # Extract analysis date
        analysis_date = predictions[0].get('analysis_date', str(date.today()))

        # Generate various insight types
        hot_streaks = self._find_hot_streaks(sorted_preds)
        elite_opportunities = self._find_elite_opportunities(sorted_preds)
        pp_specialists = self._find_pp_specialists(sorted_preds)
        goalie_vulnerabilities = self._find_goalie_vulnerabilities(sorted_preds)
        matchup_highlights = self._find_matchup_highlights(sorted_preds)

        # Generate parlay recommendations
        parlays = self._generate_parlays(sorted_preds)

        # Top picks summaries
        top_5 = self._summarize_top_picks(sorted_preds[:5])
        picks_6_10 = self._summarize_top_picks(sorted_preds[5:10])

        # Recent performance (if DB available and requested)
        recent_perf = None
        if include_settlement_analysis and self.db:
            recent_perf = self._get_recent_performance(lookback_days)

        return InsightsReport(
            analysis_date=analysis_date,
            generated_at=datetime.now().isoformat(),
            total_predictions=len(predictions),
            hot_streaks=hot_streaks,
            elite_opportunities=elite_opportunities,
            pp_specialists=pp_specialists,
            goalie_vulnerabilities=goalie_vulnerabilities,
            matchup_highlights=matchup_highlights,
            parlays=parlays,
            top_5_picks=top_5,
            picks_6_to_10=picks_6_10,
            recent_performance=recent_perf,
        )

    # ========================================================================
    # Hot Streak Detection
    # ========================================================================

    def _find_hot_streaks(self, predictions: List[Dict]) -> List[PlayerInsight]:
        """Find players on significant point streaks."""
        insights = []

        for p in predictions[:25]:  # Focus on top 25
            streak = p.get('point_streak', 0)
            recent_ppg = p.get('recent_ppg', 0)

            if streak >= self.HOT_STREAK_THRESHOLD or recent_ppg >= self.ELITE_PPG_THRESHOLD:
                streak_desc = f"{streak}-game point streak" if streak >= 3 else ""
                ppg_desc = f"{recent_ppg:.2f} PPG over last 10" if recent_ppg >= 1.0 else ""

                headline = f"{p['player_name']} is on fire"
                details_parts = [x for x in [streak_desc, ppg_desc] if x]
                details = " | ".join(details_parts) if details_parts else "Strong recent form"

                # Determine insight subtype
                if streak >= 5:
                    insight_type = "extended_hot_streak"
                elif streak >= 3:
                    insight_type = "hot_streak"
                else:
                    insight_type = "high_ppg"

                insights.append(PlayerInsight(
                    player_id=p['player_id'],
                    player_name=p['player_name'],
                    team=p['team'],
                    insight_type=insight_type,
                    headline=headline,
                    details=details,
                    confidence=p.get('confidence', 'medium'),
                    supporting_stats={
                        'point_streak': streak,
                        'recent_ppg': recent_ppg,
                        'recent_goals': p.get('recent_goals', 0),
                        'recent_assists': p.get('recent_assists', 0),
                        'final_score': p.get('final_score', 0),
                    }
                ))

        return insights[:10]  # Limit to top 10 hot streak insights

    # ========================================================================
    # Elite Opportunity Detection
    # ========================================================================

    def _find_elite_opportunities(self, predictions: List[Dict]) -> List[PlayerInsight]:
        """Find elite players with favorable matchups."""
        insights = []

        for p in predictions[:15]:
            line = p.get('line_number', 4)
            pp_unit = p.get('pp_unit', 0)
            goalie_tier = p.get('goalie_weakness_details', {}).get('quality_tier', 'average')
            score = p.get('final_score', 0)

            # Elite opportunity: Top line + PP1 + weak goalie
            if line == 1 and pp_unit == 1 and goalie_tier in ['below_average', 'poor']:
                opp_goalie = p.get('opposing_goalie_name', 'Unknown')
                opp_gaa = p.get('opposing_goalie_gaa', 0)

                insights.append(PlayerInsight(
                    player_id=p['player_id'],
                    player_name=p['player_name'],
                    team=p['team'],
                    insight_type="elite_opportunity",
                    headline=f"{p['player_name']} has elite setup tonight",
                    details=f"Top line + PP1 vs struggling {opp_goalie} ({opp_gaa:.2f} GAA)",
                    confidence="very_high",
                    supporting_stats={
                        'line_number': line,
                        'pp_unit': pp_unit,
                        'opposing_goalie': opp_goalie,
                        'goalie_gaa': opp_gaa,
                        'goalie_tier': goalie_tier,
                        'final_score': score,
                    }
                ))

        return insights[:5]

    # ========================================================================
    # Power Play Specialists
    # ========================================================================

    def _find_pp_specialists(self, predictions: List[Dict]) -> List[PlayerInsight]:
        """Find PP1 players with high PP goal production."""
        insights = []

        for p in predictions[:30]:
            pp_unit = p.get('pp_unit', 0)
            pp_goals = p.get('season_pp_goals', 0)
            season_games = p.get('season_games', 1)

            if pp_unit == 1 and pp_goals >= 3:
                pp_goal_rate = pp_goals / max(season_games, 1)

                insights.append(PlayerInsight(
                    player_id=p['player_id'],
                    player_name=p['player_name'],
                    team=p['team'],
                    insight_type="pp_specialist",
                    headline=f"{p['player_name']} - PP1 weapon",
                    details=f"{pp_goals} PP goals in {season_games} games ({pp_goal_rate:.2f}/game)",
                    confidence=p.get('confidence', 'high'),
                    supporting_stats={
                        'pp_goals': pp_goals,
                        'pp_unit': pp_unit,
                        'pp_goal_rate': round(pp_goal_rate, 3),
                        'final_score': p.get('final_score', 0),
                    }
                ))

        return insights[:5]

    # ========================================================================
    # Goalie Vulnerability Detection
    # ========================================================================

    def _find_goalie_vulnerabilities(self, predictions: List[Dict]) -> List[GoalieInsight]:
        """Find opposing goalies who are struggling."""
        insights = []
        seen_goalies = set()

        for p in predictions:
            goalie_id = p.get('opposing_goalie_id')
            if not goalie_id or goalie_id in seen_goalies:
                continue

            seen_goalies.add(goalie_id)

            goalie_name = p.get('opposing_goalie_name', 'Unknown')
            gaa = p.get('opposing_goalie_gaa', 0)
            sv_pct = p.get('opposing_goalie_sv_pct', 0.900)
            goalie_details = p.get('goalie_weakness_details', {})
            quality_tier = goalie_details.get('quality_tier', 'average')

            # Check for vulnerability
            is_cold = gaa >= self.COLD_GOALIE_GAA_THRESHOLD or sv_pct <= self.COLD_GOALIE_SV_PCT_THRESHOLD

            if is_cold or quality_tier in ['below_average', 'poor']:
                if gaa >= 3.5:
                    insight_type = "high_gaa"
                    headline = f"{goalie_name} bleeding goals"
                    details = f"{gaa:.2f} GAA - opponents averaging over 3.5 goals"
                elif sv_pct <= 0.880:
                    insight_type = "low_sv_pct"
                    headline = f"{goalie_name} can't stop a beach ball"
                    details = f"{sv_pct:.3f} SV% - well below league average"
                else:
                    insight_type = "cold_streak"
                    headline = f"{goalie_name} struggling lately"
                    details = f"{gaa:.2f} GAA, {sv_pct:.3f} SV% - below average form"

                insights.append(GoalieInsight(
                    goalie_id=goalie_id,
                    goalie_name=goalie_name,
                    team=p.get('opponent', ''),
                    insight_type=insight_type,
                    headline=headline,
                    details=details,
                    gaa=gaa,
                    sv_pct=sv_pct,
                    quality_tier=quality_tier,
                ))

        # Sort by GAA descending (worst goalies first)
        insights.sort(key=lambda x: x.gaa, reverse=True)
        return insights[:5]

    # ========================================================================
    # Matchup Highlights
    # ========================================================================

    def _find_matchup_highlights(self, predictions: List[Dict]) -> List[MatchupInsight]:
        """Find notable game-level matchup insights."""
        insights = []
        games = defaultdict(list)

        # Group predictions by game
        for p in predictions:
            game_id = p.get('game_id')
            if game_id:
                games[game_id].append(p)

        for game_id, players in games.items():
            if not players:
                continue

            # Sort players in this game by score
            players.sort(key=lambda x: x.get('final_score', 0), reverse=True)

            home_team = None
            away_team = None
            for p in players:
                if p.get('is_home'):
                    home_team = p['team']
                    away_team = p.get('opponent')
                else:
                    away_team = p['team']
                    home_team = p.get('opponent')
                if home_team and away_team:
                    break

            # Stack opportunity: 3+ top-25 players from same game
            top_25_in_game = [p for p in players[:5] if predictions.index(p) < 25]
            if len(top_25_in_game) >= 3:
                featured = [p['player_name'] for p in top_25_in_game[:4]]
                insights.append(MatchupInsight(
                    game_id=game_id,
                    home_team=home_team or '',
                    away_team=away_team or '',
                    insight_type="stack_opportunity",
                    headline=f"Game Stack: {away_team} @ {home_team}",
                    details=f"{len(top_25_in_game)} top-25 players in this matchup",
                    featured_players=featured,
                ))

            # Goalie mismatch: One weak goalie
            for p in players[:1]:
                goalie_tier = p.get('goalie_weakness_details', {}).get('quality_tier', '')
                if goalie_tier in ['below_average', 'poor']:
                    goalie_name = p.get('opposing_goalie_name', '')
                    featured = [p['player_name'] for p in players[:3]]
                    insights.append(MatchupInsight(
                        game_id=game_id,
                        home_team=home_team or '',
                        away_team=away_team or '',
                        insight_type="goalie_mismatch",
                        headline=f"Target {goalie_name}",
                        details=f"{p['team']} faces struggling goalie ({p.get('opposing_goalie_gaa', 0):.2f} GAA)",
                        featured_players=featured,
                    ))

        return insights[:5]

    # ========================================================================
    # Parlay Generation
    # ========================================================================

    def _generate_parlays(self, predictions: List[Dict]) -> Dict[str, ParlayRecommendation]:
        """Generate parlay recommendations at different risk levels."""
        parlays = {}

        # Filter to top 15 for parlay consideration
        candidates = predictions[:15]

        # Build ParlayLeg objects
        def make_leg(p: Dict) -> ParlayLeg:
            return ParlayLeg(
                player_id=p['player_id'],
                player_name=p['player_name'],
                team=p['team'],
                opponent=p.get('opponent', ''),
                game_id=p.get('game_id', 0),
                final_score=p.get('final_score', 0),
                confidence=p.get('confidence', 'medium'),
                line_number=p.get('line_number', 4),
                pp_unit=p.get('pp_unit', 0),
                point_streak=p.get('point_streak', 0),
                recent_ppg=p.get('recent_ppg', 0),
            )

        # 1. Conservative 2-Leg: Top 2 from different games
        conservative_legs = self._select_diverse_legs(candidates, n=2, by='game')
        if len(conservative_legs) >= 2:
            parlays['conservative'] = ParlayRecommendation(
                parlay_type='conservative',
                legs=[make_leg(p) for p in conservative_legs],
                combined_confidence='high',
                rationale="Top 2 picks from different games - minimizes correlation risk",
                estimated_hit_probability=0.35,  # ~59% per leg squared
            )

        # 2. Balanced 3-Leg: Top 3 with position diversity
        balanced_legs = self._select_diverse_legs(candidates, n=3, by='position')
        if len(balanced_legs) >= 3:
            parlays['balanced'] = ParlayRecommendation(
                parlay_type='balanced',
                legs=[make_leg(p) for p in balanced_legs],
                combined_confidence='medium',
                rationale="Position-diverse selection for balanced exposure",
                estimated_hit_probability=0.20,  # ~58% per leg cubed
            )

        # 3. Aggressive 4-Leg: Top 4 PP1 specialists
        pp1_players = [p for p in candidates if p.get('pp_unit') == 1][:4]
        if len(pp1_players) >= 4:
            parlays['aggressive'] = ParlayRecommendation(
                parlay_type='aggressive',
                legs=[make_leg(p) for p in pp1_players],
                combined_confidence='medium',
                rationale="All PP1 players - high-volume opportunity seekers",
                estimated_hit_probability=0.12,
            )

        # 4. Moonshot 5-Leg: Hot streaks only
        hot_players = [p for p in candidates if p.get('point_streak', 0) >= 3][:5]
        if len(hot_players) >= 5:
            parlays['moonshot'] = ParlayRecommendation(
                parlay_type='moonshot',
                legs=[make_leg(p) for p in hot_players],
                combined_confidence='low',
                rationale="All on 3+ game point streaks - riding the hot hand",
                estimated_hit_probability=0.07,
            )
        elif len(candidates) >= 5:
            # Fallback: just top 5
            parlays['moonshot'] = ParlayRecommendation(
                parlay_type='moonshot',
                legs=[make_leg(p) for p in candidates[:5]],
                combined_confidence='low',
                rationale="Top 5 overall picks - high risk, high reward",
                estimated_hit_probability=0.07,
            )

        return parlays

    def _select_diverse_legs(
        self,
        candidates: List[Dict],
        n: int,
        by: str = 'game'
    ) -> List[Dict]:
        """Select n candidates with diversity constraint."""
        selected = []
        seen = set()

        for p in candidates:
            if by == 'game':
                key = p.get('game_id')
            elif by == 'position':
                pos = p.get('position', 'C')
                key = self.POSITION_GROUPS.get(pos, pos)
            elif by == 'team':
                key = p.get('team')
            else:
                key = None

            if key is None or key not in seen:
                selected.append(p)
                if key:
                    seen.add(key)
                if len(selected) >= n:
                    break

        return selected

    # ========================================================================
    # Top Picks Summary
    # ========================================================================

    def _summarize_top_picks(self, picks: List[Dict]) -> List[Dict[str, Any]]:
        """Create summary of top picks."""
        summaries = []

        for i, p in enumerate(picks, 1):
            summaries.append({
                'rank': i if len(summaries) == 0 else len(summaries) + 1,
                'player_id': p.get('player_id'),
                'player_name': p.get('player_name'),
                'team': p.get('team'),
                'opponent': p.get('opponent'),
                'position': p.get('position'),
                'final_score': round(p.get('final_score', 0), 2),
                'confidence': p.get('confidence'),
                'line_number': p.get('line_number'),
                'pp_unit': p.get('pp_unit'),
                'point_streak': p.get('point_streak', 0),
                'recent_ppg': round(p.get('recent_ppg', 0), 2),
                'opposing_goalie': p.get('opposing_goalie_name'),
                'goalie_gaa': round(p.get('opposing_goalie_gaa', 0), 2),
            })

        return summaries

    # ========================================================================
    # Recent Performance Analysis
    # ========================================================================

    def _get_recent_performance(self, lookback_days: int = 5) -> Optional[Dict[str, Any]]:
        """Get system performance over recent days from settlement data."""
        if not self.db:
            return None

        try:
            end_date = date.today() - timedelta(days=1)  # Yesterday
            start_date = end_date - timedelta(days=lookback_days)

            summary = self.db.get_hit_rate_summary(start_date, end_date)

            if summary.get('total_predictions', 0) > 0:
                return {
                    'period': f"Last {lookback_days} days",
                    'start_date': str(start_date),
                    'end_date': str(end_date),
                    'total_predictions': summary.get('total_predictions', 0),
                    'hits': summary.get('hits', 0),
                    'misses': summary.get('misses', 0),
                    'hit_rate': summary.get('overall_hit_rate', 0),
                    'top_10_hit_rate': summary.get('top_10_hit_rate', 0),
                    'top_5_hit_rate': summary.get('top_5_hit_rate', 0),
                }
        except Exception as e:
            logger.warning(f"Could not fetch recent performance: {e}")

        return None

    def _empty_report(self) -> InsightsReport:
        """Return empty report when no predictions available."""
        return InsightsReport(
            analysis_date=str(date.today()),
            generated_at=datetime.now().isoformat(),
            total_predictions=0,
            hot_streaks=[],
            elite_opportunities=[],
            pp_specialists=[],
            goalie_vulnerabilities=[],
            matchup_highlights=[],
            parlays={},
            top_5_picks=[],
            picks_6_to_10=[],
            recent_performance=None,
        )

    # ========================================================================
    # Report Output
    # ========================================================================

    def print_report(self, report: InsightsReport) -> str:
        """Print formatted insights report and return as string."""
        lines = []

        lines.append("=" * 80)
        lines.append(f"NHL INSIGHTS REPORT - {report.analysis_date}")
        lines.append("=" * 80)
        lines.append(f"Generated: {report.generated_at}")
        lines.append(f"Total Players Analyzed: {report.total_predictions}")
        lines.append("")

        # Recent Performance (if available)
        if report.recent_performance:
            perf = report.recent_performance
            lines.append("-" * 80)
            lines.append("SYSTEM PERFORMANCE (Recent)")
            lines.append("-" * 80)
            lines.append(f"  Period: {perf['period']} ({perf['start_date']} to {perf['end_date']})")
            lines.append(f"  Overall Hit Rate: {perf['hit_rate']:.1f}%")
            lines.append(f"  Top 5 Hit Rate: {perf.get('top_5_hit_rate', 'N/A')}")
            lines.append(f"  Top 10 Hit Rate: {perf.get('top_10_hit_rate', 'N/A')}")
            lines.append("")

        # Top 5 Picks
        lines.append("-" * 80)
        lines.append("TOP 5 PICKS")
        lines.append("-" * 80)
        for i, pick in enumerate(report.top_5_picks, 1):
            streak_str = f"({pick['point_streak']}G streak)" if pick['point_streak'] >= 3 else ""
            lines.append(
                f"  {i}. {pick['player_name']} ({pick['team']}) vs {pick['opponent']} "
                f"- Score: {pick['final_score']:.1f} [{pick['confidence']}] {streak_str}"
            )
            lines.append(
                f"     Line {pick['line_number']} | PP{pick['pp_unit'] or '-'} | "
                f"PPG: {pick['recent_ppg']:.2f} | vs {pick['opposing_goalie']} ({pick['goalie_gaa']:.2f} GAA)"
            )
        lines.append("")

        # Picks 6-10
        if report.picks_6_to_10:
            lines.append("-" * 80)
            lines.append("PICKS 6-10 (Value Plays)")
            lines.append("-" * 80)
            for i, pick in enumerate(report.picks_6_to_10, 6):
                lines.append(
                    f"  {i}. {pick['player_name']} ({pick['team']}) "
                    f"- Score: {pick['final_score']:.1f} [{pick['confidence']}]"
                )
            lines.append("")

        # Hot Streaks
        if report.hot_streaks:
            lines.append("-" * 80)
            lines.append("HOT STREAKS")
            lines.append("-" * 80)
            for hs in report.hot_streaks[:5]:
                lines.append(f"  {hs.headline}")
                lines.append(f"    {hs.details}")
            lines.append("")

        # Elite Opportunities
        if report.elite_opportunities:
            lines.append("-" * 80)
            lines.append("ELITE OPPORTUNITIES")
            lines.append("-" * 80)
            for eo in report.elite_opportunities:
                lines.append(f"  {eo.headline}")
                lines.append(f"    {eo.details}")
            lines.append("")

        # Goalie Vulnerabilities
        if report.goalie_vulnerabilities:
            lines.append("-" * 80)
            lines.append("GOALIE VULNERABILITIES (Target These)")
            lines.append("-" * 80)
            for gv in report.goalie_vulnerabilities:
                lines.append(f"  {gv.headline}")
                lines.append(f"    {gv.details}")
            lines.append("")

        # Parlay Recommendations
        if report.parlays:
            lines.append("-" * 80)
            lines.append("PARLAY RECOMMENDATIONS")
            lines.append("-" * 80)

            for parlay_type, parlay in report.parlays.items():
                lines.append(f"\n  [{parlay_type.upper()}] - {parlay.combined_confidence.upper()} confidence")
                lines.append(f"  Rationale: {parlay.rationale}")
                lines.append(f"  Est. Hit Prob: {parlay.estimated_hit_probability:.0%}")
                lines.append("  Legs:")
                for leg in parlay.legs:
                    streak_note = f" ({leg.point_streak}G streak)" if leg.point_streak >= 3 else ""
                    lines.append(
                        f"    - {leg.player_name} ({leg.team}) vs {leg.opponent} "
                        f"[Score: {leg.final_score:.1f}]{streak_note}"
                    )

        lines.append("")
        lines.append("=" * 80)

        output = "\n".join(lines)
        print(output)
        return output

    def to_json(self, report: InsightsReport) -> str:
        """Convert report to JSON string."""
        # Convert dataclasses to dicts
        data = {
            'analysis_date': report.analysis_date,
            'generated_at': report.generated_at,
            'total_predictions': report.total_predictions,
            'hot_streaks': [asdict(hs) for hs in report.hot_streaks],
            'elite_opportunities': [asdict(eo) for eo in report.elite_opportunities],
            'pp_specialists': [asdict(pp) for pp in report.pp_specialists],
            'goalie_vulnerabilities': [asdict(gv) for gv in report.goalie_vulnerabilities],
            'matchup_highlights': [asdict(mh) for mh in report.matchup_highlights],
            'parlays': {
                k: {
                    'parlay_type': v.parlay_type,
                    'legs': [asdict(leg) for leg in v.legs],
                    'combined_confidence': v.combined_confidence,
                    'rationale': v.rationale,
                    'estimated_hit_probability': v.estimated_hit_probability,
                }
                for k, v in report.parlays.items()
            },
            'top_5_picks': report.top_5_picks,
            'picks_6_to_10': report.picks_6_to_10,
            'recent_performance': report.recent_performance,
        }
        return json.dumps(data, indent=2)


# ============================================================================
# Convenience Functions
# ============================================================================

def generate_insights_from_file(
    json_path: str,
    include_settlement: bool = True
) -> InsightsReport:
    """
    Generate insights from a predictions JSON file.

    Args:
        json_path: Path to predictions JSON file
        include_settlement: Include settlement analysis if DB available

    Returns:
        InsightsReport
    """
    with open(json_path) as f:
        predictions = json.load(f)

    db = None
    if include_settlement:
        try:
            from database.db_manager import NHLDBManager
            db = NHLDBManager()
        except Exception:
            pass

    generator = NHLInsightsGenerator(db_manager=db)
    return generator.generate_insights(predictions, include_settlement_analysis=include_settlement)


def generate_insights_for_date(
    target_date: date = None,
    include_settlement: bool = True,
    use_database: bool = True
) -> InsightsReport:
    """
    Generate insights for a specific date's predictions.

    In production, fetches predictions from database.
    Falls back to JSON files for local development/testing.

    Args:
        target_date: Date to generate insights for (default: today)
        include_settlement: Include settlement analysis
        use_database: Try database first (default: True)

    Returns:
        InsightsReport
    """
    if target_date is None:
        target_date = date.today()

    db = None
    predictions = None

    # Try database first (production path)
    if use_database:
        try:
            from database.db_manager import NHLDBManager
            db = NHLDBManager()
            predictions = db.get_predictions_for_date(target_date)
            if predictions:
                logger.info(f"Loaded {len(predictions)} predictions from database for {target_date}")
        except Exception as e:
            logger.warning(f"Database fetch failed, falling back to JSON: {e}")
            predictions = None

    # Fallback to JSON files (local development)
    if not predictions:
        predictions_dir = Path(__file__).parent.parent / "data" / "predictions"
        date_str = target_date.strftime('%Y-%m-%d')

        patterns = [
            f"nhl_predictions_{date_str}_nhlapi.json",
            f"nhl_predictions_{date_str}_full.json",
            f"nhl_predictions_{date_str}.json",
        ]

        for pattern in patterns:
            json_path = predictions_dir / pattern
            if json_path.exists():
                with open(json_path) as f:
                    predictions = json.load(f)
                logger.info(f"Loaded {len(predictions)} predictions from {json_path.name}")
                break

    if not predictions:
        logger.warning(f"No predictions found for {target_date}")
        return NHLInsightsGenerator()._empty_report()

    # Initialize DB manager for settlement analysis if not already set
    if include_settlement and db is None:
        try:
            from database.db_manager import NHLDBManager
            db = NHLDBManager()
        except Exception:
            pass

    generator = NHLInsightsGenerator(db_manager=db)
    return generator.generate_insights(predictions, include_settlement_analysis=include_settlement)


# ============================================================================
# CLI Entry Point
# ============================================================================

if __name__ == '__main__':
    import sys

    # Parse date argument
    if len(sys.argv) > 1:
        try:
            target = date.fromisoformat(sys.argv[1])
        except ValueError:
            print(f"Invalid date format: {sys.argv[1]}. Use YYYY-MM-DD")
            sys.exit(1)
    else:
        target = date.today()

    print(f"Generating insights for {target}...")

    report = generate_insights_for_date(target)

    generator = NHLInsightsGenerator()
    output = generator.print_report(report)

    # Save to file
    output_dir = Path(__file__).parent.parent / "data" / "insights"
    output_dir.mkdir(parents=True, exist_ok=True)

    # Save text report
    text_path = output_dir / f"insights_{target}.txt"
    with open(text_path, 'w') as f:
        f.write(output)
    print(f"\nSaved text report to: {text_path}")

    # Save JSON
    json_path = output_dir / f"insights_{target}.json"
    with open(json_path, 'w') as f:
        f.write(generator.to_json(report))
    print(f"Saved JSON report to: {json_path}")
