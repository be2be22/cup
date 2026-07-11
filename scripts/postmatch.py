#!/usr/bin/env python3
"""Sends a final-result report the first time a match is seen as ended.

Also:
  - Closes the Live Thread (edits the live-scoreboard message to show
    'بازی پایان یافت' instead of 'بازی زنده')
  - Searches Reddit r/soccer for a full match highlights clip and
    sends it to the channel via sendVideo
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from lib.api_client import FootballAPIClient
from lib.formatter import PersianFormatter
from lib.telegram_sender import send_message, send_video
from lib.state_manager import remove_active_match, update_match_state, get_match_state
from lib.formatter import fa, TEAM_FA, PLAYER_FA, get_flag, SEP
from lib.live_thread import close_live_thread
from lib.reddit_video import fetch_reddit_highlight_video


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
        if state.get('postmatch_sent'):
            continue

        # 1. Send the final match report
        send_message(fmt.format_postmatch({
            'home_team': match['home_team'], 'away_team': match['away_team'],
            'home_score': match['home_score'], 'away_score': match['away_score'],
            'goals': match['goals'],
        }))

        # 2. Close the Live Thread
        try:
            close_live_thread(match)
        except Exception as e:
            print(f"[postmatch] close_live_thread failed: {e}")

        # 3. Search Reddit for full match highlights and send the video
        try:
            highlight_url, highlight_title = fetch_reddit_highlight_video(
                match['home_team'], match['away_team'],
            )
            if highlight_url:
                home_fa = fa(match['home_team'], TEAM_FA)
                away_fa = fa(match['away_team'], TEAM_FA)
                caption = (
                    f"🎞️ *هایلایت کامل بازی*\n"
                    f"{get_flag(match['home_team'])} {home_fa} {match['home_score']} - "
                    f"{match['away_score']} {away_fa} {get_flag(match['away_team'])}\n"
                    f"📎 منبع: Reddit r/soccer"
                )
                send_video(highlight_url, caption=caption)
                print(f"Highlight video sent for {match['home_team']} vs {match['away_team']}")
        except Exception as e:
            print(f"[postmatch] highlight video failed: {e}")

        update_match_state(str(match['id']), postmatch_sent=True)
        remove_active_match(str(match['id']))

        print(f"Postmatch report sent for {match['home_team']} vs {match['away_team']}")


if __name__ == '__main__':
    mid = sys.argv[1] if len(sys.argv) > 1 else None
    main(match_id=mid)
