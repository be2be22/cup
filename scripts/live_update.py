#!/usr/bin/env python3
"""Sends a periodic live score/clock update for matches in progress."""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from lib.api_client import FootballAPIClient
from lib.formatter import PersianFormatter, fa, TEAM_FA, PLAYER_FA
from lib.telegram_sender import send_message
from lib.state_manager import get_match_state, update_match_state


def build_events_text(match):
    lines = []
    for g in match.get('goals', []):
        lines.append(f"⚽ گل: {fa(g['team'], TEAM_FA)} - {fa(g['player'], PLAYER_FA)} ({g['minute']})")
    for c in match.get('cards', []):
        emoji = '🟡' if 'زرد' in c['detail'] else '🔴'
        lines.append(f"{emoji} {c['detail']}: {fa(c['team'], TEAM_FA)} - {fa(c['player'], PLAYER_FA)} ({c['minute']})")
    return '\n'.join(lines) if lines else None


def main(match_id=None):
    client = FootballAPIClient()
    fmt = PersianFormatter()

    live = client.get_live_fixtures()
    if not live:
        return

    for event in live:
        match = client.parse_event(event)

        if match_id and str(match['id']) != str(match_id):
            continue
        if not match['home_team']:
            continue

        state = get_match_state(str(match['id']))
        last_clock = state.get('last_clock', 0)
        if match['minute'] <= last_clock:
            continue

        events_text = build_events_text(match)
        msg = fmt.format_live_update({
            'home_team': match['home_team'], 'away_team': match['away_team'],
            'home_score': match['home_score'], 'away_score': match['away_score'],
            'clock': match.get('clock', f"{match['minute']}'"),
            'status': match['status'],
        }, events_text)

        send_message(msg)
        update_match_state(str(match['id']), last_clock=match['minute'])


if __name__ == '__main__':
    mid = sys.argv[1] if len(sys.argv) > 1 else None
    main(match_id=mid)
