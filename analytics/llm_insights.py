# nhl_isolated/analytics/llm_insights.py
"""
NHL LLM-Powered Insights Generator - Phase 1

Uses Claude or OpenAI to generate natural language insights based on:
- Recent settlement performance
- Current day's predictions
- Historical patterns
- System accuracy trends

This module builds on Phase 0 (rule-based insights) by adding AI-generated
narrative and contextual analysis.
"""

import os
import json
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, List, Any, Optional
from dataclasses import dataclass

from utilities.logger import get_logger
from analytics.insights_generator import (
    NHLInsightsGenerator,
    InsightsReport,
    generate_insights_for_date,
)

logger = get_logger('llm_insights')


# ============================================================================
# LLM Configuration
# ============================================================================

@dataclass
class LLMConfig:
    """Configuration for LLM provider."""
    provider: str = "openrouter"  # "anthropic", "openai", or "openrouter"
    model: str = None  # Will default based on provider
    max_tokens: int = 2000
    temperature: float = 0.7

    def __post_init__(self):
        """Set default model based on provider if not specified."""
        if self.model is None:
            if self.provider == "openrouter":
                self.model = os.getenv('OPENROUTER_MODEL_NAME', 'google/gemini-2.0-flash-001')
            elif self.provider == "google":
                self.model = "gemini-2.5-flash"
            elif self.provider == "openai":
                self.model = "gpt-5-mini"


# ============================================================================
# Settlement Data Collector
# ============================================================================

class SettlementDataCollector:
    """Collects and formats settlement data for LLM analysis."""

    def __init__(self, db_manager=None):
        self.db = db_manager

    def get_recent_settlements(
        self,
        lookback_days: int = 5,
        top_n_focus: int = 10
    ) -> Dict[str, Any]:
        """
        Get recent settlement data formatted for LLM analysis.

        Args:
            lookback_days: Number of days to look back
            top_n_focus: Focus on top N predictions per day

        Returns:
            Dictionary with settlement analysis data
        """
        if not self.db:
            return self._empty_settlement_data()

        try:
            end_date = date.today() - timedelta(days=1)
            start_date = end_date - timedelta(days=lookback_days)

            # Get hit rate summary
            summary = self.db.get_hit_rate_summary(start_date, end_date)

            # Get daily breakdown
            daily_data = self._get_daily_breakdown(start_date, end_date, top_n_focus)

            # Identify patterns
            patterns = self._identify_patterns(daily_data)

            return {
                'period': f"{start_date} to {end_date}",
                'lookback_days': lookback_days,
                'summary': {
                    'total_predictions': summary.get('total_predictions', 0),
                    'hits': summary.get('hits', 0),
                    'misses': summary.get('misses', 0),
                    'overall_hit_rate': summary.get('overall_hit_rate', 0),
                    'top_10_hit_rate': summary.get('top_10_hit_rate', 'N/A'),
                    'top_5_hit_rate': summary.get('top_5_hit_rate', 'N/A'),
                },
                'daily_breakdown': daily_data,
                'patterns': patterns,
            }

        except Exception as e:
            logger.error(f"Error collecting settlement data: {e}")
            return self._empty_settlement_data()

    def _get_daily_breakdown(
        self,
        start_date: date,
        end_date: date,
        top_n: int
    ) -> List[Dict[str, Any]]:
        """Get day-by-day settlement breakdown from database."""
        daily = []

        if not self.db:
            return daily

        try:
            # Get recent settled predictions from database
            lookback_days = (end_date - start_date).days + 1
            settled = self.db.get_recent_settled_predictions(
                lookback_days=lookback_days,
                top_n_per_day=top_n
            )

            # Group by date
            by_date = {}
            for pred in settled:
                pred_date = str(pred.get('analysis_date', ''))
                if pred_date not in by_date:
                    by_date[pred_date] = {'hits': [], 'misses': [], 'dnp': []}

                outcome = pred.get('point_outcome')
                if outcome == 1:  # HIT
                    by_date[pred_date]['hits'].append(pred)
                elif outcome == 0:  # MISS
                    by_date[pred_date]['misses'].append(pred)
                else:  # DNP or PPD
                    by_date[pred_date]['dnp'].append(pred)

            # Build daily breakdown
            current = start_date
            while current <= end_date:
                date_str = str(current)
                day_data = by_date.get(date_str, {'hits': [], 'misses': [], 'dnp': []})

                total_valid = len(day_data['hits']) + len(day_data['misses'])
                hit_rate = (len(day_data['hits']) / total_valid * 100) if total_valid > 0 else 0

                daily.append({
                    'date': date_str,
                    'predictions': total_valid,
                    'hits': len(day_data['hits']),
                    'misses': len(day_data['misses']),
                    'hit_rate': round(hit_rate, 1),
                    'top_performers': [
                        f"{p['player_name']} ({p.get('actual_points', 0)} pts)"
                        for p in day_data['hits'][:3]
                    ],
                    'notable_misses': [
                        p['player_name'] for p in day_data['misses'][:3]
                    ],
                })
                current += timedelta(days=1)

        except Exception as e:
            logger.warning(f"Error fetching daily breakdown: {e}")

        return daily

    def _identify_patterns(self, daily_data: List[Dict]) -> Dict[str, Any]:
        """Identify patterns in recent settlements."""
        if not daily_data:
            return {}

        hit_rates = [d['hit_rate'] for d in daily_data if d.get('hit_rate')]

        if not hit_rates:
            return {}

        avg_hit_rate = sum(hit_rates) / len(hit_rates) if hit_rates else 0

        # Detect trend
        if len(hit_rates) >= 3:
            recent = hit_rates[-3:]
            if all(recent[i] < recent[i+1] for i in range(len(recent)-1)):
                trend = "improving"
            elif all(recent[i] > recent[i+1] for i in range(len(recent)-1)):
                trend = "declining"
            else:
                trend = "stable"
        else:
            trend = "insufficient_data"

        return {
            'average_hit_rate': round(avg_hit_rate, 1),
            'trend': trend,
            'best_day': max(daily_data, key=lambda x: x.get('hit_rate', 0)).get('date') if daily_data else None,
            'worst_day': min(daily_data, key=lambda x: x.get('hit_rate', 100)).get('date') if daily_data else None,
        }

    def _empty_settlement_data(self) -> Dict[str, Any]:
        return {
            'period': 'N/A',
            'lookback_days': 0,
            'summary': {},
            'daily_breakdown': [],
            'patterns': {},
        }


