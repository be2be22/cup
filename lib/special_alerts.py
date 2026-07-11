"""
Special alerts for noteworthy match events:

1. Hat-trick alert 🎩
   When a player scores their 3rd goal in a match, send a special
   'HAT-TRICK!' message instead of (or in addition to) the regular
   goal notification.

2. Comeback alert 🔄
   When a team that was trailing by 2+ goals comes back to equalize
   or take the lead, send a special 'بازگشت حماسی!' message.

3. Star substitution alert 👤
   When a well-known star player (see lib/star_players.py) is
   substituted, send a special alert noting which star left the
   pitch and who replaced them.

All alerts are tracked in state.json (under 'alerts_sent' list) so
we don't re-send them on subsequent cron runs.
"""
import json

from lib.formatter import fa, TEAM_FA, PLAYER_FA, get_flag, SEP
from lib.star_players import is_star_player
from lib.telegram_sender import send_message
from lib.state_manager import get_match_state, update_match_state


def _alert_key(alert_type, **kwargs):
    """Build a unique key for an alert so we can track it as 'sent'."""
    parts = [alert_type]
    for k, v in sorted(kwargs.items()):
        parts.append(f"{k}={v}")
    return "|".join(parts)


def _is_alert_sent(match_id, alert_key):
    """Check if an alert has already been sent for this match."""
    state = get_match_state(str(match_id))
    sent = state.get('alerts_sent', []) or []
    return alert_key in sent


def _mark_alert_sent(match_id, alert_key):
    """Mark an alert as sent so we don't re-send it."""
    state = get_match_state(str(match_id))
    sent = state.get('alerts_sent', []) or []
    if alert_key not in sent:
        sent.append(alert_key)
    # Keep the list bounded
    update_match_state(str(match_id), alerts_sent=sent[-50:])


# ============================================================
# 1. HAT-TRICK ALERT
# ============================================================
def check_hat_trick(match, scorer_name, scorer_team):
    """Check if the scorer just completed a hat-trick (3 goals).
    If so, send a special alert. Returns True if alert was sent."""
    # Count how many goals this player has scored in the match
    goals_by_player = [
        g for g in match.get('goals', [])
        if g.get('player') == scorer_name and g.get('team') == scorer_team
    ]
    count = len(goals_by_player)
    if count < 3:
        return False

    alert_key = _alert_key('hat_trick', player=scorer_name, match=match['id'])
    if _is_alert_sent(match['id'], alert_key):
        return False

    player_fa = fa(scorer_name, PLAYER_FA)
    team_fa = fa(scorer_team, TEAM_FA)
    # Determine hat-trick type
    if count >= 5:
        title = f"🤯 *{count} گله! فوق‌العاده!*"
    elif count == 4:
        title = f"🔥 *پوکر! ۴ گل!*"
    else:
        title = f"🎩 *هت‌تریک!*"

    msg = (
        f"\n{title}\n{SEP}\n"
        f"⚽ {get_flag(scorer_team)} *{player_fa}* از تیم *{team_fa}* "
        f"تو این بازی {count} گل زد!\n"
        f"🎯 دقایق گل‌ها: {', '.join(g.get('minute','?') for g in goals_by_player)}\n"
        f"📊 {fa(match['home_team'], TEAM_FA)} {match['home_score']} - "
        f"{match['away_score']} {fa(match['away_team'], TEAM_FA)}\n{SEP}"
    ).strip()

    if send_message(msg):
        _mark_alert_sent(match['id'], alert_key)
        return True
    return False


