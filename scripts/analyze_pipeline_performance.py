#!/usr/bin/env python3
"""
NHL Pipeline Performance Analysis

Analyzes:
1. Top 3 daily player rankings - perfect day hit rate (all 3 hit)
2. SGP parlay patterns - identify what makes winning parlays

Run from project root:
    python scripts/analyze_pipeline_performance.py
"""
import os
import sys
from datetime import date, datetime, timedelta
from collections import defaultdict
from decimal import Decimal

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv('.env')

from sqlalchemy import create_engine, text

def get_engine():
    """Create database engine."""
    conn_str = os.getenv("DATABASE_URL")
    if not conn_str:
        raise ValueError("DATABASE_URL not set")
    return create_engine(conn_str, connect_args={"sslmode": "require"})


def analyze_top3_daily_performance(engine):
    """
    Analyze Top 3 ranked players each day.
    Calculate how often ALL 3 hit (got at least 1 point).
    """
    print("\n" + "="*80)
    print("📊 TOP 3 DAILY PLAYER RANKINGS ANALYSIS")
    print("="*80)

    # Query all settled predictions with rank <= 3
    query = text("""
        SELECT
            analysis_date,
            rank,
            player_name,
            team,
            opponent,
            final_score,
            confidence,
            line_number,
            pp_unit,
            recent_ppg,
            actual_points,
            point_outcome,
            is_scoreable
        FROM nhl_daily_predictions
        WHERE rank <= 3
          AND point_outcome IS NOT NULL
          AND point_outcome IN (0, 1)  -- Only settled games (exclude PPD/DNP)
        ORDER BY analysis_date DESC, rank ASC
    """)

    with engine.connect() as conn:
        result = conn.execute(query)
        rows = result.fetchall()

    if not rows:
        print("❌ No settled Top 3 predictions found!")
        return

    # Group by date
    by_date = defaultdict(list)
    for row in rows:
        by_date[row.analysis_date].append(row)

    # Analyze each day
    perfect_days = []
    two_hit_days = []
    one_hit_days = []
    zero_hit_days = []

    all_days_details = []

    for analysis_date, players in sorted(by_date.items(), reverse=True):
        # Only analyze days with exactly 3 players in Top 3
        if len(players) < 3:
            continue

        top3 = players[:3]  # Ensure we only look at top 3
        hits = sum(1 for p in top3 if p.point_outcome == 1)

        day_detail = {
            'date': analysis_date,
            'hits': hits,
            'players': [
                {
                    'rank': p.rank,
                    'name': p.player_name,
                    'team': p.team,
                    'opponent': p.opponent,
                    'score': float(p.final_score) if p.final_score else 0,
                    'confidence': p.confidence,
                    'line': p.line_number,
                    'pp': p.pp_unit,
                    'recent_ppg': float(p.recent_ppg) if p.recent_ppg else 0,
                    'actual_points': p.actual_points,
                    'hit': p.point_outcome == 1
                }
                for p in top3
            ]
        }
        all_days_details.append(day_detail)

        if hits == 3:
            perfect_days.append(day_detail)
        elif hits == 2:
            two_hit_days.append(day_detail)
        elif hits == 1:
            one_hit_days.append(day_detail)
        else:
            zero_hit_days.append(day_detail)

    total_days = len(all_days_details)

    print(f"\n📅 Analysis Period: {min(by_date.keys())} to {max(by_date.keys())}")
    print(f"📊 Total Days Analyzed: {total_days}")
    print()

    # Summary stats
    print("🎯 DAILY HIT BREAKDOWN:")
    print("-" * 40)
    print(f"  🟢 Perfect Days (3/3 hit): {len(perfect_days):3d} ({100*len(perfect_days)/total_days:.1f}%)")
    print(f"  🟡 2 of 3 hit:             {len(two_hit_days):3d} ({100*len(two_hit_days)/total_days:.1f}%)")
    print(f"  🟠 1 of 3 hit:             {len(one_hit_days):3d} ({100*len(one_hit_days)/total_days:.1f}%)")
    print(f"  🔴 0 of 3 hit:             {len(zero_hit_days):3d} ({100*len(zero_hit_days)/total_days:.1f}%)")
    print()

    # Calculate total individual hit rate
    total_players = sum(len(d['players']) for d in all_days_details)
    total_hits = sum(d['hits'] for d in all_days_details)
    print(f"📈 Individual Hit Rate: {total_hits}/{total_players} = {100*total_hits/total_players:.1f}%")
    print()

    # Analyze by rank
    print("\n🏆 HIT RATE BY RANK:")
    print("-" * 40)
    for rank in [1, 2, 3]:
        rank_players = [p for d in all_days_details for p in d['players'] if p['rank'] == rank]
        rank_hits = sum(1 for p in rank_players if p['hit'])
        if rank_players:
            print(f"  Rank {rank}: {rank_hits}/{len(rank_players)} = {100*rank_hits/len(rank_players):.1f}%")

    # Analyze by confidence
    print("\n💪 HIT RATE BY CONFIDENCE (Top 3 only):")
    print("-" * 40)
    all_top3_players = [p for d in all_days_details for p in d['players']]
    by_confidence = defaultdict(list)
    for p in all_top3_players:
        by_confidence[p['confidence']].append(p)

    for conf in ['very_high', 'high', 'medium', 'low']:
        if conf in by_confidence:
            players = by_confidence[conf]
            hits = sum(1 for p in players if p['hit'])
            print(f"  {conf:10s}: {hits:3d}/{len(players):3d} = {100*hits/len(players):.1f}%")

    # Analyze by line number
    print("\n🏒 HIT RATE BY LINE NUMBER (Top 3 only):")
    print("-" * 40)
    by_line = defaultdict(list)
    for p in all_top3_players:
        by_line[p['line']].append(p)

    for line in sorted(by_line.keys()):
        if line:
            players = by_line[line]
            hits = sum(1 for p in players if p['hit'])
            print(f"  Line {line}: {hits:3d}/{len(players):3d} = {100*hits/len(players):.1f}%")

    # Analyze by PP unit
    print("\n⚡ HIT RATE BY POWER PLAY UNIT (Top 3 only):")
    print("-" * 40)
    by_pp = defaultdict(list)
    for p in all_top3_players:
        pp = p['pp'] if p['pp'] else 0
        by_pp[pp].append(p)

    for pp in sorted(by_pp.keys()):
        players = by_pp[pp]
        hits = sum(1 for p in players if p['hit'])
        label = f"PP{pp}" if pp > 0 else "No PP"
        print(f"  {label:6s}: {hits:3d}/{len(players):3d} = {100*hits/len(players):.1f}%")

    # Show perfect days
    print("\n\n🌟 PERFECT DAYS (All 3 Hit):")
    print("-" * 80)
    for day in perfect_days[:15]:  # Show recent 15
        print(f"\n📅 {day['date']}")
        for p in day['players']:
            pp_str = f"PP{p['pp']}" if p['pp'] else ""
            print(f"   #{p['rank']} {p['name']:25s} ({p['team']} vs {p['opponent']}) "
                  f"L{p['line']} {pp_str:4s} Score:{p['score']:.1f} → {p['actual_points']}pts ✅")

    # Show zero-hit days for pattern analysis
    print("\n\n❌ ZERO-HIT DAYS (0/3 Hit) - Analyzing Patterns:")
    print("-" * 80)
    for day in zero_hit_days[:10]:  # Show recent 10
        print(f"\n📅 {day['date']}")
        for p in day['players']:
            pp_str = f"PP{p['pp']}" if p['pp'] else ""
            print(f"   #{p['rank']} {p['name']:25s} ({p['team']} vs {p['opponent']}) "
                  f"L{p['line']} {pp_str:4s} Score:{p['score']:.1f} PPG:{p['recent_ppg']:.2f} → 0pts ❌")

    # Score threshold analysis
    print("\n\n📊 SCORE THRESHOLD ANALYSIS:")
    print("-" * 60)
    for threshold in [80, 75, 70, 65, 60, 55, 50]:
        above_threshold = [p for p in all_top3_players if p['score'] >= threshold]
        if above_threshold:
            hits = sum(1 for p in above_threshold if p['hit'])
            print(f"  Score >= {threshold}: {hits:3d}/{len(above_threshold):3d} = {100*hits/len(above_threshold):.1f}%")

    # Recent PPG analysis
    print("\n\n📈 RECENT PPG ANALYSIS (Last 10 Games):")
    print("-" * 60)
    for ppg_min in [1.5, 1.25, 1.0, 0.75, 0.5]:
        above_ppg = [p for p in all_top3_players if p['recent_ppg'] >= ppg_min]
        if above_ppg:
            hits = sum(1 for p in above_ppg if p['hit'])
            print(f"  PPG >= {ppg_min:.2f}: {hits:3d}/{len(above_ppg):3d} = {100*hits/len(above_ppg):.1f}%")

    return {
        'total_days': total_days,
        'perfect_days': len(perfect_days),
        'two_hit_days': len(two_hit_days),
        'one_hit_days': len(one_hit_days),
        'zero_hit_days': len(zero_hit_days),
        'individual_hit_rate': total_hits / total_players if total_players > 0 else 0,
        'all_days': all_days_details,
        'perfect_days_detail': perfect_days,
        'zero_hit_days_detail': zero_hit_days
    }


