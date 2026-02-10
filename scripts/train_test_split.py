"""
Train/Test split validation of backtest results.

Splits signals by date into two halves:
  - TRAIN (first half): derive optimal filters
  - TEST (second half): validate filters on unseen data

Usage:
    python scripts/train_test_split.py full_results.json
"""
import json
import sys
import os
from collections import defaultdict
from datetime import datetime


def load_signals(path: str) -> list[dict]:
    with open(path) as f:
        data = json.load(f)
    return data.get("signals", [])


def split_by_date(signals: list[dict], ratio: float = 0.5) -> tuple[list, list]:
    """Split signals chronologically."""
    sorted_sigs = sorted(signals, key=lambda s: s.get("end_date", ""))
    split_idx = int(len(sorted_sigs) * ratio)
    return sorted_sigs[:split_idx], sorted_sigs[split_idx:]


def analyze_pool(signals: list[dict], label: str) -> dict:
    """Compute stats for a set of signals."""
    if not signals:
        return {"count": 0}

    dates = [s.get("end_date", "")[:10] for s in signals if s.get("end_date")]
    date_range = f"{min(dates)} → {max(dates)}" if dates else "?"

    total = len(signals)
    wins = sum(1 for s in signals if s.get("correct"))
    wr = wins / total if total > 0 else 0

    # By tier
    tiers = {}
    for tier in (1, 2, 3):
        t_sigs = [s for s in signals if s.get("tier") == tier]
        if not t_sigs:
            continue
        t_wins = sum(1 for s in t_sigs if s.get("correct"))
        t_wr = t_wins / len(t_sigs)
        t_avg_pnl = sum(s.get("pnl", 0) for s in t_sigs) / len(t_sigs)
        tiers[tier] = {"count": len(t_sigs), "wins": t_wins, "wr": t_wr, "avg_pnl": t_avg_pnl}

    # By category
    cats = {}
    cat_groups = defaultdict(list)
    for s in signals:
        cat = (s.get("category") or "OTHER").upper()
        cat_groups[cat].append(s)
    for cat, sigs in sorted(cat_groups.items(), key=lambda x: -len(x[1])):
        c_wins = sum(1 for s in sigs if s.get("correct"))
        c_wr = c_wins / len(sigs)
        c_pnl = sum(s.get("pnl", 0) for s in sigs) / len(sigs)
        cats[cat] = {"count": len(sigs), "wr": c_wr, "avg_pnl": c_pnl}

    # By price range
    price_ranges = {
        "penny (<0.10)": lambda s: s.get("entry_price", 0) < 0.10,
        "low (0.10-0.30)": lambda s: 0.10 <= s.get("entry_price", 0) < 0.30,
        "mid (0.30-0.60)": lambda s: 0.30 <= s.get("entry_price", 0) < 0.60,
        "high (0.60-0.85)": lambda s: 0.60 <= s.get("entry_price", 0) <= 0.85,
        "very high (>0.85)": lambda s: s.get("entry_price", 0) > 0.85,
    }
    prices = {}
    for name, filt in price_ranges.items():
        p_sigs = [s for s in signals if filt(s)]
        if not p_sigs:
            continue
        p_wins = sum(1 for s in p_sigs if s.get("correct"))
        p_wr = p_wins / len(p_sigs)
        p_pnl = sum(s.get("pnl", 0) for s in p_sigs) / len(p_sigs)
        prices[name] = {"count": len(p_sigs), "wr": p_wr, "avg_pnl": p_pnl}

    return {
        "label": label,
        "date_range": date_range,
        "count": total,
        "wins": wins,
        "wr": wr,
        "tiers": tiers,
        "categories": cats,
        "price_ranges": prices,
    }


def apply_filters(signals: list[dict],
                   min_price: float = 0.10,
                   max_price: float = 0.85,
                   bad_cats: set = None,
                   max_tier: int = 2) -> list[dict]:
    """Apply main pool filters."""
    if bad_cats is None:
        bad_cats = set()
    return [
        s for s in signals
        if s.get("tier", 99) <= max_tier
        and min_price <= s.get("entry_price", 0) <= max_price
        and (s.get("category") or "OTHER").upper() not in bad_cats
    ]


