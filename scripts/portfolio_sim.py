"""
Portfolio simulator: run strategies on backtest results and compare equity curves.

Two pools:
  - MAIN ($100): filtered signals, conservative sizing (Quarter-Kelly)
  - GAMBLING ($100): penny bets (entry < $0.10), aggressive sizing (Half-Kelly)

Usage:
    python scripts/portfolio_sim.py full_results.json
"""
import json
import math
import sys
import os
from collections import defaultdict
from datetime import datetime

INITIAL_BALANCE = 100.0
MAX_BET_FRACTION = 0.25  # max 25% of portfolio per trade

# ── Price & category filters ────────────────────────────────────────

PENNY_THRESHOLD = 0.10        # below this → gambling pool
MAX_ENTRY_PRICE = 0.85        # above this → skip (tiny upside)
BAD_CATEGORIES = {"CRYPTO", "CULTURE", "FINANCE"}  # negative avg P&L in backtest


def is_main_signal(s: dict) -> bool:
    """Signal qualifies for main portfolio."""
    price = s.get("entry_price", 0)
    cat = (s.get("category") or "OTHER").upper()
    return (
        PENNY_THRESHOLD <= price <= MAX_ENTRY_PRICE
        and cat not in BAD_CATEGORIES
    )


def is_gambling_signal(s: dict) -> bool:
    """Signal qualifies for gambling pool (penny bets)."""
    price = s.get("entry_price", 0)
    return 0 < price < PENNY_THRESHOLD


# ── Strategies ──────────────────────────────────────────────────────

MAIN_STRATEGIES = {
    "Main: Tier 1 Only": {
        "filter": lambda s: is_main_signal(s) and s["tier"] == 1,
        "description": "Tier 1, entry $0.10-$0.85, excl. CRYPTO/CULTURE/FINANCE",
    },
    "Main: Tier 1+2": {
        "filter": lambda s: is_main_signal(s) and s["tier"] <= 2,
        "description": "Tier 1+2, entry $0.10-$0.85, excl. CRYPTO/CULTURE/FINANCE",
    },
    "Main: Tier 1+2 Sports+Politics+Tech": {
        "filter": lambda s: (
            is_main_signal(s) and s["tier"] <= 2
            and (s.get("category") or "OTHER").upper() in ("SPORTS", "POLITICS", "TECH", "OTHER", "WEATHER")
        ),
        "description": "Tier 1+2, only profitable categories",
    },
}

GAMBLING_STRATEGIES = {
    "Gambling: Tier 1 Penny": {
        "filter": lambda s: is_gambling_signal(s) and s["tier"] == 1,
        "description": "Tier 1 penny bets (entry < $0.10) — lottery tickets",
    },
    "Gambling: Tier 1+2 Penny": {
        "filter": lambda s: is_gambling_signal(s) and s["tier"] <= 2,
        "description": "Tier 1+2 penny bets (entry < $0.10) — lottery tickets",
    },
}


# ── Kelly calculation ───────────────────────────────────────────────


def calc_kelly(signals: list[dict], tier: int, fraction: float = 0.5) -> float:
    """Calculate Kelly fraction for a specific tier. fraction=0.5 → Half-Kelly, 0.25 → Quarter."""
    tier_signals = [s for s in signals if s["tier"] == tier]
    if not tier_signals:
        return 0.03  # fallback

    wins = [s for s in tier_signals if s["correct"]]
    if not wins:
        return 0.0

    win_rate = len(wins) / len(tier_signals)
    avg_win_pnl = sum(s["pnl"] for s in wins) / len(wins)

    if avg_win_pnl <= 0:
        return 0.0

    kelly = (win_rate * avg_win_pnl - (1 - win_rate)) / avg_win_pnl
    return min(max(kelly * fraction, 0), MAX_BET_FRACTION)


# ── Portfolio simulation ────────────────────────────────────────────


