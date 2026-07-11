"""
AI-powered Persian translation of player names.

When a goal is scored by a player whose name isn't in the static
PLAYER_FA dictionary (lib/formatter.py), this module asks the AI to
translate the name to Persian. Translations are cached in memory for
the process lifetime and also persisted to disk (player_translations.json)
so they survive across cron runs.

Examples:
  'Andreas Schjelderup' -> 'آندریاس شلدروپ'
  'Elliot Anderson'      -> 'الیوت اندرسون'
  'Fabián Ruiz'          -> 'فابیان رویز'
  'Charles De Ketelaere' -> 'چارلز د کتلر'

The cache is keyed by the original (Latin) name so we never call the
AI twice for the same player. The on-disk cache is loaded once at
startup and appended to whenever a new translation is made.
"""
import json
import os
import urllib.request
import threading

from lib import settings
from lib.ai_analysis import _extract_json, _config

# In-memory cache: original_name -> persian_name
_cache = {}
_cache_loaded = False
_cache_lock = threading.Lock()

# Path to the persistent on-disk cache. Lives next to state.json so
# it's writable on the alwaysdata server.
CACHE_FILE = os.path.join(os.path.dirname(__file__), '..', 'player_translations.json')

# Timeout for the AI translation call - keep it short so we don't
# block the goal notification if the AI is slow.
TRANSLATE_TIMEOUT = 15


def _load_cache():
    """Load the on-disk cache into memory (once, thread-safe)."""
    global _cache_loaded
    with _cache_lock:
        if _cache_loaded:
            return
        try:
            if os.path.exists(CACHE_FILE):
                with open(CACHE_FILE, encoding='utf-8') as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    _cache.update(data)
        except Exception as e:
            print(f"[player_translator] failed to load cache: {e}")
        _cache_loaded = True


def _save_cache():
    """Persist the in-memory cache to disk."""
    try:
        with open(CACHE_FILE, 'w', encoding='utf-8') as f:
            json.dump(_cache, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[player_translator] failed to save cache: {e}")


def _call_ai_translate(names):
    """Ask the AI to translate a batch of player names to Persian.

    `names` is a list of Latin-script names. Returns a dict mapping
    each name to its Persian translation, or None on failure.
    """
    base, key, model = _config()
    if not base or not key:
        return None

    # For a single name, use a simple prompt (faster, more reliable).
    # For multiple names, ask for a numbered list which is easy to parse.
    if len(names) == 1:
        name = names[0]
        prompt = (
            f"اسم فوتبالیست «{name}» رو به فارسی بنویس. "
            "فقط خود اسم فارسی رو بنویس، هیچ چیز دیگه‌ای نگو. "
            "از حرف فارسی «ی» استفاده کن نه «ي» عربی."
        )
    else:
        names_list = "\n".join(f"{i+1}. {n}" for i, n in enumerate(names))
        prompt = (
            "این اسم‌های فوتبالیست رو به فارسی بنویس. برای هر کدوم، فقط "
            "اسم فارسی رو توی یه خط بنویس (شماره‌گذاری شده):\n\n"
            f"{names_list}\n\n"
            "مثال فرمت پاسخ:\n"
            "1. ترجمه فارسی اول\n"
            "2. ترجمه فارسی دوم\n"
            "از حرف فارسی «ی» استفاده کن نه «ي» عربی. هیچ توضیح اضافه نده."
        )

    payload = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.3,
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
        with urllib.request.urlopen(req, timeout=TRANSLATE_TIMEOUT) as resp:
            raw = resp.read().decode()
        data = _extract_json(raw)
        content = data["choices"][0]["message"]["content"].strip()

        if len(names) == 1:
            # Single name - the content should be just the translation
            # (maybe with a leading number or punctuation)
            translation = content.strip().strip('"').strip('\'').strip('*').strip()
            # Remove leading "1." or similar
            import re
            translation = re.sub(r'^\d+\.\s*', '', translation)
            # Take the first line only (in case AI added extra text)
            translation = translation.split('\n')[0].strip()
            # Normalize Arabic ي to Persian ی
            translation = translation.replace('ي', 'ی').replace('ك', 'ک')
            if translation:
                return {names[0]: translation}
        else:
            # Multiple names - parse the numbered list
            translations = {}
            lines = content.strip().split('\n')
            for i, line in enumerate(lines):
                line = line.strip()
                if not line:
                    continue
                # Remove leading number and dot
                import re
                m = re.match(r'^\d+\.\s*(.+)$', line)
                if m:
                    translation = m.group(1).strip().strip('"').strip('\'').strip('*').strip()
                    # Normalize Arabic chars
                    translation = translation.replace('ي', 'ی').replace('ك', 'ک')
                    if i < len(names) and translation:
                        translations[names[i]] = translation
            if translations:
                return translations
    except Exception as e:
        print(f"[player_translator] AI translate failed: {e}")
    return None


def translate_player_name(name):
    """Translate a single player name to Persian.

    Returns the Persian name, or the original name if translation fails.
    Uses the in-memory + on-disk cache so each name is only translated
    once across the entire tournament.
    """
    if not name:
        return name

    _load_cache()

    # Check cache first
    with _cache_lock:
        if name in _cache:
            return _cache[name]

    # Not in cache - ask the AI
    translations = _call_ai_translate([name])
    persian_name = name  # default: return original
    if translations and name in translations:
        translated = translations[name]
        if translated and isinstance(translated, str):
            persian_name = translated.strip()

    # Only cache if the translation actually succeeded (different from
    # the original). This way, a failed translation will be retried on
    # the next call instead of being permanently cached as the original.
    if persian_name != name:
        with _cache_lock:
            _cache[name] = persian_name
        _save_cache()

    return persian_name


def translate_player_names(names):
    """Translate a batch of player names at once (more efficient than
    calling translate_player_name one-by-one).

    `names` is a list of Latin-script names. Returns a dict mapping
    each name to its Persian translation (or the original if translation
    failed).
    """
    if not names:
        return {}

    _load_cache()

    # Filter out names that are already cached
    uncached = [n for n in names if n and n not in _cache]
    result = {}

    with _cache_lock:
        for n in names:
            if n in _cache:
                result[n] = _cache[n]

    if not uncached:
        return result

    # Translate the uncached batch in one AI call
    translations = _call_ai_translate(uncached)
    cache_updated = False
    for n in uncached:
        persian = n  # default
        if translations and n in translations:
            translated = translations[n]
            if translated and isinstance(translated, str):
                persian = translated.strip()
        result[n] = persian
        # Only cache successful translations
        if persian != n:
            with _cache_lock:
                _cache[n] = persian
            cache_updated = True
    if cache_updated:
        _save_cache()

    return result
