# nhl_isolated/analytics/goalie_weakness_calculator.py
"""
Goalie Weakness Calculator for NHL Player Points Algorithm

Calculates the opposing goalie weakness score (15% of final score).
Higher score = weaker goalie = better chance for skaters to score.

Factors:
- Save Percentage (SV%) - lower = weaker
- Goals Against Average (GAA) - higher = weaker
- Backup/Starter status
- Recent form (if available)

References NHL_ALGORITHM_ADR.md Section 2.3
"""
from typing import Dict, Any, List, Optional


# League average benchmarks (2024-25 season)
LEAGUE_AVG_SV_PCT = 0.905
LEAGUE_AVG_GAA = 2.90

# Goalie weakness score weights
SV_PCT_WEIGHT = 0.50
GAA_WEIGHT = 0.30
STATUS_WEIGHT = 0.20


def calculate_goalie_weakness_score(player_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Calculate the opposing goalie weakness score for a player.

    Higher score = weaker opposing goalie = better for skater.

    Args:
        player_data: Enriched player dictionary with opposing goalie info

    Returns:
        Dictionary with:
        - goalie_weakness_score: Normalized score (0-1 scale)
        - weakness_details: Breakdown of calculation
    """
    # Extract goalie data
    opposing_goalie_id = player_data.get('opposing_goalie_id')
    opposing_goalie_name = player_data.get('opposing_goalie_name')
    sv_pct = player_data.get('opposing_goalie_sv_pct')
    gaa = player_data.get('opposing_goalie_gaa')
    goalie_confirmed = player_data.get('goalie_confirmed', False)

    # Handle missing goalie data
    if opposing_goalie_id is None or sv_pct is None:
        # No goalie data - use neutral score
        return {
            'goalie_weakness_score': 0.50,  # Neutral
            'weakness_details': {
                'method': 'no_data',
                'sv_pct': None,
                'gaa': None,
                'goalie_name': opposing_goalie_name,
                'goalie_confirmed': goalie_confirmed,
            }
        }

    # SV% Component: Lower SV% = higher weakness score
    # Elite goalie (0.920 SV%) = 0.0 weakness
    # League avg (0.905 SV%) = 0.5 weakness
    # Bad goalie (0.880 SV%) = 1.0 weakness
    sv_range = 0.920 - 0.880  # 0.04 range
    sv_deviation = LEAGUE_AVG_SV_PCT - sv_pct  # Positive if below avg

    # Normalize: -0.015 to +0.025 → 0 to 1
    sv_component = 0.5 + (sv_deviation / sv_range) * 0.5
    sv_component = max(0.0, min(1.0, sv_component))

    # GAA Component: Higher GAA = higher weakness score
    # Elite goalie (2.20 GAA) = 0.0 weakness
    # League avg (2.90 GAA) = 0.5 weakness
    # Bad goalie (3.60 GAA) = 1.0 weakness
    gaa_range = 3.60 - 2.20  # 1.40 range
    gaa_deviation = gaa - LEAGUE_AVG_GAA  # Positive if above avg

    gaa_component = 0.5 + (gaa_deviation / gaa_range) * 0.5
    gaa_component = max(0.0, min(1.0, gaa_component))

    # Status Component (backup bonus)
    # Inferred goalies get slight boost (uncertainty favors offense)
    status_component = 0.5
    if not goalie_confirmed:
        status_component = 0.6  # Slight boost for inferred/uncertain

    # Combine components
    goalie_weakness_score = (
        sv_component * SV_PCT_WEIGHT +
        gaa_component * GAA_WEIGHT +
        status_component * STATUS_WEIGHT
    )

    # Determine goalie quality tier
    if sv_pct >= 0.915:
        quality_tier = 'elite'
    elif sv_pct >= 0.900:
        quality_tier = 'above_average'
    elif sv_pct >= 0.890:
        quality_tier = 'average'
    else:
        quality_tier = 'below_average'

    return {
        'goalie_weakness_score': round(goalie_weakness_score, 4),
        'weakness_details': {
            'method': 'full_calculation',
            'goalie_name': opposing_goalie_name,
            'goalie_confirmed': goalie_confirmed,
            'sv_pct': sv_pct,
            'gaa': gaa,
            'sv_component': round(sv_component, 4),
            'gaa_component': round(gaa_component, 4),
            'status_component': round(status_component, 4),
            'quality_tier': quality_tier,
        }
    }


def calculate_goalie_weakness_batch(players: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Calculate goalie weakness scores for a batch of players.

    Args:
        players: List of enriched player dictionaries

    Returns:
        Players with goalie weakness scores added
    """
    for player in players:
        weakness_result = calculate_goalie_weakness_score(player)

        player['goalie_weakness_score'] = weakness_result['goalie_weakness_score']
        player['goalie_weakness_details'] = weakness_result['weakness_details']

    return players


if __name__ == '__main__':
    # Test with sample data
    import json

    sample_players = [
        {
            'player_name': 'Test vs Elite Goalie',
            'opposing_goalie_id': 1,
            'opposing_goalie_name': 'Andrei Vasilevskiy',
            'opposing_goalie_sv_pct': 0.918,
            'opposing_goalie_gaa': 2.30,
            'goalie_confirmed': True,
        },
        {
            'player_name': 'Test vs Average Goalie',
            'opposing_goalie_id': 2,
            'opposing_goalie_name': 'Average Goalie',
            'opposing_goalie_sv_pct': 0.905,
            'opposing_goalie_gaa': 2.90,
            'goalie_confirmed': True,
        },
        {
            'player_name': 'Test vs Weak Goalie',
            'opposing_goalie_id': 3,
            'opposing_goalie_name': 'Struggling Goalie',
            'opposing_goalie_sv_pct': 0.885,
            'opposing_goalie_gaa': 3.50,
            'goalie_confirmed': False,  # Inferred - extra boost
        },
        {
            'player_name': 'Test No Goalie Data',
            'opposing_goalie_id': None,
            'opposing_goalie_name': None,
            'opposing_goalie_sv_pct': None,
            'opposing_goalie_gaa': None,
            'goalie_confirmed': False,
        },
    ]

    players = calculate_goalie_weakness_batch(sample_players)

    print("Goalie Weakness Calculation Test Results:")
    print("=" * 60)
    for p in players:
        print(f"\n{p['player_name']}:")
        print(f"  Opposing Goalie: {p.get('opposing_goalie_name', 'Unknown')}")
        print(f"  Weakness Score: {p['goalie_weakness_score']:.3f}")
        details = p['goalie_weakness_details']
        if details.get('sv_pct'):
            print(f"  SV%: {details['sv_pct']:.3f} → Component: {details['sv_component']:.3f}")
            print(f"  GAA: {details['gaa']:.2f} → Component: {details['gaa_component']:.3f}")
            print(f"  Quality Tier: {details['quality_tier']}")
