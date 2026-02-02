# Polymarket Whale Radar

Система мониторинга топ-трейдеров Polymarket. Генерирует сигналы когда несколько квалифицированных трейдеров конвергируют на одном рынке.

---

## Внешние API

### Data API — `https://data-api.polymarket.com`

| Endpoint | Метод | Описание | Ключевые параметры |
|---|---|---|---|
| `/v1/leaderboard` | GET | Рейтинг трейдеров | `category` (OVERALL/POLITICS/CRYPTO/SPORTS/CULTURE/MENTIONS/WEATHER/ECONOMICS/TECH/FINANCE), `timePeriod` (DAY/WEEK/MONTH/ALL), `orderBy` (PNL/VOL), `limit` (1-50), `offset` |
| `/positions` | GET | Текущие открытые позиции | `user` (address, required), `market` (conditionId[]), `eventId` |
| `/closed-positions` | GET | Закрытые позиции | `user` (address, required), `market` (conditionId[]), `limit`, `offset` |
| `/trades` | GET | История сделок | `user`, `market`, `limit` (0-10000), `offset`, `takerOnly`, `filterType`, `filterAmount` |
| `/activity` | GET | On-chain активность | `user` (required), `market`, `limit` (0-500), `offset` |
| `/holders` | GET | Топ холдеры по рынку | `market` (conditionId[], required), `limit` (0-20), `minBalance` |
| `/value` | GET | Общая стоимость позиций | `user` (required), `market` |

### Gamma API — `https://gamma-api.polymarket.com`

| Endpoint | Метод | Описание |
|---|---|---|
| `/events` | GET | Список событий |
| `/markets` | GET | Метаданные рынков |
| `/public-profile` | GET | Профиль трейдера (param: `address`) |

### CLOB API — `https://clob.polymarket.com`

| Endpoint | Метод | Описание |
|---|---|---|
| `/price` | GET | Текущая цена токена |
| `/midpoint` | GET | Мидпоинт цены |

### Rate Limits

| Endpoint | Лимит |
|---|---|
| Data API (общий) | 1000 req / 10s |
| `/positions` | 150 req / 10s |
| `/trades` | 200 req / 10s |
| `/closed-positions` | 150 req / 10s |
| Gamma API (общий) | 4000 req / 10s |

---

## Схема базы данных (SQLite)

### traders

| Поле | Тип | Описание |
|---|---|---|
| wallet_address | TEXT PK | Proxy wallet address |
| username | TEXT | Имя на Polymarket |
| profile_image | TEXT | URL аватара |
| x_username | TEXT | Twitter username |
| trader_score | REAL | Общий скор трейдера |
| category_scores | TEXT | JSON: `{"POLITICS": 8.2, "CRYPTO": 6.1}` |
| avg_position_size | REAL | Средний размер позиции в USDC |
| total_closed | INTEGER | Количество закрытых позиций |
| win_rate | REAL | Процент выигрышных позиций (0-1) |
| roi | REAL | Return on investment |
| last_updated | TIMESTAMP | Время последнего обновления |

### position_snapshots

| Поле | Тип | Описание |
|---|---|---|
| id | INTEGER PK | Autoincrement |
| wallet_address | TEXT FK | Ссылка на traders |
| condition_id | TEXT | ID рынка |
| title | TEXT | Название рынка |
| slug | TEXT | Slug для URL |
| outcome | TEXT | YES / NO |
| size | REAL | Размер позиции |
| avg_price | REAL | Средняя цена входа |
| current_value | REAL | Текущая стоимость |
| cur_price | REAL | Текущая цена |
| scanned_at | TIMESTAMP | Время снэпшота |

### position_changes

| Поле | Тип | Описание |
|---|---|---|
| id | INTEGER PK | Autoincrement |
| wallet_address | TEXT FK | Ссылка на traders |
| condition_id | TEXT | ID рынка |
| title | TEXT | Название рынка |
| slug | TEXT | Slug для URL |
| event_slug | TEXT | Slug события |
| outcome | TEXT | YES / NO |
| change_type | TEXT | OPEN / INCREASE / DECREASE / CLOSE |
| old_size | REAL | Предыдущий размер (0 для OPEN) |
| new_size | REAL | Новый размер (0 для CLOSE) |
| price_at_change | REAL | Цена в момент изменения |
| conviction_score | REAL | Размер сделки / avg_position_size трейдера |
| detected_at | TIMESTAMP | Время обнаружения |

