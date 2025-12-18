#!/usr/bin/env python3
"""
Signal Backtest Engine for NHL SGP

Runs a comprehensive backtest with FULL SIGNAL STORAGE for weight optimization.
This is the NBA-style analysis: measure hit rate BY SIGNAL to find optimal weights.

Key difference from previous backtests:
- Stores all 6 signal breakdowns (line_value, trend, usage, matchup, environment, correlation)
- Uses historical context (no look-ahead bias)
- Enables signal-level hit rate analysis

Usage:
    python signal_backtest.py --start 2025-11-01 --end 2025-12-15
    python signal_backtest.py --start 2025-11-01 --end 2025-12-15 --dry-run
"""
import sys
import json
import argparse
from pathlib import Path
from datetime import datetime, date, timedelta
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, asdict, field

# Add paths
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent))

from nhl_sgp_engine.providers.odds_api_client import OddsAPIClient, PlayerProp
from nhl_sgp_engine.providers.nhl_data_provider import NHLDataProvider, normalize_team
from nhl_sgp_engine.edge_detection.edge_calculator import EdgeCalculator
from nhl_sgp_engine.signals.base import PropContext
from nhl_sgp_engine.config.settings import DATA_DIR
from providers.nhl_official_api import NHLOfficialAPI


@dataclass
class SignalBreakdown:
    """Individual signal result."""
    name: str
    strength: float  # -1.0 to +1.0
    confidence: float  # 0.0 to 1.0
    evidence: str
    raw_data: Dict = field(default_factory=dict)


@dataclass
class BacktestProp:
    """A single prop with full signal breakdown and outcome."""
    # Identification
    game_date: str
    event_id: str
    matchup: str
    player_name: str
    player_id: Optional[int]
    team: str

    # Prop details
    market_key: str
    stat_type: str
    line: float
    direction: str  # 'over' or 'under'
    odds: int

    # Edge calculation
    edge_pct: float
    model_prob: float
    market_prob: float
    confidence: float

    # FULL SIGNAL BREAKDOWN - the key addition
    signals: Dict[str, SignalBreakdown]

    # Context used (for debugging)
    context_snapshot: Dict

    # Contrarian mode tracking
    contrarian_applied: bool = False
    original_direction: Optional[str] = None

    # Outcome (filled after settlement)
    actual_value: Optional[float] = None
    hit: Optional[bool] = None
    settled: bool = False


