"""
AI-powered live match commentary.

Pulls ESPN's English-language play-by-play `commentary` feed for a live
match, passes it (along with the current boxscore stats) to the AI, and
gets back a Persian reporter-style narration that gets posted to the
Telegram channel.

This is what makes the channel feel like a live football broadcast
instead of just score updates — the AI turns dry ESPN events like
'Attempt missed. Jude Bellingham header from the centre of the box
misses to the right' into something like:

  '⛔ موقعیت خطرناک برای انگلیس! بلینگهام روی پاس عرضی اندرسون سر
   زد ولی توپ کنار پایه رفت. انگلیس فشارش رو بیشتر می‌کنه...'

Two modes:
  - generate_live_commentary()       — used every time we detect new
                                       commentary entries. Returns a
                                       short paragraph about the last
                                       few minutes of play.
  - generate_match_pulse()           — used every ~5 minutes as a
                                       'pulse check' that includes
                                       boxscore stats (possession,
                                       shots, corners, etc.) and a
                                       narrative summary of the match
                                       flow so far.

Both fall back to None on any failure so the caller can skip posting
without crashing the cron job.
"""
import json
import urllib.request

from lib import settings
from lib.ai_analysis import _extract_json, _config
from lib.formatter import fa, TEAM_FA
from lib.match_summary import fetch_summary
from lib.api_client import _load_league


# Separate timeout for live commentary - we want it faster than the
# pre-match analysis since it runs every minute during a live match.
# 10s is enough for a short prompt; if the AI is slower we just skip
# the commentary for this cycle and try again next minute.
COMMENTARY_TIMEOUT = 10


def _fetch_commentary(event_id):
    """Pull ESPN's English play-by-play commentary for a live match.
    Returns a list of {'minute': str, 'text': str} entries, newest last."""
    league = _load_league()
    summary = fetch_summary(league, event_id)
    if not summary:
        return None, None
    commentary = summary.get('commentary', []) or []
    entries = []
    for c in commentary:
        time_obj = c.get('time', {}) or {}
        minute = time_obj.get('displayValue', '') or ''
        text = c.get('text', '') or ''
        if text:
            entries.append({'minute': minute, 'text': text})
    # Pull boxscore stats too for the pulse-check mode.
    boxscore = summary.get('boxscore', {}) or {}
    teams_stats = boxscore.get('teams', []) or []
    return entries, teams_stats


def _format_stats_brief(teams_stats, home_team, away_team):
    """Build a compact English-ish stats summary for the AI prompt.
    Returns None if no stats are available."""
    if not teams_stats or len(teams_stats) < 2:
        return None
    # Map team name -> stats dict
    stats_by_team = {}
    for t in teams_stats:
        name = t.get('team', {}).get('displayName', '')
        stats_list = t.get('statistics', []) or []
        stats = {}
        for s in stats_list:
            label = s.get('label', '') or s.get('abbreviation', '')
            val = s.get('displayValue', '')
            if label and val != '':
                stats[label] = val
        stats_by_team[name] = stats

    home_stats = stats_by_team.get(home_team, {})
    away_stats = stats_by_team.get(away_team, {})

    # Pick the most informative stats for a quick narrative pulse.
    keys = [
        'POSSESSION', 'SHOTS', 'ON GOAL', 'Corner Kicks', 'Fouls',
        'Yellow Cards', 'Saves', 'Passes', 'Pass Completion %',
        'Crosses', 'Tackles', 'Interceptions',
    ]

    def _line(stats_dict):
        parts = []
        for k in keys:
            v = stats_dict.get(k)
            if v is not None and v != '':
                # Shorten labels for the prompt
                short = {
                    'POSSESSION': 'تسلط',
                    'SHOTS': 'شوت',
                    'ON GOAL': 'روی هدف',
                    'Corner Kicks': 'کرنر',
                    'Fouls': 'خطا',
                    'Yellow Cards': 'کارت زرد',
                    'Saves': 'سیو',
                    'Passes': 'پاس',
                    'Pass Completion %': 'دقت پاس',
                    'Crosses': 'سانتر',
                    'Tackles': 'تکل',
                    'Interceptions': 'قطع توپ',
                }.get(k, k)
                parts.append(f"{short}: {v}")
        return ' | '.join(parts) if parts else None

    h_line = _line(home_stats)
    a_line = _line(away_stats)
    if not h_line and not a_line:
        return None
    hf = fa(home_team, TEAM_FA)
    af = fa(away_team, TEAM_FA)
    return f"{hf}: {h_line or '—'}\n{af}: {a_line or '—'}"