def simulate(signals: list[dict], strategy_filter, kelly_by_tier: dict,
             initial_balance: float = INITIAL_BALANCE,
             flat_bet: float | None = None) -> dict:
    """
    Simulate a portfolio following a strategy on sorted signals.

    flat_bet: if set, bet this fixed dollar amount per trade (no compounding).
              if None, use Kelly-based fraction of current portfolio (compounding).
    """
    sorted_signals = sorted(
        [s for s in signals if strategy_filter(s)],
        key=lambda s: s.get("end_date", ""),
    )

    if not sorted_signals:
        return {
            "trades": 0, "wins": 0, "losses": 0,
            "final_balance": initial_balance, "roi": 0,
            "max_drawdown": 0, "equity_curve": [],
        }

    portfolio = initial_balance
    peak = initial_balance
    max_drawdown = 0
    equity_curve = [{"date": "start", "balance": portfolio, "event": "initial"}]
    wins = 0
    losses = 0

    for signal in sorted_signals:
        tier = signal["tier"]
        entry_price = signal["entry_price"]

        if entry_price <= 0 or entry_price >= 1 or portfolio <= 0.01:
            continue

        if flat_bet is not None:
            bet_size = min(flat_bet, portfolio)
        else:
            kelly = kelly_by_tier.get(tier, 0.03)
            bet_size = portfolio * kelly
            bet_size = min(bet_size, portfolio * MAX_BET_FRACTION, portfolio)

        bet_size = max(bet_size, 0)
        if bet_size < 0.01:
            continue

        if signal["correct"]:
            shares = bet_size / entry_price
            payout = shares * 1.0
            profit = payout - bet_size
            wins += 1
        else:
            profit = -bet_size
            losses += 1

        portfolio += profit

        if portfolio > peak:
            peak = portfolio
        drawdown = (peak - portfolio) / peak if peak > 0 else 0
        if drawdown > max_drawdown:
            max_drawdown = drawdown

        date_str = signal.get("end_date", "")[:10]
        equity_curve.append({
            "date": date_str,
            "balance": round(portfolio, 2),
            "event": f"{'WIN' if signal['correct'] else 'LOSS'} T{tier} "
                     f"@{entry_price:.2f} bet=${bet_size:.1f} → "
                     f"{'$' + str(round(profit, 1)) if profit >= 0 else '-$' + str(round(-profit, 1))}",
        })

    total = wins + losses
    return {
        "trades": total,
        "wins": wins,
        "losses": losses,
        "win_rate": round(wins / total, 4) if total > 0 else 0,
        "final_balance": round(portfolio, 2),
        "roi": round((portfolio - initial_balance) / initial_balance * 100, 1),
        "max_drawdown": round(max_drawdown * 100, 1),
        "equity_curve": equity_curve,
    }


# ── Weekly equity chart ─────────────────────────────────────────────


def render_equity_chart(equity_curve: list[dict], width: int = 50,
                        initial: float = INITIAL_BALANCE) -> str:
    """Render a simple text-based equity chart grouped by week."""
    if len(equity_curve) < 2:
        return "  (not enough data)"

    weekly: dict[str, float] = {}
    for point in equity_curve:
        date = point["date"]
        if date == "start":
            continue
        try:
            dt = datetime.fromisoformat(date)
            week = dt.strftime("%Y-W%W")
        except (ValueError, TypeError):
            continue
        weekly[week] = point["balance"]

    if not weekly:
        return "  (no dated entries)"

    weeks = sorted(weekly.keys())
    values = [weekly[w] for w in weeks]
    min_val = min(min(values), initial * 0.5)
    max_val = max(max(values), initial * 1.5)
    spread = max_val - min_val if max_val > min_val else 1

    lines = []
    for week, val in zip(weeks, values):
        bar_len = int((val - min_val) / spread * width)
        bar = "█" * max(bar_len, 0)
        marker = " ◀" if val < initial else ""
        lines.append(f"  {week} │{bar} ${val:.0f}{marker}")

    return "\n".join(lines)


# ── Signal stats ────────────────────────────────────────────────────


def print_pool_stats(signals: list[dict], pool_filter, label: str):
    """Print quick stats about a signal pool."""
    pool = [s for s in signals if pool_filter(s)]
    if not pool:
        print(f"  {label}: 0 signals")
        return
    wins = sum(1 for s in pool if s["correct"])
    wr = wins / len(pool) * 100
    avg_price = sum(s["entry_price"] for s in pool) / len(pool)
    cats = defaultdict(int)
    for s in pool:
        cats[s.get("category") or "OTHER"] += 1
    top_cats = sorted(cats.items(), key=lambda x: -x[1])[:5]
    cat_str = ", ".join(f"{c}({n})" for c, n in top_cats)
    print(f"  {label}: {len(pool)} signals, WR {wr:.1f}%, avg entry ${avg_price:.2f}")
    print(f"    Categories: {cat_str}")


