# Scope: HUMAN vs ALGO trader classification

## Problem

Traders with 2000+ closed positions are almost certainly bots/algorithmic systems.
They need to be analyzed differently from human traders.

Example from live data:
- **kch123**: 2000+ closed, $8.7M PnL, $227M volume (vol/pnl = 26x) — ALGO
- **Theo4**: 22 closed, $22M PnL, $43M volume (vol/pnl = 2x) — HUMAN

## Classification heuristic

```
total_closed >= 200 OR vol/pnl > 10  →  ALGO
everything else                      →  HUMAN
```

## HUMAN scoring (current formula — works)

```
timing_quality × consistency × (1 + roi_normalized)
```

What we look for: who enters the right side early.
Convergence signal: 3+ humans in the same market = strong directional signal.

## ALGO scoring (new formula needed)

For bots, timing is irrelevant. What matters:
- **efficiency** = pnl / volume (cents of profit per dollar of turnover)
- **volume** = scale of operations (log-scaled)
- **consistency** = WR × log2(sample_size)

```
efficiency × log10(volume) × consistency
```

## Signal types

- **HUMAN convergence**: "3 smart traders entered the same market" → directional signal
- **ALGO convergence**: "2 bots started trading the same market" → market inefficiency / arbitrage opportunity

## Implementation plan

1. Add `trader_type` field (HUMAN/ALGO) to DB schema
2. Classify in `_score_trader` based on heuristic
3. Apply different scoring formula per type
4. Show trader_type in Telegram alerts
5. Later: separate analysis script for algo traders
