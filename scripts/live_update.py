#!/usr/bin/env python3
"""Sends a periodic live score/clock update for matches in progress.

Enhanced: in addition to the basic score/clock format, also pulls
ESPN's English play-by-play commentary feed and asks the AI to write
a short Persian reporter-style narration of the last few minutes.
Every 5 minutes (or when the minute crosses a 5-minute boundary) we
also send a 'pulse check' with boxscore stats (possession, shots,
corners, fouls) plus a narrative summary of the match flow.

CLOCK HANDLING (fixes stoppage-time bug):
  We track the last reported clock as a STRING (e.g. "45'+5'", "90'+3'",
  "105'+2'") instead of a numeric minute. This correctly handles:
    - Stoppage time: 45' -> 45'+1' -> 45'+2' -> ... each gets its own report
    - Half transitions: 45'+5' (halftime) -> 46' (second half) - the clock
      string changes so a new report is sent
    - End of regulation: 90' -> 90'+1' -> ... -> extra time 91' (which is
      actually minute 106 in absolute terms, but ESPN reports it as 91'
      during STATUS_OVERTIME)
    - Extra time: 91' -> 105' -> 105'+1' -> 120' -> penalties

HALFTIME / END-OF-PERIOD HANDLING:
  - STATUS_HALFTIME: send ONE 'end of first half' summary, then go quiet
    until STATUS_SECOND_HALF starts.
  - STATUS_END_PERIOD (at 90'): send ONE 'end of regulation' summary,
    then go quiet until STATUS_OVERTIME starts.
  - In both cases we track a flag in state.json so we only send once.

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
from lib.live_commentary import (
    generate_live_commentary,
    generate_match_pulse,
    generate_halftime_summary,
)


def build_events_text(match):
    lines = []
    for g in match.get('goals', []):
        lines.append(f"⚽ گل: {fa(g['team'], TEAM_FA)} - {fa(g['player'], PLAYER_FA)} ({g['minute']})")
    for c in match.get('cards', []):
        emoji = '🟡' if 'زرد' in c['detail'] else '🔴'
        lines.append(f"{emoji} {c['detail']}: {fa(c['team'], TEAM_FA)} - {fa(c['player'], PLAYER_FA)} ({c['minute']})")
    return '\n'.join(lines) if lines else None


def _extract_minute_int(clock_str):
    """Extract the base minute (without stoppage) from a clock string.
    e.g. "45'+5'" -> 45, "90'+3'" -> 90, "46'" -> 46, "105'+2'" -> 105.
    Used for the 5-minute pulse check."""
    try:
        base = clock_str.split("'")[0].split("+")[0]
        return int(base)
    except Exception:
        return 0


def _is_pulse_minute(clock_str):
    """Return True every 5 minutes (5, 10, 15, ..., 40, 50, 55, ..., 85)
    so we send a richer 'pulse check' instead of the regular update.
    Skip 45 (halftime) and 90 (end of regulation) - those are handled
    separately by STATUS_HALFTIME / STATUS_END_PERIOD."""
    minute = _extract_minute_int(clock_str)
    if minute <= 0:
        return False
    if minute in (45, 90):
        return False  # handled by end-of-period logic
    return minute % 5 == 0


def _is_halftime(match):
    return match.get('status') == 'STATUS_HALFTIME'


def _is_end_of_regulation(match):
    """Return True if ESPN reports STATUS_END_PERIOD after the second half
    (i.e. end of 90 minutes, before extra time or penalties)."""
    return match.get('status') == 'STATUS_END_PERIOD'


def _is_overtime(match):
    """Return True if the match is in extra time (30 min overtime)."""
    return match.get('status') == 'STATUS_OVERTIME'


def _is_second_half_start(match, state):
    """Return True if we just transitioned from halftime to second half."""
    if match.get('status') != 'STATUS_SECOND_HALF':
        return False
    return state.get('halftime_summary_sent', False)


def _is_overtime_start(match, state):
    """Return True if we just transitioned from end-of-regulation to overtime."""
    if not _is_overtime(match):
        return False
    return state.get('end_regulation_sent', False)


def _send_halftime_summary(match, events_text, score_str):
    """Send a single 'end of first half' summary message."""
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


def _send_end_regulation_summary(match, events_text, score_str):
    """Send a summary when the 90 minutes of regulation end and we're
    waiting for extra time / penalties to start."""
    try:
        summary = generate_halftime_summary(
            match['id'], match['home_team'], match['away_team'],
            score_str=score_str,
        )
    except Exception as e:
        print(f"[live_update] end-regulation summary AI call failed: {e}")
        summary = None

    fmt = PersianFormatter()
    header = fmt.format_live_update({
        'home_team': match['home_team'], 'away_team': match['away_team'],
        'home_score': match['home_score'], 'away_score': match['away_score'],
        'clock': match.get('clock', "90'"),
        'status': match['status'],
    }, events_text)

    if summary:
        msg = f"{header}\n\n⏸️ *پایان وقت قانونی — خلاصه‌ی بازی:*\n{summary}\n\n⏳ منتظر شروع وقت اضافه..."
    else:
        msg = f"{header}\n\n⏳ پایان وقت قانونی — منتظر شروع وقت اضافه..."
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
        # Track last clock as a STRING so stoppage time is handled correctly.
        # e.g. last_clock_str="45'+5'" -> next clock "46'" triggers a new report.
        last_clock_str = state.get('last_clock_str', '')
        last_pulse_clock = state.get('last_pulse_clock', '')
        halftime_summary_sent = state.get('halftime_summary_sent', False)
        end_regulation_sent = state.get('end_regulation_sent', False)

        current_clock = match.get('clock', f"{match['minute']}'")
        events_text = build_events_text(match)
        score_str = f"{match['home_score']}-{match['away_score']}"

        # ============================================================
        # HALFTIME HANDLING - go quiet, only send one summary
        # ============================================================
        if _is_halftime(match):
            if halftime_summary_sent:
                # Already sent - stay quiet, just update the clock tracker
                if current_clock != last_clock_str:
                    update_match_state(str(match['id']), last_clock_str=current_clock)
                continue
            if _send_halftime_summary(match, events_text, score_str):
                update_match_state(
                    str(match['id']),
                    last_clock_str=current_clock,
                    halftime_summary_sent=True,
                )
            continue

        # ============================================================
        # END OF REGULATION (90') - send one summary, wait for overtime
        # ============================================================
        if _is_end_of_regulation(match):
            if end_regulation_sent:
                if current_clock != last_clock_str:
                    update_match_state(str(match['id']), last_clock_str=current_clock)
                continue
            if _send_end_regulation_summary(match, events_text, score_str):
                update_match_state(
                    str(match['id']),
                    last_clock_str=current_clock,
                    end_regulation_sent=True,
                )
            continue

        # ============================================================
        # SECOND HALF START - clear halftime flag, announce
        # ============================================================
        if _is_second_half_start(match, state) and halftime_summary_sent:
            header = fmt.format_live_update({
                'home_team': match['home_team'], 'away_team': match['away_team'],
                'home_score': match['home_score'], 'away_score': match['away_score'],
                'clock': current_clock,
                'status': match['status'],
            }, events_text)
            msg = f"{header}\n\n▶️ *نیمه‌ی دوم شروع شد!*"
            if send_message(msg):
                update_match_state(
                    str(match['id']),
                    last_clock_str=current_clock,
                    halftime_summary_sent=False,
                )
            continue

        # ============================================================
        # OVERTIME START - clear end_regulation flag, announce
        # ============================================================
        if _is_overtime_start(match, state) and end_regulation_sent:
            header = fmt.format_live_update({
                'home_team': match['home_team'], 'away_team': match['away_team'],
                'home_score': match['home_score'], 'away_score': match['away_score'],
                'clock': current_clock,
                'status': match['status'],
            }, events_text)
            msg = f"{header}\n\n⚡ *وقت اضافه شروع شد!*"
            if send_message(msg):
                update_match_state(
                    str(match['id']),
                    last_clock_str=current_clock,
                    end_regulation_sent=False,
                )
            continue

        # ============================================================
        # NORMAL LIVE COMMENTARY (any period in progress)
        # Includes: first half, second half, stoppage time, overtime,
        # overtime stoppage time.
        # Skip if the clock string hasn't changed since last report.
        # ============================================================
        if current_clock == last_clock_str:
            continue

        # Decide which type of update to send this cycle:
        # 1. Pulse check (every 5 minutes) - richer, includes stats + narrative
        # 2. Regular live update with AI commentary
        # 3. Fallback: basic format if AI fails
        sent = False
        is_pulse = _is_pulse_minute(current_clock) and current_clock != last_pulse_clock

        if is_pulse:
            try:
                pulse = generate_match_pulse(
                    match['id'], match['home_team'], match['away_team'],
                    score_str=score_str, minute_str=current_clock,
                )
                if pulse:
                    header = fmt.format_live_update({
                        'home_team': match['home_team'], 'away_team': match['away_team'],
                        'home_score': match['home_score'], 'away_score': match['away_score'],
                        'clock': current_clock,
                        'status': match['status'],
                    }, events_text)
                    msg = f"{header}\n\n📡 *گزارش ۵ دقیقه‌ای:*\n{pulse}"
                    if send_message(msg):
                        sent = True
                        update_match_state(
                            str(match['id']),
                            last_clock_str=current_clock,
                            last_pulse_clock=current_clock,
                        )
            except Exception as e:
                print(f"[live_update] pulse failed: {e}")

        if not sent:
            try:
                commentary = generate_live_commentary(
                    match['id'], match['home_team'], match['away_team'],
                    score_str=score_str, minute_str=current_clock,
                )
                if commentary:
                    header = fmt.format_live_update({
                        'home_team': match['home_team'], 'away_team': match['away_team'],
                        'home_score': match['home_score'], 'away_score': match['away_score'],
                        'clock': current_clock,
                        'status': match['status'],
                    }, events_text)
                    msg = f"{header}\n\n🎙️ *گزارش لحظه‌ای:*\n{commentary}"
                    if send_message(msg):
                        sent = True
                        update_match_state(str(match['id']), last_clock_str=current_clock)
            except Exception as e:
                print(f"[live_update] commentary failed: {e}")

        if not sent:
            msg = fmt.format_live_update({
                'home_team': match['home_team'], 'away_team': match['away_team'],
                'home_score': match['home_score'], 'away_score': match['away_score'],
                'clock': current_clock,
                'status': match['status'],
            }, events_text)
            if send_message(msg):
                sent = True
                update_match_state(str(match['id']), last_clock_str=current_clock)

        if not sent:
            update_match_state(str(match['id']), last_clock_str=current_clock)


if __name__ == '__main__':
    mid = sys.argv[1] if len(sys.argv) > 1 else None
    main(match_id=mid)
