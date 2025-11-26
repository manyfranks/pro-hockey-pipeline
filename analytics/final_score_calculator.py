# nhl_isolated/analytics/final_score_calculator.py
"""
Final Score Calculator for NHL Player Points Algorithm

Combines all scoring components into a unified final score.

WEIGHTS UPDATED 2024-11-25 based on empirical analysis:
- Correlation analysis showed line_opportunity is the BEST predictor (r=+0.14)
- Recent form is NEGATIVELY correlated in top ranks (r=-0.09) - regression to mean
- PP1 status is more predictive than line number

GOALIE WEAKNESS - CONDITIONAL USAGE (Updated 2024-11-25):
- Raw goalie_weakness as a standalone weight was HURTING predictions (r=-0.04)
- Paradox: Players facing GOOD goalies had BETTER hit rates than those facing BAD goalies
- Root cause: Confounding variable - bad goalies play for bad teams with bad offenses
- Solution: Goalie weakness now used CONDITIONALLY within matchup_score:
  * Elite players (L1+PP1): 60% of goalie weakness impact
  * Top 6 + PP: 40% of goalie weakness impact
  * Top 6 no PP: 20% of goalie weakness impact
  * Depth players: Near neutral (goalie quality doesn't help them score)

NEW Formula:
    final_score = (
        line_opportunity_score * 45 +      # 45% - Line quality + PP1 status (PRIMARY)
        situational_score * 25 +           # 25% - Fatigue (B2B), home/away, goalie fatigue
        recent_form_score * 20 +           # 20% - Recent PPG (CAPPED at 2.0 to avoid regression)
        matchup_score * 10                 # 10% - Conditional goalie weakness by player tier
        # goalie_weakness standalone weight = 0 (rolled into matchup conditionally)
    )

Position-specific weights are applied to adjust for different scoring profiles.
"""
from typing import Dict, Any, List, Optional
import json

from nhl_isolated.analytics.recent_form_calculator import calculate_recent_form_score
from nhl_isolated.analytics.goalie_weakness_calculator import calculate_goalie_weakness_score
from nhl_isolated.analytics.line_opportunity_calculator import calculate_line_opportunity_score


# Global component weights (0-100 scale)
# UPDATED 2024-11-25: Based on correlation analysis of 3,163 predictions
# - line_opportunity has BEST correlation with actual points (r=+0.14)
# - recent_form is NEGATIVELY correlated in top ranks (regression to mean)
# - goalie_weakness was HURTING predictions (r=-0.04) - REMOVED
WEIGHTS = {
    'line_opportunity': 45,  # PRIMARY - best predictor of actual points
    'situational': 25,       # INCREASED - good effect size (+0.21)
    'recent_form': 20,       # REDUCED - negative correlation in top ranks
    'matchup': 10,           # Keep as tiebreaker
    'goalie_weakness': 0,    # REMOVED - was hurting predictions
}

# Position-specific weight adjustments
# All positions now use same weights since line_opportunity dominates
POSITION_WEIGHTS = {
    'C': {  # Centers
        'line_opportunity': 45,
        'situational': 25,
        'recent_form': 20,
        'matchup': 10,
        'goalie_weakness': 0,
    },
    'LW': {  # Left Wings
        'line_opportunity': 45,
        'situational': 25,
        'recent_form': 20,
        'matchup': 10,
        'goalie_weakness': 0,
    },
    'RW': {  # Right Wings
        'line_opportunity': 45,
        'situational': 25,
        'recent_form': 20,
        'matchup': 10,
        'goalie_weakness': 0,
    },
    'D': {  # Defensemen - PP role even more important
        'line_opportunity': 50,  # D-men on PP1 are key
        'situational': 25,
        'recent_form': 15,
        'matchup': 10,
        'goalie_weakness': 0,
    },
}


