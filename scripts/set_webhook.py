#!/usr/bin/env python3
"""
Registers (or removes) the Telegram webhook URL, so button taps on the
bot get delivered to webhook.py. Run this ONCE by hand over SSH, after
webhook.py is deployed and reachable over HTTPS as its own alwaysdata
site:

    python3 scripts/set_webhook.py https://your-bot-site.alwaysdata.net/

To remove the webhook later (e.g. before debugging locally):

    python3 scripts/set_webhook.py --delete

Requires TELEGRAM_BOT_TOKEN in the environment. If you export
TELEGRAM_WEBHOOK_SECRET too, it's sent along so Telegram includes it on
every request and webhook.py can verify requests really come from
Telegram.
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from lib.telegram_sender import set_webhook, delete_webhook, get_webhook_info


def main():
    if not os.environ.get("TELEGRAM_BOT_TOKEN"):
        print("✗ TELEGRAM_BOT_TOKEN is not set in this shell. On alwaysdata, "
              "environment variables set in the control panel are NOT "
              "automatically available in an SSH shell - export it manually "
              "for this one command, e.g.:\n"
              "  TELEGRAM_BOT_TOKEN=123:abc python3 scripts/set_webhook.py https://...")
        return

    if len(sys.argv) < 2:
        print(__doc__)
        return

    if sys.argv[1] == "--delete":
        result = delete_webhook()
        print(result)
        return

    if sys.argv[1] == "--info":
        result = get_webhook_info()
        print(result)
        return

    url = sys.argv[1].rstrip("/") + "/"
    secret = os.environ.get("TELEGRAM_WEBHOOK_SECRET", "") or None
    result = set_webhook(url, secret_token=secret)
    print(result)
    if result and result.get("ok"):
        print(f"\n✓ Webhook set to {url}")
        if secret:
            print("✓ Secret token configured - make sure TELEGRAM_WEBHOOK_SECRET "
                  "is also set in the webhook site's Environment on alwaysdata.")
    else:
        print("\n✗ Failed to set webhook - check the URL is publicly reachable over HTTPS.")


if __name__ == '__main__':
    main()