### signals

| Поле | Тип | Описание |
|---|---|---|
| id | INTEGER PK | Autoincrement |
| condition_id | TEXT | ID рынка |
| market_title | TEXT | Название рынка |
| market_slug | TEXT | Slug для URL |
| direction | TEXT | YES / NO |
| signal_score | REAL | Сила сигнала |
| tier | INTEGER | 1 (сильный) / 2 (средний) / 3 (инфо) |
| traders_involved | TEXT | JSON: массив объектов с деталями |
| current_price | REAL | Цена на момент сигнала |
| created_at | TIMESTAMP | Время создания |
| sent | BOOLEAN | Отправлен ли алерт |

---

## Структура проекта
```
polymarket-radar/
├── ARCHITECTURE.md
├── config.py
├── main.py
├── requirements.txt
├── .env.example
├── db/
│   ├── __init__.py
│   ├── models.py
│   └── migrations.py
├── api/
│   ├── __init__.py
│   ├── data_api.py
│   ├── gamma_api.py
│   └── clob_api.py
├── modules/
│   ├── __init__.py
│   ├── watchlist_builder.py
│   ├── position_scanner.py
│   ├── signal_detector.py
│   └── alert_sender.py
└── scheduler.py
```

---

## Формулы скоринга

### Trader Score (при построении watchlist)
```
Consistency = win_rate × log2(closed_positions_count)

ROI = sum(realizedPnl) / sum(totalBought)  # по всем closed-positions
ROI_normalized = (roi - min_roi) / (max_roi - min_roi)  # в пределах всего пула 0..1

TimingQuality = mean((resolution_price - avg_entry_price) / resolution_price)
  # только по выигрышным позициям
  # для YES-позиций resolution_price = 1.0
  # для NO-позиций resolution_price = 0.0 (инвертировать формулу)

TraderScore = Consistency × ROI_normalized × (1 + TimingQuality)
```

Все метрики считаются как общие, так и по каждой категории отдельно. Трейдер получает тег категории если у него 10+ закрытых позиций в ней.

### Signal Score (при детекции конвергенции)
```
SignalScore = sum(
  trader_score_i × conviction_i × category_match_i × freshness_i
) для каждого трейдера в конвергенции

conviction_i = position_size / avg_position_size трейдера
  # 1.0 = обычный размер, 2.0+ = повышенная уверенность

category_match_i:
  1.5 — категория рынка совпадает с экспертизой трейдера
  1.0 — не совпадает

freshness_i:
  2.0 — вход < 2 часов назад
  1.5 — вход < 6 часов назад
  1.0 — вход < 24 часов назад
  0.5 — вход < 48 часов назад
```

### Пороги сигналов

| Tier | Условие | Описание |
|---|---|---|
| 1 | 3+ трейдеров AND SignalScore > HIGH_THRESHOLD | Сильный сигнал |
| 2 | 2+ трейдеров AND SignalScore > MEDIUM_THRESHOLD | Стандартный сигнал |
| 3 | 1 трейдер из топ-10 AND conviction > 2.0 | Информационный |

HIGH_THRESHOLD и MEDIUM_THRESHOLD задаются в config.py, калибруются после первой недели работы.

---

## Шаги реализации

---

### Шаг 1: Project scaffold, конфиг, база данных

Создай структуру проекта как описано в разделе "Структура проекта" этого документа.

**config.py** — единый файл конфигурации. Загружает переменные из `.env`. Содержит:
- BASE URLs всех API (Data API, Gamma API, CLOB API)
- Интервалы: SCAN_INTERVAL_MINUTES=5, WATCHLIST_UPDATE_HOURS=24
- Пороги: HIGH_THRESHOLD=15.0, MEDIUM_THRESHOLD=8.0, MIN_CLOSED_POSITIONS=30, MIN_TRADERS_FOR_SIGNAL=2
- Окна: SIGNAL_WINDOW_HOURS=24, FRESHNESS_TIERS (словарь часы→множитель)
- Telegram: BOT_TOKEN, CHAT_ID из env
- DB_PATH="data/radar.db"

