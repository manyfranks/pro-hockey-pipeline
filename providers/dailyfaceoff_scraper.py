# nhl_isolated/providers/dailyfaceoff_scraper.py
"""
DailyFaceoff Line Combinations Scraper

Scrapes line combinations, defensive pairings, power play units, and goalie info
from DailyFaceoff.com for all 32 NHL teams.

Data includes:
- Even strength forward lines (L1-L4) with LW/C/RW
- Defensive pairings (D1-D3) with LD/RD
- Power play units (PP1, PP2)
- Starting/backup goalies

The data is extracted from Next.js __NEXT_DATA__ JSON embedded in the page,
making it reliable and structured.

Usage:
    scraper = DailyFaceoffScraper()

    # Get single team
    edm_lines = scraper.get_team_lines('EDM')

    # Get all teams (with caching)
    all_lines = scraper.get_all_teams()

    # Force refresh cache
    all_lines = scraper.get_all_teams(force_refresh=True)
"""

import os
import json
import time
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Any
from pathlib import Path


# Team abbreviation to DailyFaceoff slug mapping
TEAM_SLUGS = {
    'ANA': 'anaheim-ducks',
    # 'ARI': 'arizona-coyotes',  # Relocated to Utah - use UTA
    'BOS': 'boston-bruins',
    'BUF': 'buffalo-sabres',
    'CGY': 'calgary-flames',
    'CAR': 'carolina-hurricanes',
    'CHI': 'chicago-blackhawks',
    'COL': 'colorado-avalanche',
    'CBJ': 'columbus-blue-jackets',
    'DAL': 'dallas-stars',
    'DET': 'detroit-red-wings',
    'EDM': 'edmonton-oilers',
    'FLA': 'florida-panthers',
    'LAK': 'los-angeles-kings',
    'MIN': 'minnesota-wild',
    'MTL': 'montreal-canadiens',
    'NSH': 'nashville-predators',
    'NJD': 'new-jersey-devils',
    'NYI': 'new-york-islanders',
    'NYR': 'new-york-rangers',
    'OTT': 'ottawa-senators',
    'PHI': 'philadelphia-flyers',
    'PIT': 'pittsburgh-penguins',
    'SJS': 'san-jose-sharks',
    'SEA': 'seattle-kraken',
    'STL': 'st-louis-blues',
    'TBL': 'tampa-bay-lightning',
    'TOR': 'toronto-maple-leafs',
    'UTA': 'utah-hockey-club',  # Formerly Arizona
    'VAN': 'vancouver-canucks',
    'VGK': 'vegas-golden-knights',
    'WSH': 'washington-capitals',
    'WPG': 'winnipeg-jets',
}

# Reverse mapping
SLUG_TO_ABBREV = {v: k for k, v in TEAM_SLUGS.items()}


