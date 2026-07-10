"""Small JSON-file-backed state store, shared by all monitor scripts."""
import json
import os
from datetime import datetime

STATE_FILE = os.path.join(os.path.dirname(__file__), '..', 'state.json')

_DEFAULT_STATE = {
    "active_matches": [],
    "match_states": {},
    "last_scheduler_run": None,
}


def load():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
            # Backfill any keys missing from older state files.
            for k, v in _DEFAULT_STATE.items():
                data.setdefault(k, v)
            return data
        except (json.JSONDecodeError, OSError):
            pass
    return dict(_DEFAULT_STATE)


def save(state):
    with open(STATE_FILE, 'w', encoding='utf-8') as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


def update_match_state(match_id, **kwargs):
    s = load()
    if match_id not in s["match_states"]:
        s["match_states"][match_id] = {}
    s["match_states"][match_id].update(kwargs)
    s["match_states"][match_id]["last_updated"] = datetime.utcnow().isoformat()
    save(s)
    return s["match_states"][match_id]


def get_match_state(match_id):
    return load()["match_states"].get(match_id, {})


def add_active_match(match_id):
    s = load()
    if match_id not in s["active_matches"]:
        s["active_matches"].append(match_id)
        save(s)


def remove_active_match(match_id):
    s = load()
    if match_id in s["active_matches"]:
        s["active_matches"].remove(match_id)
        save(s)


def get_active_matches():
    return load()["active_matches"]
