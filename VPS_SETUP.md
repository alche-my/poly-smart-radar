# VPS Setup Guide — Poly Smart Radar

## Быстрое обновление (если проект уже склонирован)

```bash
cd /root/poly-smart-radar
git pull origin main
source venv/bin/activate
pip install -r requirements.txt
```

Запуск:

```bash
# Один цикл сканирования (тест)
python main.py --once

# Пересобрать watchlist
python main.py --rebuild-watchlist

# Демон-режим (непрерывное сканирование каждые 5 мин)
python main.py
```

---

## Установка с нуля

### 1. Подключиться к VPS

```bash
ssh root@YOUR_VPS_IP
```

### 2. Установить зависимости системы

```bash
apt update && apt install -y python3 python3-venv python3-pip git
```

### 3. Склонировать репозиторий

```bash
cd /root
git clone https://github.com/alche-my/poly-smart-radar.git
cd poly-smart-radar
```

### 4. Создать виртуальное окружение и установить пакеты

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 5. Настроить переменные окружения

```bash
cp .env.example .env
nano .env
```

Заполнить:

```
TELEGRAM_BOT_TOKEN=ваш_токен_бота
TELEGRAM_CHAT_ID=ваш_chat_id
```

Если Telegram-уведомления не нужны — можно оставить пустыми.

### 6. Проверить что все работает

```bash
python main.py --once
```

Должен выполниться один цикл сканирования и завершиться.

### 7. Запуск в фоне (демон-режим)

Вариант A — через `screen`:

```bash
apt install -y screen
screen -S radar
cd /root/poly-smart-radar && source venv/bin/activate
python main.py
```

Отключиться от screen: `Ctrl+A`, затем `D`
Вернуться: `screen -r radar`

Вариант B — через `systemd` (рекомендуется для продакшена):

```bash
cat > /etc/systemd/system/poly-radar.service << 'EOF'
[Unit]
Description=Poly Smart Radar
After=network.target

[Service]
Type=simple
WorkingDirectory=/root/poly-smart-radar
ExecStart=/root/poly-smart-radar/venv/bin/python main.py
Restart=on-failure
RestartSec=30
EnvironmentFile=/root/poly-smart-radar/.env

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable poly-radar
systemctl start poly-radar
```

Проверить статус:

```bash
systemctl status poly-radar
journalctl -u poly-radar -f
```

### 8. Веб-интерфейс (опционально)

Запустить API + фронтенд:

```bash
cd /root/poly-smart-radar
source venv/bin/activate
uvicorn webapp.main:app --host 0.0.0.0 --port 8000
```

Доступ: `http://YOUR_VPS_IP:8000`

---

## Частые ошибки

| Ошибка | Причина | Решение |
|--------|---------|---------|
| `can't open file '/root/main.py'` | Запуск не из папки проекта | `cd /root/poly-smart-radar` перед запуском |
| `ModuleNotFoundError` | venv не активирован | `source venv/bin/activate` |
| `No module named 'aiohttp'` | Зависимости не установлены | `pip install -r requirements.txt` |

---

## Режимы запуска

| Команда | Описание |
|---------|----------|
| `python main.py` | Демон: сканирует каждые 5 мин, watchlist обновляется раз в 24ч |
| `python main.py --once` | Один цикл сканирования и выход |
| `python main.py --rebuild-watchlist` | Пересобрать список трейдеров и выйти |
