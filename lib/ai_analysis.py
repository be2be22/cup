"""
AI-generated Persian pre-match analysis via an OpenAI-compatible
chat-completions endpoint (e.g. a router like 9router, OpenRouter, etc.)

Configure these as environment variables from alwaysdata's control panel
(Sites > your site > Environment) - never hardcode the key in a file:

  AI_API_BASE_URL   e.g. https://9router-production-2f7f.up.railway.app/v1
  AI_API_KEY        your bearer token
  AI_MODEL          e.g. oc/mimo-v2.5-free   (optional, has a default below)

If these are not set, or the request fails for any reason (bad key,
endpoint down, timeout), generate_prematch_analysis() returns None and
the caller falls back to a simple message instead of crashing the cron
job - a World Cup update is more important than a fancy analysis.
"""
import json
import os
import urllib.request

DEFAULT_MODEL = "oc/mimo-v2.5-free"
TIMEOUT_SECONDS = 25


def _config():
    base = os.environ.get("AI_API_BASE_URL", "").rstrip("/")
    key = os.environ.get("AI_API_KEY", "")
    model = os.environ.get("AI_MODEL", DEFAULT_MODEL)
    return base, key, model


def generate_prematch_analysis(home_team_fa, away_team_fa, stage="", venue="", group=""):
    base, key, model = _config()
    if not base or not key:
        return None

    prompt = (
        f"یک تحلیل کوتاه پیش از بازی فوتبال به زبان فارسی و لحن گزارشگری "
        f"ورزشی حرفه‌ای بنویس برای بازی {home_team_fa} مقابل {away_team_fa}"
        + (f" در {stage}" if stage else "")
        + (f" (گروه {group})" if group else "")
        + (f" در ورزشگاه {venue}" if venue else "")
        + ".\nحداکثر ۸ تا ۱۰ خط باشد، شامل: نقاط قوت هر دو تیم، یک نبرد "
          "کلیدی احتمالی بین دو بازیکن شاخص، و یک پیش‌بینی کلی از روند "
          "بازی. برای بولد کردن از ستاره (*متن*) در قالب مارک‌داون تلگرام "
          "استفاده کن. فقط خود متن تحلیل را بنویس، بدون مقدمه یا توضیح "
          "اضافه درباره‌ی خودت."
    )

    payload = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.7,
    }).encode()

    try:
        req = urllib.request.Request(
            f"{base}/chat/completions",
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {key}",
            },
        )
        with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as resp:
            data = json.loads(resp.read().decode())
        return data["choices"][0]["message"]["content"].strip()
    except Exception as e:
        print(f"[ai_analysis] AI request failed, falling back: {e}")
        return None
