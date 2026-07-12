#!/usr/bin/env python3
"""Sends a final-result report the first time a match is seen as ended.

Also:
  - Closes the Live Thread (edits the live-scoreboard message to show
    'بازی پایان یافت' instead of 'بازی زنده')
  - Waits 10 minutes for highlights to be published, then searches:
    1. Varzesh3.com (Iranian site, Persian highlights - primary source)
    2. Reddit r/soccer (fallback if varzesh3 doesn't have it)
  - Sends the highlight video to the channel via sendVideo

The 10-minute delay is tracked via 'postmatch_time' in state.json.
The video search is retried on subsequent cron runs until a video is
found or 30 minutes have passed.
"""
import sys
import os
import time
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from lib.api_client import FootballAPIClient
from lib.formatter import PersianFormatter, fa, TEAM_FA, get_flag, SEP
from lib.telegram_sender import send_message, send_video
from lib.state_manager import remove_active_match, update_match_state, get_match_state
from lib.live_thread import close_live_thread
from lib.reddit_video import fetch_reddit_highlight_video
from lib.varzesh3_video import fetch_varzesh3_highlight


# How long to wait after match ends before searching for highlights
HIGHLIGHT_DELAY_SECONDS = 600  # 10 minutes
# How long to keep retrying before giving up
HIGHLIGHT_RETRY_WINDOW = 1800  # 30 minutes


def main(match_id=None):
    client = FootballAPIClient()
    fmt = PersianFormatter()

    for event in client.get_all_fixtures():
        match = client.parse_event(event)

        if match_id and str(match['id']) != str(match_id):
            continue
        if match['status_state'] != 'post':
            continue

        state = get_match_state(str(match['id']))

        # ============================================================
        # Step 1: Send the text postmatch report (only once)
        # ============================================================
        if not state.get('postmatch_sent'):
            # Send the final match report
            send_message(fmt.format_postmatch({
                'home_team': match['home_team'], 'away_team': match['away_team'],
                'home_score': match['home_score'], 'away_score': match['away_score'],
                'goals': match['goals'],
            }))

            # Close the Live Thread
            try:
                close_live_thread(match)
            except Exception as e:
                print(f"[postmatch] close_live_thread failed: {e}")

            # Record the time we sent the postmatch report
            update_match_state(str(match['id']),
                postmatch_sent=True,
                postmatch_time=time.time(),
                highlight_sent=False,
            )
            print(f"Postmatch report sent for {match['home_team']} vs {match['away_team']}")

        # ============================================================
        # Step 2: Send highlight video (with 10-min delay, retried)
        # ============================================================
        if not state.get('highlight_sent'):
            postmatch_time = state.get('postmatch_time', 0)
            now = time.time()
            elapsed = now - postmatch_time

            # Wait at least 10 minutes after match ended
            if elapsed < HIGHLIGHT_DELAY_SECONDS:
                remaining = HIGHLIGHT_DELAY_SECONDS - elapsed
                print(f"[postmatch] waiting {remaining:.0f}s before searching for highlights ({match['home_team']} vs {match['away_team']})")
                continue

            # Give up after 30 minutes
            if elapsed > HIGHLIGHT_RETRY_WINDOW:
                print(f"[postmatch] giving up on highlight video after 30 min ({match['home_team']} vs {match['away_team']})")
                update_match_state(str(match['id']), highlight_sent=True)
                continue

            home_fa = fa(match['home_team'], TEAM_FA)
            away_fa = fa(match['away_team'], TEAM_FA)
            score_str = f"{match['home_score']} - {match['away_score']}"

            # Try varzesh3.com FIRST (Iranian source, Persian highlights)
            video_url = None
            video_source = None
            video_page_url = None

            try:
                v3_url, v3_page, v3_title = fetch_varzesh3_highlight(
                    match['home_team'], match['away_team'],
                )
                if v3_url:
                    video_url = v3_url
                    video_page_url = v3_page
                    video_source = 'ورزش سه'
            except Exception as e:
                print(f"[postmatch] varzesh3 failed: {e}")

            # Fallback: try Reddit if varzesh3 didn't have it
            if not video_url:
                try:
                    reddit_url, reddit_title = fetch_reddit_highlight_video(
                        match['home_team'], match['away_team'],
                    )
                    if reddit_url:
                        video_url = reddit_url
                        video_source = 'Reddit r/soccer'
                except Exception as e:
                    print(f"[postmatch] reddit failed: {e}")

            # Send the video if we found one
            if video_url:
                source_line = f"📎 منبع: {video_source}"
                if video_page_url and video_source == 'ورزش سه':
                    source_line = f"📎 منبع: [ورزش سه]({video_page_url})"

                caption = (
                    f"🎞️ *هایلایت کامل بازی*\n"
                    f"{get_flag(match['home_team'])} {home_fa} {score_str} {away_fa} {get_flag(match['away_team'])}\n"
                    f"{source_line}"
                )
                if send_video(video_url, caption=caption):
                    update_match_state(str(match['id']), highlight_sent=True)
                    print(f"Highlight video sent for {match['home_team']} vs {match['away_team']} via {video_source}")
                else:
                    print(f"[postmatch] send_video failed, will retry next cron run")
            else:
                print(f"[postmatch] no highlight found yet ({elapsed:.0f}s elapsed), will retry next cron run")

        # Remove from active matches once everything is done
        if state.get('postmatch_sent') and state.get('highlight_sent'):
            remove_active_match(str(match['id']))


if __name__ == '__main__':
    mid = sys.argv[1] if len(sys.argv) > 1 else None
    main(match_id=mid)
