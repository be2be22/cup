"""
Shared pre-match analysis text builder.

Used by scripts/prematch.py (channel post) and lib/bot_logic.py (bot
button reply) so both places behave identically: try AI analysis first
(with live ESPN context so it's current, not stale), fall back to the
static hand-written dataset, and if neither is available just say so
instead of crashing.
"""
from lib.formatter import fa, TEAM_FA
from lib.ai_analysis import generate_prematch_analysis
from lib.analysis_data import TEAM_ANALYSIS, MATCHUP_PROBABILITIES
from lib.match_summary import fetch_summary, build_match_context
from lib.api_client import _load_league


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


def _fetch_live_context(event_id, home, away):
    """Pull ESPN summary data + format it into a context blob for the AI.
    Returns None if the summary isn't available (e.g. event ID missing
    or ESPN's summary endpoint returns nothing)."""
    if not event_id:
        return None
    try:
        league = _load_league()
        summary = fetch_summary(league, event_id)
        if not summary:
            return None
        ctx = build_match_context(summary, home, away)
        return ctx.get('ai_context') if ctx else None
    except Exception as e:
        print(f"[analysis_builder] live context fetch failed: {e}")
        return None


def build_analysis(home, away, stage='', venue='', group='', event_id=None):
    """AI analysis (with live ESPN context) if configured and reachable,
    otherwise static fallback, otherwise None (caller should just omit
    the analysis section).

    If event_id is provided, we first fetch ESPN's summary for that
    event and pass the live form / leaders / H2H data to the AI prompt
    so the analysis reflects the actual current tournament state."""
    live_context = _fetch_live_context(event_id, home, away)
    ai_text = generate_prematch_analysis(
        fa(home, TEAM_FA), fa(away, TEAM_FA),
        stage=stage, venue=venue, group=group,
        live_context=live_context,
    )
    if ai_text:
        return ai_text
    return static_analysis(home, away)
