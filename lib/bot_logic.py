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
from lib.match_summary import fetch_summary, build_match_context
from lib.api_client import _load_league

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


def _get_match_context(event_id, home, away):
    """Cached helper to fetch + build the match-summary context for a
    given event. Returns None on any failure."""
    if not event_id:
        return None
    try:
        league = _load_league()
        summary = fetch_summary(league, event_id)
        if not summary:
            return None
        return build_match_context(summary, home, away)
    except Exception as e:
        print(f"[bot_logic] match context fetch failed: {e}")
        return None


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

    stage = m.get('stage', '') or 'جام جهانی ۲۰۲۶'
    venue_parts = [p for p in [m.get('venue', ''), m.get('venue_city', '')] if p]
    venue = '، '.join(venue_parts)

    analysis = build_analysis(
        m['home_team'], m['away_team'],
        stage=stage, venue=venue, group='',
        event_id=m.get('id'),
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
        "📅 *برنامه امروز* — همه‌ی بازی‌های امروز با وضعیت هرکدوم.\n"
        "📊 *فرم اخیر تیم‌ها* — نتیجه‌ی ۵ بازی آخر هر دو تیمِ بازی بعدی.\n"
        "⚔️ *تاریخچه رو در رو* — نتایج بازی‌های قبلی بین دو تیم.\n"
        "👑 *برترین‌های جام جهانی* — گلزن، پاسور و شوت‌زن برتر هر تیم.\n\n"
        "همچنین گزارش‌های گل، کارت، پنالتی و شروع/پایان بازی به‌صورت خودکار "
        "توی کانال منتشر می‌شن؛ این منو فقط برای چک کردن سریع وضعیته."
    )


def get_form_text():
    """Last-5-games form for both teams in the next upcoming match.
    Uses ESPN's summary endpoint for live data."""
    client = FootballAPIClient()
    now = datetime.now(timezone.utc)
    upcoming = [
        client.parse_event(e) for e in client.get_all_fixtures()
        if e.get('status', {}).get('type', {}).get('state') == 'pre'
    ]
    upcoming = [m for m in upcoming if m['home_team'] and _parse_date(m) >= now]
    if not upcoming:
        return "در حال حاضر بازی برنامه‌ریزی‌شده‌ای برای نمایش فرم وجود نداره."

    upcoming.sort(key=_parse_date)
    m = upcoming[0]

    ctx = _get_match_context(m.get('id'), m['home_team'], m['away_team'])
    if not ctx or not ctx.get('last5_text'):
        return "اطلاعات فرم اخیر تیم‌ها فعلاً در دسترس نیست. 📭"

    hf, af = fa(m['home_team'], TEAM_FA), fa(m['away_team'], TEAM_FA)
    header = (
        f"📊 *فرم اخیر تیم‌ها*\n{SEP}\n"
        f"{get_flag(m['home_team'])} *{hf}* 🆚 *{af}* {get_flag(m['away_team'])}\n{SEP}\n\n"
    )
    return header + ctx['last5_text'] + f"\n{SEP}"


def get_h2h_text():
    """Head-to-head history for the next upcoming match."""
    client = FootballAPIClient()
    now = datetime.now(timezone.utc)
    upcoming = [
        client.parse_event(e) for e in client.get_all_fixtures()
        if e.get('status', {}).get('type', {}).get('state') == 'pre'
    ]
    upcoming = [m for m in upcoming if m['home_team'] and _parse_date(m) >= now]
    if not upcoming:
        return "در حال حاضر بازی برنامه‌ریزی‌شده‌ای برای نمایش تاریخچه وجود نداره."

    upcoming.sort(key=_parse_date)
    m = upcoming[0]

    ctx = _get_match_context(m.get('id'), m['home_team'], m['away_team'])
    if not ctx or not ctx.get('h2h_text'):
        return "تاریخچه‌ی بازی‌های رو در رو بین این دو تیم فعلاً موجود نیست. 📭"

    hf, af = fa(m['home_team'], TEAM_FA), fa(m['away_team'], TEAM_FA)
    header = (
        f"⚔️ *تاریخچه‌ی رو در رو*\n{SEP}\n"
        f"{get_flag(m['home_team'])} *{hf}* 🆚 *{af}* {get_flag(m['away_team'])}\n{SEP}\n\n"
    )
    return header + ctx['h2h_text'] + f"\n{SEP}"


