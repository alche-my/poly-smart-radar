"""
Generate a report from saved backtest results.

Usage:
    python scripts/backtest_report.py results.json
"""
import json
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.backtest import print_report


def main():
    if len(sys.argv) < 2:
        print("Usage: python scripts/backtest_report.py <results.json>")
        sys.exit(1)

    path = sys.argv[1]
    if not os.path.exists(path):
        print(f"File not found: {path}")
        sys.exit(1)

    with open(path) as f:
        results = json.load(f)

    meta = results.get("meta", {})
    print(f"\nBacktest: {meta.get('months', '?')} months")
    print(f"Run at: {meta.get('run_at', '?')}")
    print(f"Traders: {meta.get('traders_count', '?')}")
    print(f"Positions analyzed: {meta.get('positions_count', '?')}")
    print(f"Markets with resolution: {meta.get('markets_count', '?')}")
    print(f"Signals reconstructed: {meta.get('signals_count', '?')}")

    stats = results.get("stats", {})
    signals = results.get("signals", [])

    if not stats or not signals:
        print("\nNo data to report.")
        sys.exit(0)

    print_report(stats, signals)


if __name__ == "__main__":
    main()
