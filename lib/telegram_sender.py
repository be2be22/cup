"""
Sends messages to Telegram (channel posts + private bot replies) and
supports the small set of Bot API calls the interactive menu needs
(inline keyboards, editing messages, answering callback queries).

The bot token must be set as an environment variable named
TELEGRAM_BOT_TOKEN. On alwaysdata this is done from the site's
Environment tab in the control panel (Sites > your site > Environment),
not from a local .env file.
"""
import json
import os
import urllib.request
import urllib.error

CONFIG_PATH = os.path.join(os.path.dirname(__file__), '..', 'config.json')


def _default_channel_id():
    with open(CONFIG_PATH, encoding='utf-8') as f:
        return json.load(f)["telegram"]["channel_id"]


def _call(method, payload):
    """POST helper for any Telegram Bot API method. Returns the parsed
    JSON response, or None if the token is missing or the call fails."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    if not token:
        print(f"[telegram_sender] TELEGRAM_BOT_TOKEN is not set - {method} not sent.")
        return None

    data = json.dumps(payload).encode()
    try:
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{token}/{method}",
            data=data,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read().decode())
            if not result.get("ok", False):
                print(f"[telegram_sender] Telegram API error ({method}): {result}")
            return result
    except urllib.error.HTTPError as e:
        try:
            body = e.read().decode()
        except Exception:
            body = ""
        print(f"[telegram_sender] HTTP error on {method}: {e.code} {body}")
        return None
    except Exception as e:
        print(f"[telegram_sender] Failed to call {method}: {e}")
        return None


def send_message(text, channel_id=None, parse_mode="Markdown", reply_markup=None):
    """Send a message. Defaults to the configured channel (used by the
    cron scripts); pass channel_id=<chat_id> to reply to a specific user
    or group instead (used by the webhook bot menu)."""
    if channel_id is None:
        channel_id = _default_channel_id()

    payload = {
        "chat_id": channel_id,
        "text": text,
        "parse_mode": parse_mode,
        "disable_web_page_preview": True,
    }
    if reply_markup is not None:
        payload["reply_markup"] = reply_markup

    result = _call("sendMessage", payload)
    return bool(result and result.get("ok"))


def edit_message(chat_id, message_id, text, parse_mode="Markdown", reply_markup=None):
    payload = {
        "chat_id": chat_id,
        "message_id": message_id,
        "text": text,
        "parse_mode": parse_mode,
        "disable_web_page_preview": True,
    }
    if reply_markup is not None:
        payload["reply_markup"] = reply_markup
    result = _call("editMessageText", payload)
    return bool(result and result.get("ok"))


def answer_callback_query(callback_query_id, text=None, show_alert=False):
    """Stops the little loading spinner on the button the user tapped,
    and optionally shows a small toast/alert."""
    payload = {"callback_query_id": callback_query_id}
    if text:
        payload["text"] = text
        payload["show_alert"] = show_alert
    result = _call("answerCallbackQuery", payload)
    return bool(result and result.get("ok"))


def set_webhook(url, secret_token=None):
    payload = {"url": url, "allowed_updates": ["message", "callback_query"]}
    if secret_token:
        payload["secret_token"] = secret_token
    return _call("setWebhook", payload)


def delete_webhook():
    return _call("deleteWebhook", {})


def get_webhook_info():
    return _call("getWebhookInfo", {})