**db/models.py** — создание всех таблиц через sqlite3 (без ORM). Функция `init_db(db_path)` создаёт файл БД и все таблицы из раздела "Схема базы данных" если не существуют. Функции-хелперы для каждой таблицы: `upsert_trader()`, `insert_snapshot()`, `insert_change()`, `insert_signal()`, `get_traders()`, `get_latest_snapshots(wallet_address)` и тд.

**db/migrations.py** — `run_migrations()` вызывает `init_db`.

**.env.example**:
```
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
```

**requirements.txt**: aiohttp, python-telegram-bot, apscheduler, python-dotenv.

**Критерий готовности:** `python -c "from db.models import init_db; init_db('test.db')"` создаёт БД с 4 таблицами. Конфиг импортируется без ошибок.

---

### Шаг 2: API клиенты

Создай три асинхронных API клиента в папке `api/`.

**api/data_api.py** — класс `DataApiClient`:
- Конструктор принимает base_url (дефолт из config), создаёт aiohttp.ClientSession
- Методы (все async):
  - `get_leaderboard(category="OVERALL", time_period="ALL", order_by="PNL", limit=50, offset=0)` → list[dict]
  - `get_positions(user: str)` → list[dict]
  - `get_closed_positions(user: str, limit=100, offset=0)` → list[dict]
  - `get_trades(user: str, limit=100, offset=0)` → list[dict]
  - `get_activity(user: str, limit=100)` → list[dict]
  - `get_holders(market: str, limit=20)` → list[dict]
  - `get_value(user: str)` → dict
  - `get_leaderboard_all(category, time_period, order_by, max_results=200)` — пагинирует через offset, собирает до max_results

**api/gamma_api.py** — класс `GammaApiClient`:
- `get_events(limit=100, offset=0)` → list[dict]
- `get_markets(limit=100, offset=0)` → list[dict]
- `get_public_profile(address: str)` → dict

**api/clob_api.py** — класс `ClobApiClient`:
- `get_price(token_id: str, side: str)` → dict
- `get_midpoint(token_id: str)` → dict

Общие требования для всех клиентов:
- aiohttp.ClientSession с timeout 30s
- Retry при 429 и 5xx: 3 попытки, exponential backoff (1s, 2s, 4s)
- Логирование через стандартный logging модуль
- Задержка 100ms между последовательными запросами (asyncio.sleep(0.1))
- Методы `async close()` и поддержка `async with`

**Критерий готовности:** Простой скрипт делает `await client.get_leaderboard()` и возвращает список трейдеров. `await client.get_positions("0x...")` возвращает позиции.

---

### Шаг 3: Watchlist Builder

Создай `modules/watchlist_builder.py` — класс `WatchlistBuilder`.

**Конструктор:** принимает `DataApiClient`, `GammaApiClient`, путь к БД.

**Основной метод: `async build_watchlist()`:**

1. Загружает лидерборд по категориям: вызывает `get_leaderboard_all()` для каждой из категорий (OVERALL, POLITICS, CRYPTO, SPORTS, CULTURE). Собирает уникальный набор wallet addresses.

2. Для каждого уникального wallet address:
   - Загружает `get_closed_positions(user, limit=500)` — все закрытые позиции
   - Если closed_positions < MIN_CLOSED_POSITIONS (из config) — пропускает трейдера
   - Загружает `get_public_profile(address)` — имя, аватар, twitter
   - Загружает `get_trades(user, limit=500)` — для расчёта avg_position_size

