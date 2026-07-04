"""Warm ship — Telegram bot that watches mostanet.ru for ferry tickets.

Polls the site's API every CHECK_INTERVAL_SECONDS and notifies subscribers
the moment tickets appear for the watched date(s).
"""

import json
import logging
import logging.handlers
import os
import sys
import time
from datetime import datetime
from pathlib import Path

import httpx
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, ApplicationBuilder, CommandHandler, ContextTypes

import config
import monitor

load_dotenv()
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not TOKEN:
    print("Error: TELEGRAM_BOT_TOKEN not found in .env")
    sys.exit(1)

ADMIN_USER_ID = os.getenv("ADMIN_USER_ID")
CRASH_BOT_TOKEN = os.getenv("CRASH_BOT_TOKEN")

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
LOGS_DIR = BASE_DIR / "logs"
SUBSCRIBERS_FILE = DATA_DIR / "subscribers.json"
STATE_FILE = DATA_DIR / "state.json"

DATA_DIR.mkdir(exist_ok=True)
LOGS_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO,
    handlers=[
        logging.StreamHandler(),
        logging.handlers.RotatingFileHandler(
            LOGS_DIR / "warmship.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8"
        ),
    ],
)
for noisy in ("httpx", "telegram", "apscheduler"):
    logging.getLogger(noisy).setLevel(logging.WARNING)
log = logging.getLogger(__name__)


# ---------- access control (fail closed) ----------

def _parse_allowed(raw):
    names, ids = set(), set()
    for entry in (raw or "").split(","):
        entry = entry.strip()
        if not entry:
            continue
        if entry.lstrip("-").isdigit():
            ids.add(int(entry))
        else:
            names.add(entry.lstrip("@").lower())
    return names, ids


ALLOWED_NAMES, ALLOWED_IDS = _parse_allowed(os.getenv("ALLOWED_USERS"))
if not ALLOWED_NAMES and not ALLOWED_IDS:
    print("WARNING: ALLOWED_USERS not set - bot will refuse all users (fail-closed).")


def _is_allowed(update: Update) -> bool:
    user = update.effective_user
    if user is None:
        return False
    if user.id in ALLOWED_IDS:
        return True
    if user.username and user.username.lower() in ALLOWED_NAMES:
        return True
    return False


# ---------- tiny JSON persistence ----------

