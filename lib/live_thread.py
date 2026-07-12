"""
Live Thread - a single editable message per live match that shows the
current score, clock, goals, and a brief status. Instead of sending
a NEW message every minute (which clutters the channel), we edit the
same message in place so users see a continuously-updating 'live
scoreboard' at the top of the channel.

How it works:
  1. When a match goes live, we send an initial 'live thread' message
     and store its message_id in state.json under 'live_thread_msg_id'.
  2. On each subsequent cron run, we edit that message with the updated
     score/clock/events.
  3. We only edit every ~2-3 minutes (not every minute) to avoid
     hitting Telegram's rate limits (max ~30 edits per minute per bot).
  4. When the match ends, we send a final 'match over' edit and clear
     the live_thread_msg_id.

The Live Thread is IN ADDITION TO the regular live commentary - the
commentary messages still go out every minute with AI narration, but
the Live Thread stays pinned at the top as a quick-glance scoreboard.
"""
from lib.api_client import FootballAPIClient
from lib.formatter import PersianFormatter, fa, TEAM_FA, PLAYER_FA, get_flag, SEP, to_jalali
from lib.state_manager import get_match_state, update_match_state


# Minimum seconds between Live Thread edits (to avoid Telegram rate limits)
MIN_EDIT_INTERVAL = 120  # 2 minutes


def _build_live_thread_text(match):
    """Build the Live Thread message text for a match."""
    home = match['home_team']
    away = match['away_team']
    home_fa = fa(home, TEAM_FA)
    away_fa = fa(away, TEAM_FA)
    home_flag = get_flag(home)
    away_flag = get_flag(away)
    score = f"{match['home_score']} - {match['away_score']}"
    clock = match.get('clock', f"{match['minute']}'")
    status = match.get('status', '')

    # Status label in Persian
    status_map = {
        'STATUS_FIRST_HALF': f'نیمه اول',
        'STATUS_SECOND_HALF': f'نیمه دوم',
        'STATUS_HALFTIME': 'استراحت نیمه',
        'STATUS_OVERTIME': 'وقت اضافه',
        'STATUS_END_PERIOD': 'پایان وقت قانونی',
        'STATUS_PENALTY_SHOOTOUT': 'ضربات پنالتی',
    }
    status_label = status_map.get(status, '')

    header = (
        f"🔴 *بازی زنده*\n{SEP}\n"
        f"{home_flag} *{home_fa}*  {score}  *{away_fa}* {away_flag}\n"
        f"⏱️ {clock}"
    )
    if status_label:
        header += f" | {status_label}"
    header += f"\n{SEP}"

    # Goals
    goals = match.get('goals', [])
    if goals:
        header += "\n⚽ *گل‌ها:*\n"
        for g in goals:
            team_flag = get_flag(g['team'])
            player_fa = fa(g['player'], PLAYER_FA)
            team_fa_name = fa(g['team'], TEAM_FA)
            header += f"  {team_flag} {team_fa_name}: {player_fa} ({g['minute']})\n"
        header += SEP

    # Cards
    cards = match.get('cards', [])
    if cards:
        header += "\n🟡🔴 *کارت‌ها:*\n"
        for c in cards:
            emoji = '🟡' if 'زرد' in c['detail'] else '🔴'
            player_fa = fa(c['player'], PLAYER_FA)
            team_fa_name = fa(c['team'], TEAM_FA)
            header += f"  {emoji} {team_fa_name}: {player_fa} ({c['minute']})\n"
        header += SEP

    header += "\n📡 این پیام هر ۲ دقیقه آپدیت می‌شه."
    return header


