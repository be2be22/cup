"""
Text builders for the interactive bot menu (lib/bot_menu.py buttons).

Kept separate from the cron scripts in scripts/ because these run
on-demand from a Telegram webhook request instead of a scheduled task,
but they reuse the exact same lib/ modules (api_client, formatter,
analysis_builder) so the wording matches what the channel already
posts.
"""
from datetime import datetime, timezone

from lib.api_client import FootballAPIClient
from lib.formatter import PersianFormatter, fa, TEAM_FA, PLAYER_FA, to_jalali, get_flag, SEP
from lib.analysis_builder import build_analysis

fmt = PersianFormatter()


def _parse_date(match):
    try:
        return datetime.fromisoformat(match.get('date', '').replace('Z', '+00:00'))
    except Exception:
        return datetime.min.replace(tzinfo=timezone.utc)


def _events_text(match):
    lines = []
    for g in match.get('goals', []):
        lines.append(f"⚽ گل: {fa(g['team'], TEAM_FA)} - {fa(g['player'], PLAYER_FA)} ({g['minute']})")
    for c in match.get('cards', []):
        emoji = '🟡' if 'زرد' in c['detail'] else '🔴'
        lines.append(f"{emoji} {c['detail']}: {fa(c['team'], TEAM_FA)} - {fa(c['player'], PLAYER_FA)} ({c['minute']})")
    return '\n'.join(lines) if lines else None


def get_live_text():
    client = FootballAPIClient()
    live = client.get_live_fixtures()
    if not live:
        return "در حال حاضر هیچ بازی زنده‌ای در جریان نیست. ⏸️\n\nبرای دیدن بازی بعدی از دکمه‌ی «⏭ بازی بعدی» استفاده کن."

    parts = []
    for event in live:
        match = client.parse_event(event)
        if not match['home_team']:
            continue
        parts.append(fmt.format_live_update({
            'home_team': match['home_team'], 'away_team': match['away_team'],
            'home_score': match['home_score'], 'away_score': match['away_score'],
            'clock': match.get('clock', f"{match['minute']}'"),
            'status': match['status'],
        }, _events_text(match)))

    return "\n\n".join(parts) if parts else "در حال حاضر هیچ بازی زنده‌ای در جریان نیست. ⏸️"


def get_last_match_text():
    client = FootballAPIClient()
    finished = [
        client.parse_event(e) for e in client.get_all_fixtures()
        if e.get('status', {}).get('type', {}).get('state') == 'post'
    ]
    finished = [m for m in finished if m['home_team']]
    if not finished:
        return "هنوز هیچ بازی‌ای تموم نشده. 🕐"

    finished.sort(key=_parse_date, reverse=True)
    m = finished[0]
    return fmt.format_postmatch({
        'home_team': m['home_team'], 'away_team': m['away_team'],
        'home_score': m['home_score'], 'away_score': m['away_score'],
        'goals': m['goals'],
    })


def get_next_match_text():
    client = FootballAPIClient()
    now = datetime.now(timezone.utc)
    upcoming = [
        client.parse_event(e) for e in client.get_all_fixtures()
        if e.get('status', {}).get('type', {}).get('state') == 'pre'
    ]
    upcoming = [m for m in upcoming if m['home_team'] and _parse_date(m) >= now]
    if not upcoming:
        return "در حال حاضر بازی برنامه‌ریزی‌شده‌ی دیگه‌ای برای نمایش وجود نداره."

    upcoming.sort(key=_parse_date)
    m = upcoming[0]

    # Use the actual stage name from ESPN (e.g. "یک‌چهارم نهایی جام جهانی ۲۰۲۶")
    # instead of the previously-hardcoded "مرحله گروهی". Also include venue city
    # if available for a richer pre-match message.
    stage = m.get('stage', '') or 'جام جهانی ۲۰۲۶'
    venue_parts = [p for p in [m.get('venue', ''), m.get('venue_city', '')] if p]
    venue = '، '.join(venue_parts)

    analysis = build_analysis(
        m['home_team'], m['away_team'],
        stage=stage, venue=venue, group='',
    )
    return fmt.format_prematch({
        'home_team': m['home_team'], 'away_team': m['away_team'],
        'time': m.get('date', ''), 'venue': venue,
        'stage': stage,
    }, analysis)


def get_today_text():
    client = FootballAPIClient()
    now = datetime.now(timezone.utc)
    fixtures = [client.parse_event(e) for e in client.get_all_fixtures()]
    today = [
        m for m in fixtures
        if m['home_team'] and _parse_date(m).date() == now.date()
    ]
    if not today:
        return "امروز بازی‌ای در برنامه نیست. 📭"

    today.sort(key=_parse_date)
    lines = ["📅 *برنامه‌ی امروز:*\n"]
    for m in today:
        hf, af = fa(m['home_team'], TEAM_FA), fa(m['away_team'], TEAM_FA)
        if m['status_state'] == 'in':
            tag = f"🔴 زنده {m.get('clock', '')} | {m['home_score']}-{m['away_score']}"
        elif m['status_state'] == 'post':
            tag = f"✅ پایان یافته | {m['home_score']}-{m['away_score']}"
        else:
            tag = f"🕐 {to_jalali(m.get('date', ''))}"
        lines.append(f"{get_flag(m['home_team'])} {hf} 🆚 {af} {get_flag(m['away_team'])}\n{tag}\n{SEP}")

    return "\n".join(lines)


def get_help_text():
    return (
        "ℹ️ *راهنمای ربات*\n\n"
        "🔴 *وضعیت بازی زنده* — نتیجه و آخرین اتفاقات بازی‌ای که الان در جریانه.\n"
        "📋 *نتیجه بازی قبلی* — نتیجه‌ی آخرین بازی‌ای که تموم شده.\n"
        "⏭ *بازی بعدی + تحلیل* — تاریخ، ساعت و یک تحلیل کوتاه پیش از بازی بعدی.\n"
        "📅 *برنامه امروز* — همه‌ی بازی‌های امروز با وضعیت هرکدوم.\n\n"
        "همچنین گزارش‌های گل، کارت، پنالتی و شروع/پایان بازی به‌صورت خودکار "
        "توی کانال منتشر می‌شن؛ این منو فقط برای چک کردن سریع وضعیته."
    )
