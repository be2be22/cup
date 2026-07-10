#!/usr/bin/env python3
"""Checks live matches for new goals and cards since the last run."""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from datetime import datetime, timezone
from lib.api_client import FootballAPIClient
from lib.formatter import PersianFormatter
from lib.telegram_sender import send_message
from lib.state_manager import get_match_state, update_match_state


def main(match_id=None):
    client = FootballAPIClient()
    fmt = PersianFormatter()

    for event in client.get_live_fixtures():
        match = client.parse_event(event)

        if match_id and str(match['id']) != str(match_id):
            continue
        if not match['home_team']:
            continue

        state = get_match_state(str(match['id']))
        last_events = state.get('last_events', [])

        for g in match['goals']:
            event_key = f"goal_{g['player']}_{g['minute']}"
            if event_key not in last_events:
                send_message(fmt.format_goal({
                    'team': g['team'], 'player': g['player'], 'minute': g['minute'],
                    'home_score': match['home_score'], 'away_score': match['away_score'],
                    'home_team': match['home_team'], 'away_team': match['away_team'],
                }))
                last_events.append(event_key)

        for c in match['cards']:
            event_key = f"card_{c['player']}_{c['minute']}"
            if event_key not in last_events:
                send_message(fmt.format_card({
                    'team': c['team'], 'player': c['player'],
                    'minute': c['minute'], 'detail': c['detail'],
                }))
                last_events.append(event_key)

        # Keep the list bounded so state.json doesn't grow forever.
        update_match_state(str(match['id']), last_events=last_events[-100:])

    print(f"Event check completed at {datetime.now(timezone.utc).isoformat()}")


if __name__ == '__main__':
    mid = sys.argv[1] if len(sys.argv) > 1 else None
    main(match_id=mid)
