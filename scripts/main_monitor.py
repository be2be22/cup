#!/usr/bin/env python3
"""
Single entry point meant to be run by an alwaysdata Scheduled Task
every 1-2 minutes.

IMPORTANT: the order of operations is carefully chosen to ensure that
critical live reporting (live commentary, goal/card alerts) happens
FIRST and is never blocked by slow operations like Reddit video
searches. Reddit 429 rate-limiting can cause event_monitor to take
3+ minutes, which would block live_update if it ran after.

Order of operations:
  1. Scheduler - refresh fixtures, mark live matches as active
  2. Prematch - send pre-match analysis for upcoming matches
  3. Live Thread - update the pinned scoreboard message
  4. Live Update - send AI live commentary (CRITICAL - must be fast)
  5. Event Monitor - detect new goals/cards/subs/VAR + video search
     (can be slow due to Reddit rate limits)
  6. Penalty Monitor - report penalty shootout kicks
  7. Delay Alert - report match delays/suspensions
  8. Postmatch - final report + highlight video for ended matches
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
        # 1. Scheduler - refresh fixtures
        from scripts.scheduler import main as scheduler_main
        scheduler_main()

        # 2. Prematch - send pre-match analysis
        from scripts.prematch import main as prematch_main
        prematch_main()

        # 3. Live Thread - update the pinned scoreboard
        try:
            from lib.live_thread import update_live_thread
            from lib.api_client import FootballAPIClient
            client = FootballAPIClient()
            for event in client.get_live_fixtures():
                match = client.parse_event(event)
                if match['home_team']:
                    try:
                        update_live_thread(match)
                    except Exception as e:
                        print(f"Live thread update failed for {match['id']}: {e}")
        except Exception as e:
            print(f"Live thread batch failed: {e}")

        # 4. CRITICAL: Live Update (AI commentary) - must run FIRST,
        #    before event_monitor which can be slow due to Reddit 429
        active_matches = get_active_matches()
        for match_id in active_matches:
            try:
                from scripts.live_update import main as live_main
                live_main(match_id=match_id)
            except Exception as e:
                print(f"Live update failed for match {match_id}: {e}")

        # 5. CRITICAL: Penalty Monitor - must also be fast
        for match_id in active_matches:
            try:
                from scripts.penalty_monitor import main as penalty_main
                penalty_main(match_id=match_id)
            except Exception as e:
                print(f"Penalty monitor failed for match {match_id}: {e}")

        # 6. CRITICAL: Delay Alert
        for match_id in active_matches:
            try:
                from scripts.delay_alert import main as delay_main
                delay_main(match_id=match_id)
            except Exception as e:
                print(f"Delay alert failed for match {match_id}: {e}")

        # 7. Event Monitor - goals/cards/subs/VAR + video search
        #    This can be SLOW (Reddit rate limits cause 30-45s per search)
        #    so it runs AFTER the critical live reporting above.
        #    Each exception is caught so one match's failure doesn't
        #    block the others.
        for match_id in active_matches:
            try:
                from scripts.event_monitor import main as event_main
                event_main(match_id=match_id)
            except Exception as e:
                print(f"Event monitor failed for match {match_id}: {e}")

        # 8. Postmatch - final report + highlight video
        from scripts.postmatch import main as postmatch_main
        postmatch_main()

        print(f"[{datetime.now(timezone.utc).isoformat()}] Monitor check completed")

    except Exception as e:
        print(f"Monitor error: {e}")
        send_message(f"⚠️ خطا در سیستم مانیتورینگ: {str(e)}")


if __name__ == '__main__':
    main()