3. Рассчитывает метрики для каждого трейдера по формулам из раздела "Trader Score":
   - win_rate: количество позиций с realizedPnl > 0 / общее количество
   - roi: sum(realizedPnl) / sum(totalBought)
   - consistency: win_rate × log2(total_closed)
   - timing_quality: среднее (1.0 - avgPrice) по выигрышным YES-позициям и среднее (avgPrice) по выигрышным NO-позициям
   - avg_position_size: median размеров из trades (usdcSize)
   - category_scores: те же метрики, но сгруппированные по eventSlug → определение категории через Gamma API или через leaderboard category

4. Нормализует ROI по всему пулу (min-max scaling).

5. Рассчитывает TraderScore = Consistency × ROI_normalized × (1 + TimingQuality).

6. Сохраняет в таблицу `traders` через `upsert_trader()`.

**Вспомогательный метод: `_classify_category(event_slug, title)`** — определяет категорию рынка. На первом этапе: простая эвристика по ключевым словам в title + данные из leaderboard.

**Критерий готовности:** `await builder.build_watchlist()` заполняет таблицу traders 30-60 записями с рассчитанными скорами. Можно вывести топ-10 по trader_score.

---

### Шаг 4: Position Scanner

Создай `modules/position_scanner.py` — класс `PositionScanner`.

**Конструктор:** принимает `DataApiClient`, путь к БД.

**Основной метод: `async scan_all()`:**

1. Загружает список трейдеров из таблицы `traders`.

2. Для каждого трейдера (с asyncio.sleep(0.1) между запросами):
   - Вызывает `get_positions(wallet_address)` — текущие позиции
   - Загружает предыдущий снэпшот из `position_snapshots` для этого wallet_address (последний по scanned_at)

3. Сравнивает текущие позиции с предыдущим снэпшотом:
   - Позиция есть сейчас, не было раньше → change_type = OPEN
   - Позиция есть сейчас и раньше, size вырос → change_type = INCREASE
   - Позиция есть сейчас и раньше, size уменьшился → change_type = DECREASE
   - Позиция была раньше, нет сейчас → change_type = CLOSE
   - Ключ для сравнения: (condition_id, outcome)

4. Для каждого изменения:
   - conviction_score = abs(new_size - old_size) × price_at_change / avg_position_size трейдера
   - Если avg_position_size = 0, conviction_score = 1.0
   - Записывает в `position_changes`

5. Записывает полный текущий снэпшот в `position_snapshots`.

6. Возвращает список всех обнаруженных changes для передачи в signal_detector.

**Метод `_diff_positions(previous: list[dict], current: list[dict])` → list[PositionChange]** — чистая функция сравнения двух списков позиций.

**Критерий готовности:** После двух последовательных запусков `scan_all()` (с паузой 1 минуту) в таблице `position_changes` появляются записи типа OPEN (при первом запуске все позиции — OPEN, при втором — реальные дифы). В `position_snapshots` два набора снэпшотов.

---

### Шаг 5: Signal Detector

Создай `modules/signal_detector.py` — класс `SignalDetector`.

**Конструктор:** принимает путь к БД.

**Основной метод: `detect_signals()` (синхронный, работает только с БД):**

1. Загружает все `position_changes` за последние SIGNAL_WINDOW_HOURS (из config, дефолт 24ч).

2. Группирует по condition_id.

3. Для каждой группы где 2+ разных wallet_address:
   - Проверяет направленность: все change_type в {OPEN, INCREASE} и один outcome → однонаправленный сигнал. Если есть и OPEN/INCREASE и DECREASE/CLOSE или разные outcome → пропускаем (разногласие).
   - Загружает trader_score и category_scores каждого вовлечённого трейдера из `traders`.
   - Определяет категорию рынка (из title, эвристика или кэш).

4. Рассчитывает SignalScore по формуле из раздела "Signal Score":
   - Для каждого трейдера: trader_score × conviction_score × category_match × freshness
   - freshness рассчитывается по detected_at vs текущее время, по тирам из config
   - category_match = 1.5 если у трейдера есть category_score для этой категории и он > 0, иначе 1.0
   - Суммирует по всем трейдерам