# ── Main report ─────────────────────────────────────────────────────


def run_simulation(results_path: str) -> None:
    with open(results_path) as f:
        data = json.load(f)

    signals = data.get("signals", [])
    if not signals:
        print("No signals in results file.")
        sys.exit(1)

    # Pre-filter signal pools for Kelly calculation
    main_signals = [s for s in signals if is_main_signal(s)]
    gambling_signals = [s for s in signals if is_gambling_signal(s)]

    # Kelly: Quarter-Kelly for main, Half-Kelly for gambling
    main_kelly = {}
    for tier in (1, 2, 3):
        main_kelly[tier] = calc_kelly(main_signals, tier, fraction=0.25)

    gambling_kelly = {}
    for tier in (1, 2, 3):
        gambling_kelly[tier] = calc_kelly(gambling_signals, tier, fraction=0.5)

    # Header
    print("\n" + "=" * 70)
    print("  PORTFOLIO SIMULATION v2")
    print("  Main pool: $100 (Quarter-Kelly) | Gambling pool: $100 (Half-Kelly)")
    print("=" * 70)
    print(f"\n  Input: {results_path}")
    print(f"  Total signals: {len(signals)}")
    print(f"  Filters: entry ${PENNY_THRESHOLD}–${MAX_ENTRY_PRICE}, excl {BAD_CATEGORIES}")
    print()
    print_pool_stats(signals, is_main_signal, "Main pool")
    print(f"    Kelly (Quarter): T1={main_kelly[1]:.3f}, T2={main_kelly[2]:.3f}")
    print()
    print_pool_stats(signals, is_gambling_signal, "Gambling pool")
    print(f"    Kelly (Half):    T1={gambling_kelly[1]:.3f}, T2={gambling_kelly[2]:.3f}")

    # Flat bet sizes: $5 per main trade, $2 per gambling trade
    MAIN_FLAT_BET = 5.0
    GAMBLING_FLAT_BET = 2.0

    # ── Main pool strategies ──
    print(f"\n{'=' * 70}")
    print(f"  MAIN POOL — $100, flat ${MAIN_FLAT_BET:.0f}/trade (no compounding)")
    print(f"{'=' * 70}")

    main_results = {}
    for name, strategy in MAIN_STRATEGIES.items():
        result = simulate(signals, strategy["filter"], main_kelly, flat_bet=MAIN_FLAT_BET)
        main_results[name] = result

    print(f"\n  {'Strategy':<38} {'Trades':>6} {'W/L':>8} {'WR':>6} {'Final $':>9} {'ROI':>8} {'MaxDD':>6}")
    for name, r in main_results.items():
        wl = f"{r['wins']}/{r['losses']}"
        print(
            f"  {name:<38} {r['trades']:>6} {wl:>8} "
            f"{r['win_rate'] * 100:>5.1f}% ${r['final_balance']:>7.0f} "
            f"{r['roi']:>+7.1f}% {r['max_drawdown']:>5.1f}%"
        )

    for name, r in main_results.items():
        print(f"\n{'─' * 70}")
        print(f"  {name} — {MAIN_STRATEGIES[name]['description']}")
        print(f"  $100 → ${r['final_balance']:.0f} ({r['roi']:+.1f}%) | MaxDD: {r['max_drawdown']:.1f}%")
        print(f"{'─' * 70}")
        print(render_equity_chart(r["equity_curve"]))

    # ── Gambling pool strategies ──
    print(f"\n{'=' * 70}")
    print(f"  GAMBLING POOL — $100, flat ${GAMBLING_FLAT_BET:.0f}/trade (lottery tickets)")
    print(f"{'=' * 70}")

    gambling_results = {}
    for name, strategy in GAMBLING_STRATEGIES.items():
        result = simulate(signals, strategy["filter"], gambling_kelly, flat_bet=GAMBLING_FLAT_BET)
        gambling_results[name] = result

    print(f"\n  {'Strategy':<38} {'Trades':>6} {'W/L':>8} {'WR':>6} {'Final $':>9} {'ROI':>8} {'MaxDD':>6}")
    for name, r in gambling_results.items():
        wl = f"{r['wins']}/{r['losses']}"
        print(
            f"  {name:<38} {r['trades']:>6} {wl:>8} "
            f"{r['win_rate'] * 100:>5.1f}% ${r['final_balance']:>7.0f} "
            f"{r['roi']:>+7.1f}% {r['max_drawdown']:>5.1f}%"
        )

    for name, r in gambling_results.items():
        print(f"\n{'─' * 70}")
        print(f"  {name} — {GAMBLING_STRATEGIES[name]['description']}")
        print(f"  $100 → ${r['final_balance']:.0f} ({r['roi']:+.1f}%) | MaxDD: {r['max_drawdown']:.1f}%")
        print(f"{'─' * 70}")
        print(render_equity_chart(r["equity_curve"]))

    # ── Combined summary ──
    print(f"\n{'=' * 70}")
    print("  COMBINED SUMMARY (Main + Gambling = $200 total invested)")
    print(f"{'=' * 70}")

    best_main_name = max(main_results, key=lambda n: main_results[n]["roi"])
    best_gambling_name = max(gambling_results, key=lambda n: gambling_results[n]["roi"])
    best_main = main_results[best_main_name]
    best_gambling = gambling_results[best_gambling_name]
    combined = best_main["final_balance"] + best_gambling["final_balance"]
    combined_roi = (combined - 200) / 200 * 100

    print(f"\n  Best main:     {best_main_name}")
    print(f"    $100 → ${best_main['final_balance']:.0f} ({best_main['roi']:+.1f}%)")
    print(f"  Best gambling: {best_gambling_name}")
    print(f"    $100 → ${best_gambling['final_balance']:.0f} ({best_gambling['roi']:+.1f}%)")
    print(f"\n  Combined: $200 → ${combined:.0f} ({combined_roi:+.1f}%)")

    # Trade log for best main strategy (last 50 trades)
    print(f"\n{'─' * 70}")
    print(f"  TRADE LOG (last 50): {best_main_name}")
    print(f"{'─' * 70}")
    trade_entries = [p for p in best_main["equity_curve"] if p["event"] != "initial"]
    for point in trade_entries[-50:]:
        print(f"  {point['date']} | ${point['balance']:>8.0f} | {point['event']}")

    print("\n" + "=" * 70)

    # Save results
    output_path = results_path.replace(".json", "_portfolio.json")
    portfolio_data = {
        "input": results_path,
        "version": 2,
        "filters": {
            "penny_threshold": PENNY_THRESHOLD,
            "max_entry_price": MAX_ENTRY_PRICE,
            "excluded_categories": list(BAD_CATEGORIES),
        },
        "main_pool": {
            "initial_balance": INITIAL_BALANCE,
            "kelly_fraction": "quarter",
            "kelly_by_tier": main_kelly,
            "strategies": {
                name: {k: v for k, v in r.items() if k != "equity_curve"}
                for name, r in main_results.items()
            },
        },
        "gambling_pool": {
            "initial_balance": INITIAL_BALANCE,
            "kelly_fraction": "half",
            "kelly_by_tier": gambling_kelly,
            "strategies": {
                name: {k: v for k, v in r.items() if k != "equity_curve"}
                for name, r in gambling_results.items()
            },
        },
        "combined": {
            "total_invested": 200,
            "best_main": best_main_name,
            "best_gambling": best_gambling_name,
            "final_balance": round(combined, 2),
            "roi": round(combined_roi, 1),
        },
    }
    with open(output_path, "w") as f:
        json.dump(portfolio_data, f, indent=2, ensure_ascii=False)
    print(f"\n  Results saved to {output_path}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python scripts/portfolio_sim.py <results.json>")
        print("  Run scripts/backtest.py first to generate results.")
        sys.exit(1)

    path = sys.argv[1]
    if not os.path.exists(path):
        print(f"File not found: {path}")
        sys.exit(1)

    run_simulation(path)