def print_stats(stats: dict):
    """Print formatted stats."""
    print(f"\n  {stats['label']}")
    print(f"  Period: {stats['date_range']}")
    print(f"  Signals: {stats['count']}, Wins: {stats['wins']}, WR: {stats['wr']:.1%}")

    print(f"\n  {'Tier':<8} {'Count':>6} {'WR':>8} {'Avg P&L':>10}")
    for tier, t in sorted(stats["tiers"].items()):
        print(f"  Tier {tier:<4} {t['count']:>6} {t['wr']:>7.1%} {t['avg_pnl']:>+9.1f}%")

    print(f"\n  {'Category':<12} {'Count':>6} {'WR':>8} {'Avg P&L':>10}")
    for cat, c in sorted(stats["categories"].items(), key=lambda x: -x[1]["count"]):
        print(f"  {cat:<12} {c['count']:>6} {c['wr']:>7.1%} {c['avg_pnl']:>+9.1f}%")

    print(f"\n  {'Price Range':<18} {'Count':>6} {'WR':>8} {'Avg P&L':>10}")
    for name, p in stats["price_ranges"].items():
        print(f"  {name:<18} {p['count']:>6} {p['wr']:>7.1%} {p['avg_pnl']:>+9.1f}%")


def simulate_flat(signals: list[dict], bet: float = 5.0, initial: float = 100.0) -> dict:
    """Quick flat-bet simulation."""
    portfolio = initial
    wins = losses = 0
    for s in sorted(signals, key=lambda x: x.get("end_date", "")):
        ep = s.get("entry_price", 0)
        if ep <= 0 or ep >= 1 or portfolio <= 0.01:
            continue
        b = min(bet, portfolio)
        if s.get("correct"):
            profit = (b / ep) - b
            wins += 1
        else:
            profit = -b
            losses += 1
        portfolio += profit
    total = wins + losses
    return {
        "trades": total, "wins": wins, "losses": losses,
        "wr": wins / total if total > 0 else 0,
        "final": round(portfolio, 2),
        "roi": round((portfolio - initial) / initial * 100, 1),
    }


