"""
Varzesh3.com video fetcher - searches the Iranian sports site
varzesh3.com for match highlight videos.

When a match ends, we wait 10 minutes for varzesh3 to publish the
highlight video, then search for it on their video search page:
  https://www.varzesh3.com/search/videos?q={query}

The search page returns HTML with links like:
  https://video.varzesh3.com/video/536782/خلاصه-بازی-نروژ-1-انگلیس-2

We fetch that video page and extract the direct .mp4 URL from the
page's HTML (it's embedded in a <script> tag as part of the video
player config).

The .mp4 URL looks like:
  https://video-vcdn.varzesh3.com/videos-quality/2026/07/12/A/kp2kkrp0.mp4

This is a direct, downloadable MP4 that Telegram can fetch via
sendVideo.

No API key needed, no authentication. The site is server-rendered
so we just parse the HTML with regex.
"""
import re
import urllib.request
import urllib.parse
from datetime import datetime, timezone

from lib.formatter import fa, TEAM_FA


# 10-minute cache for search results
_search_cache = {}
_search_cache_time = {}
_CACHE_TTL = 600


def _fetch_html(url, timeout=10):
    """Fetch a URL and return the HTML as a string."""
    try:
        # URL-encode any non-ASCII characters in the URL path
        # (varzesh3 video URLs contain Persian text in the slug)
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
        print(f"[varzesh3] fetch failed for {url}: {e}")
        return None


def _build_search_query(home_team, away_team):
    """Build the Persian search query for varzesh3.
    e.g. ('Norway', 'England') -> 'خلاصه بازی نروژ و انگلیس'"""
    home_fa = fa(home_team, TEAM_FA)
    away_fa = fa(away_team, TEAM_FA)
    return f"خلاصه بازی {home_fa} و {away_fa}"


def _search_videos(query):
    """Search varzesh3.com video search and return a list of video
    page URLs that match the query.
    
    Returns a list of dicts: {'url', 'title', 'video_id'}
    """
    cache_key = query
    now = datetime.now(timezone.utc)
    if cache_key in _search_cache and cache_key in _search_cache_time:
        if (now - _search_cache_time[cache_key]).total_seconds() < _CACHE_TTL:
            return _search_cache[cache_key]

    encoded_q = urllib.parse.quote(query)
    search_url = f"https://www.varzesh3.com/search/videos?q={encoded_q}"
    html = _fetch_html(search_url)
    if not html:
        return []

    # Find video links: https://video.varzesh3.com/video/536782/...
    # Also match /video/536782/... (relative)
    pattern = r'(?:https?://video\.varzesh3\.com)?(/video/(\d+)/[^"\']+)'
    matches = re.findall(pattern, html)

    seen_ids = set()
    results = []
    for path, video_id in matches:
        if video_id in seen_ids:
            continue
        seen_ids.add(video_id)
        full_url = f"https://video.varzesh3.com{path}"
        # Extract the title from the URL slug
        slug = path.rsplit('/', 1)[-1] if '/' in path else ''
        # Convert slug to readable title (replace hyphens with spaces)
        title = slug.replace('-', ' ')
        results.append({
            'url': full_url,
            'video_id': video_id,
            'title': title,
        })

    _search_cache[cache_key] = results
    _search_cache_time[cache_key] = now
    return results


def _extract_mp4_from_video_page(video_url):
    """Fetch a varzesh3 video page and extract the direct .mp4 URL.
    
    The page HTML contains multiple .mp4 URLs. We prefer the
    'videos-quality' (high quality) URL over the 'videos' (standard)
    URL.
    
    Returns (mp4_url, video_id) or (None, None) if not found.
    """
    html = _fetch_html(video_url, timeout=15)
    if not html:
        return None, None

    # Find all .mp4 URLs
    mp4_urls = re.findall(r'(https?://[^"\s\'\\]+\.mp4)', html)
    if not mp4_urls:
        return None, None

    # Clean up any trailing backslashes
    mp4_urls = [u.rstrip('\\') for u in mp4_urls]

    # Prefer 'videos-quality' (high quality) URLs
    hq_urls = [u for u in mp4_urls if 'videos-quality' in u]
    if hq_urls:
        return hq_urls[0], None

    # Fall back to any .mp4 URL
    return mp4_urls[0], None


def _match_best_result(results, home_team, away_team):
    """Pick the best search result that matches the match teams.
    
    We look for a result whose URL slug contains both team names
    (in Persian). The slug looks like:
      خلاصه-بازی-نروژ-1-انگلیس-2
    """
    home_fa = fa(home_team, TEAM_FA)
    away_fa = fa(away_team, TEAM_FA)

    best = None
    best_score = 0
    for r in results:
        title = r.get('title', '')
        score = 0
        if home_fa and home_fa in title:
            score += 10
        if away_fa and away_fa in title:
            score += 10
        if 'خلاصه' in title:
            score += 5
        # Score pattern like "1-2" or "2 - 1"
        if re.search(r'\b\d+\s*[-–]\s*\d+\b', title):
            score += 3

        if score > best_score and score >= 10:  # must match at least one team
            best_score = score
            best = r

    return best


def fetch_varzesh3_highlight(home_team, away_team):
    """Search varzesh3.com for a match highlight video and return the
    direct .mp4 URL.
    
    Returns (mp4_url, video_page_url, title) or (None, None, None) if
    not found.
    
    Used by postmatch.py as a primary source for Iranian/Persian
    highlights (better quality than Reddit for Persian-speaking users).
    """
    query = _build_search_query(home_team, away_team)
    print(f"[varzesh3] searching for: {query}")

    results = _search_videos(query)
    if not results:
        print(f"[varzesh3] no results found")
        return None, None, None

    print(f"[varzesh3] found {len(results)} results:")
    for r in results[:5]:
        print(f"  - {r['title'][:80]}")

    best = _match_best_result(results, home_team, away_team)
    if not best:
        # Fall back to the first result if no good match
        best = results[0]
        print(f"[varzesh3] no strong match, using first result")

    print(f"[varzesh3] best match: {best['title'][:80]}")
    print(f"[varzesh3] fetching video page: {best['url']}")

    mp4_url, _ = _extract_mp4_from_video_page(best['url'])
    if mp4_url:
        print(f"[varzesh3] found MP4: {mp4_url}")
        return mp4_url, best['url'], best['title']

    print(f"[varzesh3] no MP4 URL found on video page")
    return None, None, None
