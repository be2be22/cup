"""
Reddit r/soccer goal video fetcher.

r/soccer posts goal clips within seconds of them being scored. Each
post's title follows a strict convention:

    "Norway [1] - 0 England - Andreas Schjelderup 36'"

We search r/soccer via the public RSS search endpoint, parse the
results, and look for posts whose title matches the goal we just
detected (by scorer name + minute). When we find a match, we check
the post's external links for one of the common clip hosts:

  - v.redd.it   -> direct MP4 at https://v.redd.it/{id}/CMAF_720.mp4
  - streamable  -> needs API call (not implemented, falls back)
  - streamff    -> needs JS rendering (not implemented, falls back)

We only use v.redd.it for now because it's the only one that exposes
a direct .mp4 URL we can pass to Telegram's sendVideo.

Rate limiting: Reddit aggressively 429s bots. We cache every search
result for 10 minutes and skip a search entirely if we've done one
in the last 30 seconds.
"""
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
import html
import re
import time
import threading

# In-memory cache: (search_query) -> (timestamp, list_of_post_dicts)
# We cache for 10 minutes so we don't re-search for the same goal
# on every cron run.
_search_cache = {}
_CACHE_TTL_SECONDS = 600  # 10 minutes

# Rate limit: minimum seconds between consecutive Reddit requests.
# Reddit 429s aggressively, so we space out requests.
_MIN_REQUEST_INTERVAL = 30  # 30 seconds between requests
_last_request_time = 0.0
_rate_lock = threading.Lock()


def _throttle():
    """Sleep if we've made a Reddit request too recently. Thread-safe."""
    global _last_request_time
    with _rate_lock:
        now = time.time()
        elapsed = now - _last_request_time
        if elapsed < _MIN_REQUEST_INTERVAL:
            time.sleep(_MIN_REQUEST_INTERVAL - elapsed)
        _last_request_time = time.time()


def _normalize_player(name):
    """Normalize a player name for fuzzy matching (lowercase, strip
    accents, keep only alpha+spaces)."""
    if not name:
        return ''
    s = name.lower()
    replacements = {
        'á': 'a', 'é': 'e', 'í': 'i', 'ó': 'o', 'ú': 'u', 'ñ': 'n',
        'ü': 'u', 'ö': 'o', 'ä': 'a', 'ß': 'ss', 'ø': 'o', 'å': 'a',
        'ç': 'c', 'è': 'e', 'à': 'a', 'ù': 'u', 'ì': 'i', 'ò': 'o',
        'ï': 'i', 'ë': 'e', 'Á': 'a', 'É': 'e', 'Í': 'i', 'Ó': 'o',
        'Ú': 'u', 'Ñ': 'n', 'Ü': 'u', 'Ö': 'o', 'Ä': 'a',
    }
    for k, v in replacements.items():
        s = s.replace(k, v)
    s = re.sub(r'[^a-z\s]', '', s)
    return s.strip()


def _extract_vreddit_id(url):
    """Extract the video ID from a v.redd.it URL.
    e.g. 'https://v.redd.it/fmb9jl4l4och1' -> 'fmb9jl4l4och1'"""
    m = re.search(r'v\.redd\.it/([a-zA-Z0-9]+)', url)
    return m.group(1) if m else None


def _vreddit_mp4_url(video_id, quality='720'):
    """Build the direct .mp4 URL for a v.redd.it video.
    Reddit serves CMAF-encoded MP4s at predictable URLs:
      https://v.redd.it/{id}/CMAF_720.mp4   (720p)
      https://v.redd.it/{id}/CMAF_480.m4v   (480p, sometimes)
    We default to 720p since clips are short (~5-10 MB)."""
    return f"https://v.redd.it/{video_id}/CMAF_{quality}.mp4"


