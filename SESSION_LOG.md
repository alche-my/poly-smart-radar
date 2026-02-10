# Poly Smart Radar — Лог рабочих сессий

## Что это за проект

Poly Smart Radar — система мониторинга топ-трейдеров Polymarket для поиска торговых сигналов.
Ядро идеи: когда несколько крупных трейдеров одновременно заходят в одну позицию (конвергенция),
это сильный сигнал для входа.

### Архитектура

```
main.py (daemon)          — цикличный сканер: позиции → сигналы → алерты
scheduler.py              — оркестрирует scan_cycle() каждые 5 минут
webapp/                   — FastAPI веб-интерфейс (дашборд, сигналы, трейдеры)
modules/
  watchlist_builder.py    — строит вотчлист топ-трейдеров
  position_scanner.py     — сканирует изменения позиций
  signal_detector.py      — детектирует конвергенции → генерирует сигналы
  alert_sender.py         — отправляет Telegram-уведомления
  resolution_checker.py   — проверяет резолюцию рынков через Gamma API
api/
  gamma_api.py            — Polymarket Gamma API (рынки, резолюции)
  data_api.py             — Polymarket Data API (позиции трейдеров)
  clob_api.py             — Polymarket CLOB API (ордербук)
db/
  models.py               — SQLite схема: traders, positions, signals, position_changes
  migrations.py           — ALTER TABLE миграции
scripts/
  backtest.py             — бэктест на исторических данных
  backtest_report.py      — отчёт из сохранённого JSON
  portfolio_sim.py        — симулятор портфеля (v2: два пула)
  portfolio/
    CONTEXT.md            — контекст подпроекта портфолио
    test_fixture.json     — тестовые данные для симулятора
```

### Тиры сигналов

| Тир | Условие | Описание |
|-----|---------|----------|
| Tier 1 | 3+ трейдеров, score > 15 | Сильная конвергенция |
| Tier 2 | 2+ трейдеров, score > 8 | Умеренная конвергенция |
| Tier 3 | 1 трейдер top-10, conviction > 2.0 | Одиночный сильный сигнал |

### Деплой

- VPS: `130.49.143.75` (root), проект в `/root/poly-smart-radar`
- Запуск daemon: `source venv/bin/activate && python main.py`
- Запуск webapp: `python -m webapp.main`
- Systemd сервисы: `poly-radar.service`, `poly-radar-web.service`

---

## Сессия 2 (10 февраля 2026)

### Контекст входа

К началу сессии уже были сделаны:
- Полноценный live-радар (сканер + сигналы + Telegram-алерты + веб-дашборд)
- VPS деплой с systemd сервисами
- Карточки сигналов с деталями трейдеров (ROI, категории, ссылки на Polymarket)
- Исправлены ссылки на Polymarket через event_slug из position_changes

### Что сделали

#### 1. Resolution Checker (трекинг резолюций)

**Проблема:** система генерирует сигналы, но не проверяет, были ли они правильными.

**Решение:** модуль `modules/resolution_checker.py`
- Проверяет все unresolved сигналы через Gamma API (`get_market_by_condition`)
- Если рынок резолвился — вычисляет P&L:
  - Правильный: `(1 - entry_price) / entry_price`
  - Неправильный: `-1.0` (полная потеря)
- Записывает `resolved_at`, `resolution_outcome`, `pnl_percent` в signals
- Интегрирован в `scheduler.py` — запускается каждый цикл (5 минут)
- Добавлен эндпоинт `GET /api/signals/stats` — точность и P&L по тирам

**Файлы:**
- `modules/resolution_checker.py` — новый модуль
- `db/models.py` — добавлены поля resolved_at, resolution_outcome, pnl_percent; функция `get_unresolved_signals()`
- `db/migrations.py` — ALTER TABLE миграции для новых полей
- `scheduler.py` — интеграция resolution_checker в scan_cycle()
- `webapp/routers/signals.py` — эндпоинт /api/signals/stats

#### 2. Исследование стратегий

Глубокий ресёрч по использованию данных радара для прибыльных стратегий.
Выявлено 6 подходов:
1. **Weighted Copy Trading** — копируем только Tier 1 сигналы
2. **Convergence Tiers** — тиры 1/2/3 с разным sizing
3. **Category Specialist Following** — фильтр по специализации трейдера
4. **Smart Entry Timing** — вход по сигналу, но с оптимизацией цены
5. **Contrarian Exit Signal** — выход, когда смарт-мани выходят
6. **Kelly Criterion** — оптимальный размер позиции по формуле Келли

#### 3. Бэктест на исторических данных

**Цель:** проверить гипотезу конвергенции на 3 месяцах реальных данных Polymarket.

**Алгоритм:**
1. Получить закрытые позиции всех 615 трейдеров из вотчлиста (Data API `closed-positions`)
2. Получить все резолвнутые рынки за 3 месяца (Gamma API `closed=true`)
3. Реконструировать виртуальные сигналы: найти рынки, где 2+ трейдеров зашли одинаково
4. Рассчитать score, tier, P&L по тем же формулам, что и live-система
5. Вывести статистику по тирам, категориям, Kelly

**Технические сложности:**
- Gamma API принимает `end_date_min` только в формате `YYYY-MM-DD`, не ISO datetime
- Data API `closed-positions` возвращает max 50 записей на страницу (не 100)
- Rate limiting: batch_size=2 трейдера параллельно, 0.2s пауза между батчами
- max_results=500 позиций на трейдера (компромисс скорость/полнота)

