"""Control the laptop agent from your phone (Telegram).

    python phone.py            run the bot
    python phone.py --whoami   find out YOUR Telegram user id (needed once, for the allow-list)

One-time setup (about 3 minutes):
  1. In Telegram, chat with @BotFather -> /newbot -> copy the token it gives you.
  2. Put it in .env (this file is never committed):   TELEGRAM_BOT_TOKEN=...
  3. Run  python phone.py --whoami , then send any message to your new bot. Your numeric
     id is printed. Put it in .env:                  TELEGRAM_ALLOWED_USER_IDS=123456789
  4. Strongly recommended, also in .env:             PHONE_PIN=some-secret-pin
  5. Run  python phone.py  and message your bot.

Only the ids you list can talk to it; everyone else is silently ignored. See phone/bot.py.
"""

import os
import sys

from agent import config  # noqa: F401  (importing it loads the .env file)
from agent import events
from phone.bot import PhoneBot, whoami

API_BASE = os.getenv("TELEGRAM_API_BASE", "https://api.telegram.org")   # only changed by the tests


def main() -> None:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        raise SystemExit("TELEGRAM_BOT_TOKEN is missing. Read the setup steps at the top of phone.py.")

    if "--whoami" in sys.argv:
        whoami(token, API_BASE)
        return

    allowed = {int(part) for part in os.getenv("TELEGRAM_ALLOWED_USER_IDS", "").replace(" ", "").split(",") if part}
    if not allowed:
        raise SystemExit("TELEGRAM_ALLOWED_USER_IDS is empty - nobody would be allowed in.\n"
                         "Run  python phone.py --whoami  to find your id, then put it in .env.")
    pin = os.getenv("PHONE_PIN", "").strip()
    if not pin:
        print("WARNING: no PHONE_PIN set. Anyone who gets into your Telegram account could control this laptop.")

    from agent.session import AgentSession
    # Risky actions always need a yes/no on the phone, even if your desktop agent never asks
    confirm = os.getenv("PHONE_CONFIRM", "true").strip().lower() != "false"
    session = AgentSession(confirm_risky=confirm)
    events.subscribe(lambda kind, info: print(f"  [tool] {info['name']}") if kind == "tool" else None)

    print(f"Phone bot started for {len(allowed)} allowed user(s). Press Ctrl+C to stop.")
    try:
        PhoneBot(session, token, allowed, pin, api_base=API_BASE).run_forever()
    except KeyboardInterrupt:
        print("Stopped.")


if __name__ == "__main__":
    main()