def _fetch_reddit_search(query, limit=10):
    """Search r/soccer via the public RSS endpoint. Returns a list of
    post dicts: {'title', 'external_links', 'vreddit_id'}.
    Returns None on any failure (rate limit, network, parse)."""
    cache_key = query
    now = time.time()
    if cache_key in _search_cache:
        cached_at, cached_results = _search_cache[cache_key]
        if now - cached_at < _CACHE_TTL_SECONDS:
            return cached_results

    _throttle()

    encoded = urllib.parse.quote(query)
    url = (
        f"https://www.reddit.com/r/soccer/search.rss"
        f"?q={encoded}&sort=new&restrict_sr=on&limit={limit}"
    )
    try:
        req = urllib.request.Request(
            url,
            headers={
                'User-Agent': 'linux:worldcup_bot:v1.0 (by /u/worldcup_bot)',
                'Accept': 'application/atom+xml',
            },
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = resp.read().decode('utf-8', errors='replace')
    except Exception as e:
        print(f"[reddit_video] search failed for '{query}': {e}")
        return None

    ns = {'atom': 'http://www.w3.org/2005/Atom'}
    try:
        root = ET.fromstring(body)
    except ET.ParseError as e:
        print(f"[reddit_video] RSS parse failed: {e}")
        return None

    entries = root.findall('atom:entry', ns)
    posts = []
    for e in entries:
        title_elem = e.find('atom:title', ns)
        title = title_elem.text if title_elem is not None else ''
        content_elem = e.find('atom:content', ns)
        html_text = ''
        if content_elem is not None and content_elem.text:
            html_text = html.unescape(content_elem.text)

        external_links = []
        for m in re.finditer(r'href="([^"]+)"', html_text):
            link = m.group(1)
            if 'reddit.com' not in link and 'redditstatic' not in link and not link.startswith('#'):
                external_links.append(link)

        vreddit_id = None
        for link in external_links:
            vid = _extract_vreddit_id(link)
            if vid:
                vreddit_id = vid
                break

        posts.append({
            'title': title,
            'external_links': external_links,
            'vreddit_id': vreddit_id,
        })

    _search_cache[cache_key] = (now, posts)
    return posts


def _match_goal_post(posts, player_name, minute_str, home_team, away_team):
    """Find the Reddit post that matches a specific goal.
    r/soccer goal post titles look like:
        "Norway [1] - 0 England - Andreas Schjelderup 36'"
        "Spain 1 - 0 Belgium - Fabián Ruiz 30'"
    We match by scorer name + minute (most reliable signals)."""
    if not posts:
        return None

    player_norm = _normalize_player(player_name)
    # Take the last name (most distinctive part)
    last_name = player_norm.split()[-1] if player_norm else ''
    # Normalize minute (e.g., "36'" -> "36")
    minute_clean = re.sub(r"[^\d+]", '', minute_str or '')

    best_match = None
    best_score = 0
    for post in posts:
        title = post.get('title', '')
        title_lower = title.lower()
        title_norm = _normalize_player(title)

        score = 0
        has_player = False
        has_minute = False

        # Player name match (most important signal)
        if last_name and last_name in title_norm:
            score += 10
            has_player = True
        if player_norm and player_norm in title_norm:
            score += 5
            has_player = True
        # Minute match - CRITICAL for avoiding wrong videos
        # r/soccer goal posts always include the minute, e.g. "Schjelderup 36'"
        if minute_clean and minute_clean in title:
            score += 8
            has_minute = True
        # Score pattern (e.g. "1-0" or "1 - 0")
        if re.search(r'\b\d+\s*-\s*\d+\b', title):
            score += 3
        # Team names match
        home_norm = _normalize_player(home_team)
        away_norm = _normalize_player(away_team)
        if home_norm and home_norm in title_norm:
            score += 3
        if away_norm and away_norm in title_norm:
            score += 3
        # 'Goal' keyword
        if 'goal' in title_lower or 'score' in title_lower:
            score += 1

        # Must have a v.redd.it link AND match the scorer's last name.
        # CRITICAL FIX: also require the minute to match (has_minute=True)
        # to prevent finding OLD videos about the same player from
        # previous matches. Without this, a search for "Bellingham 45'"
        # could match an old "Bellingham 30'" post from a previous game.
        if score > best_score and post.get('vreddit_id') and has_player and has_minute:
            best_score = score
            best_match = post

    return best_match


def fetch_reddit_goal_video(player_name, minute_str, home_team, away_team):
    """Search r/soccer for a goal post matching the given scorer + minute
    + teams, and return a direct .mp4 URL if a v.redd.it-hosted clip is
    found. Returns None on any failure (no match, rate limited, etc.).

    Called by event_monitor.py as a fallback when ESPN doesn't have a
    clip for a goal.
    """
    # Try a few different search queries in order of specificity:
    # 1. Scorer's last name (most specific)
    # 2. "{home_team} {away_team}" (broader)
    queries = []
    player_norm = _normalize_player(player_name)
    last_name = player_norm.split()[-1] if player_norm else ''
    if last_name:
        queries.append(last_name)
    queries.append(f"{home_team} {away_team}")

    for query in queries:
        posts = _fetch_reddit_search(query, limit=15)
        if not posts:
            continue
        match = _match_goal_post(posts, player_name, minute_str, home_team, away_team)
        if match and match.get('vreddit_id'):
            vreddit_id = match['vreddit_id']
            mp4_url = _vreddit_mp4_url(vreddit_id)
            print(f"[reddit_video] found clip for {player_name} ({minute_str}): "
                  f"v.redd.it/{vreddit_id}")
            return mp4_url, match.get('title', '')

    return None, None


def _match_highlight_post(posts, home_team, away_team):
    """Find a Reddit post that contains full match highlights.
    r/soccer highlight posts have titles like:
      - 'Highlights: Norway 1-2 England'
      - 'Extended Highlights: Spain 2-1 Belgium'
      - 'MATCH HIGHLIGHTS: Argentina vs Switzerland'
    """
    if not posts:
        return None

    home_norm = _normalize_player(home_team)
    away_norm = _normalize_player(away_team)

    best_match = None
    best_score = 0
    for post in posts:
        title = post.get('title', '')
        title_lower = title.lower()
        title_norm = _normalize_player(title)

        score = 0
        # Look for 'highlights' or 'extended highlights' keyword
        if 'highlight' in title_lower:
            score += 10
        # Look for both team names
        if home_norm and home_norm in title_norm:
            score += 5
        if away_norm and away_norm in title_norm:
            score += 5
        # Look for a score pattern (e.g. '2-1')
        if re.search(r'\b\d+\s*-\s*\d+\b', title):
            score += 3

        # Must have a v.redd.it link AND match the highlights keyword
        if score > best_score and post.get('vreddit_id') and 'highlight' in title_lower:
            best_score = score
            best_match = post

    return best_match if best_score >= 10 else None


def fetch_reddit_highlight_video(home_team, away_team):
    """Search r/soccer for a full match highlights clip and return the
    direct .mp4 URL. Used by postmatch.py to send a highlights video
    after a match ends.

    Returns (url, title) or (None, None) if no highlights found.
    """
    # Try a few search queries
    queries = [
        f"Highlights {home_team} {away_team}",
        f"{home_team} {away_team} highlights",
        f"{home_team} {away_team}",
    ]

    for query in queries:
        posts = _fetch_reddit_search(query, limit=15)
        if not posts:
            continue
        match = _match_highlight_post(posts, home_team, away_team)
        if match and match.get('vreddit_id'):
            vreddit_id = match['vreddit_id']
            mp4_url = _vreddit_mp4_url(vreddit_id)
            print(f"[reddit_video] found highlights for {home_team} vs {away_team}: "
                  f"v.redd.it/{vreddit_id}")
            return mp4_url, match.get('title', '')

    return None, None


def fetch_reddit_key_moment_video(moment_type, player_name, minute_str, home_team, away_team):
    """Search r/soccer for a key moment clip (save, red card, missed
    penalty, etc.) and return the direct .mp4 URL.

    moment_type: 'save', 'red card', 'missed penalty', 'free kick', etc.
    Used by event_monitor.py to send videos of notable non-goal events.

    Returns (url, title) or (None, None) if no clip found.
    """
    # r/soccer post titles for non-goal moments look like:
    #   'Great save by Pickford (England) vs Norway 35''
    #   'Red Card: Xhaka (Switzerland) vs Argentina 70''
    # We search for the moment type + player/team
    queries = [
        f"{moment_type} {player_name}",
        f"{player_name} {home_team} {away_team}",
        f"{moment_type} {home_team} {away_team}",
    ]

    player_norm = _normalize_player(player_name)
    last_name = player_norm.split()[-1] if player_norm else ''
    moment_lower = moment_type.lower()

    for query in queries:
        posts = _fetch_reddit_search(query, limit=15)
        if not posts:
            continue

        for post in posts:
            title = post.get('title', '')
            title_lower = title.lower()
            title_norm = _normalize_player(title)

            score = 0
            # Match the moment type keyword
            if moment_lower in title_lower:
                score += 10
            # Match player name
            if last_name and last_name in title_norm:
                score += 5
            # Match teams
            home_norm = _normalize_player(home_team)
            away_norm = _normalize_player(away_team)
            if home_norm and home_norm in title_norm:
                score += 2
            if away_norm and away_norm in title_norm:
                score += 2

            if score >= 10 and post.get('vreddit_id'):
                vreddit_id = post['vreddit_id']
                mp4_url = _vreddit_mp4_url(vreddit_id)
                print(f"[reddit_video] found {moment_type} clip for {player_name}: "
                      f"v.redd.it/{vreddit_id}")
                return mp4_url, post.get('title', '')

    return None, None
