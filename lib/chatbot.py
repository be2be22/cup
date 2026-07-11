"""
Football chatbot - lets users ask arbitrary questions about the World
Cup (or football in general) and get an AI-generated Persian answer.

Triggered by a new '💬 سوال از هوش مصنوعی' button in the bot menu.
When the user taps it, they're prompted to type their question. The
webhook (webhook.py) detects text messages that start with a special
prefix and routes them here instead of the default menu handler.

We include live tournament context (current matches, today's fixtures,
recent results) in the prompt so the AI can answer questions like
'what's the score in the Norway game?' or 'who scored the last goal?'
"""
import json
import urllib.request

from lib import settings
from lib.ai_analysis import _extract_json, _config
from lib.api_client import FootballAPIClient
from lib.formatter import fa, TEAM_FA, to_jalali


CHATBOT_TIMEOUT = 20  # seconds - longer than live commentary since users wait


def _build_context():
    """Build a string of live tournament context to include in the
    AI prompt. Returns None if no context is available."""
    try:
        client = FootballAPIClient()
        fixtures = client.get_all_fixtures()
        if not fixtures:
            return None

        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)

        lines = ["داده‌های زنده‌ی جام جهانی ۲۰۲۶:"]
        live_count = 0
        recent_count = 0
        upcoming_count = 0

        for event in fixtures:
            match = client.parse_event(event)
            if not match['home_team']:
                continue
            hf = fa(match['home_team'], TEAM_FA)
            af = fa(match['away_team'], TEAM_FA)
            state = match['status_state']

            if state == 'in':
                live_count += 1
                clock = match.get('clock', '')
                lines.append(
                    f"  🔴 زنده: {hf} {match['home_score']} - "
                    f"{match['away_score']} {af} (دقیقه {clock})"
                )
            elif state == 'post' and recent_count < 3:
                recent_count += 1
                lines.append(
                    f"  ✅ تمام‌شده: {hf} {match['home_score']} - "
                    f"{match['away_score']} {af}"
                )
            elif state == 'pre' and upcoming_count < 5:
                upcoming_count += 1
                try:
                    dt = datetime.fromisoformat(match['date'].replace('Z', '+00:00'))
                    if dt >= now:
                        time_str = to_jalali(match['date'])
                        lines.append(f"  📅 پیش‌رو: {hf} vs {af} — {time_str}")
                except Exception:
                    pass

        if live_count == 0 and recent_count == 0 and upcoming_count == 0:
            return None
        return "\n".join(lines)
    except Exception as e:
        print(f"[chatbot] context build failed: {e}")
        return None


def answer_question(question):
    """Answer a user's football question in Persian.

    Returns the answer text, or None if the AI is unavailable.
    """
    base, key, model = _config()
    if not base or not key:
        return None

    context = _build_context()
    prompt = (
        "تو یه دستیار هوشمند فوتبالی هستی که به زبان فارسی جواب می‌دی. "
        "کاربر می‌تونه هر سوالی درباره‌ی جام جهانی ۲۰۲۶، فوتبال جهانی، "
        "بازیکن‌ها، تیم‌ها، قوانین، تاریخچه و... بپرسه.\n\n"
    )
    if context:
        prompt += f"این داده‌های زنده‌ی الان رو داری:\n{context}\n\n"
    prompt += (
        f"سوال کاربر: {question}\n\n"
        "یه جواب مفید و دقیق به فارسی بده. اگه سوال درباره‌ی بازی زنده‌ست، "
        "از داده‌های زنده استفاده کن. اگه مطمئن نیستی، بگو. مختصر و دوستانه باش. "
        "از مارک‌داون تلگرام (با ستاره *متن* برای بولد) استفاده کن."
    )

    payload = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.5,
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
        with urllib.request.urlopen(req, timeout=CHATBOT_TIMEOUT) as resp:
            raw = resp.read().decode()
        data = _extract_json(raw)
        return data["choices"][0]["message"]["content"].strip()
    except Exception as e:
        print(f"[chatbot] AI request failed: {e}")
        return None
