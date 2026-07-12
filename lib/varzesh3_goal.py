"""
Varzesh3.com goal video fetcher.

Searches varzesh3.com for individual goal clips (not just highlights).
The search URL is:
  https://www.varzesh3.com/search/videos?q={query}

For goals, we search for "گل {player_name}" or "گل {team_name}".
The search returns video page URLs like:
  https://video.varzesh3.com/video/536795/گل-اول-آرژانتین-به-سوییس-مک-آلیستر

We then fetch that video page and extract the direct .mp4 URL.

This replaces Reddit r/soccer as the primary source for goal videos
because:
  1. No rate limiting (Reddit 429s constantly)
  2. Persian titles include the player name directly
  3. Faster - no 45s throttle between requests
  4. Better quality (720p from varzesh3 CDN)
  5. Iranian source, better for Persian-speaking users
"""
import re
import urllib.request
import urllib.parse
from lib.formatter import fa, TEAM_FA, PLAYER_FA


# Short cache (2 min) for search results
_search_cache = {}
_search_cache_time = {}
_CACHE_TTL = 120


def _fetch_html(url, timeout=10):
    """Fetch a URL and return HTML as string."""
    try:
        parsed = urllib.parse.urlsplit(url)
        encoded_path = urllib.parse.quote(parsed.path, safe='/')
        url = urllib.parse.urlunsplit((
            parsed.scheme, parsed.netloc, encoded_path,
            parsed.query, parsed.fragment
        ))
        req = urllib.request.Request(
            url,
            headers={
                'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36',
                'Accept': 'text/html,application/xhtml+xml',
                'Accept-Language': 'fa,en;q=0.5',
            },
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode('utf-8', errors='replace')
    except Exception as e:
        print(f"[varzesh3_goal] fetch failed for {url}: {e}")
        return None


def _search_videos(query):
    """Search varzesh3.com and return video page URLs."""
    import time as _time
    cache_key = query
    now = _time.time()
    if cache_key in _search_cache and cache_key in _search_cache_time:
        if now - _search_cache_time[cache_key] < _CACHE_TTL:
            return _search_cache[cache_key]

    encoded_q = urllib.parse.quote(query)
    search_url = f"https://www.varzesh3.com/search/videos?q={encoded_q}"
    html = _fetch_html(search_url)
    if not html:
        return []

    pattern = r'(?:https?://video\.varzesh3\.com)?(/video/(\d+)/[^"\']+)'
    matches = re.findall(pattern, html)

    seen_ids = set()
    results = []
    for path, video_id in matches:
        if video_id in seen_ids:
            continue
        seen_ids.add(video_id)
        full_url = f"https://video.varzesh3.com{path}"
        slug = path.rsplit('/', 1)[-1] if '/' in path else ''
        title = slug.replace('-', ' ')
        results.append({
            'url': full_url,
            'video_id': video_id,
            'title': title,
        })

    _search_cache[cache_key] = results
    _search_cache_time[cache_key] = now
    return results


def _extract_mp4(video_url):
    """Extract the direct .mp4 URL from a varzesh3 video page.
    Returns the URL or None."""
    html = _fetch_html(video_url, timeout=15)
    if not html:
        return None
    mp4_urls = re.findall(r'(https?://[^"\s\'\\]+\.mp4)', html)
    if not mp4_urls:
        return None
    mp4_urls = [u.rstrip('\\') for u in mp4_urls]
    # Prefer 'videos-quality' (high quality) URLs
    hq = [u for u in mp4_urls if 'videos-quality' in u]
    if hq:
        return hq[0]
    return mp4_urls[0]


def _match_goal_video(results, player_name, team_name, minute_str):
    """Pick the best search result that matches the goal scorer.
    varzesh3 goal titles look like:
      'گل اول آرژانتین به سوییس مک آلیستر'
      'گل دوم انگلیس بلینگام'
    """
    if not results:
        return None

    player_fa = fa(player_name, PLAYER_FA) if player_name else ''
    team_fa = fa(team_name, TEAM_FA) if team_name else ''

    # Also try short forms of the player name (last name only)
    player_last = ''
    if player_fa:
        parts = player_fa.split()
        if parts:
            player_last = parts[-1]

    best = None
    best_score = 0
    for r in results:
        title = r.get('title', '')
        score = 0
        # Player name match (most important)
        if player_fa and player_fa in title:
            score += 15
        if player_last and len(player_last) > 2 and player_last in title:
            score += 10
        # Team name match
        if team_fa and team_fa in title:
            score += 5
        # 'گل' keyword
        if 'گل' in title:
            score += 3
        # Goal number (اول=first, دوم=second, etc.)
        if any(w in title for w in ['گل اول', 'گل دوم', 'گل سوم', 'گل چهارم']):
            score += 2

        if score > best_score and score >= 5:
            best_score = score
            best = r

    return best


def fetch_varzesh3_goal_video(player_name, team_name, minute_str='', home_team='', away_team=''):
    """Search varzesh3.com for a goal video clip.

    Returns (mp4_url, video_page_url, title) or (None, None, None).
    """
    player_fa = fa(player_name, PLAYER_FA) if player_name else ''
    team_fa = fa(team_name, TEAM_FA) if team_name else ''

    # Try multiple search queries in order of specificity
    queries = []
    if player_fa:
        queries.append(f"گل {player_fa}")
    if team_fa:
        queries.append(f"گل {team_fa}")
    if home_team and away_team:
        queries.append(f"گل {fa(home_team, TEAM_FA)} {fa(away_team, TEAM_FA)}")

    for query in queries:
        print(f"[varzesh3_goal] searching: {query}")
        results = _search_videos(query)
        if not results:
            continue

        best = _match_goal_video(results, player_name, team_name, minute_str)
        if not best:
            continue

        print(f"[varzesh3_goal] best match: {best['title'][:80]}")
        mp4 = _extract_mp4(best['url'])
        if mp4:
            print(f"[varzesh3_goal] found MP4: {mp4}")
            return mp4, best['url'], best['title']

    print(f"[varzesh3_goal] no goal video found")
    return None, None, None


def fetch_varzesh3_key_moment(moment_type, player_name, team_name, minute_str='', home_team='', away_team=''):
    """Search varzesh3.com for a key moment video (VAR, red card, save, etc.).

    moment_type: 'VAR', 'کارت قرمز', 'سیو', etc. (Persian or English)
    Returns (mp4_url, video_page_url, title) or (None, None, None).
    """
    player_fa = fa(player_name, PLAYER_FA) if player_name else ''
    team_fa = fa(team_name, TEAM_FA) if team_name else ''

    # Translate moment_type to Persian
    moment_fa = {
        'VAR': 'وار',
        'red card': 'کارت قرمز',
        'yellow card': 'کارت زرد',
        'save': 'سیو',
        'penalty': 'پنالتی',
    }.get(moment_type.lower(), moment_type)

    queries = []
    if player_fa and moment_fa:
        queries.append(f"{moment_fa} {player_fa}")
    if team_fa and moment_fa:
        queries.append(f"{moment_fa} {team_fa}")
    if home_team and away_team:
        queries.append(f"{moment_fa} {fa(home_team, TEAM_FA)} {fa(away_team, TEAM_FA)}")

    for query in queries:
        print(f"[varzesh3_goal] searching key moment: {query}")
        results = _search_videos(query)
        if not results:
            continue

        # Use the first result that matches
        best = None
        best_score = 0
        for r in results:
            title = r.get('title', '')
            score = 0
            if moment_fa and moment_fa in title:
                score += 10
            if player_fa and player_fa in title:
                score += 10
            if team_fa and team_fa in title:
                score += 5
            if score > best_score and score >= 5:
                best_score = score
                best = r

        if not best:
            continue

        print(f"[varzesh3_goal] best match: {best['title'][:80]}")
        mp4 = _extract_mp4(best['url'])
        if mp4:
            print(f"[varzesh3_goal] found MP4: {mp4}")
            return mp4, best['url'], best['title']

    return None, None, None
