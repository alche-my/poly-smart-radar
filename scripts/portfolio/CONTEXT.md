# Portfolio Simulator — Контекст подпроекта

## Что это

Симулятор портфеля v2: берёт результаты бэктеста и моделирует два раздельных пула:
- **Main Pool** ($100) — консервативный, с фильтрами, flat bet $5/сделку
- **Gambling Pool** ($100) — агрессивный, penny bets, flat bet $2/сделку

## Входные данные

JSON-файл от `scripts/backtest.py --output results.json`.
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

## Фильтры (v2)

| Фильтр | Main Pool | Gambling Pool |
|--------|-----------|---------------|
| Цена входа | $0.10 – $0.85 | < $0.10 |
| Категории | Исключены: CRYPTO, CULTURE, FINANCE | Все |
| Тиры | Tier 1, Tier 1+2, Tier 1+2 + проф. категории | Tier 1, Tier 1+2 |
| Bet sizing | Flat $5/сделку | Flat $2/сделку |

## Стратегии

### Main Pool
| # | Название | Фильтр |
|---|----------|--------|
| 1 | Main: Tier 1 Only | tier == 1 + main filters |
| 2 | Main: Tier 1+2 | tier <= 2 + main filters |
| 3 | Main: Tier 1+2 Sports+Politics+Tech | tier <= 2 + only profitable categories |

### Gambling Pool
| # | Название | Фильтр |
|---|----------|--------|
| 1 | Gambling: Tier 1 Penny | tier == 1, entry < $0.10 |
| 2 | Gambling: Tier 1+2 Penny | tier <= 2, entry < $0.10 |

## Формула P&L на ставку

```
Если сигнал правильный (direction == resolution):
  shares = bet_size / entry_price
  payout = shares × $1.00
  profit = payout - bet_size

Если неправильный:
  profit = -bet_size  (потеря всей ставки)
```

## Результаты полного запуска (615 трейдеров, 2121 сигнал)

### Main Pool ($100, flat $5/trade)
666 сигналов прошли фильтры, WR 71.6%, avg entry $0.50

| Стратегия | Сделки | W/L | WR | Итого | ROI | MaxDD |
|-----------|--------|-----|-----|-------|-----|-------|
| **Tier 1 Only** | 430 | 334/96 | **77.7%** | $1,353 | **+1,253%** | 6.8% |
| **Tier 1+2** | 658 | 472/186 | **71.7%** | $1,626 | **+1,526%** | 4.9% |
| Tier 1+2 S+P+T | 658 | 472/186 | 71.7% | $1,626 | +1,526% | 4.9% |

### Gambling Pool ($100, flat $2/trade)
612 сигналов, WR 4.2%, avg entry $0.03

| Стратегия | Сделки | W/L | WR | Итого | ROI |
|-----------|--------|-----|-----|-------|-----|
| Tier 1 Penny | 81 | 2/79 | 2.5% | $0 | -100% |
| Tier 1+2 Penny | 81 | 2/79 | 2.5% | $0 | -100% |

### Итого
$200 вложено → $1,626 (+713%). Main pool прибылен, gambling убыточен.

## Выводы

1. **Main pool работает отлично:** стабильный рост, MaxDD < 7%
2. **Tier 1+2 лучше Tier 1 Only:** больше сделок при почти том же WR
3. **Gambling pool НЕ работает** при текущих настройках (WR 2.5%)
4. **Фильтры критичны:** без них (v1) портфель скакал $100→$12K→$86

## Открытые вопросы

- Gambling: пересмотреть порог? ($0.05–$0.15 вместо <$0.10)
- Progressive sizing: пересчитывать flat bet раз в неделю по балансу?
- Добавить Kelly compounding с cap (max 2x от initial)?

## Файлы

- `scripts/portfolio_sim.py` — симулятор v2 (в корне scripts/ для удобства)
- `scripts/portfolio/CONTEXT.md` — этот файл
- `scripts/portfolio/test_fixture.json` — тестовые данные
- `full_results.json` — данные полного бэктеста
- `full_results_portfolio.json` — результаты симуляции
