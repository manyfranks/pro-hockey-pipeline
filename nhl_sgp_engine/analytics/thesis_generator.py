"""
NHL SGP Parlay Thesis Generator

Generates natural language thesis narratives for SGP parlays using LLM.
Falls back to rule-based generation if LLM unavailable.

Usage:
    from nhl_sgp_engine.analytics.thesis_generator import ThesisGenerator

    generator = ThesisGenerator()
    thesis = generator.generate_thesis(game_data, legs)
"""
import os
import json
import requests
from typing import Dict, List, Optional
from collections import defaultdict
from dotenv import load_dotenv

# Load environment variables
for path in ['.env.local', '.env', '../.env.local', '../.env']:
    if os.path.exists(path):
        load_dotenv(dotenv_path=path)
        break


class ThesisGenerator:
    """
    Generates thesis narratives for SGP parlays.

    Uses OpenRouter LLM for natural narratives with rule-based fallback.
    """

    SYSTEM_PROMPT = """You are an expert NHL betting analyst writing thesis statements for Same Game Parlays (SGPs).

Your thesis should:
- Be 2-3 sentences maximum
- Explain WHY these legs correlate well together
- Reference specific player roles, matchups, or game context
- Sound confident but analytical
- NOT use bullet points or lists

Examples of good theses:
- "Edmonton's top line faces a struggling Montreal defense allowing 3.4 goals/game. McDavid and Draisaitl's PP chemistry makes this an ideal offensive stack with correlated upside."
- "Tampa's puck possession style should generate volume against Florida's aggressive forecheck. Stacking shots from their cycle-heavy forwards offers positive correlation."
- "With Vegas implied for 3.5+ goals, targeting their PP1 unit's point production aligns with the expected game script."

Return ONLY the thesis text, no JSON, no quotes, no extra formatting."""

    def __init__(self, use_llm: bool = True):
        """
        Initialize thesis generator.

        Args:
            use_llm: Whether to attempt LLM generation (default: True)
        """
        self.use_llm = use_llm
        self.api_key = os.getenv('OPENROUTER_API_KEY')
        self.model = os.getenv('OPENROUTER_MODEL_NAME', 'google/gemini-2.0-flash-001')

    def generate_thesis(self, game_data: Dict, legs: List[Dict]) -> str:
        """
        Generate thesis for a parlay.

        Args:
            game_data: Game context (home_team, away_team, matchup, etc.)
            legs: List of leg dictionaries with player info, stats, edges

        Returns:
            Thesis string
        """
        if self.use_llm and self.api_key:
            try:
                llm_thesis = self._generate_llm_thesis(game_data, legs)
                if llm_thesis and len(llm_thesis) > 20:
                    return llm_thesis
            except Exception as e:
                print(f"[ThesisGenerator] LLM failed, using fallback: {e}")

        return self._generate_rule_based_thesis(game_data, legs)

    def _generate_llm_thesis(self, game_data: Dict, legs: List[Dict]) -> Optional[str]:
        """Generate thesis using LLM."""
        prompt = self._build_prompt(game_data, legs)

        try:
            response = requests.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": "https://github.com/analytics-pro/nhl-predictions",
                    "X-Title": "NHL SGP Thesis Generator"
                },
                json={
                    "model": self.model,
                    "max_tokens": 200,
                    "temperature": 0.7,
                    "messages": [
                        {"role": "system", "content": self.SYSTEM_PROMPT},
                        {"role": "user", "content": prompt}
                    ]
                },
                timeout=30
            )

            response.raise_for_status()
            result = response.json()
            thesis = result['choices'][0]['message']['content'].strip()

            # Clean up any quotes or extra formatting
            thesis = thesis.strip('"\'')

            return thesis

        except requests.exceptions.Timeout:
            print("[ThesisGenerator] LLM request timed out")
            return None
        except Exception as e:
            print(f"[ThesisGenerator] LLM error: {e}")
            return None

    def _build_prompt(self, game_data: Dict, legs: List[Dict]) -> str:
        """Build prompt for LLM thesis generation."""
        home = game_data.get('home_team', 'HOME')
        away = game_data.get('away_team', 'AWAY')

        # Format legs
        legs_text = []
        for i, leg in enumerate(legs, 1):
            player = leg.get('player_name', 'Unknown')
            team = leg.get('team', '?')
            stat = leg.get('stat_type', 'points')
            line = leg.get('line', 0.5)
            edge = leg.get('edge_pct', 0)
            position = leg.get('position', '?')
            reason = leg.get('primary_reason', '')

            legs_text.append(
                f"{i}. {player} ({team}, {position}) - {stat} O{line} | Edge: {edge:.1f}% | {reason}"
            )

        # Analyze composition
        stat_types = [leg.get('stat_type', '') for leg in legs]
        teams = [leg.get('team', '') for leg in legs]

        team_counts = defaultdict(int)
        for t in teams:
            team_counts[t] += 1

        stacked_team = max(team_counts.keys(), key=lambda x: team_counts[x]) if team_counts else None
        is_stacked = team_counts.get(stacked_team, 0) >= 2

        composition_notes = []
        if stat_types.count('points') >= 2:
            composition_notes.append("offensive/points-focused")
        if stat_types.count('shots_on_goal') >= 2:
            composition_notes.append("shooting volume play")
        if is_stacked:
            composition_notes.append(f"{stacked_team} team stack")

        avg_edge = sum(leg.get('edge_pct', 0) for leg in legs) / len(legs) if legs else 0

        prompt = f"""Write a thesis for this NHL Same Game Parlay:

MATCHUP: {away} @ {home}

LEGS:
{chr(10).join(legs_text)}

PARLAY CHARACTERISTICS:
- Total legs: {len(legs)}
- Average edge: {avg_edge:.1f}%
- Composition: {', '.join(composition_notes) if composition_notes else 'mixed'}

Write a 2-3 sentence thesis explaining why these legs work well together."""

        return prompt

    def _generate_rule_based_thesis(self, game_data: Dict, legs: List[Dict]) -> str:
        """Generate thesis using rule-based logic (fallback)."""
        home = game_data.get('home_team', 'HOME')
        away = game_data.get('away_team', 'AWAY')

        stat_types = [leg.get('stat_type', '') for leg in legs]
        teams = [leg.get('team', 'UNK') for leg in legs]
        avg_edge = sum(leg.get('edge_pct', 0) for leg in legs) / len(legs) if legs else 0

        thesis_parts = []

        # Check for offensive theme
        if stat_types.count('points') >= 2:
            thesis_parts.append("Offensive-focused parlay targeting point production")

        # Check for shooting theme
        if stat_types.count('shots_on_goal') >= 2:
            thesis_parts.append("High-volume shooting game expected")

        # Check for team stack
        team_counts = defaultdict(int)
        for t in teams:
            team_counts[t] += 1
        stacked_team = max(team_counts.keys(), key=lambda x: team_counts[x]) if team_counts else None
        if stacked_team and team_counts[stacked_team] >= 2:
            thesis_parts.append(f"Stacking {stacked_team} players")

        # Add edge summary
        thesis_parts.append(f"Average edge: {avg_edge:.1f}%")

        # Add primary reasons from top legs
        top_reasons = [
            leg.get('primary_reason', '')
            for leg in sorted(legs, key=lambda x: x.get('edge_pct', 0), reverse=True)[:2]
        ]
        for reason in top_reasons:
            if reason:
                thesis_parts.append(reason)

        return " | ".join(thesis_parts)


# Convenience function for direct use
def generate_parlay_thesis(game_data: Dict, legs: List[Dict], use_llm: bool = True) -> str:
    """
    Generate thesis for a parlay.

    Args:
        game_data: Game context dict
        legs: List of leg dicts
        use_llm: Whether to use LLM (default: True)

    Returns:
        Thesis string
    """
    generator = ThesisGenerator(use_llm=use_llm)
    return generator.generate_thesis(game_data, legs)