def get_leaders_text():
    """Top scorer / assister / shot-taker for each team in the next
    upcoming match, based on the current World Cup tournament stats."""
    client = FootballAPIClient()
    now = datetime.now(timezone.utc)
    upcoming = [
        client.parse_event(e) for e in client.get_all_fixtures()
        if e.get('status', {}).get('type', {}).get('state') == 'pre'
    ]
    upcoming = [m for m in upcoming if m['home_team'] and _parse_date(m) >= now]
    if not upcoming:
        return "در حال حاضر بازی برنامه‌ریزی‌شده‌ای برای نمایش برترین‌ها وجود نداره."

    upcoming.sort(key=_parse_date)
    m = upcoming[0]

    ctx = _get_match_context(m.get('id'), m['home_team'], m['away_team'])
    if not ctx or not ctx.get('leaders_text'):
        return "آمار برترین‌های تیم‌ها فعلاً موجود نیست. 📭"

    hf, af = fa(m['home_team'], TEAM_FA), fa(m['away_team'], TEAM_FA)
    header = (
        f"👑 *برترین‌های جام جهانی*\n{SEP}\n"
        f"{get_flag(m['home_team'])} *{hf}* 🆚 *{af}* {get_flag(m['away_team'])}\n{SEP}\n\n"
    )
    extra = "\n\n💡 این آمار بر اساس کل بازی‌های جام جهانی ۲۰۲۶ هر تیمه."
    return header + ctx['leaders_text'] + extra + f"\n{SEP}"


# ============================================================
# SportScore-powered features (standings, bracket, top scorers, lineups)
# ============================================================

def get_standings_text():
    """Get the group-stage standings table from SportScore."""
    from lib.sportscore_client import get_standings
    tables = get_standings()
    if not tables:
        return "جدول گروه‌ها فعلاً در دسترس نیست. 📭"

    lines = ["📋 *جدول گروه‌های جام جهانی ۲۰۲۶*\n"]
    for table in tables:
        group_name = table.get('group', '')
        rows = table.get('rows', []) or []
        if not rows:
            continue
        lines.append(f"{SEP}")
        lines.append(f"🏆 *{group_name}*")
        lines.append("رتبه | تیم | بازی | برد | مساوی | باخت | گل‌ها | امتیاز")
        for row in rows:
            team = row.get('team', '')
            team_fa = fa(team, TEAM_FA)
            pos = row.get('pos', '')
            played = row.get('played', 0)
            won = row.get('won', 0)
            drawn = row.get('drawn', 0)
            lost = row.get('lost', 0)
            gf = row.get('goals_for', 0)
            ga = row.get('goals_against', 0)
            pts = row.get('points', 0)
            lines.append(
                f"{pos} | {get_flag(team)} {team_fa} | {played} | {won} | {drawn} | {lost} | {gf}-{ga} | {pts}"
            )
        lines.append("")
    return "\n".join(lines).strip()


def get_bracket_text():
    """Get the knockout-stage bracket from SportScore."""
    from lib.sportscore_client import get_bracket
    rounds = get_bracket()
    if not rounds:
        return "نمودار مرحله‌ی حذفی فعلاً در دسترس نیست. 📭"

    lines = ["🏆 *نمودار مرحله‌ی حذفی جام جهانی ۲۰۲۶*\n"]
    for rnd in rounds:
        round_name = rnd.get('name', '')
        matchups = rnd.get('matchups', []) or []
        if not matchups:
            continue
        # Translate round name
        round_fa = {
            'Matches': 'مرحله‌ی گروهی',
            'Round of 32': 'یک‌سی‌ودوم نهایی',
            'Round of 16': 'یک‌شانزدهم نهایی',
            'Quarterfinals': 'یک‌چهارم نهایی',
            'Semifinals': 'نیمه‌نهایی',
            '3rd-Place Match': 'رده‌بندی',
            'Final': 'فینال',
        }.get(round_name, round_name)

        lines.append(f"{SEP}")
        lines.append(f"⚔️ *{round_fa}*")
        for m in matchups:
            home = m.get('home', 'TBD')
            away = m.get('away', 'TBD')
            hs = m.get('home_score')
            as_ = m.get('away_score')
            home_fa = fa(home, TEAM_FA)
            away_fa = fa(away, TEAM_FA)
            if hs is not None and as_ is not None:
                lines.append(f"  {get_flag(home)} {home_fa} {hs} - {as_} {away_fa} {get_flag(away)}")
            else:
                lines.append(f"  {get_flag(home)} {home_fa} vs {away_fa} {get_flag(away)}")
        lines.append("")
    return "\n".join(lines).strip()


