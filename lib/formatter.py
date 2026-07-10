"""Persian-language message formatting for Telegram."""

SEP = "───────────────"

FLAGS = {
    "France": "🇫🇷", "Morocco": "🇲🇦", "Iran": "🇮🇷", "USA": "🇺🇸",
    "England": "🏴", "Brazil": "🇧🇷", "Argentina": "🇦🇷", "Germany": "🇩🇪",
    "Spain": "🇪🇸", "Portugal": "🇵🇹", "Italy": "🇮🇹", "Japan": "🇯🇵",
    "South Korea": "🇰🇷", "Mexico": "🇲🇽", "Canada": "🇨🇦",
    "Netherlands": "🇳🇱", "Belgium": "🇧🇪", "Croatia": "🇭🇷",
    "Senegal": "🇸🇳", "Ghana": "🇬🇭", "Cameroon": "🇨🇲", "Tunisia": "🇹🇳",
    "Saudi Arabia": "🇸🇦", "Australia": "🇦🇺", "Uruguay": "🇺🇾",
    "Ecuador": "🇪🇨", "Qatar": "🇶🇦", "Wales": "🏴", "Poland": "🇵🇱",
    "Serbia": "🇷🇸", "Switzerland": "🇨🇭", "Denmark": "🇩🇰",
    "Nigeria": "🇳🇬", "Egypt": "🇪🇬",
}

TEAM_FA = {
    "France": "فرانسه", "Morocco": "مراکش", "Iran": "ایران", "USA": "آمریکا",
    "England": "انگلیس", "Brazil": "برزیل", "Argentina": "آرژانتین",
    "Germany": "آلمان", "Spain": "اسپانیا", "Portugal": "پرتغال",
    "Italy": "ایتالیا", "Japan": "ژاپن", "South Korea": "کره جنوبی",
    "Mexico": "مکزیک", "Canada": "کانادا", "Netherlands": "هلند",
    "Belgium": "بلژیک", "Croatia": "کرواسی", "Senegal": "سنگال",
    "Ghana": "غنا", "Cameroon": "کامرون", "Tunisia": "تونس",
    "Saudi Arabia": "عربستان", "Australia": "استرالیا", "Uruguay": "اروگوئه",
    "Ecuador": "اکوادور", "Qatar": "قطر", "Wales": "ولز", "Poland": "لهستان",
    "Serbia": "صربستان", "Switzerland": "سوئیس", "Denmark": "دانمارک",
    "Nigeria": "نیجریه", "Egypt": "مصر",
}

# Player-name translations are best-effort; unknown names fall back to
# their original (Latin-script) spelling via fa().
PLAYER_FA = {
    "Kylian Mbappe": "کیلیان امباپه", "Antoine Griezmann": "آنتوان گریزمان",
    "Olivier Giroud": "اولیویه ژیرو", "Achraf Hakimi": "اشرف حکیمی",
    "Hakim Ziyech": "حکیم زیش", "Sofyan Amrabat": "سفیان آمرابات",
    "Noussair Mazraoui": "نوآیر مزراوی", "Lionel Messi": "لیونل مسی",
    "Cristiano Ronaldo": "کریستیانو رونالدو", "Neymar": "نیمار",
    "Harry Kane": "هری کین", "Robert Lewandowski": "روبرت لواندوفسکی",
    "Luka Modric": "لوکا مودریچ", "Erling Haaland": "ارلینگ هالند",
    "Vinicius Junior": "وینیسیوس جونیور", "Bukayo Saka": "بوکایو ساکا",
    "Phil Foden": "فیل فودن", "Jude Bellingham": "جود بلینگام",
    "Mehdi Taremi": "مهدی طارمی", "Sardar Azmoun": "سردار آزمون",
    "Randal Kolo Muani": "رند کولو موانی", "Marcus Thuram": "مارکوس تورام",
    "Ousmane Dembele": "اوسمن دمبله",
}


def get_flag(t):
    return FLAGS.get(t, "🏳️")


