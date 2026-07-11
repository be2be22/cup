#!/usr/bin/env python3
"""Sends a periodic live score/clock update for matches in progress.

Enhanced: in addition to the basic score/clock format, also pulls
ESPN's English play-by-play commentary feed and asks the AI to write
a short Persian reporter-style narration of the last few minutes.
Every 5 minutes (or when the minute crosses a 5-minute boundary) we
also send a 'pulse check' with boxscore stats (possession, shots,
corners, fouls) plus a narrative summary of the match flow.

HALFTIME HANDLING:
  When ESPN reports the match status as STATUS_HALFTIME, we send ONE
  'end of first half' summary message (using the AI to summarize the
  first half) and then go QUIET until the second half starts. We do
  NOT call the AI for live commentary during halftime, because the
  AI would hallucinate second-half events that haven't happened yet
  (ESPN's commentary feed doesn't update during the break).

  We track 'halftime_summary_sent' in state.json so we only send the
  summary once. When the second half starts (status changes from
  STATUS_HALFTIME to STATUS_SECOND_HALF), we clear the flag and
  resume normal live commentary.

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
from lib.live_commentary import generate_live_commentary, generate_match_pulse, generate_halftime_summary


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
    # 45 is halftime - handled separately, not as a pulse.
    # 46 is right after halftime - skip the pulse, just do normal commentary.
    return minute % 5 == 0 and minute != 45


def _is_halftime(match):
    """Return True if ESPN reports the match as currently in halftime."""
    return match.get('status') == 'STATUS_HALFTIME'


def _is_second_half_start(match, state):
    """Return True if we just transitioned from halftime to second half.
    Detected by: status is STATUS_SECOND_HALF AND we previously sent
    a halftime summary (so last_clock is around 45)."""
    if match.get('status') != 'STATUS_SECOND_HALF':
        return False
    # If we sent a halftime summary, the flag is set.
    if state.get('halftime_summary_sent'):
        return True
    return False


def _send_halftime_summary(match, events_text, score_str):
    """Send a single 'end of first half' summary message with AI-generated
    recap of the first half. Does NOT generate live commentary - just a
    summary of what happened so far."""
    try:
        summary = generate_halftime_summary(
            match['id'], match['home_team'], match['away_team'],
            score_str=score_str,
        )
    except Exception as e:
        print(f"[live_update] halftime summary AI call failed: {e}")
        summary = None

    fmt = PersianFormatter()
    header = fmt.format_live_update({
        'home_team': match['home_team'], 'away_team': match['away_team'],
        'home_score': match['home_score'], 'away_score': match['away_score'],
        'clock': match.get('clock', "45'"),
        'status': match['status'],
    }, events_text)

    if summary:
        msg = f"{header}\n\n⏸️ *خلاصه‌ی نیمه‌ی اول:*\n{summary}\n\n⏳ منتظر شروع نیمه‌ی دوم..."
    else:
        msg = f"{header}\n\n⏳ استراحت — منتظر شروع نیمه‌ی دوم..."
    return send_message(msg)


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
        last_pulse_minute = state.get('last_pulse_minute', 0)
        halftime_summary_sent = state.get('halftime_summary_sent', False)

        events_text = build_events_text(match)
        score_str = f"{match['home_score']}-{match['away_score']}"
        minute_str = f"{match['minute']}'"

        # ============================================================
        # HALFTIME HANDLING - go quiet, only send one summary
        # ============================================================
        if _is_halftime(match):
            if halftime_summary_sent:
                # Already sent the halftime summary - stay quiet.
                # Update last_clock to current so we don't flood when
                # second half starts.
                if match['minute'] > last_clock:
                    update_match_state(str(match['id']), last_clock=match['minute'])
                continue
            # Send the one-time halftime summary
            if _send_halftime_summary(match, events_text, score_str):
                update_match_state(
                    str(match['id']),
                    last_clock=match['minute'],
                    halftime_summary_sent=True,
                )
            continue

        # ============================================================
        # SECOND HALF START - clear the halftime flag and announce
        # ============================================================
        if _is_second_half_start(match, state) and halftime_summary_sent:
            # Send a "second half starting" message
            header = fmt.format_live_update({
                'home_team': match['home_team'], 'away_team': match['away_team'],
                'home_score': match['home_score'], 'away_score': match['away_score'],
                'clock': match.get('clock', minute_str),
                'status': match['status'],
            }, events_text)
            msg = f"{header}\n\n▶️ *نیمه‌ی دوم شروع شد!*"
            if send_message(msg):
                update_match_state(
                    str(match['id']),
                    last_clock=match['minute'],
                    halftime_summary_sent=False,  # clear the flag
                )
            continue

        # ============================================================
        # NORMAL LIVE COMMENTARY (first half or second half, not break)
        # ============================================================
        # If the clock hasn't advanced, skip - nothing new to report.
        if match['minute'] <= last_clock:
            continue

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
