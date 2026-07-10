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

Important: many OpenAI-compatible routers (9router included) append a
trailing `data: [DONE]` SSE marker after the JSON body even when
streaming is not requested. Plain `json.loads()` then fails with
"Extra data" because there's text after the closing `}`. We strip any
trailing SSE frames before parsing so the AI analysis actually works.

The prompt now includes live data from ESPN's summary endpoint (recent
form, top scorers, head-to-head, odds) so the AI's analysis reflects
the actual current tournament state instead of relying on whatever was
in its training data. This avoids stale claims like "Phil Foden was not
called up" when ESPN confirms he's been playing and scoring.
"""
import json
import urllib.request

from lib import settings

DEFAULT_MODEL = "oc/mimo-v2.5-free"
# 12s is enough for most prompts; if the AI is slower we fall back to
# the static analysis gracefully. The webhook also shows a loading
# placeholder so the user doesn't see a frozen message.
TIMEOUT_SECONDS = 15


def _config():
    base = settings.get("AI_API_BASE_URL", "").rstrip("/")
    key = settings.get("AI_API_KEY", "")
    model = settings.get("AI_MODEL", DEFAULT_MODEL)
    return base, key, model


def _extract_json(body):
    """Pull the first JSON object out of an HTTP body that may have a
    trailing `data: [DONE]` SSE frame (or other non-JSON noise)."""
    body = body.strip()
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        pass
    depth = 0
    start = -1
    in_string = False
    escape = False
    for i, ch in enumerate(body):
        if escape:
            escape = False
            continue
        if ch == '\\':
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == '{':
            if depth == 0:
                start = i
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0 and start >= 0:
                candidate = body[start:i + 1]
                try:
                    return json.loads(candidate)
                except json.JSONDecodeError:
                    start = -1
    raise json.JSONDecodeError("no JSON object found in body", body, 0)


def _build_prompt(home_team_fa, away_team_fa, stage="", venue="", group="", live_context=None):
    """Build the chat prompt. If live_context is provided (from
    lib.match_summary.build_match_context), include the current
    tournament data so the AI doesn't rely on its training-set
    knowledge of who's injured or called up."""
    prompt = (
        f"یک تحلیل کوتاه پیش از بازی فوتبال به زبان فارسی و لحن گزارشگری "
        f"ورزشی حرفه‌ای بنویس برای بازی {home_team_fa} مقابل {away_team_fa}"
        + (f" در {stage}" if stage else "")
        + (f" (گروه {group})" if group else "")
        + (f" در ورزشگاه {venue}" if venue else "")
        + ".\n"
    )

    if live_context:
        prompt += (
            "\nاز این داده‌های زنده از جام جهانی استفاده کن و بر اساسشون تحلیل کن "
            "(این داده‌ها به‌روز هستن، فقط اسم بازیکن‌ها و آماری که اینجا داده شده رو "
            "بیان کن، حدس نزن):\n"
            f"{live_context}\n"
        )

    prompt += (
        "\nحداکثر ۸ تا ۱۰ خط باشد، شامل: وضعیت فعلی هر دو تیم بر اساس فرم اخیرشون، "
        "یک نبرد کلیدی احتمالی بین دو بازیکن شاخص (از بین بازیکنانی که در داده‌های "
        "زنده آمده‌اند)، و یک پیش‌بینی کلی از روند بازی. برای بولد کردن از ستاره "
        "(*متن*) در قالب مارک‌داون تلگرام استفاده کن. فقط خود متن تحلیل را بنویس، "
        "بدون مقدمه یا توضیح اضافه درباره‌ی خودت."
    )
    return prompt


def generate_prematch_analysis(
    home_team_fa, away_team_fa, stage="", venue="", group="", live_context=None
):
    base, key, model = _config()
    if not base or not key:
        return None

    prompt = _build_prompt(
        home_team_fa, away_team_fa,
        stage=stage, venue=venue, group=group,
        live_context=live_context,
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
            raw = resp.read().decode()
        data = _extract_json(raw)
        return data["choices"][0]["message"]["content"].strip()
    except Exception as e:
        print(f"[ai_analysis] AI request failed, falling back: {e}")
        return None
