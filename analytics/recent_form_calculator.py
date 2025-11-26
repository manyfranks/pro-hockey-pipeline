# nhl_isolated/analytics/recent_form_calculator.py
"""
Recent Form Calculator for NHL Player Points Algorithm

Calculates the recent form score (now 20% of final score) based on:
- Points per game (PPG) over last 10 games
- Goal/assist split
- Point streak bonus (REDUCED - chasing hot streaks doesn't work)

UPDATED 2024-11-25: Based on empirical analysis:
- Players with PPG 3.0+ had WORST hit rate (11.9%) - regression to mean
- Players with PPG 2.0-3.0 had BEST hit rate (21.6%) - sweet spot
- Added PPG_CAP to prevent over-crediting hot streaks that will regress

References NHL_ALGORITHM_ADR.md Section 2.1
"""
from typing import Dict, Any, List, Optional
import pandas as pd


# League average benchmarks (2024-25 season approximations)
LEAGUE_AVG_PPG = 0.50  # ~0.5 points per game for average player
ELITE_PPG = 1.50       # Elite scorers (McDavid, Draisaitl level)

# PPG CAP - Players above this get NO additional credit (regression to mean risk)
# Analysis showed 3.0+ PPG players had WORST hit rate (11.9%)
# Sweet spot is 2.0-3.0 PPG (21.6% hit rate)
PPG_CAP = 2.0  # Cap at 2.0 PPG - anything above this is regression risk

# Streak bonuses - REDUCED since chasing hot streaks leads to regression
STREAK_BONUS_3_GAMES = 0.02   # 3+ consecutive games with point (was 0.05)
STREAK_BONUS_5_GAMES = 0.05   # 5+ consecutive games with point (was 0.10)


def calculate_recent_form_score(player_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Calculate the recent form score for a player.

    This is the PRIMARY scoring component (50% weight).

    Args:
        player_data: Enriched player dictionary from enrichment pipeline

    Returns:
        Dictionary with:
        - recent_form_score: Normalized score (0-1 scale)
        - recent_form_raw: Raw PPG value
        - streak_bonus: Bonus applied for point streak
        - form_details: Breakdown of calculation
    """
    # Extract recent stats
    recent_ppg = player_data.get('recent_ppg', 0.0)
    recent_games = player_data.get('recent_games', 0)
    recent_points = player_data.get('recent_points', 0)
    recent_goals = player_data.get('recent_goals', 0)
    recent_assists = player_data.get('recent_assists', 0)
    point_streak = player_data.get('point_streak', 0)

    # Handle insufficient data
    if recent_games < 3:
        # Not enough games - use season stats as fallback
        season_games = player_data.get('season_games', 0)
        season_points = player_data.get('season_points', 0)

        if season_games > 0:
            recent_ppg = season_points / season_games
        else:
            recent_ppg = LEAGUE_AVG_PPG * 0.5  # Unknown player - below average

    # Apply PPG cap to prevent regression-to-mean issues
    # Players with 3.0+ PPG had WORST hit rate - cap at 2.0 PPG
    capped_ppg = min(recent_ppg, PPG_CAP)

    # Normalize capped PPG to 0-1 scale
    # League avg (0.5 PPG) = 0.33
    # Elite (1.5 PPG) = 1.0
    # Cap at 1.0
    normalized_ppg = min(capped_ppg / ELITE_PPG, 1.0)

    # Calculate streak bonus
    streak_bonus = 0.0
    if point_streak >= 5:
        streak_bonus = STREAK_BONUS_5_GAMES
    elif point_streak >= 3:
        streak_bonus = STREAK_BONUS_3_GAMES

    # Final form score (with streak bonus capped)
    recent_form_score = min(normalized_ppg + streak_bonus, 1.0)

    # Goal/assist ratio (for context, not used in scoring)
    goal_ratio = recent_goals / recent_points if recent_points > 0 else 0.0

    return {
        'recent_form_score': round(recent_form_score, 4),
        'recent_form_raw': round(recent_ppg, 3),
        'streak_bonus': round(streak_bonus, 3),
        'form_details': {
            'recent_games': recent_games,
            'recent_points': recent_points,
            'recent_goals': recent_goals,
            'recent_assists': recent_assists,
            'point_streak': point_streak,
            'goal_ratio': round(goal_ratio, 3),
            'raw_ppg': round(recent_ppg, 4),
            'capped_ppg': round(capped_ppg, 4),  # PPG after cap applied
            'ppg_was_capped': recent_ppg > PPG_CAP,  # Flag if cap was applied
            'normalized_ppg': round(normalized_ppg, 4),
        }
    }


def calculate_recent_form_batch(players: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Calculate recent form scores for a batch of players.

    Args:
        players: List of enriched player dictionaries

    Returns:
        Players with recent form scores added
    """
    for player in players:
        form_result = calculate_recent_form_score(player)

        # Add to player dict
        player['recent_form_score'] = form_result['recent_form_score']
        player['recent_form_raw'] = form_result['recent_form_raw']
        player['streak_bonus'] = form_result['streak_bonus']
        player['form_details'] = form_result['form_details']

    return players


def analyze_form_distribution(players: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Analyze the distribution of recent form scores.

    Useful for calibration and debugging.

    Returns:
        Statistics about the form score distribution
    """
    if not players:
        return {}

    scores = [p.get('recent_form_score', 0) for p in players]

    df = pd.Series(scores)

    return {
        'count': len(scores),
        'mean': round(df.mean(), 4),
        'std': round(df.std(), 4),
        'min': round(df.min(), 4),
        'max': round(df.max(), 4),
        'percentiles': {
            '25%': round(df.quantile(0.25), 4),
            '50%': round(df.quantile(0.50), 4),
            '75%': round(df.quantile(0.75), 4),
            '90%': round(df.quantile(0.90), 4),
        }
    }


if __name__ == '__main__':
    # Test with sample data
    import json

    sample_players = [
        {
            'player_name': 'Connor McDavid',
            'recent_ppg': 2.0,
            'recent_games': 10,
            'recent_points': 20,
            'recent_goals': 8,
            'recent_assists': 12,
            'point_streak': 7,
            'season_games': 20,
            'season_points': 40,
        },
        {
            'player_name': 'Average Player',
            'recent_ppg': 0.5,
            'recent_games': 10,
            'recent_points': 5,
            'recent_goals': 2,
            'recent_assists': 3,
            'point_streak': 0,
            'season_games': 20,
            'season_points': 10,
        },
        {
            'player_name': 'Cold Player',
            'recent_ppg': 0.1,
            'recent_games': 10,
            'recent_points': 1,
            'recent_goals': 0,
            'recent_assists': 1,
            'point_streak': 0,
            'season_games': 20,
            'season_points': 8,
        },
    ]

    players = calculate_recent_form_batch(sample_players)

    print("Recent Form Calculation Test Results:")
    print("=" * 60)
    for p in players:
        print(f"\n{p['player_name']}:")
        print(f"  Recent PPG: {p['recent_form_raw']}")
        print(f"  Form Score: {p['recent_form_score']}")
        print(f"  Streak Bonus: {p['streak_bonus']}")

    print("\n\nDistribution Analysis:")
    print(json.dumps(analyze_form_distribution(players), indent=2))
