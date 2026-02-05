"""
Telegram Bot for MiniApp.

This bot provides the entry point to the MiniApp via inline buttons.
"""

import logging

from telegram import Update, WebAppInfo, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes

import config

logger = logging.getLogger(__name__)

# MiniApp URL from config
MINIAPP_URL = config.MINIAPP_URL


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /start command - show welcome message with MiniApp button."""
    user = update.effective_user

    # Create inline keyboard with MiniApp button
    keyboard = [
        [
            InlineKeyboardButton(
                "📊 Open Radar",
                web_app=WebAppInfo(url=MINIAPP_URL),
            )
        ],
        [
            InlineKeyboardButton(
                "📈 Signals",
                web_app=WebAppInfo(url=f"{MINIAPP_URL}?tab=signals"),
            ),
            InlineKeyboardButton(
                "👥 Traders",
                web_app=WebAppInfo(url=f"{MINIAPP_URL}?tab=traders"),
            ),
        ],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    welcome_text = (
        f"👋 Привет, {user.first_name}!\n\n"
        "🎯 *Poly Smart Radar* — отслеживание топ-трейдеров Polymarket.\n\n"
        "📊 *Сигналы* — когда 2+ трейдеров входят в одну позицию\n"
        "👥 *Трейдеры* — топ-100 по PnL с классификацией\n\n"
        "Нажми кнопку ниже, чтобы открыть радар:"
    )

    await update.message.reply_text(
        welcome_text,
        reply_markup=reply_markup,
        parse_mode="Markdown",
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /help command."""
    help_text = (
        "🔹 /start — открыть радар\n"
        "🔹 /signals — список активных сигналов\n"
        "🔹 /stats — статистика системы\n"
        "🔹 /help — эта справка\n"
    )
    await update.message.reply_text(help_text)


async def signals_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /signals command - quick access to signals."""
    keyboard = [
        [
            InlineKeyboardButton(
                "🔴 Tier 1",
                web_app=WebAppInfo(url=f"{MINIAPP_URL}?tier=1"),
            ),
            InlineKeyboardButton(
                "🟡 Tier 2",
                web_app=WebAppInfo(url=f"{MINIAPP_URL}?tier=2"),
            ),
            InlineKeyboardButton(
                "🔵 Tier 3",
                web_app=WebAppInfo(url=f"{MINIAPP_URL}?tier=3"),
            ),
        ],
        [
            InlineKeyboardButton(
                "📊 All Signals",
                web_app=WebAppInfo(url=f"{MINIAPP_URL}?tab=signals"),
            ),
        ],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        "🎯 Выбери тип сигналов:",
        reply_markup=reply_markup,
    )


async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /stats command - show quick stats."""
    # Read stats from database
    from db.models import _get_connection

    conn = _get_connection(config.DB_PATH)
    try:
        # Count signals
        total_signals = conn.execute("SELECT COUNT(*) FROM signals").fetchone()[0]
        active_signals = conn.execute(
            "SELECT COUNT(*) FROM signals WHERE status = 'ACTIVE'"
        ).fetchone()[0]
        tier1 = conn.execute(
            "SELECT COUNT(*) FROM signals WHERE tier = 1"
        ).fetchone()[0]

        # Count traders
        total_traders = conn.execute("SELECT COUNT(*) FROM traders").fetchone()[0]
        human_traders = conn.execute(
            "SELECT COUNT(*) FROM traders WHERE trader_type = 'HUMAN'"
        ).fetchone()[0]

        stats_text = (
            "📊 *Статистика Poly Smart Radar*\n\n"
            f"📡 *Сигналы*\n"
            f"  • Всего: {total_signals}\n"
            f"  • Активных: {active_signals}\n"
            f"  • Tier 1: {tier1}\n\n"
            f"👥 *Трейдеры*\n"
            f"  • Всего: {total_traders}\n"
            f"  • HUMAN: {human_traders}\n"
        )
    except Exception as e:
        logger.error("Failed to get stats: %s", e)
        stats_text = "❌ Не удалось получить статистику"
    finally:
        conn.close()

    # Add button to open full app
    keyboard = [
        [
            InlineKeyboardButton(
                "📊 Open Radar",
                web_app=WebAppInfo(url=MINIAPP_URL),
            )
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        stats_text,
        reply_markup=reply_markup,
        parse_mode="Markdown",
    )


def create_bot_application() -> Application:
    """Create and configure the bot application."""
    if not config.TELEGRAM_BOT_TOKEN:
        raise ValueError("TELEGRAM_BOT_TOKEN not configured")

    application = Application.builder().token(config.TELEGRAM_BOT_TOKEN).build()

    # Add handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("signals", signals_command))
    application.add_handler(CommandHandler("stats", stats_command))

    return application


async def run_bot() -> None:
    """Run the bot (polling mode)."""
    application = create_bot_application()
    logger.info("Starting Telegram bot...")
    await application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    import asyncio

    logging.basicConfig(
        level=logging.INFO,
        format="[%(asctime)s] %(levelname)s %(name)s: %(message)s",
    )

    asyncio.run(run_bot())
