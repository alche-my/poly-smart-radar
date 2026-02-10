# Portfolio Simulator — Контекст подпроекта

## Что это

Симулятор портфеля, который берёт результаты бэктеста (`backtest.py`) и моделирует,
как бы рос/падал виртуальный портфель в $100, следуя разным стратегиям.

## Зависимость от бэктеста

Входные данные: JSON-файл от `scripts/backtest.py --output results.json`.
Структура каждого сигнала:
```json
{
  "condition_id": "0x...",
  "market_title": "Will Bitcoin...",
  "category": "CRYPTO",
  "direction": "YES",
  "resolution": "YES",
  "correct": true,
  "tier": 1,
  "signal_score": 25.3,
  "num_traders": 3,
  "entry_price": 0.18,
  "pnl": 4.5556,
  "avg_conviction": 2.1,
  "cat_match_ratio": 0.67,
  "end_date": "2026-01-15T00:00:00Z"
}
```

## 3 стратегии

| # | Название | Фильтр сигналов | Bet sizing |
|---|----------|-----------------|------------|
| 1 | Tier 1 Only | tier == 1 | Half-Kelly T1 |
| 2 | Tier 1+2 | tier in (1, 2) | Half-Kelly per tier |
| 3 | Tier 1+2 + Cat | tier in (1, 2) AND cat_match > 50% | Half-Kelly per tier |

## Формула ставки

```
bet_size = portfolio × half_kelly[tier]
bet_size = min(bet_size, portfolio × 0.25)  # макс 25% на сделку
```

## Формула P&L на ставку

```
Если сигнал правильный (direction == resolution):
  shares = bet_size / entry_price
  payout = shares × $1.00
  profit = payout - bet_size

Если неправильный:
  profit = -bet_size  (потеря всей ставки)
```

## Метрики отчёта

- Начальный/конечный баланс
- ROI %
- Max drawdown %
- Количество сделок (wins/losses)
- Equity curve по неделям (текстовый график)

## Результаты первого запуска (20 трейдеров)

*Будут заполнены после запуска*

## Результаты полного запуска (615 трейдеров)

*Будут заполнены после запуска*

## Файлы

- `scripts/portfolio/CONTEXT.md` — этот файл
- `scripts/portfolio_sim.py` — симулятор (в корне scripts/ для удобства запуска)