# ============================================================================
# LLM Prompt Builder
# ============================================================================

class LLMPromptBuilder:
    """Builds prompts for LLM analysis."""

    SYSTEM_PROMPT = """You are an expert NHL analytics assistant helping users make informed decisions about player point predictions. You analyze prediction data, settlement results, and current matchups to provide actionable insights.

Your tone should be:
- Confident but not overconfident
- Data-driven with specific numbers
- Honest about uncertainty
- Focused on actionable advice

When analyzing:
- Point out hot streaks and momentum
- Highlight favorable matchups (weak goalies, high-scoring games)
- Note any concerning patterns in recent misses
- Provide parlay advice with appropriate risk warnings
- Be specific with player names and stats

IMPORTANT: You MUST respond with valid JSON only. No markdown, no extra text. Your response must be parseable by JSON.parse()."""

    @staticmethod
    def build_analysis_prompt(
        predictions: List[Dict],
        settlement_data: Dict[str, Any],
        rule_based_insights: InsightsReport
    ) -> str:
        """Build the analysis prompt for the LLM."""

        # Format top 10 predictions
        top_10 = predictions[:10]
        top_10_text = "\n".join([
            f"{i+1}. {p['player_name']} ({p['team']}) vs {p.get('opponent', '?')} "
            f"- Score: {p.get('final_score', 0):.1f}, "
            f"Streak: {p.get('point_streak', 0)}G, "
            f"PPG: {p.get('recent_ppg', 0):.2f}, "
            f"Line {p.get('line_number', '?')}/PP{p.get('pp_unit', 0) or '-'}"
            for i, p in enumerate(top_10)
        ])

        # Format settlement summary
        settlement_summary = ""
        if settlement_data.get('summary'):
            s = settlement_data['summary']
            settlement_summary = f"""
Recent Performance ({settlement_data.get('period', 'N/A')}):
- Overall Hit Rate: {s.get('overall_hit_rate', 'N/A')}%
- Top 5 Hit Rate: {s.get('top_5_hit_rate', 'N/A')}
- Top 10 Hit Rate: {s.get('top_10_hit_rate', 'N/A')}
- Trend: {settlement_data.get('patterns', {}).get('trend', 'unknown')}
"""

        # Format hot streaks
        hot_streaks_text = ""
        if rule_based_insights.hot_streaks:
            streaks = rule_based_insights.hot_streaks[:5]
            hot_streaks_text = "Hot Streaks Detected:\n" + "\n".join([
                f"- {hs.player_name}: {hs.details}"
                for hs in streaks
            ])

        # Format goalie vulnerabilities
        goalie_text = ""
        if rule_based_insights.goalie_vulnerabilities:
            goalies = rule_based_insights.goalie_vulnerabilities[:3]
            goalie_text = "Weak Goalies to Target:\n" + "\n".join([
                f"- {gv.goalie_name}: {gv.gaa:.2f} GAA, {gv.sv_pct:.3f} SV%"
                for gv in goalies
            ])

        prompt = f"""Analyze today's NHL player point predictions and provide insights.

TODAY'S TOP 10 PREDICTIONS:
{top_10_text}

{settlement_summary}

{hot_streaks_text}

{goalie_text}

Respond with a JSON object containing these fields:

{{
  "system_health": {{
    "status": "hot" | "neutral" | "cold",
    "summary": "2-3 sentence analysis of system performance with specific hit rate numbers"
  }},
  "top_picks": {{
    "summary": "3-4 sentence analysis of why the top 3 picks are strong today",
    "highlights": ["key point 1", "key point 2", "key point 3"]
  }},
  "value_plays": {{
    "summary": "2-3 sentence analysis of value picks in positions 4-10",
    "players": ["player name 1", "player name 2"]
  }},
  "caution_flags": {{
    "summary": "2-3 sentence warning about risks to watch",
    "concerns": ["concern 1", "concern 2"]
  }},
  "parlay_pick": {{
    "legs": ["Player Name 1", "Player Name 2"],
    "reasoning": "2-3 sentence explanation of why this parlay makes sense",
    "confidence": "high" | "medium" | "low"
  }}
}}

Be concise and actionable. Use specific player names and numbers. Return ONLY valid JSON."""

        return prompt