5. Определяет tier:
   - Tier 1: количество трейдеров >= 3 AND SignalScore > HIGH_THRESHOLD
   - Tier 2: количество трейдеров >= 2 AND SignalScore > MEDIUM_THRESHOLD
   - Tier 3: 1 трейдер, но его trader_score в топ-10 из watchlist AND conviction > 2.0
   - Если ни одно условие не выполнено — не создавать сигнал

6. Проверяет дедупликацию: если сигнал с таким condition_id и direction уже существует за последние SIGNAL_WINDOW_HOURS → обновляет signal_score и traders_involved, не создаёт дубликат.

7. Записывает новые/обновлённые сигналы в таблицу `signals` с sent=false.

8. Возвращает список новых/обновлённых сигналов.

**Критерий готовности:** При наличии тестовых данных в position_changes (руками вставить 3 записи с одним condition_id от разных трейдеров) — detect_signals() создаёт запись в signals с правильным tier и score.

---

### Шаг 6: Alert Sender (Telegram)

Создай `modules/alert_sender.py` — класс `AlertSender`.

**Конструктор:** принимает bot_token, chat_id из config.

**Основной метод: `async send_pending_alerts()`:**

1. Загружает все signals с sent=false из БД.
2. Для каждого сигнала форматирует сообщение.
3. Отправляет в Telegram через Bot API.
4. Помечает сигнал как sent=true в БД.

**Формат сообщения:**
```
{tier_emoji} TIER {tier} | Score: {signal_score:.1f}

{market_title}
Direction: {direction} @ ${current_price:.2f}
https://polymarket.com/event/{market_slug}

Traders ({count}):
{для каждого трейдера из traders_involved:}
- {username} (score {trader_score:.1f}, WR {win_rate:.0%}) — {change_type} ${size} ({conviction:.1f}x avg) {time_ago}
```

Где tier_emoji: Tier 1 = 🔴, Tier 2 = 🟡, Tier 3 = 🔵

**Метод `_format_time_ago(timestamp)`** — возвращает "2h ago", "15min ago" и тд.

Использовать библиотеку `python-telegram-bot` для отправки. Если bot_token не задан в config — логировать сигнал в консоль вместо отправки (для разработки).

**Критерий готовности:** При наличии сигнала в БД с sent=false и заданном BOT_TOKEN — сообщение приходит в Telegram чат. Без токена — выводится в консоль.

---

### Шаг 7: Scheduler и main.py

Создай `scheduler.py` и `main.py`.

**scheduler.py** — класс `RadarScheduler`:
- Конструктор: инициализирует все модули (создаёт API клиенты, scanner, detector, alert_sender, watchlist_builder)
- Инициализирует APScheduler (AsyncIOScheduler)
- Метод `start()`:
  - При старте: запускает `watchlist_builder.build_watchlist()` если таблица traders пустая
  - Добавляет job: `_scan_cycle` каждые SCAN_INTERVAL_MINUTES минут
  - Добавляет job: `watchlist_builder.build_watchlist` каждые WATCHLIST_UPDATE_HOURS часов
  - Запускает scheduler
- Метод `async _scan_cycle()`:
  - Вызывает `position_scanner.scan_all()`
  - Вызывает `signal_detector.detect_signals()`
  - Вызывает `alert_sender.send_pending_alerts()`
  - Логирует: количество трейдеров просканировано, изменений найдено, сигналов создано
- Метод `stop()`: graceful shutdown — закрывает API клиенты, останавливает scheduler

**main.py**:
- Парсит аргументы: `--once` (один цикл и выход, для тестов), `--rebuild-watchlist` (пересобрать watchlist и выход)
- Инициализирует БД через `run_migrations()`
- Создаёт и запускает `RadarScheduler`
- Обрабатывает SIGINT/SIGTERM для graceful shutdown
- Логирование: настроить logging с форматом `[%(asctime)s] %(levelname)s %(name)s: %(message)s`

**Критерий готовности:**
- `python main.py --rebuild-watchlist` — собирает watchlist, выводит топ-10 трейдеров, завершается
- `python main.py --once` — делает один цикл сканирования, выводит результаты, завершается
- `python main.py` — запускается в фоне, каждые 5 минут сканирует, при нахождении сигнала отправляет в Telegram