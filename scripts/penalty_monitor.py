#!/usr/bin/env python3
"""
Penalty shootout monitor. Only does anything once a match's ESPN status
is STATUS_PENALTY_SHOOTOUT.

Note: ESPN's public scoreboard marks each penalty kick's `scoringPlay`
as true/false but does not reliably distinguish "saved" from "missed
wide", so we report those together as "not scored" - still useful, just
slightly less detailed than a paid football-data API would give you.
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

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
        if match['status'] != 'STATUS_PENALTY_SHOOTOUT':
            continue

        penalties = match['penalties']
        state = get_match_state(str(match['id']))
        last_seen = state.get('last_penalty_count', 0)

        if len(penalties) <= last_seen:
            continue

        home_team, away_team = match['home_team'], match['away_team']
        home_pen = away_pen = 0

        for i, p in enumerate(penalties):
            if p['team'] == home_team and p['scored']:
                home_pen += 1
            elif p['team'] == away_team and p['scored']:
                away_pen += 1

            if i < last_seen:
                continue

            send_message(fmt.format_penalty({
                'team': p['team'], 'player': p['player'],
                'result': 'scored' if p['scored'] else 'missed',
                'penalty_num': i + 1,
                'home_penalty': home_pen, 'away_penalty': away_pen,
            }))

        update_match_state(str(match['id']), last_penalty_count=len(penalties))

        # A shootout typically ends once one side has an unbeatable lead
        # with equal (or fewer) kicks remaining for the other side, or
        # after sudden death. We use a simple heuristic: 3+ goal gap, or
        # 10+ total kicks taken, and only announce once.
        if not state.get('penalty_end_sent') and (
            abs(home_pen - away_pen) >= 3 or len(penalties) >= 10
        ):
            send_message(fmt.format_penalty_end({
                'home_team': home_team, 'away_team': away_team,
                'home_penalty': home_pen, 'away_penalty': away_pen,
            }))
            update_match_state(str(match['id']), penalty_end_sent=True)

    print("Penalty check completed")


if __name__ == '__main__':
    mid = sys.argv[1] if len(sys.argv) > 1 else None
    main(match_id=mid)