# ============================================================================
# LLM Insights Generator
# ============================================================================

class LLMInsightsGenerator:
    """
    Generates LLM-powered natural language insights.

    Usage:
        generator = LLMInsightsGenerator()
        insights = generator.generate_llm_insights(predictions)
        print(insights['narrative'])
    """

    def __init__(self, config: LLMConfig = None, db_manager=None):
        self.config = config or LLMConfig()
        self.db = db_manager
        self.settlement_collector = SettlementDataCollector(db_manager)
        self.rule_generator = NHLInsightsGenerator(db_manager)
        self.prompt_builder = LLMPromptBuilder()

    def generate_llm_insights(
        self,
        predictions: List[Dict],
        lookback_days: int = 5
    ) -> Dict[str, Any]:
        """
        Generate LLM-powered insights.

        Args:
            predictions: Today's predictions
            lookback_days: Days of settlement data to analyze

        Returns:
            Dictionary with LLM narrative and structured data
        """
        # Get rule-based insights first
        rule_insights = self.rule_generator.generate_insights(
            predictions,
            include_settlement_analysis=True,
            lookback_days=lookback_days
        )

        # Get settlement data
        settlement_data = self.settlement_collector.get_recent_settlements(
            lookback_days=lookback_days
        )

        # Build prompt
        prompt = self.prompt_builder.build_analysis_prompt(
            predictions,
            settlement_data,
            rule_insights
        )

        # Call LLM
        raw_response = self._call_llm(prompt)

        # Parse JSON response
        structured_insights = self._parse_llm_response(raw_response)

        return {
            'analysis_date': rule_insights.analysis_date,
            'generated_at': datetime.now().isoformat(),
            'narrative': raw_response,  # Keep raw for backwards compatibility
            'structured': structured_insights,  # New structured format for frontend
            'rule_based_insights': rule_insights,
            'settlement_data': settlement_data,
            'prompt_used': prompt,  # For debugging
        }

    def _parse_llm_response(self, response: str) -> Optional[Dict[str, Any]]:
        """
        Parse LLM JSON response into structured format.

        Returns parsed dict or None if parsing fails.
        """
        if not response:
            return None

        try:
            # Try to extract JSON from response (in case LLM added extra text)
            # Look for JSON object pattern
            import re
            json_match = re.search(r'\{[\s\S]*\}', response)
            if json_match:
                return json.loads(json_match.group())
            return None
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse LLM response as JSON: {e}")
            return None
        except Exception as e:
            logger.warning(f"Error parsing LLM response: {e}")
            return None

    def _call_llm(self, prompt: str) -> str:
        """Call the LLM API."""
        if self.config.provider == "openrouter":
            return self._call_openrouter(prompt)
        elif self.config.provider == "anthropic":
            return self._call_anthropic(prompt)
        elif self.config.provider == "openai":
            return self._call_openai(prompt)
        else:
            return self._generate_fallback(prompt)

    def _call_openrouter(self, prompt: str) -> str:
        """Call OpenRouter API (supports many models via unified interface)."""
        try:
            import requests

            api_key = os.getenv('OPENROUTER_API_KEY')
            if not api_key:
                logger.warning("OPENROUTER_API_KEY not set, using fallback")
                return self._generate_fallback(prompt)

            model = self.config.model or os.getenv('OPENROUTER_MODEL_NAME', 'anthropic/claude-3.5-sonnet')

            response = requests.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": "https://github.com/analytics-pro/nhl-predictions",
                    "X-Title": "NHL Insights Generator"
                },
                json={
                    "model": model,
                    "max_tokens": self.config.max_tokens,
                    "temperature": self.config.temperature,
                    "messages": [
                        {"role": "system", "content": self.prompt_builder.SYSTEM_PROMPT},
                        {"role": "user", "content": prompt}
                    ]
                },
                timeout=60
            )

            response.raise_for_status()
            result = response.json()
            return result['choices'][0]['message']['content']

        except Exception as e:
            logger.error(f"OpenRouter API error: {e}")
            return self._generate_fallback(prompt)

    def _call_anthropic(self, prompt: str) -> str:
        """Call Anthropic Claude API."""
        try:
            import anthropic

            api_key = os.getenv('ANTHROPIC_API_KEY')
            if not api_key:
                logger.warning("ANTHROPIC_API_KEY not set, using fallback")
                return self._generate_fallback(prompt)

            client = anthropic.Anthropic(api_key=api_key)

            message = client.messages.create(
                model=self.config.model,
                max_tokens=self.config.max_tokens,
                temperature=self.config.temperature,
                system=self.prompt_builder.SYSTEM_PROMPT,
                messages=[
                    {"role": "user", "content": prompt}
                ]
            )

            return message.content[0].text

        except ImportError:
            logger.warning("anthropic package not installed")
            return self._generate_fallback(prompt)
        except Exception as e:
            logger.error(f"Anthropic API error: {e}")
            return self._generate_fallback(prompt)

    def _call_openai(self, prompt: str) -> str:
        """Call OpenAI API."""
        try:
            import openai

            api_key = os.getenv('OPENAI_API_KEY')
            if not api_key:
                logger.warning("OPENAI_API_KEY not set, using fallback")
                return self._generate_fallback(prompt)

            client = openai.OpenAI(api_key=api_key)

            response = client.chat.completions.create(
                model=self.config.model if 'gpt' in self.config.model else 'gpt-4',
                max_tokens=self.config.max_tokens,
                temperature=self.config.temperature,
                messages=[
                    {"role": "system", "content": self.prompt_builder.SYSTEM_PROMPT},
                    {"role": "user", "content": prompt}
                ]
            )

            return response.choices[0].message.content

        except ImportError:
            logger.warning("openai package not installed")
            return self._generate_fallback(prompt)
        except Exception as e:
            logger.error(f"OpenAI API error: {e}")
            return self._generate_fallback(prompt)

    def _generate_fallback(self, prompt: str) -> str:
        """Generate basic insights without LLM (fallback mode)."""
        return """**LLM Analysis Unavailable**

LLM insights could not be generated (API key not configured or service unavailable).

Please review the rule-based insights above for:
- Hot streak players
- Elite opportunities (Top line + PP1 vs weak goalie)
- Parlay recommendations

To enable LLM insights, set ANTHROPIC_API_KEY or OPENAI_API_KEY environment variable."""


