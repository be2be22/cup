#!/usr/bin/env python3
"""Refreshes the fixture list from ESPN and tracks which matches are live."""
import sys
import os
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from datetime import datetime, timezone
from lib.api_client import FootballAPIClient
from lib.state_manager import load, save, add_active_match


def main():
    client = FootballAPIClient()
    state = load()
    now = datetime.now(timezone.utc)

    all_fixtures = client.get_all_fixtures()

    results = {
        'timestamp': now.isoformat(),
        'total_matches': len(all_fixtures),
        'live': [], 'prematch': [], 'postmatch': [],
    }

    for event in all_fixtures:
        match = client.parse_event(event)
        if not match['home_team']:
            continue

        match_info = {
            'id': match['id'], 'home': match['home_team'], 'away': match['away_team'],
            'status': match['status_state'], 'clock': match.get('clock', ''),
        }

        if match['status_state'] == 'in':
            results['live'].append(match_info)
            add_active_match(match['id'])
        elif match['status_state'] == 'pre':
            results['prematch'].append(match_info)
        elif match['status_state'] == 'post':
            results['postmatch'].append(match_info)

    state['last_scheduler_run'] = now.isoformat()
    save(state)

    print(json.dumps(results, ensure_ascii=False, indent=2))
    return results


if __name__ == '__main__':
    main()