def _translate_commentary_entries(entries, last_n=8):
    """Pick the last N commentary entries and format them as a single
    English text block for the AI prompt. Returns None if empty."""
    if not entries:
        return None
    recent = entries[-last_n:]
    lines = []
    for e in recent:
        minute = e.get('minute', '')
        text = e.get('text', '')
        if minute:
            lines.append(f"[{minute}] {text}")
        else:
            lines.append(text)
    return "\n".join(lines)


def _call_ai(prompt, timeout=COMMENTARY_TIMEOUT):
    """Send a chat-completions request and return the text content, or
    None on any failure. Reuses _extract_json from ai_analysis so we
    handle the trailing `data: [DONE]` SSE marker correctly."""
    base, key, model = _config()
    if not base or not key:
        return None

    payload = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.75,
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
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode()
        data = _extract_json(raw)
        return data["choices"][0]["message"]["content"].strip()
    except Exception as e:
        print(f"[live_commentary] AI request failed: {e}")
        return None


def generate_live_commentary(
    event_id, home_team, away_team, score_str="", minute_str=""
):
    """Generate a short Persian reporter-style commentary for the last
    few minutes of play. Returns the text, or None on any failure.

    Used by live_update.py every time new commentary entries are
    detected (typically every 1-2 minutes during a live match).
    """
    entries, _ = _fetch_commentary(event_id)
    if not entries:
        return None

    english_block = _translate_commentary_entries(entries, last_n=6)
    if not english_block:
        return None

    hf = fa(home_team, TEAM_FA)
    af = fa(away_team, TEAM_FA)

    prompt = (
        f"تو یه گزارشگر ورزشی فارسی‌زبان حرفه‌ای هستی که داره بازی "
        f"{hf} مقابل {af} رو تو جام جهانی ۲۰۲۶ گزارش می‌کنه."
        + (f" نتیجه‌ی فعلی: {score_str}." if score_str else "")
        + (f" دقیقه: {minute_str}." if minute_str else "")
        + "\n\nاین توضیحات اخیر مسابقه به زبان انگلیسی هستن (آخرین موارد آخر هستن):\n"
        f"{english_block}\n\n"
        "یک گزارش کوتاه (۲ تا ۴ خط) به فارسی بنویس که مثل گزارشگر تلویزیونی "
        "آخرین اتفاقات بازی رو تعریف کنه. از اموجی مناسب (⚽🥅🧤⚡🔴🟡) استفاده کن. "
        "اسم بازیکن‌ها و تیم‌ها رو به فارسی بنویس. مختصر و هیجان‌انگیز باشه. "
        "فقط خود گزارش رو بنویس، بدون مقدمه."
    )

    return _call_ai(prompt)