def get_top_scorers_text(stat='goals'):
    """Get the top scorers or assist leaders from SportScore."""
    from lib.sportscore_client import get_top_scorers
    scorers = get_top_scorers(stat=stat, limit=15)
    if not scorers:
        return "لیست برترین گلزن‌ها فعلاً در دسترس نیست. 📭"

    title = "👟 برترین گلزن‌های جام جهانی ۲۰۲۶" if stat == 'goals' else "🎯 برترین پاسورهای جام جهانی ۲۰۲۶"
    value_label = "گل" if stat == 'goals' else "پاس گل"
    lines = [f"{title}\n{SEP}\n"]
    lines.append("رتبه | بازیکن | تیم | بازی | {} | دقیقه".format(value_label))
    lines.append(SEP)
    for s in scorers:
        rank = s.get('rank', '')
        player = s.get('player', '')
        team = s.get('team', '')
        matches = s.get('matches', 0)
        value = s.get('goals' if stat == 'goals' else 'assists', 0)
        minutes = s.get('minutes', 0)
        player_fa = fa(player, PLAYER_FA)
        team_fa = fa(team, TEAM_FA)
        lines.append(
            f"{rank} | {player_fa} | {get_flag(team)} {team_fa} | {matches} | {value} | {minutes}'"
        )
    lines.append(SEP)
    return "\n".join(lines)


def get_lineups_text():
    """Get the lineups for the next upcoming match from SportScore."""
    from lib.sportscore_client import get_lineups, find_match_slug
    client = FootballAPIClient()
    now = datetime.now(timezone.utc)
    upcoming = [
        client.parse_event(e) for e in client.get_all_fixtures()
        if e.get('status', {}).get('type', {}).get('state') == 'pre'
    ]
    upcoming = [m for m in upcoming if m['home_team'] and _parse_date(m) >= now]
    if not upcoming:
        return "در حال حاضر بازی برنامه‌ریزی‌شده‌ای برای نمایش ترکیب وجود نداره."

    upcoming.sort(key=_parse_date)
    m = upcoming[0]

    # Try to find the lineups - try both home-vs-away and away-vs-home
    slug1 = find_match_slug(m['home_team'], m['away_team'])
    slug2 = find_match_slug(m['away_team'], m['home_team'])

    home_lineup, away_lineup = get_lineups(slug1)
    if not home_lineup:
        home_lineup, away_lineup = get_lineups(slug2)
        if home_lineup:
            # Swap since we tried the reversed slug
            home_lineup, away_lineup = away_lineup, home_lineup

    if not home_lineup and not away_lineup:
        return (
            f"ترکیب بازی {fa(m['home_team'], TEAM_FA)} - {fa(m['away_team'], TEAM_FA)} "
            "هنوز اعلام نشده. معمولاً ۱ ساعت قبل از بازی اعلام می‌شه. ⏳"
        )

    hf, af = fa(m['home_team'], TEAM_FA), fa(m['away_team'], TEAM_FA)
    lines = [
        f"📋 *ترکیب‌های اولیه*\n{SEP}",
        f"{get_flag(m['home_team'])} *{hf}* 🆚 *{af}* {get_flag(m['away_team'])}\n{SEP}",
    ]

    def format_lineup(lineup, team_name):
        if not lineup:
            return None
        formation = lineup.get('formation', '') if isinstance(lineup, dict) else ''
        players = lineup.get('players', []) if isinstance(lineup, dict) else []
        if not players:
            return None
        team_fa = fa(team_name, TEAM_FA)
        result = [f"\n{get_flag(team_name)} *{team_fa}*"]
        if formation:
            result.append(f"Formation: {formation}")
        for p in players:
            if isinstance(p, dict):
                name = p.get('name', '') or p.get('player', '')
                pos = p.get('position', '') or p.get('pos', '')
                num = p.get('number', '') or p.get('shirt', '')
                name_fa = fa(name, PLAYER_FA)
                if num:
                    result.append(f"  {num}. {name_fa} ({pos})")
                else:
                    result.append(f"  • {name_fa} ({pos})")
        return "\n".join(result)

    home_text = format_lineup(home_lineup, m['home_team'])
    away_text = format_lineup(away_lineup, m['away_team'])
    if home_text:
        lines.append(home_text)
    if away_text:
        lines.append(away_text)
    lines.append(SEP)
    return "\n".join(lines)
