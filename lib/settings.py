"""
Central place every module reads secrets/config values from.

Order of precedence:
  1. A real environment variable (works fine if your alwaysdata site
     type does expose a working per-site Environment tab).
  2. local_settings.py in the project root - a file that is
     intentionally NOT committed to git (see .gitignore), so your real
     tokens never end up in the GitHub history, even though this
     project is deployed to the server via `git pull`. Create it once
     directly on the server over SSH - see local_settings.py.example
     for the exact format and README.md / DEPLOY_SSH.md for the exact
     command to create it.
  3. the given default (usually None).
"""
import os

try:
    import local_settings
except ImportError:
    local_settings = None


def get(name, default=None):
    val = os.environ.get(name)
    if val:
        return val
    if local_settings is not None:
        val = getattr(local_settings, name, None)
        if val:
            return val
    return default
