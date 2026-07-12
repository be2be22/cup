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

from lib import settings

CONFIG_PATH = os.path.join(os.path.dirname(__file__), '..', 'config.json')


def _default_channel_id():
    with open(CONFIG_PATH, encoding='utf-8') as f:
        return json.load(f)["telegram"]["channel_id"]


def _call(method, payload):
    """POST helper for any Telegram Bot API method. Returns the parsed
    JSON response, or None if the token is missing or the call fails."""
    token = settings.get("TELEGRAM_BOT_TOKEN", "")
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


def send_video(video_url, caption=None, channel_id=None, parse_mode="Markdown"):
    """Send a video by URL to the channel (or a specific chat).

    Telegram downloads the video from `video_url` server-side and posts
    it. We use this to forward Reddit's v.redd.it goal-clips and
    varzesh3's highlight videos to the channel.

    If Telegram rejects the URL (some servers set Content-Disposition:
    attachment which Telegram can't handle), we fall back to downloading
    the video ourselves and uploading it as multipart/form-data. The
    downloaded file is deleted immediately after upload - we never
    keep video data on disk.

    Falls back gracefully: if both methods fail, returns False.
    """
    if channel_id is None:
        channel_id = _default_channel_id()

    # Method 1: Try passing the URL directly to Telegram
    payload = {
        "chat_id": channel_id,
        "video": video_url,
        "disable_notification": False,
    }
    if caption:
        payload["caption"] = caption
        payload["parse_mode"] = parse_mode

    result = _call("sendVideo", payload)
    if result and result.get("ok"):
        return True

    # Method 2: URL was rejected (e.g. Content-Disposition: attachment).
    # Download the video ourselves and upload it as multipart.
    print(f"[telegram_sender] URL rejected, trying download+upload fallback...")
    try:
        return _send_video_by_upload(video_url, caption, channel_id, parse_mode)
    except Exception as e:
        print(f"[telegram_sender] video upload fallback failed: {e}")
        return False


def _send_video_by_upload(video_url, caption, channel_id, parse_mode):
    """Download a video from video_url and upload it to Telegram as
    multipart/form-data. Used as a fallback when sendVideo with a URL
    fails (e.g. when the source server sets Content-Disposition:
    attachment, which Telegram can't handle).

    The video is downloaded to a temp file, uploaded, then deleted.
    We never keep video data on disk after the upload completes.
    """
    import tempfile
    import os
    import mimetypes
    import uuid

    # Download the video to a temp file
    tmp_path = None
    try:
        req = urllib.request.Request(
            video_url,
            headers={
                'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36',
                'Accept': 'video/mp4,*/*',
            },
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            content_type = resp.headers.get('Content-Type', 'video/mp4')
            # Read in chunks to avoid memory issues
            tmp_fd, tmp_path = tempfile.mkstemp(suffix='.mp4')
            with os.fdopen(tmp_fd, 'wb') as f:
                while True:
                    chunk = resp.read(65536)
                    if not chunk:
                        break
                    f.write(chunk)

        file_size = os.path.getsize(tmp_path)
        print(f"[telegram_sender] downloaded {file_size} bytes to {tmp_path}")

        # Telegram limit: 50MB for bots
        if file_size > 50 * 1024 * 1024:
            print(f"[telegram_sender] video too large ({file_size} bytes > 50MB)")
            return False

        # Upload via multipart/form-data
        token = settings.get("TELEGRAM_BOT_TOKEN", "")
        if not token:
            return False

        import http.client
        from urllib.parse import urlparse

        boundary = uuid.uuid4().hex
        api_url = f"https://api.telegram.org/bot{token}/sendVideo"

        # Build multipart body
        body_parts = []
        # chat_id field
        body_parts.append(f'--{boundary}\r\n'.encode())
        body_parts.append(b'Content-Disposition: form-data; name="chat_id"\r\n\r\n')
        body_parts.append(f'{channel_id}\r\n'.encode())
        # caption field
        if caption:
            body_parts.append(f'--{boundary}\r\n'.encode())
            body_parts.append(b'Content-Disposition: form-data; name="caption"\r\n\r\n')
            body_parts.append(f'{caption}\r\n'.encode())
            body_parts.append(f'--{boundary}\r\n'.encode())
            body_parts.append(b'Content-Disposition: form-data; name="parse_mode"\r\n\r\n')
            body_parts.append(f'{parse_mode}\r\n'.encode())
        # video file field
        body_parts.append(f'--{boundary}\r\n'.encode())
        body_parts.append(
            b'Content-Disposition: form-data; name="video"; filename="video.mp4"\r\n'
        )
        body_parts.append(f'Content-Type: {content_type}\r\n\r\n'.encode())

        # Read file content
        with open(tmp_path, 'rb') as f:
            file_data = f.read()
        body_parts.append(file_data)
        body_parts.append(f'\r\n--{boundary}--\r\n'.encode())

        body = b''.join(body_parts)

        # Make the HTTP request
        parsed = urlparse(api_url)
        conn = http.client.HTTPSConnection(parsed.netloc, timeout=180)
        conn.request(
            "POST",
            parsed.path,
            body=body,
            headers={
                "Content-Type": f"multipart/form-data; boundary={boundary}",
                "Content-Length": str(len(body)),
            },
        )
        resp = conn.getresponse()
        resp_data = resp.read().decode()
        conn.close()

        result = json.loads(resp_data)
        if result.get("ok"):
            print(f"[telegram_sender] video uploaded successfully")
            return True
        else:
            print(f"[telegram_sender] upload failed: {result}")
            return False

    finally:
        # Always clean up the temp file - never keep video data on disk
        if tmp_path and os.path.exists(tmp_path):
            os.remove(tmp_path)
            print(f"[telegram_sender] temp file deleted")


def pin_chat_message(message_id, channel_id=None, disable_notification=True):
    """Pin a message in the channel. The bot must be an admin with
    'can_pin_messages' permission.

    Used by lib/live_thread.py to pin the Live Thread scoreboard at
    the top of the channel so users always see the current score.

    disable_notification=True means pinning won't send a notification
    to all channel members (silent pin).
    """
    if channel_id is None:
        channel_id = _default_channel_id()

    payload = {
        "chat_id": channel_id,
        "message_id": message_id,
        "disable_notification": disable_notification,
    }
    result = _call("pinChatMessage", payload)
    return bool(result and result.get("ok"))


def unpin_chat_message(message_id=None, channel_id=None):
    """Unpin a specific message (or all messages if message_id is None)
    from the channel."""
    if channel_id is None:
        channel_id = _default_channel_id()

    payload = {"chat_id": channel_id}
    if message_id is not None:
        payload["message_id"] = message_id
        result = _call("unpinChatMessage", payload)
    else:
        result = _call("unpinAllChatMessages", payload)
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