class SignalBacktestEngine:
    """
    Runs backtests with full signal storage for weight optimization.

    Process:
    1. Fetch historical odds from Odds API (with caching)
    2. For each prop, build historical context using NHL API
    3. Run edge calculator - store ALL signal breakdowns
    4. Settle against box scores
    5. Output data ready for signal analysis
    """

    def __init__(
        self,
        use_cache: bool = True,
        contrarian_threshold: float = None,
        signal_isolation: str = None,
    ):
        """
        Initialize backtest engine.

        Args:
            use_cache: Whether to use cached API responses
            contrarian_threshold: If set, fade predictions when edge > this value.
                                  Based on backtest: 15%+ edge = 42.8% hit rate,
                                  fading = 57.2% theoretical hit rate.
            signal_isolation: If set, only use this single signal (e.g., 'line_value')
                              to test individual signal performance.
        """
        self.odds_client = OddsAPIClient()
        self.nhl_provider = NHLDataProvider()
        self.nhl_api = NHLOfficialAPI()
        self.contrarian_threshold = contrarian_threshold
        self.signal_isolation = signal_isolation

        # Initialize edge calculator with contrarian mode if specified
        self.edge_calculator = EdgeCalculator(
            contrarian_threshold=contrarian_threshold
        )
        self.use_cache = use_cache

        # Results storage
        self.props: List[BacktestProp] = []
        self.errors: List[Dict] = []

        # Stats
        self.api_calls_made = 0
        self.props_processed = 0
        self.props_with_context = 0

    def run_backtest(
        self,
        start_date: str,
        end_date: str,
        markets: List[str] = None,
        dry_run: bool = False,
    ) -> Dict:
        """
        Run full backtest with signal storage.

        Args:
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)
            markets: Markets to backtest (default: player_points, player_shots_on_goal)
            dry_run: If True, just estimate costs without fetching

        Returns:
            Summary statistics
        """
        # Player prop markets for actual betting
        markets = markets or ['player_points', 'player_shots_on_goal']

        # Also fetch game-level markets for correlation signal context
        # (totals = O/U for game scoring, needed for correlation signal)
        self.game_markets = ['totals', 'spreads']

        print("\n" + "=" * 70)
        print("NHL SGP SIGNAL BACKTEST ENGINE")
        print("=" * 70)
        print(f"Date range: {start_date} to {end_date}")
        print(f"Markets: {markets}")
        print(f"Dry run: {dry_run}")
        if self.contrarian_threshold:
            print(f"CONTRARIAN MODE: Fading predictions when edge > {self.contrarian_threshold}%")
        if self.signal_isolation:
            print(f"SIGNAL ISOLATION: Testing only '{self.signal_isolation}' signal")
        print("=" * 70 + "\n")

        # Parse dates
        start = datetime.strptime(start_date, "%Y-%m-%d").date()
        end = datetime.strptime(end_date, "%Y-%m-%d").date()

        if dry_run:
            return self._estimate_costs(start, end, markets)

        # Process each date
        current = start
        while current <= end:
            try:
                self._process_date(current, markets)
            except Exception as e:
                self.errors.append({
                    'date': str(current),
                    'error': str(e),
                    'type': 'date_processing'
                })
                print(f"  ERROR on {current}: {e}")

            current += timedelta(days=1)

        # Settle all props
        print("\n" + "-" * 50)
        print("SETTLING PROPS AGAINST BOX SCORES...")
        print("-" * 50)
        self._settle_all_props()

        # Generate summary
        summary = self._generate_summary()

        # Save results
        self._save_results(start_date, end_date)

        return summary

    def _estimate_costs(self, start: date, end: date, markets: List[str]) -> Dict:
        """Estimate API costs without fetching."""
        num_days = (end - start).days + 1

        # Estimate games per day (NHL averages ~12-14)
        est_games_per_day = 13
        est_total_games = num_days * est_games_per_day

        # Cost breakdown:
        # - Player props: 10 per market per region per event
        # - Game markets (totals, spreads): 10 per market per region per event
        player_prop_cost = 10 * len(markets) * 1  # player props
        game_market_cost = 10 * 2 * 1  # totals + spreads for correlation signal
        cost_per_game = player_prop_cost + game_market_cost
        events_cost = num_days  # 1 per day for event listing

        total_cost = (est_total_games * cost_per_game) + events_cost

        print(f"COST ESTIMATE:")
        print(f"  Days: {num_days}")
        print(f"  Est. games: {est_total_games}")
        print(f"  Player prop markets: {len(markets)} ({markets})")
        print(f"  Game-level markets: 2 (totals, spreads - for correlation signal)")
        print(f"  Cost per game: {cost_per_game} ({player_prop_cost} props + {game_market_cost} game)")
        print(f"  Events queries: {events_cost}")
        print(f"  TOTAL ESTIMATED: {total_cost:,} API calls")
        print(f"  Current remaining: {self.odds_client.usage.requests_remaining:,}")
        print(f"  Budget: 25,000")
        print(f"  Headroom: {25000 - total_cost:,} calls")

        return {
            'dry_run': True,
            'estimated_days': num_days,
            'estimated_games': est_total_games,
            'estimated_cost': total_cost,
            'budget': 25000,
            'headroom': 25000 - total_cost,
        }

    def _process_date(self, game_date: date, markets: List[str]):
        """Process all games for a single date."""
        date_str = game_date.strftime('%Y-%m-%d')
        print(f"\n[{date_str}] Fetching games...")

        # Get historical events for this date
        events = self.odds_client.get_historical_events(date_str, use_cache=self.use_cache)

        if not events:
            print(f"  No events found for {date_str}")
            return

        print(f"  Found {len(events)} games")

        # Process each event
        for event in events:
            event_id = event.get('id')
            home_team = event.get('home_team', '')
            away_team = event.get('away_team', '')
            matchup = f"{away_team}@{home_team}"

            print(f"  [{matchup}] Fetching props...")

            try:
                # Fetch game-level odds (totals, spreads) for correlation signal
                game_context = self._fetch_game_context(event_id, date_str)

                # Get historical odds for this event (player props)
                odds_data = self.odds_client.get_historical_event_odds(
                    event_id=event_id,
                    date_str=date_str,
                    markets=markets,
                    use_cache=self.use_cache,
                )

                if not odds_data or 'data' not in odds_data:
                    print(f"    No odds data")
                    continue

                # Parse player props
                props = self.odds_client.parse_player_props(
                    odds_data.get('data', {}),
                    market_keys=markets,
                )

                print(f"    Found {len(props)} props (total: {game_context.get('game_total')}, spread: {game_context.get('spread')})")

                # Process each prop with game context
                for prop in props:
                    self._process_prop(prop, game_date, matchup, home_team, away_team, game_context)

            except Exception as e:
                self.errors.append({
                    'date': date_str,
                    'event_id': event_id,
                    'matchup': matchup,
                    'error': str(e),
                    'type': 'event_processing'
                })
                print(f"    ERROR: {e}")

    def _fetch_game_context(self, event_id: str, date_str: str) -> Dict:
        """Fetch game totals and spreads for correlation signal."""
        try:
            game_odds = self.odds_client.get_historical_event_odds(
                event_id=event_id,
                date_str=date_str,
                markets=['totals', 'spreads'],
                use_cache=self.use_cache,
            )

            if not game_odds or 'data' not in game_odds:
                return {'game_total': None, 'spread': None}

            data = game_odds.get('data', {})
            game_total = None
            spread = None

            # Parse totals and spreads from bookmakers
            for bm in data.get('bookmakers', []):
                for market in bm.get('markets', []):
                    if market.get('key') == 'totals':
                        for outcome in market.get('outcomes', []):
                            if outcome.get('name') == 'Over':
                                game_total = outcome.get('point')
                                break
                    elif market.get('key') == 'spreads':
                        for outcome in market.get('outcomes', []):
                            # Get home team spread
                            if outcome.get('name') == data.get('home_team'):
                                spread = outcome.get('point')
                                break

                # Found both, stop searching
                if game_total is not None and spread is not None:
                    break

            return {'game_total': game_total, 'spread': spread}

        except Exception as e:
            return {'game_total': None, 'spread': None}

    def _process_prop(
        self,
        prop: PlayerProp,
        game_date: date,
        matchup: str,
        home_team: str,
        away_team: str,
        game_context: Dict = None,
    ):
        """Process a single prop with full signal calculation."""
        self.props_processed += 1
        game_context = game_context or {}

        # Determine player's team and opponent
        player_team, opponent, is_home = self._find_player_team(
            prop.player_name, home_team, away_team
        )

        if not player_team:
            # Can't determine team, skip
            return

        # Build historical context (no look-ahead bias)
        context = self._build_historical_context(
            player_name=prop.player_name,
            team=player_team,
            opponent=opponent,
            stat_type=prop.stat_type,
            game_date=game_date,
            is_home=is_home,
        )

        # Add game-level context for correlation signal
        if context:
            context['game_total'] = game_context.get('game_total')
            context['spread'] = game_context.get('spread')

        if not context:
            # Couldn't build context
            return

        self.props_with_context += 1

        # Build PropContext for edge calculator
        prop_context = PropContext(
            player_id=context.get('player_id', 0),
            player_name=prop.player_name,
            team=player_team,
            position=context.get('position', ''),
            stat_type=prop.stat_type,
            line=prop.line,
            game_id=prop.event_id,
            game_date=str(game_date),
            opponent=opponent,
            is_home=is_home,
            # Season stats (from historical context)
            season_games=context.get('season_games', 0),
            season_avg=context.get('season_avg', 0),
            # Recent form - TrendSignal uses recent_ppg
            recent_games=context.get('recent_games', 0),
            recent_avg=context.get('recent_avg', 0),
            recent_ppg=context.get('recent_avg', 0),  # Map recent_avg to recent_ppg for TrendSignal
            # TOI
            avg_toi_minutes=context.get('avg_toi_minutes', 0),
            # NEW: Line deployment (inferred from TOI and PP production)
            line_number=context.get('line_number'),  # 1-4 inferred from TOI
            pp_unit=context.get('pp_unit'),  # 0/1/2 inferred from PP production
            # Goalie matchup
            opposing_goalie_name=context.get('opp_goalie_name'),
            opposing_goalie_sv_pct=context.get('opp_goalie_sv_pct', 0.900),
            opposing_goalie_gaa=context.get('opp_goalie_gaa', 3.0),
            # Betting context
            game_total=context.get('game_total'),
            spread=context.get('spread'),
            # Environment
            is_b2b=context.get('is_b2b', False),
        )

        # Calculate edge with full signal breakdown
        try:
            edge_result = self.edge_calculator.calculate_edge(
                prop_context,
                prop.over_price,
                prop.under_price,
            )
        except Exception as e:
            self.errors.append({
                'player': prop.player_name,
                'stat': prop.stat_type,
                'error': str(e),
                'type': 'edge_calculation'
            })
            return

        # Extract signal breakdown
        signals = {}
        for sig_name, sig_data in edge_result.signals.items():
            signals[sig_name] = SignalBreakdown(
                name=sig_name,
                strength=sig_data.get('strength', 0),
                confidence=sig_data.get('confidence', 0),
                evidence=sig_data.get('evidence', ''),
                raw_data=sig_data.get('raw_data', {}),
            )

        # Create BacktestProp
        backtest_prop = BacktestProp(
            game_date=str(game_date),
            event_id=prop.event_id,
            matchup=matchup,
            player_name=prop.player_name,
            player_id=context.get('player_id'),
            team=player_team,
            market_key=prop.market_key,
            stat_type=prop.stat_type,
            line=prop.line,
            direction=edge_result.direction,
            odds=prop.over_price if edge_result.direction == 'over' else prop.under_price,
            edge_pct=edge_result.edge_pct,
            model_prob=edge_result.model_probability,
            market_prob=edge_result.market_probability,
            confidence=edge_result.confidence,
            signals=signals,
            context_snapshot={
                'season_games': context.get('season_games'),
                'season_avg': context.get('season_avg'),
                'recent_avg': context.get('recent_avg'),
                'opp_goalie': context.get('opp_goalie_name'),
            },
            contrarian_applied=edge_result.contrarian_applied,
            original_direction=edge_result.original_direction,
        )

        self.props.append(backtest_prop)

    def _find_player_team(
        self,
        player_name: str,
        home_team: str,
        away_team: str,
    ) -> Tuple[Optional[str], Optional[str], bool]:
        """Determine which team the player is on."""
        # Try home team first
        home_abbrev = normalize_team(home_team)
        away_abbrev = normalize_team(away_team)

        # Search home roster
        try:
            home_roster = self.nhl_api.get_team_roster(home_abbrev)
            for player in home_roster:
                if self._names_match(player_name, player.get('name', '')):
                    return home_abbrev, away_abbrev, True
        except:
            pass

        # Search away roster
        try:
            away_roster = self.nhl_api.get_team_roster(away_abbrev)
            for player in away_roster:
                if self._names_match(player_name, player.get('name', '')):
                    return away_abbrev, home_abbrev, False
        except:
            pass

        return None, None, False

    def _names_match(self, name1: str, name2: str) -> bool:
        """Fuzzy name matching."""
        n1 = name1.lower().strip()
        n2 = name2.lower().strip()

        # Exact match
        if n1 == n2:
            return True

        # One contains the other
        if n1 in n2 or n2 in n1:
            return True

        # Last name match (handle "J. Smith" vs "John Smith")
        parts1 = n1.split()
        parts2 = n2.split()
        if parts1 and parts2:
            if parts1[-1] == parts2[-1]:  # Last names match
                # Check if first initial matches
                if parts1[0][0] == parts2[0][0]:
                    return True

        return False

    def _build_historical_context(
        self,
        player_name: str,
        team: str,
        opponent: str,
        stat_type: str,
        game_date: date,
        is_home: bool,
    ) -> Optional[Dict]:
        """
        Build context using only data available BEFORE the game date.
        No look-ahead bias.
        """
        # Find player ID
        player_info = self.nhl_provider.get_player_by_name(player_name, team)
        if not player_info:
            return None

        player_id = player_info['player_id']

        # Get game log (includes all games with dates)
        game_log = self.nhl_api.get_player_game_log(player_id, num_games=50)

        # Filter to games BEFORE target date
        games_before = [
            g for g in game_log
            if datetime.strptime(g['game_date'], '%Y-%m-%d').date() < game_date
        ]

        if len(games_before) < 3:
            # Not enough historical data
            return None

        # Calculate stats from historical games only
        stat_map = {
            'points': 'points',
            'goals': 'goals',
            'assists': 'assists',
            'shots_on_goal': 'shots',
        }
        stat_key = stat_map.get(stat_type, 'points')

        # Season totals (all games before this date)
        season_total = sum(g.get(stat_key, 0) for g in games_before)
        season_games = len(games_before)
        season_avg = season_total / season_games if season_games > 0 else 0

        # Recent form (L5 or L10 before this date)
        recent_games = games_before[:10]  # Already sorted most recent first
        recent_total = sum(g.get(stat_key, 0) for g in recent_games)
        recent_count = len(recent_games)
        recent_avg = recent_total / recent_count if recent_count > 0 else 0

        # Average TOI
        toi_values = []
        for g in games_before[:10]:
            toi_str = g.get('toi', '0:00')
            if toi_str and ':' in toi_str:
                mins, secs = toi_str.split(':')
                toi_values.append(int(mins) + int(secs) / 60)
        avg_toi = sum(toi_values) / len(toi_values) if toi_values else 0

        # Get opponent goalie info (current, not historical - acceptable approximation)
        opp_goalie = self.nhl_provider.get_opposing_goalie(opponent)

        # Check for back-to-back (look at previous game date)
        is_b2b = False
        if games_before:
            last_game_date = datetime.strptime(games_before[0]['game_date'], '%Y-%m-%d').date()
            if (game_date - last_game_date).days == 1:
                is_b2b = True

        # =========================================================================
        # INFER LINE NUMBER FROM TOI (higher TOI = higher line)
        # This is a proxy for L1/L2/L3/L4 deployment since we don't have DailyFaceoff
        # =========================================================================
        position = player_info.get('position', '')
        line_number = self._infer_line_from_toi(avg_toi, position)

        # =========================================================================
        # INFER PP UNIT FROM PP PRODUCTION
        # Players with PP goals/points are likely on PP1 or PP2
        # =========================================================================
        pp_goals = sum(g.get('pp_goals', 0) for g in games_before)
        pp_points = sum(g.get('pp_points', 0) for g in games_before)
        pp_unit = self._infer_pp_unit_from_production(pp_goals, pp_points, season_games)

        return {
            'player_id': player_id,
            'position': position,
            'season_games': season_games,
            'season_total': season_total,
            'season_avg': round(season_avg, 3),
            'recent_games': recent_count,
            'recent_total': recent_total,
            'recent_avg': round(recent_avg, 3),
            'avg_toi_minutes': round(avg_toi, 1),
            # NEW: Line deployment inference
            'line_number': line_number,
            'pp_unit': pp_unit,
            'pp_goals': pp_goals,
            'pp_points': pp_points,
            # Goalie matchup
            'opp_goalie_name': opp_goalie.get('name') if opp_goalie else None,
            'opp_goalie_sv_pct': opp_goalie.get('save_pct', 0.900) if opp_goalie else 0.900,
            'opp_goalie_gaa': opp_goalie.get('gaa', 3.0) if opp_goalie else 3.0,
            'is_b2b': is_b2b,
            'game_total': None,  # Would need historical odds lookup
            'spread': None,
        }

    def _infer_line_from_toi(self, avg_toi: float, position: str) -> int:
        """
        Infer line number from average TOI.

        Thresholds based on NHL averages:
        - L1 forwards: 18+ min, L2: 15-18, L3: 12-15, L4: <12
        - D1 pair: 22+ min, D2: 18-22, D3: <18

        Args:
            avg_toi: Average time on ice in minutes
            position: Player position (C, LW, RW, D)

        Returns:
            Line number 1-4 (or pair number for D)
        """
        if position == 'D':
            # Defensemen - pairs
            if avg_toi >= 22:
                return 1  # Top pair
            elif avg_toi >= 18:
                return 2  # Second pair
            else:
                return 3  # Third pair
        else:
            # Forwards
            if avg_toi >= 18:
                return 1  # First line
            elif avg_toi >= 15:
                return 2  # Second line
            elif avg_toi >= 12:
                return 3  # Third line
            else:
                return 4  # Fourth line

    def _infer_pp_unit_from_production(self, pp_goals: int, pp_points: int, games: int) -> int:
        """
        Infer PP unit from power play production.

        Thresholds:
        - PP1: High PP production (>= 0.2 PP points/game)
        - PP2: Some PP production (>= 0.05 PP points/game)
        - 0: Little to no PP time

        Args:
            pp_goals: Total PP goals in sample
            pp_points: Total PP points in sample
            games: Number of games in sample

        Returns:
            PP unit: 0 (no PP), 1 (PP1), or 2 (PP2)
        """
        if games == 0:
            return 0

        pp_rate = pp_points / games

        if pp_rate >= 0.2:
            return 1  # PP1 - significant PP production
        elif pp_rate >= 0.05:
            return 2  # PP2 - some PP production
        else:
            return 0  # Not a regular PP player

    def _settle_all_props(self):
        """Settle all props against box scores."""
        # Group by date for efficiency
        props_by_date = {}
        for prop in self.props:
            if prop.game_date not in props_by_date:
                props_by_date[prop.game_date] = []
            props_by_date[prop.game_date].append(prop)

        settled_count = 0

        for date_str, date_props in props_by_date.items():
            game_date = datetime.strptime(date_str, '%Y-%m-%d').date()

            # Get games for this date
            games = self.nhl_api.get_games_by_date(game_date)

            # Get box scores for completed games
            box_scores = {}
            for game in games:
                if game['game_state'] in ['OFF', 'FINAL']:
                    box = self.nhl_api.get_box_score(game['game_id'])
                    if box:
                        box_scores[game['game_id']] = box

            # Settle each prop
            for prop in date_props:
                actual = self._find_player_stat(
                    prop.player_name,
                    prop.stat_type,
                    box_scores,
                )

                if actual is not None:
                    prop.actual_value = actual
                    prop.settled = True

                    # Determine if hit
                    if prop.direction == 'over':
                        prop.hit = actual > prop.line
                    else:
                        prop.hit = actual < prop.line

                    settled_count += 1

        print(f"  Settled {settled_count}/{len(self.props)} props")

    def _find_player_stat(
        self,
        player_name: str,
        stat_type: str,
        box_scores: Dict[int, Dict],
    ) -> Optional[float]:
        """Find player's stat from box scores."""
        stat_map = {
            'points': 'points',
            'goals': 'goals',
            'assists': 'assists',
            'shots_on_goal': 'shots',
        }
        stat_key = stat_map.get(stat_type, 'points')

        for game_id, box in box_scores.items():
            for player in box.get('players', []):
                if self._names_match(player_name, player.get('name', '')):
                    return player.get(stat_key, 0)

        return None

    def _generate_summary(self) -> Dict:
        """Generate comprehensive summary statistics."""
        total = len(self.props)
        settled = [p for p in self.props if p.settled]
        hits = [p for p in settled if p.hit]

        # Contrarian stats
        contrarian_props = [p for p in settled if p.contrarian_applied]
        contrarian_hits = [p for p in contrarian_props if p.hit]

        # Overall metrics
        summary = {
            'total_props': total,
            'settled_props': len(settled),
            'unsettled_props': total - len(settled),
            'hit_count': len(hits),
            'hit_rate': len(hits) / len(settled) * 100 if settled else 0,
            'with_context': self.props_with_context,
            'errors': len(self.errors),
            # Contrarian mode stats
            'contrarian_mode': self.contrarian_threshold is not None,
            'contrarian_threshold': self.contrarian_threshold,
            'contrarian_props': len(contrarian_props),
            'contrarian_hits': len(contrarian_hits),
            'contrarian_hit_rate': len(contrarian_hits) / len(contrarian_props) * 100 if contrarian_props else 0,
        }

        # By market
        by_market = {}
        for prop in settled:
            if prop.market_key not in by_market:
                by_market[prop.market_key] = {'total': 0, 'hits': 0}
            by_market[prop.market_key]['total'] += 1
            if prop.hit:
                by_market[prop.market_key]['hits'] += 1

        for market, stats in by_market.items():
            stats['hit_rate'] = stats['hits'] / stats['total'] * 100 if stats['total'] > 0 else 0
        summary['by_market'] = by_market

        # By edge bucket
        by_edge = {
            'negative': {'total': 0, 'hits': 0},
            '0-5%': {'total': 0, 'hits': 0},
            '5-10%': {'total': 0, 'hits': 0},
            '10-15%': {'total': 0, 'hits': 0},
            '15%+': {'total': 0, 'hits': 0},
        }

        for prop in settled:
            edge = prop.edge_pct
            if edge < 0:
                bucket = 'negative'
            elif edge < 5:
                bucket = '0-5%'
            elif edge < 10:
                bucket = '5-10%'
            elif edge < 15:
                bucket = '10-15%'
            else:
                bucket = '15%+'

            by_edge[bucket]['total'] += 1
            if prop.hit:
                by_edge[bucket]['hits'] += 1

        for bucket, stats in by_edge.items():
            stats['hit_rate'] = stats['hits'] / stats['total'] * 100 if stats['total'] > 0 else 0
        summary['by_edge_bucket'] = by_edge

        # SIGNAL ANALYSIS - the key output
        signal_analysis = self._analyze_signals(settled)
        summary['signal_analysis'] = signal_analysis

        # Print summary
        self._print_summary(summary)

        return summary

    def _analyze_signals(self, settled_props: List[BacktestProp]) -> Dict:
        """
        Analyze hit rate by signal - the core NBA-style analysis.

        For each signal, we look at:
        - Hit rate when signal is positive (strength > 0.1)
        - Hit rate when signal is negative (strength < -0.1)
        - Hit rate when signal is neutral
        - Average strength of signal in hits vs misses
        """
        signal_names = ['line_value', 'trend', 'usage', 'matchup', 'environment', 'correlation']

        analysis = {}

        for sig_name in signal_names:
            sig_stats = {
                'positive_count': 0,
                'positive_hits': 0,
                'negative_count': 0,
                'negative_hits': 0,
                'neutral_count': 0,
                'neutral_hits': 0,
                'avg_strength_in_hits': 0,
                'avg_strength_in_misses': 0,
                'hit_strengths': [],
                'miss_strengths': [],
            }

            for prop in settled_props:
                if sig_name not in prop.signals:
                    continue

                signal = prop.signals[sig_name]
                strength = signal.strength

                # Categorize by strength direction (lowered threshold to 0.05 to capture more variance)
                if strength > 0.05:
                    sig_stats['positive_count'] += 1
                    if prop.hit:
                        sig_stats['positive_hits'] += 1
                elif strength < -0.05:
                    sig_stats['negative_count'] += 1
                    if prop.hit:
                        sig_stats['negative_hits'] += 1
                else:
                    sig_stats['neutral_count'] += 1
                    if prop.hit:
                        sig_stats['neutral_hits'] += 1

                # Track strengths for averaging
                if prop.hit:
                    sig_stats['hit_strengths'].append(strength)
                else:
                    sig_stats['miss_strengths'].append(strength)

            # Calculate rates and averages
            sig_stats['positive_hit_rate'] = (
                sig_stats['positive_hits'] / sig_stats['positive_count'] * 100
                if sig_stats['positive_count'] > 0 else 0
            )
            sig_stats['negative_hit_rate'] = (
                sig_stats['negative_hits'] / sig_stats['negative_count'] * 100
                if sig_stats['negative_count'] > 0 else 0
            )
            sig_stats['neutral_hit_rate'] = (
                sig_stats['neutral_hits'] / sig_stats['neutral_count'] * 100
                if sig_stats['neutral_count'] > 0 else 0
            )

            if sig_stats['hit_strengths']:
                sig_stats['avg_strength_in_hits'] = sum(sig_stats['hit_strengths']) / len(sig_stats['hit_strengths'])
            if sig_stats['miss_strengths']:
                sig_stats['avg_strength_in_misses'] = sum(sig_stats['miss_strengths']) / len(sig_stats['miss_strengths'])

            # Calculate predictive value
            # If positive signal → higher hit rate, that's good
            # If negative signal → lower hit rate, that's also good (inverse works)
            sig_stats['predictive_value'] = abs(
                sig_stats['positive_hit_rate'] - sig_stats['negative_hit_rate']
            )

            # Clean up internal lists
            del sig_stats['hit_strengths']
            del sig_stats['miss_strengths']

            analysis[sig_name] = sig_stats

        return analysis

    def _print_summary(self, summary: Dict):
        """Print formatted summary."""
        print("\n" + "=" * 70)
        print("BACKTEST RESULTS")
        print("=" * 70)

        print(f"\nTotal props processed: {summary['total_props']}")
        print(f"Props with context: {summary['with_context']}")
        print(f"Props settled: {summary['settled_props']}")
        print(f"Overall hit rate: {summary['hit_rate']:.1f}%")

        # Contrarian mode results
        if summary.get('contrarian_mode'):
            print(f"\n--- CONTRARIAN MODE (threshold: {summary['contrarian_threshold']}%) ---")
            print(f"Props where contrarian was applied: {summary['contrarian_props']}")
            print(f"Contrarian hit rate: {summary['contrarian_hit_rate']:.1f}%")
            if summary['contrarian_props'] > 0:
                print(f"Contrarian hits: {summary['contrarian_hits']}/{summary['contrarian_props']}")

        print("\n--- By Market ---")
        for market, stats in summary.get('by_market', {}).items():
            print(f"  {market}: {stats['hit_rate']:.1f}% ({stats['hits']}/{stats['total']})")

        print("\n--- By Edge Bucket ---")
        for bucket, stats in summary.get('by_edge_bucket', {}).items():
            if stats['total'] > 0:
                print(f"  {bucket}: {stats['hit_rate']:.1f}% ({stats['hits']}/{stats['total']})")

        print("\n" + "=" * 70)
        print("SIGNAL ANALYSIS (NBA-style)")
        print("=" * 70)

        signals = summary.get('signal_analysis', {})

        # Sort by predictive value
        sorted_signals = sorted(
            signals.items(),
            key=lambda x: x[1].get('predictive_value', 0),
            reverse=True
        )

        print("\n| Signal       | Pos→Hit% | Neg→Hit% | Predictive | Recommendation |")
        print("|--------------|----------|----------|------------|----------------|")

        for sig_name, stats in sorted_signals:
            pos_rate = stats.get('positive_hit_rate', 0)
            neg_rate = stats.get('negative_hit_rate', 0)
            pred = stats.get('predictive_value', 0)

            # Recommendation based on NBA learnings
            if pred > 15:
                rec = "↑ INCREASE"
            elif pred < 5:
                rec = "↓ DECREASE"
            else:
                rec = "→ MAINTAIN"

            print(f"| {sig_name:12} | {pos_rate:7.1f}% | {neg_rate:7.1f}% | {pred:9.1f}% | {rec:14} |")

        print("\nPredictive Value = |Positive Hit Rate - Negative Hit Rate|")
        print("Higher = signal direction correlates with outcomes")

    def _save_results(self, start_date: str, end_date: str):
        """Save all results to JSON files."""
        output_dir = DATA_DIR / 'signal_backtest'
        output_dir.mkdir(exist_ok=True)

        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')

        # Convert props to serializable format
        props_data = []
        for prop in self.props:
            prop_dict = asdict(prop)
            # Convert SignalBreakdown objects
            prop_dict['signals'] = {
                name: asdict(sig) for name, sig in prop.signals.items()
            }
            props_data.append(prop_dict)

        # Save detailed results
        detailed_file = output_dir / f"signal_backtest_{start_date}_{end_date}_{timestamp}.json"
        with open(detailed_file, 'w') as f:
            json.dump({
                'meta': {
                    'start_date': start_date,
                    'end_date': end_date,
                    'generated_at': datetime.now().isoformat(),
                    'total_props': len(self.props),
                },
                'props': props_data,
                'errors': self.errors,
            }, f, indent=2, default=str)

        print(f"\nResults saved to: {detailed_file}")

        # Save summary
        summary_file = output_dir / f"signal_summary_{start_date}_{end_date}_{timestamp}.json"
        summary = self._generate_summary()
        with open(summary_file, 'w') as f:
            json.dump(summary, f, indent=2, default=str)

        print(f"Summary saved to: {summary_file}")