class DailyFaceoffScraper:
    """Scrapes line combinations from DailyFaceoff.com"""

    BASE_URL = "https://www.dailyfaceoff.com/teams"
    CACHE_DIR = Path(__file__).parent.parent / "data" / "cache" / "dailyfaceoff"
    CACHE_FILE = "line_combinations.json"
    CACHE_MAX_AGE_HOURS = 6  # Refresh cache if older than this

    def __init__(self, cache_dir: Optional[Path] = None):
        """
        Initialize the scraper.

        Args:
            cache_dir: Optional custom cache directory
        """
        self.cache_dir = Path(cache_dir) if cache_dir else self.CACHE_DIR
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
        })

    def get_team_lines(self, team_abbrev: str) -> Optional[Dict[str, Any]]:
        """
        Get line combinations for a single team.

        Args:
            team_abbrev: Team abbreviation (e.g., 'EDM', 'DAL')

        Returns:
            Dictionary with line combination data, or None if failed
        """
        team_abbrev = team_abbrev.upper()

        if team_abbrev not in TEAM_SLUGS:
            print(f"[DailyFaceoff] Unknown team: {team_abbrev}")
            return None

        slug = TEAM_SLUGS[team_abbrev]
        url = f"{self.BASE_URL}/{slug}/line-combinations"

        try:
            response = self.session.get(url, timeout=10)
            response.raise_for_status()

            return self._parse_team_page(response.text, team_abbrev)

        except requests.RequestException as e:
            print(f"[DailyFaceoff] Error fetching {team_abbrev}: {e}")
            return None

    def _parse_team_page(self, html: str, team_abbrev: str) -> Optional[Dict[str, Any]]:
        """Parse the team page HTML and extract line combinations."""
        soup = BeautifulSoup(html, 'html.parser')

        # Find the Next.js data
        next_data = soup.find('script', id='__NEXT_DATA__')
        if not next_data:
            print(f"[DailyFaceoff] No __NEXT_DATA__ found for {team_abbrev}")
            return None

        try:
            data = json.loads(next_data.string)
            props = data.get('props', {}).get('pageProps', {})
            combinations = props.get('combinations', {})
        except (json.JSONDecodeError, KeyError) as e:
            print(f"[DailyFaceoff] Error parsing JSON for {team_abbrev}: {e}")
            return None

        if not combinations:
            return None

        players = combinations.get('players', [])

        # Organize players by group
        groups = {}
        for p in players:
            group = p.get('groupIdentifier')
            category = p.get('categoryIdentifier')
            key = f"{category}_{group}"
            if key not in groups:
                groups[key] = []
            groups[key].append({
                'name': p.get('name'),
                'player_id': p.get('playerId'),
                'position': p.get('positionIdentifier'),
                'position_name': p.get('positionName'),
                'jersey_number': p.get('jerseyNumber'),
                'injury_status': p.get('injuryStatus'),
            })

        # Build structured output
        result = {
            'team': team_abbrev,
            'team_name': combinations.get('teamName'),
            'source': combinations.get('sourceName'),
            'updated_at': combinations.get('updatedAt'),
            'scraped_at': datetime.now(timezone.utc).isoformat(),
            'forward_lines': self._extract_forward_lines(groups),
            'defense_pairs': self._extract_defense_pairs(groups),
            'power_play': self._extract_power_play(groups),
            'penalty_kill': self._extract_penalty_kill(groups),
            'goalies': self._extract_goalies(groups),
            'players_by_line': self._build_player_line_map(groups),
        }

        return result

    def _extract_forward_lines(self, groups: Dict) -> Dict[int, Dict[str, str]]:
        """Extract forward lines from groups."""
        lines = {}
        for i in range(1, 5):
            key = f"ev_f{i}"
            if key in groups:
                line = groups[key]
                lw = next((p for p in line if p['position'] == 'lw'), {})
                c = next((p for p in line if p['position'] == 'c'), {})
                rw = next((p for p in line if p['position'] == 'rw'), {})
                lines[i] = {
                    'lw': lw.get('name'),
                    'c': c.get('name'),
                    'rw': rw.get('name'),
                    'players': [lw, c, rw],
                }
        return lines

    def _extract_defense_pairs(self, groups: Dict) -> Dict[int, Dict[str, str]]:
        """Extract defensive pairings from groups."""
        pairs = {}
        for i in range(1, 4):
            key = f"ev_d{i}"
            if key in groups:
                pair = groups[key]
                ld = next((p for p in pair if p['position'] == 'ld'), {})
                rd = next((p for p in pair if p['position'] == 'rd'), {})
                pairs[i] = {
                    'ld': ld.get('name'),
                    'rd': rd.get('name'),
                    'players': [ld, rd],
                }
        return pairs

    def _extract_power_play(self, groups: Dict) -> Dict[int, List[str]]:
        """Extract power play units from groups."""
        pp_units = {}
        for i in range(1, 3):
            key = f"pp_pp{i}"
            if key in groups:
                unit = groups[key]
                pp_units[i] = {
                    'players': [p['name'] for p in unit],
                    'full_data': unit,
                }
        return pp_units

    def _extract_penalty_kill(self, groups: Dict) -> Dict[int, List[str]]:
        """Extract penalty kill units from groups."""
        pk_units = {}
        for i in range(1, 3):
            key = f"pk_pk{i}"
            if key in groups:
                unit = groups[key]
                pk_units[i] = {
                    'players': [p['name'] for p in unit],
                    'full_data': unit,
                }
        return pk_units

    def _extract_goalies(self, groups: Dict) -> List[Dict]:
        """Extract goalie information from groups."""
        goalies = []
        for key in groups:
            if key.endswith('_g1') or key.endswith('_g2'):
                for g in groups[key]:
                    goalie_data = {
                        'name': g.get('name'),
                        'jersey_number': g.get('jersey_number'),
                        'is_starter': 'g1' in key,
                    }
                    if goalie_data not in goalies:
                        goalies.append(goalie_data)
        return goalies

    def _build_player_line_map(self, groups: Dict) -> Dict[str, Dict]:
        """Build a map from player name to their line/PP assignments."""
        player_map = {}

        # Even strength forwards
        for i in range(1, 5):
            key = f"ev_f{i}"
            if key in groups:
                for p in groups[key]:
                    name = p.get('name')
                    if name:
                        if name not in player_map:
                            player_map[name] = {'line': None, 'pp_unit': 0, 'position': p.get('position')}
                        player_map[name]['line'] = i

        # Even strength defense
        for i in range(1, 4):
            key = f"ev_d{i}"
            if key in groups:
                for p in groups[key]:
                    name = p.get('name')
                    if name:
                        if name not in player_map:
                            player_map[name] = {'line': None, 'pp_unit': 0, 'position': p.get('position')}
                        player_map[name]['line'] = i

        # Power play
        for i in range(1, 3):
            key = f"pp_pp{i}"
            if key in groups:
                for p in groups[key]:
                    name = p.get('name')
                    if name and name in player_map:
                        player_map[name]['pp_unit'] = i

        return player_map

    def get_all_teams(self, force_refresh: bool = False) -> Dict[str, Dict]:
        """
        Get line combinations for all teams, using cache when available.

        Args:
            force_refresh: Force refresh from website even if cache is fresh

        Returns:
            Dictionary mapping team abbreviations to their line data
        """
        cache_path = self.cache_dir / self.CACHE_FILE

        # Check cache
        if not force_refresh and cache_path.exists():
            try:
                with open(cache_path, 'r') as f:
                    cached = json.load(f)

                cached_at_str = cached.get('cached_at', '2000-01-01')
                # Handle both timezone-aware and naive datetimes
                if '+' in cached_at_str or cached_at_str.endswith('Z'):
                    cached_at = datetime.fromisoformat(cached_at_str.replace('Z', '+00:00'))
                else:
                    cached_at = datetime.fromisoformat(cached_at_str).replace(tzinfo=timezone.utc)
                age_hours = (datetime.now(timezone.utc) - cached_at).total_seconds() / 3600

                if age_hours < self.CACHE_MAX_AGE_HOURS:
                    print(f"[DailyFaceoff] Using cached data ({age_hours:.1f}h old)")
                    return cached.get('teams', {})
                else:
                    print(f"[DailyFaceoff] Cache expired ({age_hours:.1f}h old), refreshing...")
            except (json.JSONDecodeError, KeyError):
                print("[DailyFaceoff] Cache corrupted, refreshing...")

        # Fetch all teams
        all_teams = {}
        failed_teams = []

        print(f"[DailyFaceoff] Fetching {len(TEAM_SLUGS)} teams...")

        for i, abbrev in enumerate(TEAM_SLUGS.keys()):
            try:
                data = self.get_team_lines(abbrev)
                if data:
                    all_teams[abbrev] = data
                    print(f"  [{i+1}/{len(TEAM_SLUGS)}] {abbrev}: OK")
                else:
                    failed_teams.append(abbrev)
                    print(f"  [{i+1}/{len(TEAM_SLUGS)}] {abbrev}: FAILED")

                # Rate limiting - be respectful
                time.sleep(0.5)

            except Exception as e:
                failed_teams.append(abbrev)
                print(f"  [{i+1}/{len(TEAM_SLUGS)}] {abbrev}: ERROR - {e}")

        # Save to cache
        cache_data = {
            'cached_at': datetime.now(timezone.utc).isoformat(),
            'teams_count': len(all_teams),
            'failed_teams': failed_teams,
            'teams': all_teams,
        }

        with open(cache_path, 'w') as f:
            json.dump(cache_data, f, indent=2)

        print(f"[DailyFaceoff] Cached {len(all_teams)} teams to {cache_path}")

        return all_teams

    def get_player_line_info(self, player_name: str, team_abbrev: str) -> Optional[Dict]:
        """
        Get line and PP info for a specific player.

        Args:
            player_name: Player's full name
            team_abbrev: Team abbreviation

        Returns:
            Dict with 'line' (1-4) and 'pp_unit' (0, 1, or 2), or None
        """
        team_data = self.get_team_lines(team_abbrev)
        if not team_data:
            return None

        player_map = team_data.get('players_by_line', {})

        # Try exact match first
        if player_name in player_map:
            return player_map[player_name]

        # Try fuzzy match (last name)
        last_name = player_name.split()[-1].lower()
        for name, info in player_map.items():
            if name.split()[-1].lower() == last_name:
                return info

        return None