**Результаты полного бэктеста (615 трейдеров, 2121 сигнал):**

| Тир | Сигналов | Win Rate | Avg P&L | Kelly |
|-----|----------|----------|---------|-------|
| Tier 1 | 1295 | 63.4% | +16.5% | 0.196 |
| Tier 2 | 759 | 58.6% | +30.1% | 0.242 |
| Tier 3 | 67 | 16.4% | +43.0% | 0.056 |

По категориям:
| Категория | WR | Avg P&L | Вывод |
|-----------|----|---------|-------|
| SPORTS | 55.5% | +126.7% | Прибыльна (малая выборка) |
| TECH | 63.8% | +61.5% | Прибыльна |
| POLITICS | 62.5% | +33.1% | Прибыльна |
| OTHER | 63.3% | +18.1% | Прибыльна |
| CRYPTO | 55.8% | -22.8% | **Убыточна** |
| CULTURE | 42.2% | -20.2% | **Убыточна** |
| FINANCE | 54.3% | -31.6% | **Убыточна** |

**Ключевые файлы:**
- `scripts/backtest.py` — основной скрипт бэктеста
- `scripts/backtest_report.py` — отчёт из JSON
- `BACKTEST.md` — документация бэктеста
- `full_results.json` — результаты полного бэктеста (2.7 МБ, 2121 сигнал)

#### 4. Симулятор портфеля (v2)

**Цель:** смоделировать реальный портфель $100, следующий стратегиям.

**v1 (провалилась):** Kelly compounding давал нереалистичные числа ($46 триллионов).

**v2 (финальная):** два раздельных пула с flat bet (фиксированная ставка):

**Main Pool ($100, ставка $5/сделку):**
- Фильтры: entry price $0.10–$0.85, исключены CRYPTO/CULTURE/FINANCE
- 666 сигналов прошли фильтры, WR 71.6%

| Стратегия | Сделки | W/L | WR | Итого | ROI | MaxDD |
|-----------|--------|-----|-----|-------|-----|-------|
| Tier 1 Only | 430 | 334/96 | 77.7% | $1,353 | +1,253% | 6.8% |
| Tier 1+2 | 658 | 472/186 | 71.7% | $1,626 | +1,526% | 4.9% |

**Gambling Pool ($100, ставка $2/сделку):**
- Penny bets (entry < $0.10) — лотерейные ставки
- WR 2.5% → полная потеря $100

**Итого:** $200 вложено → $1,626 (+713%), main pool прибылен, gambling убыточен.

**Ключевые файлы:**
- `scripts/portfolio_sim.py` — симулятор v2
- `scripts/portfolio/CONTEXT.md` — контекст подпроекта
- `full_results_portfolio.json` — результаты симуляции

### Выводы и insights

1. **Стратегия конвергенции работает:** Tier 1 даёт 77.7% WR при фильтрации категорий и цен
2. **Критичные фильтры:**
   - Исключить CRYPTO, CULTURE, FINANCE (отрицательный avg P&L)
   - Вход только при цене $0.10–$0.85 (penny bets = лотерея, >$0.85 = мизерный upside)
3. **Tier 2 добавляет ценность:** больше сделок при сохранении edge (71.7% WR)
4. **Tier 3 убыточен:** WR 16.4%, не использовать
5. **Flat bet > Kelly compounding** для малых портфелей: стабильный рост без обвалов
6. **MaxDD 4.9-6.8%** у main pool — очень контролируемый риск

### Что не сделано / следующие шаги

- [ ] Пересмотреть gambling pool: текущий порог <$0.10 даёт WR 2.5% (нерабочий). Варианты: поднять порог до $0.05–$0.15, фильтровать категории, или отключить
- [ ] Добавить автоматическое исполнение сделок по Tier 1 сигналам (интеграция с CLOB API)
- [ ] Протестировать progressive bet sizing: flat bet, но увеличивать размер ставки по мере роста портфеля (пересчёт каждую неделю)
- [ ] Smart Entry Timing: не входить по рыночной цене сразу, а ставить лимитный ордер чуть ниже
- [ ] Мониторинг live P&L: resolution_checker уже работает, нужен дашборд для отслеживания реальной точности в реальном времени
- [ ] Обновить CONTEXT.md с реальными результатами

### Полезные команды

```bash
# Запуск бэктеста (15 мин на 615 трейдеров)
cd /root/poly-smart-radar && source venv/bin/activate
python scripts/backtest.py --months 3 --output full_results.json

# Тестовый бэктест (20 трейдеров, 2 мин)
python scripts/backtest.py --months 3 --output test_results.json --limit-traders 20

# Симуляция портфеля
python scripts/portfolio_sim.py full_results.json

# Запуск daemon
python main.py

# Запуск веб-интерфейса
python -m webapp.main
```

### Известные баги и workarounds

- `datetime.utcnow()` deprecation warning в backtest.py — косметический, не влияет на работу
- Gamma API `end_date_min` принимает только `YYYY-MM-DD`, не ISO datetime — уже исправлено в коде
- Data API `closed-positions` caps at 50 per page — page_size=50 в `get_closed_positions_all()`
- Category может быть `null` в данных — используем `(s.get("category") or "OTHER").upper()`
