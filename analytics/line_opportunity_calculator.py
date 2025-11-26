# nhl_isolated/analytics/line_opportunity_calculator.py
"""
Line Opportunity Calculator for NHL Player Points Algorithm

Calculates the line opportunity score (20% of final score) based on:
- Line number (1st line > 2nd > 3rd > 4th)
- Power Play unit (PP1 >> PP2 >> None)
- Average ice time

References NHL_ALGORITHM_ADR.md Section 2.2
"""
from typing import Dict, Any, List


# Line number scores (1st line = best opportunity)
LINE_SCORES = {
    1: 1.00,  # Top line / Top pair
    2: 0.70,  # Second line / Second pair
    3: 0.40,  # Third line / Third pair
    4: 0.15,  # Fourth line / Scratched D
}

# Power Play unit bonuses
PP_BONUSES = {
    0: 0.00,  # Not on PP
    1: 0.30,  # PP1 - top unit
    2: 0.15,  # PP2 - second unit
}

# Weight distribution within line opportunity score
LINE_WEIGHT = 0.50
PP_WEIGHT = 0.35
TOI_WEIGHT = 0.15

# TOI benchmarks (minutes per game)
ELITE_TOI = 22.0  # Top forwards
AVERAGE_TOI = 15.0  # Middle-6 forwards
MIN_TOI = 8.0  # 4th line


def calculate_line_opportunity_score(player_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Calculate the line opportunity score for a player.

    Args:
        player_data: Enriched player dictionary with line info

    Returns:
        Dictionary with:
        - line_opportunity_score: Normalized score (0-1 scale)
        - opportunity_details: Breakdown of calculation
    """
    line_number = player_data.get('line_number', 4)
    pp_unit = player_data.get('pp_unit', 0)
    avg_toi = player_data.get('avg_toi_minutes', AVERAGE_TOI)
    position = player_data.get('position', 'C')

    # Line number component
    line_component = LINE_SCORES.get(line_number, 0.15)

    # PP unit component (bonus added to base)
    pp_component = PP_BONUSES.get(pp_unit, 0.0)

    # TOI component (normalized)
    # Elite TOI = 1.0, Average = 0.5, Min = 0.0
    toi_range = ELITE_TOI - MIN_TOI
    toi_normalized = (avg_toi - MIN_TOI) / toi_range if toi_range > 0 else 0.5
    toi_component = max(0.0, min(1.0, toi_normalized))

    # Defenseman adjustment
    # Top-pair D often have higher TOI but different scoring patterns
    if position == 'D':
        # D-men on PP1 get full PP value (they quarterback)
        if pp_unit == 1:
            pp_component = PP_BONUSES[1] * 1.2  # 20% boost for PP1 D

    # Combine components
    line_opportunity_score = (
        line_component * LINE_WEIGHT +
        pp_component * PP_WEIGHT +
        toi_component * TOI_WEIGHT
    )

    # Cap at 1.0
    line_opportunity_score = min(line_opportunity_score, 1.0)

    # Determine role tier
    if line_number == 1 and pp_unit == 1:
        role_tier = 'elite'
    elif line_number <= 2 and pp_unit > 0:
        role_tier = 'top_6_pp'
    elif line_number <= 2:
        role_tier = 'top_6'
    elif line_number == 3:
        role_tier = 'middle_6'
    else:
        role_tier = 'depth'

    return {
        'line_opportunity_score': round(line_opportunity_score, 4),
        'opportunity_details': {
            'line_number': line_number,
            'pp_unit': pp_unit,
            'avg_toi': round(avg_toi, 1),
            'line_component': round(line_component, 4),
            'pp_component': round(pp_component, 4),
            'toi_component': round(toi_component, 4),
            'role_tier': role_tier,
        }
    }


def calculate_line_opportunity_batch(players: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Calculate line opportunity scores for a batch of players.

    Args:
        players: List of enriched player dictionaries

    Returns:
        Players with line opportunity scores added
    """
    for player in players:
        opp_result = calculate_line_opportunity_score(player)

        player['line_opportunity_score'] = opp_result['line_opportunity_score']
        player['opportunity_details'] = opp_result['opportunity_details']

    return players


if __name__ == '__main__':
    # Test with sample data
    sample_players = [
        {
            'player_name': 'Elite 1st Line PP1',
            'position': 'C',
            'line_number': 1,
            'pp_unit': 1,
            'avg_toi_minutes': 21.5,
        },
        {
            'player_name': 'Top 6 No PP',
            'position': 'LW',
            'line_number': 2,
            'pp_unit': 0,
            'avg_toi_minutes': 17.0,
        },
        {
            'player_name': 'PP1 Defenseman',
            'position': 'D',
            'line_number': 1,
            'pp_unit': 1,
            'avg_toi_minutes': 24.0,
        },
        {
            'player_name': '4th Line Grinder',
            'position': 'RW',
            'line_number': 4,
            'pp_unit': 0,
            'avg_toi_minutes': 9.0,
        },
    ]

    players = calculate_line_opportunity_batch(sample_players)

    print("Line Opportunity Calculation Test Results:")
    print("=" * 60)
    for p in players:
        print(f"\n{p['player_name']} ({p['position']}):")
        print(f"  Line: {p['line_number']}, PP Unit: {p['pp_unit']}")
        print(f"  Avg TOI: {p['avg_toi_minutes']:.1f} min")
        print(f"  Opportunity Score: {p['line_opportunity_score']:.3f}")
        print(f"  Role Tier: {p['opportunity_details']['role_tier']}")