def main():
    if len(sys.argv) < 2:
        print("Usage: python scripts/train_test_split.py <results.json>")
        sys.exit(1)

    path = sys.argv[1]
    signals = load_signals(path)
    if not signals:
        print("No signals found.")
        sys.exit(1)

    train, test = split_by_date(signals, ratio=0.5)

    print("=" * 70)
    print("  TRAIN / TEST SPLIT VALIDATION")
    print("=" * 70)
    print(f"\n  Total signals: {len(signals)}")
    print(f"  Train: {len(train)} | Test: {len(test)}")

    # ── Unfiltered stats ──
    print(f"\n{'─' * 70}")
    print("  UNFILTERED (all signals)")
    print(f"{'─' * 70}")

    train_stats = analyze_pool(train, "TRAIN (first half)")
    test_stats = analyze_pool(test, "TEST (second half)")

    print_stats(train_stats)
    print_stats(test_stats)

    # ── Derive filters from TRAIN ──
    print(f"\n{'=' * 70}")
    print("  FILTER DERIVATION (from TRAIN data only)")
    print("=" * 70)

    # Find bad categories in train: WR < 50% or avg_pnl < 0
    train_bad_cats = set()
    for cat, c in train_stats["categories"].items():
        if c["wr"] < 0.50 or c["avg_pnl"] < -10:
            train_bad_cats.add(cat)
    print(f"\n  Bad categories (WR<50% or P&L<-10%): {train_bad_cats or 'none'}")

    # Find optimal price range: check which ranges have WR > 55%
    good_price_ranges = []
    for name, p in train_stats["price_ranges"].items():
        if p["wr"] > 0.55 and p["count"] >= 10:
            good_price_ranges.append(name)
    print(f"  Good price ranges (WR>55%, n≥10): {good_price_ranges}")

    # Find best tier cutoff
    for tier in (1, 2, 3):
        if tier in train_stats["tiers"]:
            t = train_stats["tiers"][tier]
            verdict = "USE" if t["wr"] > 0.50 else "SKIP"
            print(f"  Tier {tier}: WR={t['wr']:.1%}, n={t['count']} → {verdict}")

    # ── Apply TRAIN-derived filters to TEST ──
    print(f"\n{'=' * 70}")
    print("  APPLYING TRAIN FILTERS TO TEST DATA")
    print("=" * 70)

    # Also derive what our backtest v2 used: CRYPTO, CULTURE, FINANCE excluded
    backtest_bad_cats = {"CRYPTO", "CULTURE", "FINANCE"}

    configs = [
        ("No filters (baseline)", lambda s: True, {}),
        ("Backtest v2 filters", lambda s: True,
         {"min_price": 0.10, "max_price": 0.85, "bad_cats": backtest_bad_cats, "max_tier": 2}),
        ("TRAIN-derived filters", lambda s: True,
         {"min_price": 0.10, "max_price": 0.85, "bad_cats": train_bad_cats, "max_tier": 2}),
        ("Tier 1 only + TRAIN filters", lambda s: True,
         {"min_price": 0.10, "max_price": 0.85, "bad_cats": train_bad_cats, "max_tier": 1}),
    ]

    print(f"\n  {'Config':<32} {'Set':<6} {'Trades':>6} {'WR':>8} {'Final $':>9} {'ROI':>8}")
    print(f"  {'─' * 32} {'─' * 6} {'─' * 6} {'─' * 8} {'─' * 9} {'─' * 8}")

    for name, _, filter_kwargs in configs:
        if filter_kwargs:
            train_filtered = apply_filters(train, **filter_kwargs)
            test_filtered = apply_filters(test, **filter_kwargs)
        else:
            train_filtered = [s for s in train if s.get("tier", 99) <= 3]
            test_filtered = [s for s in test if s.get("tier", 99) <= 3]

        train_sim = simulate_flat(train_filtered)
        test_sim = simulate_flat(test_filtered)

        print(
            f"  {name:<32} {'TRAIN':<6} {train_sim['trades']:>6} "
            f"{train_sim['wr']:>7.1%} ${train_sim['final']:>7.0f} {train_sim['roi']:>+7.1f}%"
        )
        print(
            f"  {'':<32} {'TEST':<6} {test_sim['trades']:>6} "
            f"{test_sim['wr']:>7.1%} ${test_sim['final']:>7.0f} {test_sim['roi']:>+7.1f}%"
        )
        print()

    # ── Statistical significance ──
    print(f"{'=' * 70}")
    print("  STATISTICAL SIGNIFICANCE")
    print("=" * 70)

    # Binomial test on test set with backtest v2 filters
    test_v2 = apply_filters(test, min_price=0.10, max_price=0.85,
                            bad_cats=backtest_bad_cats, max_tier=2)
    test_v2_sorted = sorted(test_v2, key=lambda x: x.get("end_date", ""))
    n = len(test_v2_sorted)
    k = sum(1 for s in test_v2_sorted if s.get("correct"))

    if n > 0:
        wr = k / n
        # Normal approximation for binomial test
        import math
        se = math.sqrt(0.5 * 0.5 / n)  # SE under H0: p=0.5
        z = (wr - 0.5) / se
        # One-sided p-value approximation
        p_value = 0.5 * math.erfc(z / math.sqrt(2))

        print(f"\n  Test set (backtest v2 filters): {n} signals, {k} wins, WR={wr:.1%}")
        print(f"  H0: WR = 50% (coin flip)")
        print(f"  Z-score: {z:.2f}")
        print(f"  p-value (one-sided): {p_value:.6f}")
        if p_value < 0.05:
            print(f"  → STATISTICALLY SIGNIFICANT at 5% level")
        elif p_value < 0.10:
            print(f"  → Marginally significant at 10% level")
        else:
            print(f"  → NOT statistically significant")

    print(f"\n{'=' * 70}")


if __name__ == "__main__":
    main()
