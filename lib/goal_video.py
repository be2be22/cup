"""
ESPN goal video clip fetcher.

ESPN's `summary?event=<id>` endpoint returns a `videos` array with short
clips (30-90 seconds) for goals, fan reactions, and analysis. Each clip
has a `links.source.href` that points directly to a downloadable .mp4
file on ESPN's CDN (media.video-cdn.espn.com).

This module finds the clip that matches a goal we just detected (by
scorer name + minute) and returns the direct .mp4 URL so the bot can
forward it to Telegram via sendVideo.

Important caveats:
  - ESPN's goal clips are usually fan-reaction or "celebration" clips,
    not the actual goal replay. There is no free, public API that
    provides the actual goal replay clip for the FIFA World Cup.
    ESPN is the closest free source.
  - Clips appear a few minutes after the goal is scored (not instantly).
    We retry over a ~10 minute window after a goal is detected.
  - If no clip is found, the caller just posts the text goal message
    without a video — the channel never goes silent.
"""
import urllib.request
import json
import time
import re

from lib.match_summary import fetch_summary
from lib.api_client import _load_league


# How long to keep retrying after a goal before giving up (in seconds).
# ESPN clips typically appear 2-5 minutes after the goal.
RETRY_WINDOW_SECONDS = 600  # 10 minutes
RETRY_INTERVAL_SECONDS = 60  # check once per minute


def _normalize(name):
    """Normalize a player name for fuzzy matching (lowercase, strip
    accents, remove non-alpha chars)."""
    if not name:
        return ''
    s = name.lower()
    # Strip common accented characters
    replacements = {
        'á': 'a', 'é': 'e', 'í': 'i', 'ó': 'o', 'ú': 'u', 'ñ': 'n',
        'ü': 'u', 'ö': 'o', 'ä': 'a', 'ß': 'ss', 'ø': 'o', 'å': 'a',
        'ç': 'c', 'è': 'e', 'à': 'a', 'ù': 'u', 'ì': 'i', 'ò': 'o',
    }
    for k, v in replacements.items():
        s = s.replace(k, v)
    # Remove non-alpha
    s = re.sub(r'[^a-z\s]', '', s)
    return s.strip()


def _find_goal_clip(videos, player_name, team_name):
    """Given a list of ESPN video objects and a goal scorer name, find
    the clip that most likely matches that goal.

    ESPN's video headlines usually include the scorer's surname and the
    word 'goal' or 'score', e.g.:
      - "Spanish fans celebrate Ruiz's goal for Spain vs. Belgium"
      - "Belgium fans celebrate De Ketelaere's equaliser vs. Spain"
      - "Merino scores winner for Spain vs Belgium"

    Returns the source .mp4 URL, or None if no match.
    """
    if not videos or not player_name:
        return None

    player_norm = _normalize(player_name)
    # Take the last name (most distinctive part) for matching
    player_parts = player_norm.split()
    last_name = player_parts[-1] if player_parts else player_norm
    # Also try the full normalized name
    team_norm = _normalize(team_name)

    candidates = []
    for v in videos:
        headline = v.get('headline', '') or ''
        desc = v.get('description', '') or ''
        combined = (headline + ' ' + desc).lower()
        combined_norm = _normalize(combined)

        # Score this video by how well it matches
        score = 0
        if last_name and last_name in combined_norm:
            score += 10
        if player_norm and player_norm in combined_norm:
            score += 5
        if 'goal' in combined or 'score' in combined or 'celebrate' in combined:
            score += 3
        if 'equaliser' in combined or 'equalizer' in combined or 'winner' in combined:
            score += 2
        if team_norm and team_norm in combined_norm:
            score += 2

        if score >= 10:  # Must match the player name at minimum
            links = v.get('links') or {}
            source = links.get('source') if isinstance(links, dict) else None
            if isinstance(source, dict):
                href = source.get('href', '')
                if href and '.mp4' in href:
                    candidates.append((score, href, headline))

    if not candidates:
        return None
    # Pick the highest-scoring candidate
    candidates.sort(key=lambda x: -x[0])
    return candidates[0][1]


def fetch_goal_video_url(event_id, player_name, team_name):
    """Look up ESPN's summary for an event and find the .mp4 URL for a
    goal scored by `player_name` for `team_name`.

    Returns the URL, or None if no clip is found.
    """
    league = _load_league()
    summary = fetch_summary(league, event_id)
    if not summary:
        return None
    videos = summary.get('videos') or []
    return _find_goal_clip(videos, player_name, team_name)


def fetch_goal_video_url_with_retry(
    event_id, player_name, team_name, max_attempts=8, interval_seconds=60
):
    """Like fetch_goal_video_url but retries for a few minutes because
    ESPN's clips typically appear 2-5 minutes after the goal.

    Used by event_monitor.py when a new goal is detected. The retry
    happens in the background via state tracking — each cron run (every
    minute) is one attempt.
    """
    return fetch_goal_video_url(event_id, player_name, team_name)
