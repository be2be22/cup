#!/usr/bin/env python3
"""
WSGI app that receives Telegram updates (button taps / messages) via a
webhook and answers them. This is the piece that makes the bot
*interactive* - the cron scripts in scripts/ only ever push messages
out, they never listen for anything coming back.

Deploy this as its OWN alwaysdata "Site" (Python / WSGI), separate from
the cron job, pointing its WSGI entry point at this file's
`application` callable. See README.md for the full alwaysdata setup
and how to register the webhook URL with Telegram
(scripts/set_webhook.py does that part).

Required environment variables (same alwaysdata Environment tab as the
cron site):
  TELEGRAM_BOT_TOKEN      same token the cron scripts use
  TELEGRAM_WEBHOOK_SECRET optional but recommended - random string,
                           also passed to scripts/set_webhook.py, used
                           to reject requests that don't come from
                           Telegram
"""
import json
import os
import sys
import traceback

sys.path.insert(0, os.path.dirname(__file__))

from lib.telegram_sender import send_message, edit_message, answer_callback_query
from lib.bot_menu import MAIN_MENU, BACK_TO_MENU, WELCOME_TEXT
from lib import bot_logic
from lib import settings

HANDLERS = {
    "live": bot_logic.get_live_text,
    "last": bot_logic.get_last_match_text,
    "next": bot_logic.get_next_match_text,
    "today": bot_logic.get_today_text,
    "help": bot_logic.get_help_text,
}

# Shown immediately while the handler is working. Without this the user sees
# the button's loading spinner stop (because we answerCallbackQuery right
# away) but the message text doesn't change for 10-20s while we wait on
# ESPN + the AI analysis endpoint, which feels broken. Editing the message
# to a Persian "loading..." first makes the delay feel much shorter.
LOADING_TEXT = "⏳ یک ثانیه، دارم اطلاعات رو از ESPN و تحلیل هوش مصنوعی می‌گیرم..."


def _handle_update(update):
    if "callback_query" in update:
        cq = update["callback_query"]
        data = cq.get("data", "")
        chat_id = cq["message"]["chat"]["id"]
        message_id = cq["message"]["message_id"]

        # Stop the button's loading spinner right away; the actual
        # answer (which may call the AI analysis endpoint and take a
        # few seconds) is filled in below.
        answer_callback_query(cq["id"])

        if data == "menu":
            edit_message(chat_id, message_id, WELCOME_TEXT, reply_markup=MAIN_MENU)
            return

        handler = HANDLERS.get(data)
        if not handler:
            return

        # Show a loading placeholder immediately so the user knows the
        # tap was registered. The handlers (especially "next") can take
        # 5-15s because of the AI analysis endpoint - without this edit
        # the message looks frozen.
        if data != "help":
            edit_message(chat_id, message_id, LOADING_TEXT, reply_markup=None)

        try:
            text = handler()
        except Exception as e:
            print(f"[webhook] handler '{data}' failed: {e}\n{traceback.format_exc()}")
            text = "⚠️ مشکلی پیش اومد، لطفاً چند لحظه‌ی دیگه دوباره امتحان کن."

        edit_message(chat_id, message_id, text, reply_markup=BACK_TO_MENU)
        return

    if "message" in update:
        msg = update["message"]
        chat_id = msg["chat"]["id"]
        text = (msg.get("text") or "").strip()

        if text in ("/start", "/menu", "منو", "شروع"):
            send_message(WELCOME_TEXT, channel_id=chat_id, reply_markup=MAIN_MENU)
        else:
            send_message(
                "برای شروع، /start رو بفرست یا از دکمه‌های زیر استفاده کن 👇",
                channel_id=chat_id, reply_markup=MAIN_MENU,
            )
        return


def application(environ, start_response):
    method = environ.get("REQUEST_METHOD", "GET")

    if method != "POST":
        start_response("200 OK", [("Content-Type", "text/plain; charset=utf-8")])
        return [b"World Cup bot webhook is up."]

    secret = settings.get("TELEGRAM_WEBHOOK_SECRET", "")
    if secret:
        received = environ.get("HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN", "")
        if received != secret:
            start_response("403 Forbidden", [("Content-Type", "text/plain; charset=utf-8")])
            return [b"forbidden"]

    try:
        length = int(environ.get("CONTENT_LENGTH", 0) or 0)
        body = environ["wsgi.input"].read(length) if length else b"{}"
        update = json.loads(body.decode("utf-8"))
        _handle_update(update)
    except Exception as e:
        print(f"[webhook] error handling update: {e}\n{traceback.format_exc()}")

    # Always answer Telegram with 200, otherwise it will keep retrying
    # the same update.
    start_response("200 OK", [("Content-Type", "application/json; charset=utf-8")])
    return [b'{"ok": true}']


if __name__ == "__main__":
    # Quick local smoke test: `python3 webhook.py` starts a dev server
    # on :8000 so you can curl it before wiring it into alwaysdata.
    from wsgiref.simple_server import make_server
    port = int(os.environ.get("PORT", 8000))
    print(f"Serving webhook locally on http://127.0.0.1:{port}")
    make_server("127.0.0.1", port, application).serve_forever()