def calculate_matchup_score(player_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Get or calculate matchup score (Skater-vs-Goalie).

    UPDATED 2024-11-25: Goalie weakness is now used CONDITIONALLY:
    - For elite players (L1/L2 + PP1): goalie weakness matters more
    - For depth players: goalie quality matters less (low opportunity anyway)

    This addresses the paradox where raw goalie_weakness hurt predictions:
    - Good teams face good goalies but their stars still score
    - Bad teams face bad goalies but their players don't capitalize

    If matchup_score is already present (from matchup_analyzer via enrichment),
    use that. Otherwise, apply conditional goalie weakness logic.
    """
    # Check if already calculated
    if 'matchup_score' in player_data and 'matchup_details' in player_data:
        return {
            'matchup_score': player_data['matchup_score'],
            'matchup_details': player_data['matchup_details']
        }

    # Get player context
    line_number = player_data.get('line_number', 4)
    pp_unit = player_data.get('pp_unit', 0)
    goalie_weakness = player_data.get('goalie_weakness_score', 0.5)
    opposing_gaa = player_data.get('opposing_goalie_gaa', 2.9)

    # Determine player tier
    is_elite = line_number == 1 and pp_unit == 1
    is_top6 = line_number <= 2
    is_pp_player = pp_unit > 0

    # CONDITIONAL GOALIE WEAKNESS LOGIC:
    # - Elite players (L1+PP1): Full goalie weakness impact
    # - Top 6 + PP: Partial goalie weakness impact
    # - Top 6 no PP: Minimal goalie weakness impact
    # - Depth: Near neutral (0.5) - goalie quality doesn't help much

    if is_elite:
        # Elite players can exploit weak goalies
        # But cap the benefit - a weak goalie doesn't guarantee points
        matchup_score = 0.5 + (goalie_weakness - 0.5) * 0.6  # 60% of goalie weakness impact
        method = 'elite_goalie_weighted'
    elif is_top6 and is_pp_player:
        # PP players get some benefit from weak goalies
        matchup_score = 0.5 + (goalie_weakness - 0.5) * 0.4  # 40% impact
        method = 'top6_pp_goalie_weighted'
    elif is_top6:
        # Top 6 without PP - minimal goalie impact
        matchup_score = 0.5 + (goalie_weakness - 0.5) * 0.2  # 20% impact
        method = 'top6_minimal_goalie'
    else:
        # Depth players - goalie quality doesn't help them score
        # Use near-neutral with tiny boost for very weak goalies (GAA > 3.5)
        if opposing_gaa and opposing_gaa > 3.5:
            matchup_score = 0.55  # Slight boost only for extremely bad goalies
            method = 'depth_extreme_weakness_only'
        else:
            matchup_score = 0.5  # Neutral
            method = 'depth_neutral'

    # Clamp to valid range
    matchup_score = max(0.3, min(0.7, matchup_score))

    return {
        'matchup_score': round(matchup_score, 4),
        'matchup_details': {
            'method': method,
            'raw_goalie_weakness': round(goalie_weakness, 4),
            'opposing_gaa': opposing_gaa,
            'player_tier': 'elite' if is_elite else 'top6_pp' if (is_top6 and is_pp_player) else 'top6' if is_top6 else 'depth',
            'note': 'Conditional goalie weakness - scaled by player tier'
        }
    }


def calculate_situational_score(player_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Get or calculate situational score (B2B fatigue, home/away).

    If situational_score is already present (from enrichment pipeline),
    use that. Otherwise, fall back to simplified calculation.
    """
    # Check if already calculated by enrichment pipeline
    if 'situational_score' in player_data and 'situational_details' in player_data:
        return {
            'situational_score': player_data['situational_score'],
            'situational_details': player_data['situational_details']
        }

    # Fallback: simplified calculation (home bonus only)
    is_home = player_data.get('is_home', False)
    home_bonus = 0.03 if is_home else 0.0
    situational_score = 0.5 + home_bonus

    return {
        'situational_score': round(situational_score, 4),
        'situational_details': {
            'is_home': is_home,
            'home_adjustment': round(home_bonus, 4),
            'is_b2b': False,
            'is_b2b2b': False,
            'skater_fatigue_penalty': 0.0,
            'opposing_goalie_b2b': False,
            'goalie_fatigue_boost': 0.0,
            'method': 'fallback_simplified'
        }
    }


def calculate_final_score(player_data: Dict[str, Any],
                          use_position_weights: bool = True) -> Dict[str, Any]:
    """
    Calculate the final composite score for a player.

    Args:
        player_data: Enriched player dictionary
        use_position_weights: Use position-specific weights (default True)

    Returns:
        Dictionary with:
        - final_score: Composite score (0-100 scale)
        - component_scores: Individual component scores
        - weights_used: Weights applied
        - confidence: Confidence tier
    """
    position = player_data.get('position', 'C')

    # Get weights
    if use_position_weights and position in POSITION_WEIGHTS:
        weights = POSITION_WEIGHTS[position]
    else:
        weights = WEIGHTS

    # Calculate component scores (if not already calculated)
    if 'recent_form_score' not in player_data:
        form_result = calculate_recent_form_score(player_data)
        player_data['recent_form_score'] = form_result['recent_form_score']
        player_data['form_details'] = form_result.get('form_details', {})

    if 'line_opportunity_score' not in player_data:
        opp_result = calculate_line_opportunity_score(player_data)
        player_data['line_opportunity_score'] = opp_result['line_opportunity_score']
        player_data['opportunity_details'] = opp_result.get('opportunity_details', {})

    if 'goalie_weakness_score' not in player_data:
        weakness_result = calculate_goalie_weakness_score(player_data)
        player_data['goalie_weakness_score'] = weakness_result['goalie_weakness_score']
        player_data['goalie_weakness_details'] = weakness_result.get('weakness_details', {})

    # Calculate matchup and situational
    matchup_result = calculate_matchup_score(player_data)
    situational_result = calculate_situational_score(player_data)

    # Extract scores
    recent_form = player_data['recent_form_score']
    line_opportunity = player_data['line_opportunity_score']
    goalie_weakness = player_data['goalie_weakness_score']
    matchup = matchup_result['matchup_score']
    situational = situational_result['situational_score']

    # Calculate weighted final score (0-100 scale)
    final_score = (
        recent_form * weights['recent_form'] +
        line_opportunity * weights['line_opportunity'] +
        goalie_weakness * weights['goalie_weakness'] +
        matchup * weights['matchup'] +
        situational * weights['situational']
    )

    # Determine confidence tier
    confidence = _calculate_confidence_tier(player_data)

    # Build component breakdown
    component_scores = {
        'recent_form': {
            'raw': recent_form,
            'weighted': round(recent_form * weights['recent_form'], 2),
            'weight': weights['recent_form'],
        },
        'line_opportunity': {
            'raw': line_opportunity,
            'weighted': round(line_opportunity * weights['line_opportunity'], 2),
            'weight': weights['line_opportunity'],
        },
        'goalie_weakness': {
            'raw': goalie_weakness,
            'weighted': round(goalie_weakness * weights['goalie_weakness'], 2),
            'weight': weights['goalie_weakness'],
        },
        'matchup': {
            'raw': matchup,
            'weighted': round(matchup * weights['matchup'], 2),
            'weight': weights['matchup'],
        },
        'situational': {
            'raw': situational,
            'weighted': round(situational * weights['situational'], 2),
            'weight': weights['situational'],
        },
    }

    return {
        'final_score': round(final_score, 2),
        'component_scores': component_scores,
        'weights_used': weights,
        'confidence': confidence,
        'matchup_details': matchup_result['matchup_details'],
        'situational_details': situational_result['situational_details'],
    }


def _calculate_confidence_tier(player_data: Dict[str, Any]) -> str:
    """
    Determine confidence tier for prediction.

    Tiers:
    - very_high: Top line + PP1 + hot streak
    - high: Top 6 + some PP + decent recent form
    - medium: Middle 6 or decent data
    - low: Depth player or missing data
    """
    line_number = player_data.get('line_number', 4)
    pp_unit = player_data.get('pp_unit', 0)
    recent_ppg = player_data.get('recent_ppg', 0)
    recent_games = player_data.get('recent_games', 0)
    point_streak = player_data.get('point_streak', 0)
    goalie_confirmed = player_data.get('goalie_confirmed', False)

    # Very High: Top line + PP1 + hot
    if line_number == 1 and pp_unit == 1 and recent_ppg >= 0.8 and point_streak >= 2:
        return 'very_high'

    # High: Top 6 with PP involvement
    if line_number <= 2 and (pp_unit > 0 or recent_ppg >= 0.6) and recent_games >= 5:
        return 'high'

    # Medium: Middle 6 or decent data
    if line_number <= 3 and recent_games >= 3:
        return 'medium'

    # Low: Everything else
    return 'low'


def calculate_final_scores_batch(players: List[Dict[str, Any]],
                                  use_position_weights: bool = True) -> List[Dict[str, Any]]:
    """
    Calculate final scores for a batch of players.

    Args:
        players: List of enriched player dictionaries
        use_position_weights: Use position-specific weights

    Returns:
        Players sorted by final_score descending
    """
    for player in players:
        result = calculate_final_score(player, use_position_weights)

        player['final_score'] = result['final_score']
        player['component_scores'] = result['component_scores']
        player['confidence'] = result['confidence']
        player['matchup_details'] = result['matchup_details']
        player['situational_details'] = result['situational_details']

    # Sort by final score descending
    players.sort(key=lambda x: x.get('final_score', 0), reverse=True)

    return players


def get_top_n(players: List[Dict[str, Any]], n: int = 25) -> List[Dict[str, Any]]:
    """
    Get top N players by final score.

    Args:
        players: List of scored players
        n: Number of players to return (default 25)

    Returns:
        Top N players
    """
    # Sort if not already sorted
    sorted_players = sorted(players, key=lambda x: x.get('final_score', 0), reverse=True)
    return sorted_players[:n]


if __name__ == '__main__':
    # Test with sample data
    sample_players = [
        {
            'player_name': 'Connor McDavid',
            'team': 'EDM',
            'position': 'C',
            'line_number': 1,
            'pp_unit': 1,
            'avg_toi_minutes': 22.0,
            'recent_ppg': 1.8,
            'recent_games': 10,
            'recent_points': 18,
            'recent_goals': 7,
            'recent_assists': 11,
            'point_streak': 5,
            'opposing_goalie_sv_pct': 0.900,
            'opposing_goalie_gaa': 3.0,
            'goalie_confirmed': True,
            'is_home': True,
        },
        {
            'player_name': 'Role Player',
            'team': 'EDM',
            'position': 'RW',
            'line_number': 3,
            'pp_unit': 0,
            'avg_toi_minutes': 12.0,
            'recent_ppg': 0.3,
            'recent_games': 10,
            'recent_points': 3,
            'recent_goals': 1,
            'recent_assists': 2,
            'point_streak': 0,
            'opposing_goalie_sv_pct': 0.900,
            'opposing_goalie_gaa': 3.0,
            'goalie_confirmed': True,
            'is_home': True,
        },
    ]

    scored_players = calculate_final_scores_batch(sample_players)

    print("Final Score Calculation Test Results:")
    print("=" * 70)

    for p in scored_players:
        print(f"\n{p['player_name']} ({p['team']} - {p['position']})")
        print(f"  Final Score: {p['final_score']:.1f}")
        print(f"  Confidence: {p['confidence']}")
        print(f"  Component Breakdown:")
        for comp, data in p['component_scores'].items():
            print(f"    {comp}: {data['raw']:.3f} × {data['weight']} = {data['weighted']:.1f}")
