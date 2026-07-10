#!/usr/bin/env python3
"""Sends a final-result report the first time a match is seen as ended."""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from lib.api_client import FootballAPIClient
from lib.formatter import PersianFormatter
from lib.telegram_sender import send_message
from lib.state_manager import remove_active_match, update_match_state, get_match_state


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

        send_message(fmt.format_postmatch({
            'home_team': match['home_team'], 'away_team': match['away_team'],
            'home_score': match['home_score'], 'away_score': match['away_score'],
            'goals': match['goals'],
        }))

        update_match_state(str(match['id']), postmatch_sent=True)
        remove_active_match(str(match['id']))

        print(f"Postmatch report sent for {match['home_team']} vs {match['away_team']}")


if __name__ == '__main__':
    mid = sys.argv[1] if len(sys.argv) > 1 else None
    main(match_id=mid)
