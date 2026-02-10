"""
Portfolio simulator: run 3 strategies on backtest results and compare equity curves.

Usage:
    python scripts/portfolio_sim.py test_results.json
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


# ── Strategies ────────────────────────────────────────────────────────


STRATEGIES = {
    "Tier 1 Only": {
        "filter": lambda s: s["tier"] == 1,
        "description": "Only Tier 1 signals (3+ traders, score > 15)",
    },
    "Tier 1+2": {
        "filter": lambda s: s["tier"] <= 2,
        "description": "Tier 1 and Tier 2 signals",
    },
    "Tier 1+2 + Cat": {
        "filter": lambda s: s["tier"] <= 2 and s.get("cat_match_ratio", 0) > 0.5,
        "description": "Tier 1+2, only when traders match market category",
    },
}


# ── Kelly calculation ─────────────────────────────────────────────────


def calc_kelly_for_tier(signals: list[dict], tier: int) -> float:
    """Calculate Half-Kelly fraction for a specific tier."""
    tier_signals = [s for s in signals if s["tier"] == tier]
    if not tier_signals:
        return 0.05  # fallback: 5%

    wins = [s for s in tier_signals if s["correct"]]
    if not wins:
        return 0.0

    win_rate = len(wins) / len(tier_signals)
    avg_win_pnl = sum(s["pnl"] for s in wins) / len(wins)

    if avg_win_pnl <= 0:
        return 0.0

    kelly = (win_rate * avg_win_pnl - (1 - win_rate)) / avg_win_pnl
    half_kelly = max(kelly / 2, 0)
    return min(half_kelly, MAX_BET_FRACTION)  # cap at max bet


# ── Portfolio simulation ──────────────────────────────────────────────


def simulate(signals: list[dict], strategy_filter, kelly_by_tier: dict) -> dict:
    """Simulate a portfolio following a strategy on sorted signals."""
    # Sort by end_date (resolution date)
    sorted_signals = sorted(
        [s for s in signals if strategy_filter(s)],
        key=lambda s: s.get("end_date", ""),
    )

    if not sorted_signals:
        return {
            "trades": 0, "wins": 0, "losses": 0,
            "final_balance": INITIAL_BALANCE, "roi": 0,
            "max_drawdown": 0, "equity_curve": [],
        }

    portfolio = INITIAL_BALANCE
    peak = INITIAL_BALANCE
    max_drawdown = 0
    equity_curve = [{"date": "start", "balance": portfolio, "event": "initial"}]
    wins = 0
    losses = 0

    for signal in sorted_signals:
        tier = signal["tier"]
        entry_price = signal["entry_price"]

        # Skip bad data
        if entry_price <= 0 or entry_price >= 1 or portfolio <= 0:
            continue

        # Bet sizing: Half-Kelly for this tier, capped at 25%
        kelly = kelly_by_tier.get(tier, 0.05)
        bet_size = portfolio * kelly
        bet_size = min(bet_size, portfolio * MAX_BET_FRACTION)
        bet_size = min(bet_size, portfolio)
        bet_size = max(bet_size, 0)

        if bet_size < 0.01:  # skip dust
            continue

        # Calculate outcome
        if signal["correct"]:
            # Bought shares at entry_price, each pays $1
            shares = bet_size / entry_price
            payout = shares * 1.0
            profit = payout - bet_size
            wins += 1
        else:
            # Lost the bet
            profit = -bet_size
            losses += 1

        portfolio += profit

        # Track peak and drawdown
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

    return {
        "trades": wins + losses,
        "wins": wins,
        "losses": losses,
        "win_rate": round(wins / (wins + losses), 4) if (wins + losses) > 0 else 0,
        "final_balance": round(portfolio, 2),
        "roi": round((portfolio - INITIAL_BALANCE) / INITIAL_BALANCE * 100, 1),
        "max_drawdown": round(max_drawdown * 100, 1),
        "equity_curve": equity_curve,
    }


# ── Weekly equity curve (text chart) ─────────────────────────────────


def render_equity_chart(equity_curve: list[dict], width: int = 50) -> str:
    """Render a simple text-based equity chart grouped by week."""
    if len(equity_curve) < 2:
        return "  (not enough data)"

    # Group by week
    weekly: dict[str, float] = {}
    for point in equity_curve:
        date = point["date"]
        if date == "start":
            continue
        # Get ISO week
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
    min_val = min(min(values), INITIAL_BALANCE * 0.5)
    max_val = max(max(values), INITIAL_BALANCE * 1.5)
    spread = max_val - min_val if max_val > min_val else 1

    lines = []
    for week, val in zip(weeks, values):
        bar_len = int((val - min_val) / spread * width)
        bar = "█" * bar_len
        marker = " ◀" if val < INITIAL_BALANCE else ""
        lines.append(f"  {week} │{bar} ${val:.0f}{marker}")

    return "\n".join(lines)


# ── Main report ───────────────────────────────────────────────────────


def run_simulation(results_path: str) -> None:
    with open(results_path) as f:
        data = json.load(f)

    signals = data.get("signals", [])
    stats = data.get("stats", {})

    if not signals:
        print("No signals in results file.")
        sys.exit(1)

    # Calculate Kelly fractions from backtest stats
    kelly_by_tier = {}
    for tier in (1, 2, 3):
        kelly_by_tier[tier] = calc_kelly_for_tier(signals, tier)

    print("\n" + "=" * 70)
    print("  PORTFOLIO SIMULATION — $100 starting balance")
    print("=" * 70)
    print(f"\n  Input: {results_path}")
    print(f"  Total signals: {len(signals)}")
    print(f"  Kelly fractions: T1={kelly_by_tier[1]:.3f}, T2={kelly_by_tier[2]:.3f}, T3={kelly_by_tier[3]:.3f}")
    print(f"  Max bet: {MAX_BET_FRACTION * 100:.0f}% of portfolio")

    results = {}

    for name, strategy in STRATEGIES.items():
        result = simulate(signals, strategy["filter"], kelly_by_tier)
        results[name] = result

    # Comparison table
    print("\n" + "-" * 70)
    print("  STRATEGY COMPARISON")
    print("-" * 70)
    print(f"  {'Strategy':<22} {'Trades':>7} {'W/L':>8} {'WR':>7} {'Final $':>9} {'ROI':>8} {'MaxDD':>7}")

    for name, r in results.items():
        wl = f"{r['wins']}/{r['losses']}"
        print(
            f"  {name:<22} {r['trades']:>7} {wl:>8} "
            f"{r['win_rate'] * 100:>6.1f}% ${r['final_balance']:>7.0f} "
            f"{r['roi']:>+7.1f}% {r['max_drawdown']:>6.1f}%"
        )

    # Equity curves
    for name, r in results.items():
        print(f"\n{'─' * 70}")
        print(f"  {name} — {STRATEGIES[name]['description']}")
        print(f"  ${INITIAL_BALANCE:.0f} → ${r['final_balance']:.0f} "
              f"({r['roi']:+.1f}%) | MaxDD: {r['max_drawdown']:.1f}%")
        print(f"{'─' * 70}")
        chart = render_equity_chart(r["equity_curve"])
        print(chart)

    # Trade log for best strategy
    best_name = max(results, key=lambda n: results[n]["roi"])
    best = results[best_name]
    print(f"\n{'─' * 70}")
    print(f"  TRADE LOG: {best_name} (best ROI)")
    print(f"{'─' * 70}")
    for point in best["equity_curve"]:
        if point["event"] == "initial":
            continue
        print(f"  {point['date']} | ${point['balance']:>8.0f} | {point['event']}")

    print("\n" + "=" * 70)

    # Save results
    output_path = results_path.replace(".json", "_portfolio.json")
    portfolio_data = {
        "input": results_path,
        "initial_balance": INITIAL_BALANCE,
        "kelly_by_tier": kelly_by_tier,
        "strategies": {
            name: {k: v for k, v in r.items() if k != "equity_curve"}
            for name, r in results.items()
        },
        "equity_curves": {name: r["equity_curve"] for name, r in results.items()},
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
