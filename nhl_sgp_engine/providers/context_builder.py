"""
Prop Context Builder

Builds PropContext by combining:
1. PRIMARY: NHLDataProvider (NHL Official API)
2. SUPPLEMENTAL: PipelineAdapter (points prediction pipeline)

Per MULTI_LEAGUE_ARCHITECTURE.md, the SGP engine should be INDEPENDENT
and able to function with just NHL API data. The pipeline is optional
bonus context that adds value for points props.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from datetime import date
from typing import Optional, Dict

from nhl_sgp_engine.signals.base import PropContext
from nhl_sgp_engine.providers.nhl_data_provider import NHLDataProvider
from nhl_sgp_engine.providers.pipeline_adapter import PipelineAdapter


class PropContextBuilder:
    """
    Builds PropContext for any prop type.

    Uses NHL API as PRIMARY data source.
    Uses Pipeline as SUPPLEMENTAL (optional) for points props.
    """

    def __init__(self):
        self.nhl = NHLDataProvider()
        self.pipeline = PipelineAdapter()

    def build_context(
        self,
        player_name: str,
        stat_type: str,
        line: float,
        game_date: date,
        event_id: str = None,
        team: str = None,
        opponent: str = None,
        is_home: bool = None,
        use_pipeline: bool = True,
    ) -> Optional[PropContext]:
        """
        Build full context for a prop.

        Args:
            player_name: Player's full name
            stat_type: points, goals, assists, shots_on_goal, etc.
            line: Prop line (e.g., 0.5, 1.5)
            game_date: Date of the game
            event_id: Odds API event ID (optional)
            team: Player's team (helps with matching)
            opponent: Opposing team
            is_home: Whether player is home team
            use_pipeline: Whether to include pipeline context (default True)

        Returns:
            PropContext with all available data, or None if player not found
        """
        # =====================================================================
        # STEP 1: Get PRIMARY data from NHL API
        # =====================================================================
        player_ctx = self.nhl.get_player_stat_context(player_name, stat_type, team)

        if not player_ctx:
            # Try to find player in pipeline if NHL API fails
            if use_pipeline:
                pipeline_ctx = self.pipeline.get_prediction_context(player_name, game_date)
                if pipeline_ctx:
                    team = pipeline_ctx.get('team')
                    player_ctx = self.nhl.get_player_stat_context(player_name, stat_type, team)

        if not player_ctx:
            return None

        player_id = player_ctx['player_id']
        resolved_team = player_ctx.get('team') or team

        # =====================================================================
        # STEP 2: Get matchup context from NHL API
        # =====================================================================
        matchup_ctx = {}
        if opponent:
            matchup_ctx = self.nhl.get_matchup_context(
                resolved_team or '',
                opponent,
                is_home if is_home is not None else True
            )

        # =====================================================================
        # STEP 3: Build base context from NHL API data
        # =====================================================================
        ctx = PropContext(
            # Prop details
            player_id=player_id,
            player_name=player_ctx['player_name'],
            team=resolved_team or '',
            position=player_ctx.get('position', ''),
            stat_type=stat_type,
            line=line,

            # Game context
            game_id=event_id or '',
            game_date=str(game_date),
            opponent=opponent or '',
            is_home=is_home if is_home is not None else True,

            # PRIMARY: Season stats from NHL API
            season_games=player_ctx.get('season_games'),
            season_points=player_ctx.get('raw_season_stats', {}).get('season_points'),
            season_goals=player_ctx.get('raw_season_stats', {}).get('season_goals'),
            season_assists=player_ctx.get('raw_season_stats', {}).get('season_assists'),
            season_shots=player_ctx.get('raw_season_stats', {}).get('season_shots'),
            season_avg=player_ctx.get('season_avg'),

            # PRIMARY: Recent form from NHL API
            recent_games=player_ctx.get('recent_games'),
            recent_ppg=player_ctx.get('recent_avg'),  # Map to expected field name
            recent_avg=player_ctx.get('recent_avg'),
            point_streak=player_ctx.get('point_streak'),
            trend_direction=player_ctx.get('trend_direction'),
            trend_pct=player_ctx.get('trend_pct'),

            # PRIMARY: TOI from NHL API
            avg_toi_minutes=player_ctx.get('avg_toi_minutes'),

            # PRIMARY: Matchup from NHL API
            opposing_goalie_id=matchup_ctx.get('opposing_goalie_id'),
            opposing_goalie_name=matchup_ctx.get('opposing_goalie_name'),
            opposing_goalie_sv_pct=matchup_ctx.get('opposing_goalie_sv_pct'),
            opposing_goalie_gaa=matchup_ctx.get('opposing_goalie_gaa'),
            goalie_confirmed=matchup_ctx.get('goalie_confirmed'),
            opponent_ga_per_game=matchup_ctx.get('opponent_ga_per_game'),
            opponent_sa_per_game=matchup_ctx.get('opponent_sa_per_game'),
        )

        # =====================================================================
        # STEP 4: Enrich with SUPPLEMENTAL pipeline data (if available)
        # =====================================================================
        if use_pipeline:
            pipeline_ctx = self.pipeline.get_prediction_context(player_name, game_date)

            if pipeline_ctx:
                # Pipeline scores (SUPPLEMENTAL)
                ctx.pipeline_score = pipeline_ctx.get('final_score')
                ctx.pipeline_confidence = pipeline_ctx.get('confidence')
                ctx.pipeline_rank = pipeline_ctx.get('rank')
                ctx.is_scoreable = pipeline_ctx.get('is_scoreable', False)

                # Line deployment (SUPPLEMENTAL - valuable for points props!)
                ctx.line_number = pipeline_ctx.get('line_number')
                ctx.pp_unit = pipeline_ctx.get('pp_unit')

                # Situational (SUPPLEMENTAL)
                ctx.is_b2b = pipeline_ctx.get('is_b2b')

                # Override goalie if pipeline has confirmed data
                if pipeline_ctx.get('goalie_confirmed'):
                    ctx.opposing_goalie_name = pipeline_ctx.get('opposing_goalie_name')
                    ctx.opposing_goalie_sv_pct = pipeline_ctx.get('opposing_goalie_sv_pct')
                    ctx.opposing_goalie_gaa = pipeline_ctx.get('opposing_goalie_gaa')
                    ctx.goalie_confirmed = True

        return ctx

    def build_context_nhl_only(
        self,
        player_name: str,
        stat_type: str,
        line: float,
        game_date: date,
        team: str = None,
        opponent: str = None,
        is_home: bool = None,
        event_id: str = None,
    ) -> Optional[PropContext]:
        """
        Build context using NHL API ONLY (no pipeline).

        Use this for prop types the pipeline doesn't support:
        - shots_on_goal
        - blocked_shots
        - saves
        - goals_against
        """
        return self.build_context(
            player_name=player_name,
            stat_type=stat_type,
            line=line,
            game_date=game_date,
            event_id=event_id,
            team=team,
            opponent=opponent,
            is_home=is_home,
            use_pipeline=False,  # No pipeline
        )


# ============================================================================
# Test
# ============================================================================

if __name__ == '__main__':
    from datetime import date

    builder = PropContextBuilder()

    print("=" * 70)
    print("PROP CONTEXT BUILDER TEST")
    print("=" * 70)

    # Test 1: Points prop with pipeline (validated prop type)
    print("\n--- TEST 1: Points prop (with pipeline) ---")
    ctx = builder.build_context(
        player_name='Connor McDavid',
        stat_type='points',
        line=1.5,
        game_date=date.today(),
        team='EDM',
        opponent='TOR',
        is_home=False,
        use_pipeline=True,
    )

    if ctx:
        print(f"Player: {ctx.player_name} ({ctx.team})")
        print(f"Stat: {ctx.stat_type} line {ctx.line}")
        print(f"\nPRIMARY (NHL API):")
        print(f"  Season avg: {ctx.season_avg:.3f}")
        print(f"  Recent avg: {ctx.recent_avg:.3f}")
        print(f"  Trend: {ctx.trend_pct:+.1f}%")
        print(f"  Opposing goalie: {ctx.opposing_goalie_name} ({ctx.opposing_goalie_sv_pct:.3f})")
        print(f"\nSUPPLEMENTAL (Pipeline):")
        print(f"  Pipeline score: {ctx.pipeline_score}")
        print(f"  Pipeline rank: {ctx.pipeline_rank}")
        print(f"  Is scoreable: {ctx.is_scoreable}")
        print(f"  Line number: {ctx.line_number}")
        print(f"  PP unit: {ctx.pp_unit}")
        print(f"\nData sources:")
        print(f"  Has NHL API data: {ctx.has_nhl_api_data}")
        print(f"  Has pipeline data: {ctx.has_pipeline_data}")

    # Test 2: SOG prop (no pipeline support)
    print("\n--- TEST 2: SOG prop (NHL API only) ---")
    ctx2 = builder.build_context_nhl_only(
        player_name='Connor McDavid',
        stat_type='shots_on_goal',
        line=3.5,
        game_date=date.today(),
        team='EDM',
        opponent='TOR',
    )

    if ctx2:
        print(f"Player: {ctx2.player_name}")
        print(f"Stat: {ctx2.stat_type} line {ctx2.line}")
        print(f"Season avg: {ctx2.season_avg}")
        print(f"Has NHL API data: {ctx2.has_nhl_api_data}")
        print(f"Has pipeline data: {ctx2.has_pipeline_data}")
