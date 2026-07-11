#!/usr/bin/env python3
"""Sends a periodic live score/clock update for matches in progress.

Enhanced: in addition to the basic score/clock format, also pulls
ESPN's English play-by-play commentary feed and asks the AI to write
a short Persian reporter-style narration of the last few minutes.
Every 5 minutes (or when the minute crosses a 5-minute boundary) we
also send a 'pulse check' with boxscore stats (possession, shots,
corners, fouls) plus a narrative summary of the match flow.

Falls back gracefully: if the AI is unreachable or slow, we still
post the basic score update so the channel never goes silent.
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from lib.api_client import FootballAPIClient
from lib.formatter import PersianFormatter, fa, TEAM_FA, PLAYER_FA
from lib.telegram_sender import send_message
from lib.state_manager import get_match_state, update_match_state
from lib.live_commentary import generate_live_commentary, generate_match_pulse


def build_events_text(match):
    lines = []
    for g in match.get('goals', []):
        lines.append(f"⚽ گل: {fa(g['team'], TEAM_FA)} - {fa(g['player'], PLAYER_FA)} ({g['minute']})")
    for c in match.get('cards', []):
        emoji = '🟡' if 'زرد' in c['detail'] else '🔴'
        lines.append(f"{emoji} {c['detail']}: {fa(c['team'], TEAM_FA)} - {fa(c['player'], PLAYER_FA)} ({c['minute']})")
    return '\n'.join(lines) if lines else None


def _is_pulse_minute(minute):
    """Return True every 5 minutes (at minute 5, 10, 15, ...) so we
    send a richer 'pulse check' instead of the regular update."""
    if minute <= 0:
        return False
    # Also send one at halftime (45) and right after (46).
    return minute % 5 == 0 or minute in (45, 46, 90, 91)


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
        last_commentary_seq = state.get('last_commentary_seq', 0)
        last_pulse_minute = state.get('last_pulse_minute', 0)

        # If the clock hasn't advanced, skip - nothing new to report.
        if match['minute'] <= last_clock:
            continue

        events_text = build_events_text(match)
        score_str = f"{match['home_score']}-{match['away_score']}"
        minute_str = f"{match['minute']}'"

        # Decide which type of update to send this cycle:
        # 1. Pulse check (every 5 minutes) - richer, includes stats + narrative
        # 2. Regular live update with AI commentary
        # 3. Fallback: basic format if AI fails
        sent = False
        is_pulse = _is_pulse_minute(match['minute']) and match['minute'] != last_pulse_minute

        if is_pulse:
            # Pulse check - richer update with stats
            try:
                pulse = generate_match_pulse(
                    match['id'], match['home_team'], match['away_team'],
                    score_str=score_str, minute_str=minute_str,
                )
                if pulse:
                    header = fmt.format_live_update({
                        'home_team': match['home_team'], 'away_team': match['away_team'],
                        'home_score': match['home_score'], 'away_score': match['away_score'],
                        'clock': match.get('clock', minute_str),
                        'status': match['status'],
                    }, events_text)
                    msg = f"{header}\n\n📡 *گزارش ۵ دقیقه‌ای:*\n{pulse}"
                    if send_message(msg):
                        sent = True
                        update_match_state(
                            str(match['id']),
                            last_clock=match['minute'],
                            last_pulse_minute=match['minute'],
                        )
            except Exception as e:
                print(f"[live_update] pulse failed: {e}")

        if not sent:
            # Regular update - try AI commentary first
            try:
                commentary = generate_live_commentary(
                    match['id'], match['home_team'], match['away_team'],
                    score_str=score_str, minute_str=minute_str,
                )
                if commentary:
                    header = fmt.format_live_update({
                        'home_team': match['home_team'], 'away_team': match['away_team'],
                        'home_score': match['home_score'], 'away_score': match['away_score'],
                        'clock': match.get('clock', minute_str),
                        'status': match['status'],
                    }, events_text)
                    msg = f"{header}\n\n🎙️ *گزارش لحظه‌ای:*\n{commentary}"
                    if send_message(msg):
                        sent = True
                        update_match_state(str(match['id']), last_clock=match['minute'])
            except Exception as e:
                print(f"[live_update] commentary failed: {e}")

        if not sent:
            # Fallback: basic format without AI commentary
            msg = fmt.format_live_update({
                'home_team': match['home_team'], 'away_team': match['away_team'],
                'home_score': match['home_score'], 'away_score': match['away_score'],
                'clock': match.get('clock', minute_str),
                'status': match['status'],
            }, events_text)
            if send_message(msg):
                sent = True
                update_match_state(str(match['id']), last_clock=match['minute'])

        # Always update last_clock so we don't re-send the same minute
        if not sent:
            update_match_state(str(match['id']), last_clock=match['minute'])


if __name__ == '__main__':
    mid = sys.argv[1] if len(sys.argv) > 1 else None
    main(match_id=mid)
