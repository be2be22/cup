#!/usr/bin/env python3
"""Sends a one-time alert if a match is suspended, postponed, or delayed."""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from lib.api_client import FootballAPIClient
from lib.formatter import PersianFormatter
from lib.telegram_sender import send_message
from lib.state_manager import get_match_state, update_match_state

REASONS_FA = {
    'suspended': 'توقف موقت بازی',
    'postponed': 'به تعویق افتادن بازی',
    'delayed': 'تاخیر در شروع بازی',
}


def main(match_id=None):
    client = FootballAPIClient()
    fmt = PersianFormatter()

    for event in client.get_all_fixtures():
        match = client.parse_event(event)

        if match_id and str(match['id']) != str(match_id):
            continue

        status = match['status'].lower()
        matched_reason = next((k for k in REASONS_FA if k in status), None)
        if not matched_reason:
            continue

        state = get_match_state(str(match['id']))
        if state.get('delay_alerted'):
            continue

        send_message(fmt.format_delay_alert({
            'home_team': match['home_team'], 'away_team': match['away_team'],
        }, REASONS_FA[matched_reason]))
        update_match_state(str(match['id']), delay_alerted=True)

        print(f"Delay alert sent for {match['home_team']} vs {match['away_team']}: {matched_reason}")


if __name__ == '__main__':
    mid = sys.argv[1] if len(sys.argv) > 1 else None
    main(match_id=mid)