def _load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def _save_json(path: Path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _subscribers() -> dict:
    """chat_id (str) -> display name"""
    return _load_json(SUBSCRIBERS_FILE, {})


def _state() -> dict:
    return _load_json(STATE_FILE, {})


# ---------- messaging ----------

async def _send_all(app: Application, text: str, silent: bool = False):
    for chat_id in list(_subscribers()):
        try:
            await app.bot.send_message(
                chat_id=int(chat_id), text=text, disable_notification=silent
            )
        except Exception as e:  # noqa: BLE001 - one bad chat must not stop the rest
            log.warning("Failed to send to %s: %s", chat_id, e)


async def _notify_admin(app: Application, text: str):
    if not ADMIN_USER_ID:
        return
    try:
        await app.bot.send_message(chat_id=int(ADMIN_USER_ID), text=text)
    except Exception as e:  # noqa: BLE001
        log.warning("Failed to notify admin: %s", e)


# ---------- monitor job ----------

async def monitor_job(context: ContextTypes.DEFAULT_TYPE):
    app = context.application
    state = _state()
    now = time.time()
    api_ok = True

    async with httpx.AsyncClient() as client:
        for watch in config.WATCHES:
            try:
                rides = await monitor.check_watch(client, watch)
            except Exception as e:  # noqa: BLE001 - network hiccups are expected
                log.warning("Check failed for %s: %s", watch["key"], e)
                api_ok = False
                continue

            wstate = state.setdefault(watch["key"], {"rides": {}})
            wstate["last_check"] = now
            wstate["last_rides"] = [
                monitor.format_ride(watch, r) for r in rides
            ] or [f"{watch['from_name']} → {watch['to_name']} ({watch['date']}): рейс не найден"]

            for ride in rides:
                rstate = wstate["rides"].setdefault(
                    ride.ride_id, {"snapshot": None, "last_alert": 0}
                )
                prev = rstate["snapshot"]
                cur = ride.snapshot()
                prev_avail = prev["available"] if prev else 0
                text = monitor.format_ride(watch, ride)

                if prev_avail == 0 and cur["available"] > 0:
                    log.info("TICKETS APPEARED for %s: %s", watch["key"], cur)
                    await _send_all(
                        app,
                        "🚨🚨 БИЛЕТЫ ПОЯВИЛИСЬ! 🚨🚨\n\n"
                        f"{text}\n\nПокупать здесь: {config.SITE_URL}",
                    )
                    rstate["last_alert"] = now
                elif prev_avail > 0 and cur["available"] == 0:
                    log.info("Tickets gone for %s", watch["key"])
                    await _send_all(app, f"😞 Билеты закончились.\n\n{text}")
                elif cur["available"] > 0 and prev and cur != prev:
                    await _send_all(
                        app, f"ℹ️ Изменилось количество мест:\n\n{text}", silent=True
                    )
                elif (
                    cur["available"] > 0
                    and now - rstate["last_alert"] >= config.REMIND_INTERVAL_SECONDS
                ):
                    await _send_all(
                        app,
                        f"⏰ Напоминание: билеты всё ещё в продаже!\n\n{text}\n\n{config.SITE_URL}",
                    )
                    rstate["last_alert"] = now

                rstate["snapshot"] = cur

    # API health: complain to admin once if it stays down, confirm recovery
    if api_ok:
        if state.get("api_down_alerted"):
            await _notify_admin(app, "✅ API mostanet.ru снова отвечает.")
        state["api_down_since"] = None
        state["api_down_alerted"] = False
    else:
        state.setdefault("api_down_since", None)
        if not state["api_down_since"]:
            state["api_down_since"] = now
        elif (
            not state.get("api_down_alerted")
            and now - state["api_down_since"] >= config.API_DOWN_ALERT_SECONDS
        ):
            mins = int((now - state["api_down_since"]) / 60)
            await _notify_admin(
                app, f"⚠️ API mostanet.ru недоступен уже {mins} минут. Мониторю дальше."
            )
            state["api_down_alerted"] = True

    _save_json(STATE_FILE, state)


# ---------- commands ----------

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_allowed(update):
        await update.message.reply_text("Извини, это личный бот.")
        return
    subs = _subscribers()
    user = update.effective_user
    subs[str(update.effective_chat.id)] = user.username or user.full_name
    _save_json(SUBSCRIBERS_FILE, subs)
    watch_lines = "\n".join(
        f"• {w['from_name']} → {w['to_name']}, {w['date']}" for w in config.WATCHES
    )
    await update.message.reply_text(
        "Привет! Я слежу за билетами на теплоход на mostanet.ru.\n\n"
        f"Наблюдаю:\n{watch_lines}\n\n"
        f"Проверяю каждые {config.CHECK_INTERVAL_SECONDS // 60} мин. "
        "Как только билеты появятся — сразу напишу сюда!\n\n"
        "Команды:\n/status — что там сейчас\n/check — проверить прямо сейчас"
    )
    log.info("Subscribed: %s (%s)", update.effective_chat.id, subs[str(update.effective_chat.id)])


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_allowed(update):
        return
    state = _state()
    parts = []
    for watch in config.WATCHES:
        wstate = state.get(watch["key"], {})
        last = wstate.get("last_check")
        when = (
            datetime.fromtimestamp(last).strftime("%d.%m %H:%M:%S") if last else "ещё не было"
        )
        rides = wstate.get("last_rides") or ["данных пока нет"]
        parts.append(f"Последняя проверка: {when}\n\n" + "\n\n".join(rides))
    parts.append(f"Подписчиков: {len(_subscribers())}")
    await update.message.reply_text("\n\n———\n\n".join(parts))


async def cmd_check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_allowed(update):
        return
    msg = await update.message.reply_text("Проверяю…")
    try:
        async with httpx.AsyncClient() as client:
            blocks = []
            for watch in config.WATCHES:
                rides = await monitor.check_watch(client, watch)
                if rides:
                    blocks += [monitor.format_ride(watch, r) for r in rides]
                else:
                    blocks.append(
                        f"{watch['from_name']} → {watch['to_name']} ({watch['date']}): рейс не найден"
                    )
        await msg.edit_text("\n\n".join(blocks))
    except Exception as e:  # noqa: BLE001
        log.warning("Manual check failed: %s", e)
        await msg.edit_text(f"Не получилось достучаться до API: {e}")


# ---------- crash notifier ----------

def _crash_notify(error: str):
    """Best-effort alert via secondary bot; must never raise."""
    try:
        if not (CRASH_BOT_TOKEN and ADMIN_USER_ID):
            return
        httpx.post(
            f"https://api.telegram.org/bot{CRASH_BOT_TOKEN}/sendMessage",
            json={"chat_id": int(ADMIN_USER_ID), "text": f"💀 Warm ship упал:\n{error[:3500]}"},
            timeout=15,
        )
    except Exception:  # noqa: BLE001
        pass


def main():
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("check", cmd_check))
    app.job_queue.run_repeating(
        monitor_job, interval=config.CHECK_INTERVAL_SECONDS, first=5
    )
    log.info(
        "Warm ship started. Watching %d route(s), every %d s.",
        len(config.WATCHES),
        config.CHECK_INTERVAL_SECONDS,
    )
    app.run_polling()


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # noqa: BLE001
        log.exception("Fatal error")
        _crash_notify(repr(e))
        raise