# ============================================================================
# Combined Report Generator
# ============================================================================

class NHLDailyReportGenerator:
    """
    Generates complete daily report combining Phase 0 and Phase 1 insights.

    Usage:
        generator = NHLDailyReportGenerator()
        report = generator.generate_full_report(date.today())
        generator.save_report(report, '/path/to/output')
    """

    def __init__(self, db_manager=None, llm_config: LLMConfig = None):
        self.db = db_manager
        self.llm_config = llm_config or LLMConfig()
        self.rule_generator = NHLInsightsGenerator(db_manager)
        self.llm_generator = LLMInsightsGenerator(self.llm_config, db_manager)

    def generate_full_report(
        self,
        target_date: date = None,
        include_llm: bool = True,
        lookback_days: int = 5
    ) -> Dict[str, Any]:
        """
        Generate complete daily report.

        Args:
            target_date: Date to generate report for
            include_llm: Whether to include LLM-generated insights
            lookback_days: Days of history for context

        Returns:
            Complete report dictionary
        """
        if target_date is None:
            target_date = date.today()

        # Load predictions
        predictions = self._load_predictions(target_date)

        if not predictions:
            return {
                'analysis_date': str(target_date),
                'error': 'No predictions available for this date',
            }

        # Generate rule-based insights (Phase 0)
        rule_insights = self.rule_generator.generate_insights(
            predictions,
            include_settlement_analysis=True,
            lookback_days=lookback_days
        )

        report = {
            'analysis_date': str(target_date),
            'generated_at': datetime.now().isoformat(),
            'total_predictions': len(predictions),
            'rule_based_insights': rule_insights,
            'llm_narrative': None,
            'llm_structured': None,
        }

        # Generate LLM insights (Phase 1)
        if include_llm:
            try:
                llm_result = self.llm_generator.generate_llm_insights(
                    predictions,
                    lookback_days=lookback_days
                )
                report['llm_narrative'] = llm_result.get('narrative')
                report['llm_structured'] = llm_result.get('structured')
            except Exception as e:
                logger.error(f"LLM generation failed: {e}")
                report['llm_narrative'] = f"LLM insights unavailable: {e}"

        return report

    def _load_predictions(self, target_date: date) -> List[Dict]:
        """
        Load predictions for target date.

        In production, fetches from database first.
        Falls back to JSON files for local development.
        """
        # Try database first (production path)
        if self.db:
            try:
                predictions = self.db.get_predictions_for_date(target_date)
                if predictions:
                    logger.info(f"Loaded {len(predictions)} predictions from database for {target_date}")
                    return predictions
            except Exception as e:
                logger.warning(f"Database fetch failed, falling back to JSON: {e}")

        # Fallback to JSON files (local development)
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
                return predictions

        return []

    def save_report(self, report: Dict[str, Any], output_dir: str = None) -> str:
        """
        Save report to files.

        Args:
            report: Report dictionary
            output_dir: Output directory (default: data/insights)

        Returns:
            Path to saved report
        """
        if output_dir is None:
            output_dir = Path(__file__).parent.parent / "data" / "insights"
        else:
            output_dir = Path(output_dir)

        output_dir.mkdir(parents=True, exist_ok=True)

        analysis_date = report.get('analysis_date', str(date.today()))

        # Save JSON
        json_path = output_dir / f"full_report_{analysis_date}.json"
        with open(json_path, 'w') as f:
            # Convert dataclasses to dicts for JSON serialization
            json_safe = self._make_json_safe(report)
            json.dump(json_safe, f, indent=2)

        # Save text report
        text_path = output_dir / f"full_report_{analysis_date}.txt"
        with open(text_path, 'w') as f:
            f.write(self._format_text_report(report))

        # Cache to database (LLM narrative is expensive to regenerate)
        if self.db:
            try:
                analysis_date_obj = date.fromisoformat(analysis_date) if isinstance(analysis_date, str) else analysis_date
                self.db.upsert_daily_insights(
                    analysis_date=analysis_date_obj,
                    llm_narrative=report.get('llm_narrative'),
                    llm_structured=report.get('llm_structured'),
                    llm_model=self.llm_config.model if self.llm_config else None,
                    full_report=self._make_json_safe(report),
                    total_predictions=report.get('total_predictions', 0),
                    games_count=len(report.get('games', []))
                )
                logger.info(f"Report cached to database for {analysis_date}")
            except Exception as e:
                logger.warning(f"Failed to cache report to database: {e}")

        logger.info(f"Report saved to {output_dir}")
        return str(json_path)

    def _make_json_safe(self, obj: Any) -> Any:
        """Convert dataclasses and complex objects to JSON-safe format."""
        from decimal import Decimal

        if hasattr(obj, '__dataclass_fields__'):
            return {k: self._make_json_safe(v) for k, v in obj.__dict__.items()}
        elif isinstance(obj, dict):
            return {k: self._make_json_safe(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [self._make_json_safe(item) for item in obj]
        elif isinstance(obj, (date, datetime)):
            return obj.isoformat()
        elif isinstance(obj, Decimal):
            return float(obj)
        elif hasattr(obj, '__float__'):
            # Handle any numeric type that can be converted to float
            return float(obj)
        else:
            return obj

    def _format_text_report(self, report: Dict[str, Any]) -> str:
        """Format report as readable text."""
        lines = []

        lines.append("=" * 80)
        lines.append(f"NHL DAILY INSIGHTS REPORT - {report.get('analysis_date')}")
        lines.append("=" * 80)
        lines.append(f"Generated: {report.get('generated_at')}")
        lines.append("")

        # LLM Narrative (if available)
        if report.get('llm_narrative'):
            lines.append("-" * 80)
            lines.append("AI ANALYSIS")
            lines.append("-" * 80)
            lines.append(report['llm_narrative'])
            lines.append("")

        # Rule-based insights
        rule_insights = report.get('rule_based_insights')
        if rule_insights:
            lines.append("-" * 80)
            lines.append("RULE-BASED ANALYSIS")
            lines.append("-" * 80)
            # Use the existing print_report format
            generator = NHLInsightsGenerator()
            lines.append(generator.print_report(rule_insights))

        return "\n".join(lines)

    def print_report(self, report: Dict[str, Any]):
        """Print formatted report to console."""
        print(self._format_text_report(report))


# ============================================================================
# CLI Entry Point
# ============================================================================

def main():
    """CLI entry point for LLM insights generation."""
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

    # Check for --no-llm flag
    include_llm = '--no-llm' not in sys.argv

    print(f"Generating {'full' if include_llm else 'rule-based only'} report for {target}...")

    # Initialize DB if available
    db = None
    try:
        from database.db_manager import NHLDBManager
        db = NHLDBManager()
    except Exception as e:
        logger.warning(f"Database not available: {e}")

    generator = NHLDailyReportGenerator(db_manager=db)
    report = generator.generate_full_report(target, include_llm=include_llm)

    generator.print_report(report)

    # Save report
    output_path = generator.save_report(report)
    print(f"\nReport saved to: {output_path}")


if __name__ == '__main__':
    main()
