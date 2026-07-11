#!/usr/bin/env python3
"""Refreshes the fixture list from ESPN and tracks which matches are live.

BUG FIX (was the root cause of live reports never being posted to the
channel): the previous version loaded `state` at the start, called
`add_active_match()` inside the loop (which does its own load/modify/
save cycle), and then called `save(state)` at the end with the ORIGINAL
stale copy — overwriting the active_matches list back to empty. As a
result, main_monitor's `for match_id in active_matches:` always
iterated over an empty list and live_update / event_monitor /
penalty_monitor / delay_alert were never called for live matches.

Fix: don't keep a local `state` copy across the loop. Use the
state_manager helpers (add_active_match / remove_active_match) which
each do their own atomic load-modify-save, and update the
last_scheduler_run timestamp via a fresh load() right before saving
it, so we never clobber concurrent writes from those helpers.
"""
import sys
import os
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from datetime import datetime, timezone
from lib.api_client import FootballAPIClient
from lib.state_manager import load, save, add_active_match, remove_active_match


def main():
    client = FootballAPIClient()
    now = datetime.now(timezone.utc)

    all_fixtures = client.get_all_fixtures()

    results = {
        'timestamp': now.isoformat(),
        'total_matches': len(all_fixtures),
        'live': [], 'prematch': [], 'postmatch': [],
    }

    # Track the set of match IDs ESPN currently reports as live so we
    # can both add newly-live matches and remove any that are no longer
    # live (e.g. they just ended and main_monitor's postmatch step
    # already handled them, or ESPN flipped them to post between runs).
    current_live_ids = set()

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
            current_live_ids.add(str(match['id']))
            add_active_match(match['id'])
        elif match['status_state'] == 'pre':
            results['prematch'].append(match_info)
        elif match['status_state'] == 'post':
            results['postmatch'].append(match_info)

    # Clean up active_matches: remove any IDs that are no longer live.
    # This prevents active_matches from growing forever as the tournament
    # progresses (postmatch.py already calls remove_active_match when it
    # sends the final report, but this is a safety net for cases where
    # ESPN reports a match as 'post' without us ever noticing it ended).
    state = load()
    stale = [mid for mid in state.get('active_matches', []) if str(mid) not in current_live_ids]
    for mid in stale:
        remove_active_match(mid)

    # Reload state (add_active_match / remove_active_match may have
    # modified it since we last loaded) and only then update our
    # last_scheduler_run timestamp. This is the key fix - we must NOT
    # save a stale copy of state.
    state = load()
    state['last_scheduler_run'] = now.isoformat()
    save(state)

    print(json.dumps(results, ensure_ascii=False, indent=2))
    return results


if __name__ == '__main__':
    main()