def analyze_sgp_performance(engine):
    """
    Analyze SGP parlay performance.
    Identify patterns in winning vs losing parlays.
    """
    print("\n\n" + "="*80)
    print("🎰 SGP PARLAY PERFORMANCE ANALYSIS")
    print("="*80)

    # Query all parlays with settlement
    query = text("""
        SELECT
            p.id as parlay_id,
            p.parlay_type,
            p.game_id,
            p.game_date,
            p.home_team,
            p.away_team,
            p.total_legs,
            p.combined_odds,
            p.implied_probability,
            p.thesis,
            s.legs_hit,
            s.total_legs as settled_legs,
            s.result as parlay_result,
            s.profit
        FROM nhl_sgp_parlays p
        JOIN nhl_sgp_settlements s ON p.id = s.parlay_id
        WHERE s.result IS NOT NULL
        ORDER BY p.game_date DESC
    """)

    with engine.connect() as conn:
        result = conn.execute(query)
        parlays = result.fetchall()

    if not parlays:
        print("❌ No settled SGP parlays found!")
        return

    print(f"\n📊 Total Settled Parlays: {len(parlays)}")

    # Summary stats
    wins = [p for p in parlays if p.parlay_result == 'WIN']
    losses = [p for p in parlays if p.parlay_result == 'LOSS']

    print(f"\n🎯 PARLAY RESULTS:")
    print("-" * 40)
    print(f"  🟢 Wins:   {len(wins):3d} ({100*len(wins)/len(parlays):.1f}%)")
    print(f"  🔴 Losses: {len(losses):3d} ({100*len(losses)/len(parlays):.1f}%)")

    # Calculate profit
    total_stake = len(parlays) * 100  # $100 per parlay
    total_profit = sum(float(p.profit) if p.profit else 0 for p in parlays)
    roi = (total_profit / total_stake) * 100 if total_stake > 0 else 0

    print(f"\n💰 PROFIT/LOSS (at $100/parlay):")
    print("-" * 40)
    print(f"  Total Stake:  ${total_stake:,.0f}")
    print(f"  Total Profit: ${total_profit:,.2f}")
    print(f"  ROI:          {roi:+.1f}%")

    # Analyze by leg count
    print("\n\n📊 PERFORMANCE BY LEG COUNT:")
    print("-" * 60)
    by_legs = defaultdict(list)
    for p in parlays:
        by_legs[p.total_legs].append(p)

    for leg_count in sorted(by_legs.keys()):
        leg_parlays = by_legs[leg_count]
        leg_wins = sum(1 for p in leg_parlays if p.parlay_result == 'WIN')
        leg_profit = sum(float(p.profit) if p.profit else 0 for p in leg_parlays)
        avg_odds = sum(p.combined_odds for p in leg_parlays if p.combined_odds) / len(leg_parlays)
        print(f"  {leg_count}-leg parlays: {leg_wins}/{len(leg_parlays)} wins "
              f"({100*leg_wins/len(leg_parlays):.1f}%) | Profit: ${leg_profit:+,.0f} | Avg Odds: {avg_odds:+.0f}")

    # Analyze by parlay type
    print("\n\n📊 PERFORMANCE BY PARLAY TYPE:")
    print("-" * 60)
    by_type = defaultdict(list)
    for p in parlays:
        by_type[p.parlay_type].append(p)

    for ptype in sorted(by_type.keys()):
        type_parlays = by_type[ptype]
        type_wins = sum(1 for p in type_parlays if p.parlay_result == 'WIN')
        type_profit = sum(float(p.profit) if p.profit else 0 for p in type_parlays)
        print(f"  {ptype:15s}: {type_wins:3d}/{len(type_parlays):3d} wins "
              f"({100*type_wins/len(type_parlays):.1f}%) | Profit: ${type_profit:+,.0f}")

    # Analyze near misses
    print("\n\n🎯 NEAR MISS ANALYSIS:")
    print("-" * 60)
    near_misses = [p for p in parlays if p.legs_hit == p.total_legs - 1 and p.parlay_result == 'LOSS']
    print(f"  Near misses (missed by 1 leg): {len(near_misses)} ({100*len(near_misses)/len(losses):.1f}% of losses)")

    # By legs hit ratio
    print("\n📊 LEGS HIT DISTRIBUTION (for losses):")
    by_hit_ratio = defaultdict(int)
    for p in losses:
        if p.total_legs and p.legs_hit is not None:
            ratio = f"{p.legs_hit}/{p.total_legs}"
            by_hit_ratio[ratio] += 1

    for ratio, count in sorted(by_hit_ratio.items(), key=lambda x: x[0]):
        print(f"  {ratio} legs hit: {count} parlays")

    # Now analyze individual legs
    print("\n\n" + "="*80)
    print("🔍 INDIVIDUAL LEG ANALYSIS")
    print("="*80)

    leg_query = text("""
        SELECT
            l.player_name,
            l.team,
            l.stat_type,
            l.line,
            l.direction,
            l.odds,
            l.edge_pct,
            l.confidence,
            l.model_probability,
            l.pipeline_score,
            l.pipeline_confidence,
            l.pipeline_rank,
            l.actual_value,
            l.result,
            l.signals,
            p.game_date,
            s.result as parlay_result
        FROM nhl_sgp_legs l
        JOIN nhl_sgp_parlays p ON l.parlay_id = p.id
        JOIN nhl_sgp_settlements s ON p.id = s.parlay_id
        WHERE l.result IS NOT NULL
        ORDER BY p.game_date DESC
    """)

    with engine.connect() as conn:
        result = conn.execute(leg_query)
        legs = result.fetchall()

    if legs:
        print(f"\n📊 Total Settled Legs: {len(legs)}")

        leg_wins = [l for l in legs if l.result == 'WIN']
        leg_losses = [l for l in legs if l.result == 'LOSS']

        print(f"\n🎯 INDIVIDUAL LEG RESULTS:")
        print("-" * 40)
        print(f"  🟢 Wins:   {len(leg_wins):3d} ({100*len(leg_wins)/len(legs):.1f}%)")
        print(f"  🔴 Losses: {len(leg_losses):3d} ({100*len(leg_losses)/len(legs):.1f}%)")

        # By stat type
        print("\n\n📊 LEG HIT RATE BY STAT TYPE:")
        print("-" * 60)
        by_stat = defaultdict(list)
        for l in legs:
            by_stat[l.stat_type].append(l)

        for stat in sorted(by_stat.keys()):
            stat_legs = by_stat[stat]
            stat_wins = sum(1 for l in stat_legs if l.result == 'WIN')
            print(f"  {stat:20s}: {stat_wins:3d}/{len(stat_legs):3d} = {100*stat_wins/len(stat_legs):.1f}%")

        # By direction
        print("\n\n📊 LEG HIT RATE BY DIRECTION:")
        print("-" * 60)
        by_dir = defaultdict(list)
        for l in legs:
            by_dir[l.direction].append(l)

        for direction in sorted(by_dir.keys()):
            dir_legs = by_dir[direction]
            dir_wins = sum(1 for l in dir_legs if l.result == 'WIN')
            print(f"  {direction:10s}: {dir_wins:3d}/{len(dir_legs):3d} = {100*dir_wins/len(dir_legs):.1f}%")

        # By line value
        print("\n\n📊 LEG HIT RATE BY LINE:")
        print("-" * 60)
        by_line = defaultdict(list)
        for l in legs:
            if l.line:
                by_line[float(l.line)].append(l)

        for line in sorted(by_line.keys()):
            line_legs = by_line[line]
            line_wins = sum(1 for l in line_legs if l.result == 'WIN')
            print(f"  {line:5.1f}: {line_wins:3d}/{len(line_legs):3d} = {100*line_wins/len(line_legs):.1f}%")

        # By edge bucket
        print("\n\n📊 LEG HIT RATE BY EDGE BUCKET:")
        print("-" * 60)
        edge_buckets = [(0, 5), (5, 10), (10, 15), (15, 20), (20, 100)]
        for low, high in edge_buckets:
            bucket_legs = [l for l in legs if l.edge_pct and low <= float(l.edge_pct) < high]
            if bucket_legs:
                bucket_wins = sum(1 for l in bucket_legs if l.result == 'WIN')
                print(f"  Edge {low:2d}-{high:2d}%: {bucket_wins:3d}/{len(bucket_legs):3d} = {100*bucket_wins/len(bucket_legs):.1f}%")

        # By confidence
        print("\n\n📊 LEG HIT RATE BY MODEL CONFIDENCE:")
        print("-" * 60)
        conf_buckets = [(0.0, 0.5), (0.5, 0.6), (0.6, 0.7), (0.7, 0.8), (0.8, 1.0)]
        for low, high in conf_buckets:
            bucket_legs = [l for l in legs if l.confidence and low <= float(l.confidence) < high]
            if bucket_legs:
                bucket_wins = sum(1 for l in bucket_legs if l.result == 'WIN')
                print(f"  Conf {low:.1f}-{high:.1f}: {bucket_wins:3d}/{len(bucket_legs):3d} = {100*bucket_wins/len(bucket_legs):.1f}%")

        # By pipeline rank (for points props)
        print("\n\n📊 LEG HIT RATE BY PIPELINE RANK (Points Props Only):")
        print("-" * 60)
        points_legs = [l for l in legs if l.stat_type == 'points' and l.pipeline_rank]
        by_rank = defaultdict(list)
        for l in points_legs:
            by_rank[l.pipeline_rank].append(l)

        for rank in sorted(by_rank.keys())[:10]:  # Top 10 ranks
            rank_legs = by_rank[rank]
            rank_wins = sum(1 for l in rank_legs if l.result == 'WIN')
            print(f"  Rank {rank:2d}: {rank_wins:3d}/{len(rank_legs):3d} = {100*rank_wins/len(rank_legs):.1f}%")

        # Analyze LOSING legs - common failure patterns
        print("\n\n🔍 BUSTED LEG ANALYSIS (All failed legs):")
        print("-" * 80)

        # Analyze patterns in all losing legs
        losing_legs = [l for l in legs if l.result == 'LOSS']
        if losing_legs:
            stat_types = defaultdict(int)
            directions = defaultdict(int)
            lines = defaultdict(int)
            edge_ranges = defaultdict(int)
            pipeline_ranks = defaultdict(int)

            for leg in losing_legs:
                stat_types[leg.stat_type] += 1
                directions[leg.direction] += 1
                if leg.line:
                    lines[float(leg.line)] += 1
                if leg.edge_pct:
                    edge = float(leg.edge_pct)
                    if edge < 5:
                        edge_ranges['0-5%'] += 1
                    elif edge < 10:
                        edge_ranges['5-10%'] += 1
                    elif edge < 15:
                        edge_ranges['10-15%'] += 1
                    else:
                        edge_ranges['15%+'] += 1
                if leg.pipeline_rank:
                    if leg.pipeline_rank <= 3:
                        pipeline_ranks['Top 3'] += 1
                    elif leg.pipeline_rank <= 10:
                        pipeline_ranks['4-10'] += 1
                    else:
                        pipeline_ranks['11+'] += 1

            print(f"  Total Losing Legs: {len(losing_legs)}")
            print()
            print("  📊 Losing Leg Patterns:")
            print(f"     By Stat Type:     {dict(stat_types)}")
            print(f"     By Direction:     {dict(directions)}")
            print(f"     By Line:          {dict(lines)}")
            print(f"     By Edge:          {dict(edge_ranges)}")
            print(f"     By Pipeline Rank: {dict(pipeline_ranks)}")

    return {
        'total_parlays': len(parlays),
        'wins': len(wins),
        'losses': len(losses),
        'total_profit': total_profit,
        'roi': roi,
        'near_misses': len(near_misses) if 'near_misses' in dir() else 0
    }


