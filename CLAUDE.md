# Warm ship

Telegram bot that watches mostanet.ru (Kuril Islands ferry booking site) for returned/released
tickets on Курильск порт → Южно-Курильск порт, 2026-08-15, and instantly alerts subscribers
(Fedor + a friend). Polls the site's open JSON API — no browser, no HTML scraping.

## Run
`COMPLETE_LAUNCH.bat` — self-heals (creates `venv\` (no dot), pip-installs requirements), then
HANDS OFF to the central runner (`Admin_hub\runner.py`) when it's alive: writes `logs\runner.start`
and exits; the runner starts bot.py hidden and supervises it. Without a runner it falls back to the
legacy visible launch (kills prior instance — folder+`bot.py` match, `admin_bot` exempt — and tees
output to `logs\launcher.log`). Dev venv is `.venv\` (Python 3.14.2) — the launcher does NOT use it.
Manual run: `.venv\Scripts\python.exe bot.py`. Requires Python 3.11+ (hard-checked in bot.py).
Each recipient must send `/start` once to subscribe. Commands: `/status`, `/check`.

## Stack
Python, python-telegram-bot 22.8 (JobQueue polls every 180 s), httpx, python-dotenv.
requirements.txt is a full pip freeze pin set — keep versions as-is.

## Secrets & config
`.env` (gitignored): TELEGRAM_BOT_TOKEN, ALLOWED_USERS (IDs/usernames, comma-sep),
ADMIN_USER_ID, CRASH_BOT_TOKEN (optional secondary bot for crash alerts).
`config.py` → `WATCHES` list controls what dates/routes are monitored; also poll/remind intervals.

## Landmines
- API base is `https://seat-customer-api-prod.mostanet.ru`; endpoint `GET /customer/routesavailable`
  with a fresh random `requesterId` UUID per request. Sends a browser User-Agent on purpose.
- Bus-stop UUIDs in config.py came from `GET /customer/busstops?name=...` — don't invent them.
  `MALOKURILSKOE_PORT` is defined but currently unused (spare for a second watch).
- Access control is fail-closed: empty ALLOWED_USERS = bot refuses everyone.
- One bot token = one poller. bot.py has a single-instance guard (localhost port 47617) and
  `drop_pending_updates=True`; the legacy launcher path also kills any previous instance.
- Runtime state lives in `data/state.json` + `data/subscribers.json` (gitignored) — deleting
  state.json re-fires "tickets appeared" alerts on next check.
- stdout is reconfigured to UTF-8 (server consoles are cp1252/cp866; Cyrillic logs).
- Alert logic: 0→N seats = loud alert; N→0 = "sold out"; count change = silent info;
  still-available reminder every 30 min. Admin gets a ping if API is down >30 min.

## State (as of 2026-07-09)
Works end-to-end; built 2026-07-04/05. Remote: https://github.com/fedor5556/Warm_ship.git, deployed
on the friend's server as `Warm_ship` and registered in BOTH Admin_hub registries (`projects.json` +
`runner_projects.json`) — the runner supervises it (crash-restart, reboot autostart, heartbeat).
2026-07-09: launcher gained the central-runner handoff, bot.py gained the single-instance port guard
(47617); redeploy via Hub → warmship → Update to apply.