def main():
    """Test the scraper."""
    scraper = DailyFaceoffScraper()

    # Test single team
    print("Testing single team fetch (EDM)...")
    edm = scraper.get_team_lines('EDM')

    if edm:
        print(f"\nEdmonton Oilers Lines (source: {edm['source']}):")
        print(f"Updated: {edm['updated_at']}")

        print("\nForward Lines:")
        for num, line in edm['forward_lines'].items():
            print(f"  L{num}: {line['lw']:<20} - {line['c']:<20} - {line['rw']}")

        print("\nDefense Pairs:")
        for num, pair in edm['defense_pairs'].items():
            print(f"  D{num}: {pair['ld']:<20} - {pair['rd']}")

        print("\nPower Play:")
        for num, pp in edm['power_play'].items():
            print(f"  PP{num}: {', '.join(pp['players'])}")

        print("\nPlayer Line Map (sample):")
        for name, info in list(edm['players_by_line'].items())[:5]:
            print(f"  {name}: Line {info['line']}, PP{info['pp_unit']}")

    # Test player lookup
    print("\n" + "="*50)
    print("Testing player lookup...")

    mcdavid = scraper.get_player_line_info("Connor McDavid", "EDM")
    print(f"Connor McDavid: {mcdavid}")

    bouchard = scraper.get_player_line_info("Evan Bouchard", "EDM")
    print(f"Evan Bouchard: {bouchard}")


if __name__ == '__main__':
    main()