def main():
    """Run full pipeline analysis."""
    print("\n" + "🏒"*40)
    print("NHL PIPELINE PERFORMANCE GRADING")
    print("🏒"*40)
    print(f"\nAnalysis Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    engine = get_engine()

    # Analyze Top 3 daily performance
    top3_results = analyze_top3_daily_performance(engine)

    # Analyze SGP performance
    sgp_results = analyze_sgp_performance(engine)

    # Summary
    print("\n\n" + "="*80)
    print("📋 EXECUTIVE SUMMARY")
    print("="*80)

    if top3_results:
        print("\n🏆 TOP 3 DAILY RANKINGS:")
        print(f"   • Perfect Days (3/3): {top3_results['perfect_days']}/{top3_results['total_days']} ({100*top3_results['perfect_days']/top3_results['total_days']:.1f}%)")
        print(f"   • Individual Hit Rate: {100*top3_results['individual_hit_rate']:.1f}%")
        print(f"   • At least 2/3 hit: {top3_results['perfect_days'] + top3_results['two_hit_days']}/{top3_results['total_days']} ({100*(top3_results['perfect_days'] + top3_results['two_hit_days'])/top3_results['total_days']:.1f}%)")

    if sgp_results:
        print("\n🎰 SGP PARLAYS:")
        print(f"   • Win Rate: {sgp_results['wins']}/{sgp_results['total_parlays']} ({100*sgp_results['wins']/sgp_results['total_parlays']:.1f}%)")
        print(f"   • Total Profit: ${sgp_results['total_profit']:+,.2f}")
        print(f"   • ROI: {sgp_results['roi']:+.1f}%")
        if sgp_results.get('near_misses'):
            print(f"   • Near Misses: {sgp_results['near_misses']} parlays missed by just 1 leg")

    print("\n" + "="*80)


if __name__ == "__main__":
    main()