def main():
    parser = argparse.ArgumentParser(description='NHL SGP Signal Backtest')
    parser.add_argument('--start', required=True, help='Start date (YYYY-MM-DD)')
    parser.add_argument('--end', required=True, help='End date (YYYY-MM-DD)')
    parser.add_argument('--markets', nargs='+',
                       default=['player_points', 'player_shots_on_goal'],
                       help='Markets to backtest')
    parser.add_argument('--dry-run', action='store_true', help='Estimate costs only')
    parser.add_argument('--no-cache', action='store_true', help='Disable caching')
    parser.add_argument('--contrarian', type=float, default=None,
                       help='Contrarian threshold - fade when edge > this value (e.g., 10.0)')
    parser.add_argument('--signal-isolation', type=str, default=None,
                       help='Test single signal in isolation (e.g., line_value, trend, usage)')

    args = parser.parse_args()

    engine = SignalBacktestEngine(
        use_cache=not args.no_cache,
        contrarian_threshold=args.contrarian,
        signal_isolation=args.signal_isolation,
    )

    summary = engine.run_backtest(
        start_date=args.start,
        end_date=args.end,
        markets=args.markets,
        dry_run=args.dry_run,
    )

    if not args.dry_run:
        print("\n" + "=" * 70)
        print("BACKTEST COMPLETE")
        print("=" * 70)
        print(f"\nSettled props: {summary.get('settled_props', 0)}")
        print(f"Hit rate: {summary.get('hit_rate', 0):.1f}%")
        print("\nNext step: Review signal_analysis for weight optimization")


if __name__ == '__main__':
    main()