def update_live_thread(match):
    """Create or update the Live Thread message for a match.

    Called by main_monitor.py on each cron run for each live match.
    Returns True if the thread was created or updated, False otherwise.
    """
    match_id = str(match['id'])
    state = get_match_state(match_id)

    msg_id = state.get('live_thread_msg_id')
    last_edit = state.get('live_thread_last_edit', 0)

    import time
    now = time.time()

    text = _build_live_thread_text(match)

    if not msg_id:
        # Create a new live thread message
        result = _send_and_get_id(text)
        if result:
            update_match_state(match_id,
                live_thread_msg_id=result,
                live_thread_last_edit=now,
            )
            # Pin the new Live Thread message at the top of the channel
            # so users always see the current score. Silent pin (no
            # notification) to avoid spamming members.
            try:
                from lib.telegram_sender import pin_chat_message
                pin_chat_message(result, disable_notification=True)
                print(f"[live_thread] pinned message {result} for match {match_id}")
            except Exception as e:
                print(f"[live_thread] pin failed: {e}")
            return True
        return False

    # Edit the existing message, but only if enough time has passed
    if now - last_edit < MIN_EDIT_INTERVAL:
        return False

    edit_result = _edit_channel_post(msg_id, text)
    if edit_result:
        update_match_state(match_id, live_thread_last_edit=now)
        return True
    elif edit_result is False:
        # editMessageText returned ok=false. This could mean:
        # 1. The message was deleted by the user
        # 2. The message content is identical (no change needed) - Telegram returns
        #    'message is not modified' error
        # 3. A temporary Telegram API issue
        #
        # For case 2 (identical content), we should NOT create a new message.
        # For case 1 (deleted), we SHOULD create a new one.
        # For case 3 (temporary), we should retry next time.
        #
        # We check the error: if it's 'message is not modified', just update
        # the timestamp and return (no new message needed).
        # If it's 'message to edit not found', the message was deleted - create
        # a new one.
        # Otherwise, don't create a new message (avoid spam).
        from lib.telegram_sender import _call, _default_channel_id
        # Re-attempt to detect the specific error
        channel_id = _default_channel_id()
        check = _call("editMessageText", {
            "chat_id": channel_id,
            "message_id": msg_id,
            "text": text + " ",  # add a space to force a change
            "parse_mode": "Markdown",
            "disable_web_page_preview": True,
        })
        if check and check.get("ok"):
            # The second attempt with a forced change worked - message exists.
            # Update timestamp so we don't retry too soon.
            update_match_state(match_id, live_thread_last_edit=now)
            return True
        elif check and "not modified" in str(check.get("description", "")).lower():
            # Content was identical - just update timestamp
            update_match_state(match_id, live_thread_last_edit=now)
            return True
        elif check and "not found" in str(check.get("description", "")).lower():
            # Message was deleted - create a new one
            print(f"[live_thread] message {msg_id} was deleted, creating new one")
            result = _send_and_get_id(text)
            if result:
                update_match_state(match_id,
                    live_thread_msg_id=result,
                    live_thread_last_edit=now,
                )
                try:
                    from lib.telegram_sender import pin_chat_message
                    pin_chat_message(result, disable_notification=True)
                except Exception as e:
                    print(f"[live_thread] re-pin failed: {e}")
                return True
        else:
            # Unknown error - don't create a new message, just update timestamp
            # to avoid spamming. We'll retry on the next cron run.
            print(f"[live_thread] edit failed with unknown error, skipping: {check}")
            update_match_state(match_id, live_thread_last_edit=now)
    return False


def _send_and_get_id(text):
    """Send a message to the channel and return its message_id."""
    from lib.telegram_sender import _call, _default_channel_id
    channel_id = _default_channel_id()
    result = _call("sendMessage", {
        "chat_id": channel_id,
        "text": text,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True,
    })
    if result and result.get("ok"):
        return result["result"]["message_id"]
    return None


def _edit_channel_post(message_id, text):
    """Edit a channel post. Uses editMessageText with the channel id."""
    from lib.telegram_sender import _call, _default_channel_id
    channel_id = _default_channel_id()
    result = _call("editMessageText", {
        "chat_id": channel_id,
        "message_id": message_id,
        "text": text,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True,
    })
    return bool(result and result.get("ok"))


def close_live_thread(match, final_text=None):
    """Mark the live thread as closed (match ended). Sends a final edit."""
    match_id = str(match['id'])
    state = get_match_state(match_id)
    msg_id = state.get('live_thread_msg_id')
    if not msg_id:
        return

    if final_text is None:
        final_text = _build_live_thread_text(match)
        final_text = final_text.replace("🔴 *بازی زنده*", "✅ *بازی پایان یافت*")
        final_text = final_text.replace(
            "📡 این پیام هر ۲ دقیقه آپدیت می‌شه.",
            "🏁 این بازی به پایان رسید."
        )

    _edit_channel_post(msg_id, final_text)
    # Clear the live_thread_msg_id so we don't try to edit it again
    update_match_state(match_id, live_thread_msg_id=None, live_thread_last_edit=0)
