#!/usr/bin/env python3
"""
Sends a one-time pre-match message for each fixture ESPN reports as
'pre' (not yet started) that we haven't already announced.

Analysis text comes from, in order of preference:
  1. AI-generated analysis (lib/ai_analysis.py) if AI_API_BASE_URL /
     AI_API_KEY are configured.
  2. Static hand-written analysis (lib/analysis_data.py) if we happen to
     have canned notes for both teams.
  3. No analysis section at all - just the basic fixture info.
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from lib.api_client import FootballAPIClient
from lib.formatter import PersianFormatter
from lib.telegram_sender import send_message
from lib.state_manager import get_match_state, update_match_state
from lib.analysis_builder import build_analysis


def main(match_id=None):
    client = FootballAPIClient()
    fmt = PersianFormatter()

    for event in client.get_all_fixtures():
        match = client.parse_event(event)

        if match_id and str(match['id']) != str(match_id):
            continue
        if match['status_state'] != 'pre':
            continue

        state = get_match_state(str(match['id']))
        if state.get('prematch_sent'):
            continue

        # Use the actual stage name from ESPN instead of the previously-
        # hardcoded "مرحله گروهی". Same fix as in lib/bot_logic.py.
        stage = match.get('stage', '') or 'جام جهانی ۲۰۲۶'
        venue_parts = [p for p in [match.get('venue', ''), match.get('venue_city', '')] if p]
        venue = '، '.join(venue_parts)

        analysis = build_analysis(
            match['home_team'], match['away_team'],
            stage=stage, venue=venue, group='',
            event_id=match.get('id'),
        )

        msg = fmt.format_prematch({
            'home_team': match['home_team'],
            'away_team': match['away_team'],
            'time': match.get('date', ''),
            'venue': venue,
            'stage': stage,
        }, analysis)

        send_message(msg)
        update_match_state(str(match['id']), prematch_sent=True)
        print(f"Prematch sent for {match['home_team']} vs {match['away_team']}")


if __name__ == '__main__':
    mid = sys.argv[1] if len(sys.argv) > 1 else None
    main(match_id=mid)
