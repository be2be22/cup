#!/usr/bin/env python3
"""
Single entry point meant to be run by an alwaysdata Scheduled Task
every 1-2 minutes. It does everything in one process (lighter than N
separate cron jobs on a 0.25 CPU / 256MB plan):

  1. refresh fixtures from ESPN, mark newly-live matches as active
  2. send pre-match analysis for fixtures starting soon
  3. for each active (live) match: live score update, new goals/cards,
     penalty shootout updates, delay/suspension alerts
  4. send the final report for matches that just ended
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from datetime import datetime, timezone
from lib.state_manager import get_active_matches
from lib.telegram_sender import send_message


def main():
    print(f"[{datetime.now(timezone.utc).isoformat()}] Starting World Cup monitor check...")

    try:
        from scripts.scheduler import main as scheduler_main
        scheduler_main()

        from scripts.prematch import main as prematch_main
        prematch_main()

        active_matches = get_active_matches()
        for match_id in active_matches:
            try:
                from scripts.live_update import main as live_main
                live_main(match_id=match_id)

                from scripts.event_monitor import main as event_main
                event_main(match_id=match_id)

                from scripts.penalty_monitor import main as penalty_main
                penalty_main(match_id=match_id)

                from scripts.delay_alert import main as delay_main
                delay_main(match_id=match_id)
            except Exception as e:
                print(f"Error processing match {match_id}: {e}")

        from scripts.postmatch import main as postmatch_main
        postmatch_main()

        print(f"[{datetime.now(timezone.utc).isoformat()}] Monitor check completed")

    except Exception as e:
        print(f"Monitor error: {e}")
        send_message(f"⚠️ خطا در سیستم مانیتورینگ: {str(e)}")


if __name__ == '__main__':
    main()