def fa(t, mapping):
    return mapping.get(t, t)


def to_jalali(gs):
    """Best-effort Gregorian -> Jalali conversion for display purposes."""
    try:
        from datetime import datetime
        dt = datetime.fromisoformat(gs.replace("Z", "+00:00"))
        gy, gm, gd = dt.year, dt.month, dt.day
        g_d_m = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334]
        gy2 = gy + 1 if gm > 2 else gy
        days = (
            355666 + (365 * gy) + ((gy2 + 3) // 4) - ((gy2 + 99) // 100)
            + ((gy2 + 399) // 400) + gd + g_d_m[gm - 1]
        )
        jy = -1595 + (33 * (days // 12053))
        days %= 12053
        jy += 4 * (days // 1461)
        days %= 1461
        if days > 365:
            jy += (days - 1) // 365
            days = (days - 1) % 365
        if days < 186:
            jm = 1 + (days // 31)
            jd = 1 + (days % 31)
        else:
            jm = 7 + ((days - 186) // 30)
            jd = 1 + ((days - 186) % 30)
        h = (dt.hour + 3) % 24  # naive UTC -> Tehran (+03:30, minutes dropped)
        m = dt.minute
        return f"{jd}/{jm:02d}/{jy} ساعت {h:02d}:{m:02d}"
    except Exception:
        return gs


def status_fa(status_name, clock):
    """Convert ESPN status codes to Persian labels."""
    mapping = {
        "STATUS_SCHEDULED": "شروع نشده",
        "STATUS_FIRST_HALF": f"نیمه اول {clock}",
        "STATUS_HALFTIME": "استراحت",
        "STATUS_SECOND_HALF": f"نیمه دوم {clock}",
        "STATUS_END_PERIOD": "پایان نیمه",
        "STATUS_FULL_TIME": "پایان بازی",
        "STATUS_OVERTIME": f"وقت اضافه {clock}",
        "STATUS_PENALTY_SHOOTOUT": "ضربات پنالتی",
        "STATUS_POSTPONED": "به تعویق افتاد",
        "STATUS_SUSPENDED": "توقف",
        "STATUS_CANCELLED": "لغو شده",
        "STATUS_IN_PROGRESS": f"در حال برگزاری {clock}",
    }
    return mapping.get(status_name, status_name)


class PersianFormatter:
    def format_prematch(self, m, analysis=None):
        h = m.get("home_team", "")
        a = m.get("away_team", "")
        t = m.get("time", "")
        v = m.get("venue", "")
        s = m.get("stage", "")
        g = m.get("group", "")
        hfn, afn = fa(h, TEAM_FA), fa(a, TEAM_FA)
        ts = to_jalali(t) if "T" in str(t) else t
        r = (
            f"\n{get_flag(h)} *{hfn}* 🆚 *{afn}* {get_flag(a)}\n{SEP}\n{s}\n"
            f"{f'📋 {g}' if g else ''}\n🕐 {ts}\n🏟️ {v}\n"
        )
        if analysis:
            r += f"\n{analysis}\n"
        r += SEP
        return r.strip()

    def format_live_update(self, d, events_text=None):
        h, a = d.get("home_team", ""), d.get("away_team", "")
        hs, as_ = d.get("home_score", 0), d.get("away_score", 0)
        clock = d.get("clock", "0'")
        st = status_fa(d.get("status", ""), clock)
        hf, af = fa(h, TEAM_FA), fa(a, TEAM_FA)
        r = f"\n{get_flag(h)} *{hf}* {hs} - {as_} *{af}* {get_flag(a)}\n{SEP}\n⏱️ *{st}*\n"
        if events_text:
            r += f"\n{events_text}\n"
        r += SEP
        return r.strip()

    def format_goal(self, e):
        t, p, m = e.get("team", ""), e.get("player", ""), e.get("minute", "")
        hs, as_ = e.get("home_score", 0), e.get("away_score", 0)
        ht, at = e.get("home_team", ""), e.get("away_team", "")
        return (
            f"\n⚽⚽⚽ *گل!* ⚽⚽⚽\n{SEP}\n{get_flag(t)} *تیم:* {fa(t, TEAM_FA)}\n"
            f"👤 *بازیکن:* {fa(p, PLAYER_FA)}\n⏱️ *دقیقه:* {m}\n"
            f"📊 *نتیجه:* {get_flag(ht)} {fa(ht, TEAM_FA)} {hs} - {as_} "
            f"{fa(at, TEAM_FA)} {get_flag(at)}\n{SEP}"
        ).strip()

    def format_card(self, e):
        t, p, m = e.get("team", ""), e.get("player", ""), e.get("minute", "")
        ct = e.get("detail", "")
        em = "🟥" if "قرمز" in ct else "🟨"
        return (
            f"\n{em} *{ct}!*\n{SEP}\n{get_flag(t)} *تیم:* {fa(t, TEAM_FA)}\n"
            f"👤 *بازیکن:* {fa(p, PLAYER_FA)}\n⏱️ *دقیقه:* {m}\n{SEP}"
        ).strip()

    def format_postmatch(self, d, stats=None, motm=None):
        h, a = d.get("home_team", ""), d.get("away_team", "")
        hs, as_ = d.get("home_score", 0), d.get("away_score", 0)
        hf, af = fa(h, TEAM_FA), fa(a, TEAM_FA)
        if hs > as_:
            rt = f"🏆 *پیروزی {hf}*"
        elif as_ > hs:
            rt = f"🏆 *پیروزی {af}*"
        else:
            rt = "🤝 *مساوی*"
        r = f"\n{get_flag(h)} *{hf}* {hs} - {as_} *{af}* {get_flag(a)}\n{SEP}\n{rt}\n"
        goals = d.get("goals", [])
        if goals:
            r += "\n⚽ *گل‌زنان:*\n"
            for g in goals:
                r += f"• {fa(g.get('team', ''), TEAM_FA)}: {fa(g.get('player', ''), PLAYER_FA)} ({g.get('minute', '')})\n"
        r += SEP
        return r.strip()

    def format_penalty(self, e):
        t, p = e.get("team", ""), e.get("player", "")
        n, hs, as_ = e.get("penalty_num", 0), e.get("home_penalty", 0), e.get("away_penalty", 0)
        result = e.get("result", "")
        if result == "scored":
            em, rt = "⚽", "گل شد!"
        elif result == "saved":
            em, rt = "🧤", "سیو شد!"
        else:
            em, rt = "❌", "گل نشد!"
        return (
            f"\n{em} *پنالتی #{n}*\n{SEP}\n{get_flag(t)} {fa(t, TEAM_FA)}: {fa(p, PLAYER_FA)}\n"
            f"📋 {rt}\n📊 {hs} - {as_}\n{SEP}"
        ).strip()

    def format_penalty_end(self, d):
        h, a = d.get("home_team", ""), d.get("away_team", "")
        hp, ap = d.get("home_penalty", 0), d.get("away_penalty", 0)
        w = fa(h, TEAM_FA) if hp > ap else fa(a, TEAM_FA)
        return (
            f"\n🏆 *پایان پنالتی‌ها*\n{SEP}\n{get_flag(h)} {fa(h, TEAM_FA)} {hp} - {ap} "
            f"{fa(a, TEAM_FA)} {get_flag(a)}\n🏆 *پیروز:* {w}\n{SEP}"
        ).strip()

    def format_error(self, msg):
        return f"⚠️ *خطا:* {msg}\n{SEP}"

    def format_delay_alert(self, mi, reason):
        h, a = mi.get("home_team", ""), mi.get("away_team", "")
        return (
            f"\n⚠️ *توقف بازی*\n{SEP}\n{get_flag(h)} {fa(h, TEAM_FA)} vs "
            f"{fa(a, TEAM_FA)} {get_flag(a)}\n📋 {reason}\n{SEP}"
        ).strip()
