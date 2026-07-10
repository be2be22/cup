"""
Shared pre-match analysis text builder.

Used by scripts/prematch.py (channel post) and lib/bot_logic.py (bot
button reply) so both places behave identically: try AI analysis first,
fall back to the static hand-written dataset, and if neither is
available just say so instead of crashing.
"""
from lib.formatter import fa, TEAM_FA
from lib.ai_analysis import generate_prematch_analysis
from lib.analysis_data import TEAM_ANALYSIS, MATCHUP_PROBABILITIES


def static_probabilities(home, away):
    key = (home, away) if (home, away) in MATCHUP_PROBABILITIES else (
        (away, home) if (away, home) in MATCHUP_PROBABILITIES else None
    )
    if key:
        v = MATCHUP_PROBABILITIES[key]
        return {"home": v[0], "draw": v[1], "away": v[2]} if key == (home, away) \
            else {"home": v[2], "draw": v[1], "away": v[0]}
    return {"home": 40, "draw": 30, "away": 30}


def static_analysis(home, away):
    """Best-effort fallback analysis built from the static dataset."""
    d, b = TEAM_ANALYSIS.get(home, {}), TEAM_ANALYSIS.get(away, {})
    if not d and not b:
        return None
    hf, af = fa(home, TEAM_FA), fa(away, TEAM_FA)
    pr = static_probabilities(home, away)
    return (
        f"📊 *تحلیل پیش از بازی:*\n\n"
        f"*{hf}:* {d.get('st', 'اطلاعات کافی موجود نیست.')}\n\n"
        f"*{af}:* {b.get('st', 'اطلاعات کافی موجود نیست.')}\n\n"
        f"🎯 *نتیجه احتمالی:* {hf} {pr['home'] // 10} - {pr['away'] // 10} {af}"
    )


def build_analysis(home, away, stage='', venue='', group=''):
    """AI analysis if configured and reachable, otherwise static fallback,
    otherwise None (caller should just omit the analysis section)."""
    ai_text = generate_prematch_analysis(
        fa(home, TEAM_FA), fa(away, TEAM_FA), stage=stage, venue=venue, group=group
    )
    if ai_text:
        return ai_text
    return static_analysis(home, away)