def generate_match_pulse(
    event_id, home_team, away_team, score_str="", minute_str=""
):
    """Generate a 'pulse check' summary every ~5 minutes that includes
    boxscore stats (possession, shots, corners, etc.) plus a narrative
    summary of how the match is flowing. Returns the text, or None."""
    entries, teams_stats = _fetch_commentary(event_id)
    if not entries and not teams_stats:
        return None

    english_block = _translate_commentary_entries(entries, last_n=12) or '(هیچ اتفاق خاصی ثبت نشده)'
    stats_block = _format_stats_brief(teams_stats, home_team, away_team) or '(آمار در دسترس نیست)'

    hf = fa(home_team, TEAM_FA)
    af = fa(away_team, TEAM_FA)

    prompt = (
        f"تو یه تحلیلگر فوتبال فارسی‌زبان هستی. بازی {hf} مقابل {af} "
        f"تو جام جهانی ۲۰۲۶ در جریانه."
        + (f" نتیجه: {score_str}." if score_str else "")
        + (f" دقیقه: {minute_str}." if minute_str else "")
        + "\n\nآمار زنده‌ی بازی:\n"
        f"{stats_block}\n\n"
        "آخرین اتفاقات بازی:\n"
        f"{english_block}\n\n"
        "یک گزارش کوتاه (۳ تا ۵ خط) به فارسی بنویس که شامل این موارد باشه:\n"
        "۱. روند کلی بازی (کدوم تیم دست بالاست، فشار بیشتر روی کیه)\n"
        "۲. تحلیل کوتاه آمار (تسلط توپ، شوت‌ها، کرنرها)\n"
        "۳. یکی دو نکته‌ی کلیدی از اتفاقات اخیر\n"
        "از اموجی مناسب (📊⚽🔥⚡) استفاده کن. مختصر و حرفه‌ای باشه. "
        "فقط خود گزارش رو بنویس، بدون مقدمه."
    )

    return _call_ai(prompt, timeout=15)


def generate_halftime_summary(event_id, home_team, away_team, score_str=""):
    """Generate a Persian summary of the FIRST HALF only, to be sent
    once when the match goes to halftime.

    IMPORTANT: this is called when ESPN reports STATUS_HALFTIME. The
    commentary feed at this point only contains first-half events, so
    the AI summarizes what actually happened in the first 45+ minutes.
    We explicitly tell the AI NOT to invent or predict second-half
    events - just summarize the first half and stop.

    Returns the text, or None on any failure.
    """
    entries, teams_stats = _fetch_commentary(event_id)
    if not entries and not teams_stats:
        return None

    # Use ALL commentary entries from the first half (don't truncate)
    english_block = _translate_commentary_entries(entries, last_n=30) or '(هیچ اتفاق خاصی ثبت نشده)'
    stats_block = _format_stats_brief(teams_stats, home_team, away_team) or '(آمار در دسترس نیست)'

    hf = fa(home_team, TEAM_FA)
    af = fa(away_team, TEAM_FA)

    prompt = (
        f"تو یه گزارشگر فوتبال فارسی‌زبان هستی. نیمه‌ی اول بازی "
        f"{hf} مقابل {af} تو جام جهانی ۲۰۲۶ تموم شده و الان استراحته."
        + (f" نتیجه‌ی نیمه‌ی اول: {score_str}." if score_str else "")
        + "\n\nآمار نیمه‌ی اول:\n"
        f"{stats_block}\n\n"
        "اتفاقات نیمه‌ی اول (به ترتیب زمانی):\n"
        f"{english_block}\n\n"
        "یک خلاصه‌ی کوتاه (۳ تا ۵ خط) به فارسی بنویس که شامل این موارد باشه:\n"
        "۱. روند کلی نیمه‌ی اول (کدوم تیم دست بالاتر بود)\n"
        "۲. گل‌ها و موقعیت‌های کلیدی\n"
        "۳. تحلیل کوتاه آمار (تسلط توپ، شوت‌ها)\n"
        "\n⚠️ مهم: فقط درباره‌ی نیمه‌ی اول حرف بزن. هیچ‌چیز درباره‌ی نیمه‌ی دوم "
        "نگو، هیچ پیش‌بینی نکن، هیچ اتفاقی رو اختراع نکن. فقط چیزی که تو "
        "داده‌های بالا هست رو خلاصه کن.\n"
        "از اموجی مناسب (⚽📊🔥) استفاده کن. مختصر و حرفه‌ای باشه. "
        "فقط خود خلاصه رو بنویس، بدون مقدمه."
    )

    return _call_ai(prompt, timeout=15)
