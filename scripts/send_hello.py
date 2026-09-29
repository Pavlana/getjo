"""One-off check: send a test message to confirm Telegram notify works end-to-end.

Usage: set -a; source .env; set +a; python3 scripts/send_hello.py
"""

from core.config import require_env
from core.notify import send_telegram

if __name__ == "__main__":
    env = require_env(["TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"])
    send_telegram(
        "hello from job-radar",
        token=env["TELEGRAM_BOT_TOKEN"],
        chat_id=env["TELEGRAM_CHAT_ID"],
    )
    print("sent")