# ============================================================
# 2. COMEBACK ALERT
# ============================================================
def check_comeback(match, prev_state):
    """Check if a team just completed a comeback (was trailing by 2+,
    now equalized or took the lead). Returns True if alert was sent.

    `prev_state` is the match state dict from state.json, which should
    contain 'prev_score' (the score from the last cron run).
    """
    prev_score = prev_state.get('prev_score') or {}
    prev_home = prev_score.get('home', 0)
    prev_away = prev_score.get('away', 0)
    curr_home = match.get('home_score', 0)
    curr_away = match.get('away_score', 0)

    # Update prev_score in state for next run
    update_match_state(str(match['id']), prev_score={
        'home': curr_home, 'away': curr_away,
    })

    # Was there a 2+ goal deficit that's now closed?
    prev_diff = prev_home - prev_away  # positive = home was leading
    curr_diff = curr_home - curr_away

    # Home was trailing by 2+, now equalized or leading
    if prev_diff <= -2 and curr_diff >= 0:
        alert_key = _alert_key('comeback', team=match['home_team'], match=match['id'])
        if not _is_alert_sent(match['id'], alert_key):
            return _send_comeback_alert(match, match['home_team'], match['away_team'],
                                         prev_home, prev_away, curr_home, curr_away, alert_key)

    # Away was trailing by 2+, now equalized or leading
    if prev_diff >= 2 and curr_diff <= 0:
        alert_key = _alert_key('comeback', team=match['away_team'], match=match['id'])
        if not _is_alert_sent(match['id'], alert_key):
            return _send_comeback_alert(match, match['away_team'], match['home_team'],
                                         prev_away, prev_home, curr_away, curr_home, alert_key)

    return False


def _send_comeback_alert(match, comeback_team, opponent_team,
                          prev_team, prev_opp, curr_team, curr_opp, alert_key):
    """Send the comeback alert message."""
    team_fa = fa(comeback_team, TEAM_FA)
    opp_fa = fa(opponent_team, TEAM_FA)

    if curr_team > curr_opp:
        result_text = f"حالا پیش افتاده!"
        result_emoji = "🏆"
    elif curr_team == curr_opp:
        result_text = f"بازی رو مساوی کرد!"
        result_emoji = "🤝"
    else:
        return False  # shouldn't happen

    msg = (
        f"\n🔄 *بازگشت حماسی!*\n{SEP}\n"
        f"{get_flag(comeback_team)} *{team_fa}* که با {prev_opp}-{prev_team} عقب بود، "
        f"{result_emoji} {result_text}\n"
        f"📊 نتیجه‌ی فعلی: {fa(match['home_team'], TEAM_FA)} {match['home_score']} - "
        f"{match['away_score']} {fa(match['away_team'], TEAM_FA)}\n{SEP}"
    ).strip()

    if send_message(msg):
        _mark_alert_sent(match['id'], alert_key)
        return True
    return False


# ============================================================
# 3. STAR SUBSTITUTION ALERT
# ============================================================
def check_star_substitution(match, sub):
    """Check if a substitution involves a star player. If so, send a
    special alert. Returns True if alert was sent.

    `sub` is a dict with keys: team, out, in, minute.
    """
    out_player = sub.get('out', '')
    in_player = sub.get('in', '')

    is_star_out = is_star_player(out_player)
    is_star_in = is_star_player(in_player)

    if not is_star_out and not is_star_in:
        return False

    alert_key = _alert_key('star_sub', out=out_player, in_player=in_player, minute=sub.get('minute',''), match=match['id'])
    if _is_alert_sent(match['id'], alert_key):
        return False

    team = sub.get('team', '')
    team_fa = fa(team, TEAM_FA)
    minute = sub.get('minute', '')

    out_fa = fa(out_player, PLAYER_FA)
    in_fa = fa(in_player, PLAYER_FA)

    if is_star_out and is_star_in:
        msg = (
            f"\n👤 *تعویض ستاره‌ای!*\n{SEP}\n"
            f"⏱️ دقیقه {minute} | {get_flag(team)} {team_fa}\n"
            f"🔴 خارج شد: *{out_fa}*\n"
            f"🟢 وارد شد: *{in_fa}*\n{SEP}"
        ).strip()
    elif is_star_out:
        msg = (
            f"\n👤 *تعویض ستاره!*\n{SEP}\n"
            f"⏱️ دقیقه {minute} | {get_flag(team)} {team_fa}\n"
            f"🔴 *{out_fa}* از بازی خارج شد\n"
            f"🟢 جایگزین: {in_fa}\n{SEP}"
        ).strip()
    else:  # is_star_in
        msg = (
            f"\n✨ *ورود ستاره!*\n{SEP}\n"
            f"⏱️ دقیقه {minute} | {get_flag(team)} {team_fa}\n"
            f"🟢 *{in_fa}* وارد بازی شد!\n"
            f"🔴 جایگزین شده: {out_fa}\n{SEP}"
        ).strip()

    if send_message(msg):
        _mark_alert_sent(match['id'], alert_key)
        return True
    return False
