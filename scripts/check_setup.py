#!/usr/bin/env python3
"""
Run this once by hand after deploying, to check that everything is wired
up correctly, before you rely on the scheduled task:

    python3 worldcup/scripts/check_setup.py
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from lib.api_client import FootballAPIClient
from lib.telegram_sender import send_message
from lib import settings


def main():
    print("1) Checking TELEGRAM_BOT_TOKEN (env var or local_settings.py)...")
    if not settings.get("TELEGRAM_BOT_TOKEN"):
        print("   ✗ Not set. Either set it in the alwaysdata panel (Sites > your site > "
              "Environment) if available, or create local_settings.py on the server - "
              "see local_settings.py.example / DEPLOY_SSH.md.")
    else:
        print("   ✓ Set.")

    print("\n2) Checking AI_API_BASE_URL / AI_API_KEY (optional, for AI prematch analysis)...")
    if not settings.get("AI_API_BASE_URL") or not settings.get("AI_API_KEY"):
        print("   ⚠ Not set - prematch messages will use the static fallback analysis instead.")
    else:
        print("   ✓ Set.")

    print("\n3) Testing ESPN scoreboard (no key needed)...")
    client = FootballAPIClient()
    fixtures = client.get_all_fixtures()
    print(f"   ✓ Got {len(fixtures)} fixtures from ESPN." if fixtures else
          "   ✗ Got no fixtures - ESPN may be unreachable or there's no active tournament right now.")

    print("\n4) Sending a test message to your Telegram channel...")
    ok = send_message("✅ ربات جام جهانی با موفقیت روی alwaysdata راه‌اندازی شد.")
    print("   ✓ Sent." if ok else "   ✗ Failed - check TELEGRAM_BOT_TOKEN and that the bot is an admin of the channel.")


if __name__ == '__main__':
    main()
