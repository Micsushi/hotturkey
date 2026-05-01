# User-editable keyword lists and known-game exe names (~/.hotturkey/tracked_targets.json).

from __future__ import annotations

import json
import os
import shutil
from typing import Any, Dict, FrozenSet, List

import hotturkey.config as config

LIST_KEYS = (
    "browsers",
    "tracked_sites",
    "bonus_sites",
    "bonus_apps",
    "social_apps_or_sites",
)

_PACKAGED_DEFAULT = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "default_tracked_targets.json",
)

_META_PREFIX = "_"

_cache_data: Dict[str, Any] | None = None
_cache_path: str | None = None
_cache_mtime: float | None = None


def _normalize_keyword_list(items: Any) -> List[str]:
    if not isinstance(items, list):
        return []
    out: List[str] = []
    for x in items:
        s = str(x).strip().lower()
        if s:
            out.append(s)
    return out


def _normalize_exe_frozenset(items: Any) -> FrozenSet[str]:
    if not isinstance(items, list):
        return frozenset()
    out: List[str] = []
    for x in items:
        s = str(x).strip().lower()
        if not s:
            continue
        if not s.endswith(".exe"):
            s = f"{s}.exe"
        out.append(s)
    return frozenset(out)


def _read_json(path: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            blob = json.load(handle)
        return blob if isinstance(blob, dict) else {}
    except (json.JSONDecodeError, IOError, OSError, TypeError):
        return {}


def _strip_meta(blob: dict) -> dict:
    return {k: v for k, v in blob.items() if not k.startswith(_META_PREFIX)}


def _parse_from_flat_raw(raw: dict) -> dict:
    out: Dict[str, Any] = {}
    for key in LIST_KEYS:
        val = raw.get(key)
        out[key] = _normalize_keyword_list(val) if val is not None else []
    ex = raw.get("known_game_executables")
    out["known_game_executables"] = _normalize_exe_frozenset(
        ex if ex is not None else []
    )
    return out


def _defaults_from_packaged() -> dict:
    if not os.path.isfile(_PACKAGED_DEFAULT):
        return _parse_from_flat_raw({})
    raw = _strip_meta(_read_json(_PACKAGED_DEFAULT))
    return _parse_from_flat_raw(raw)


def _install_user_defaults() -> None:
    os.makedirs(config.STATE_DIR, exist_ok=True)
    if os.path.isfile(_PACKAGED_DEFAULT):
        shutil.copy2(_PACKAGED_DEFAULT, config.TRACKED_TARGETS_FILE)
        return
    minimal = {
        "_about": "edit lists; see README or default_tracked_targets.json in repo"
    }
    for key in LIST_KEYS:
        minimal[key] = []
    minimal["known_game_executables"] = []
    with open(config.TRACKED_TARGETS_FILE, "w", encoding="utf-8") as handle:
        json.dump(minimal, handle, indent=2)
        handle.write("\n")


def merge_user_with_defaults(user_raw_stripped: dict, defaults: dict) -> dict:
    """Absent JSON keys use packaged defaults; present keys (including []) use user lists."""
    out: Dict[str, Any] = {}
    for key in LIST_KEYS:
        if key in user_raw_stripped and isinstance(user_raw_stripped[key], list):
            out[key] = _normalize_keyword_list(user_raw_stripped[key])
        else:
            out[key] = list(defaults.get(key, []))

    ga = "known_game_executables"
    if ga in user_raw_stripped and isinstance(user_raw_stripped[ga], list):
        out[ga] = _normalize_exe_frozenset(user_raw_stripped[ga])
    else:
        out[ga] = defaults.get(ga, frozenset())

    assert isinstance(out[ga], frozenset)
    return out


def load_tracked_targets_from_disk(*, ensure_file: bool = True) -> dict:
    if ensure_file and not os.path.isfile(config.TRACKED_TARGETS_FILE):
        _install_user_defaults()

    defaults = _defaults_from_packaged()
    blob = _strip_meta(_read_json(config.TRACKED_TARGETS_FILE))

    if not blob and not defaults:
        return merge_user_with_defaults({}, _parse_from_flat_raw({}))

    if not blob:
        return defaults

    return merge_user_with_defaults(blob, defaults)


def refresh_tracked_targets_cache() -> None:
    """Drop cached snapshot after tests overwrite tracked_targets.json."""
    global _cache_data, _cache_path, _cache_mtime
    _cache_data = None
    _cache_path = None
    _cache_mtime = None


def get_tracked_targets() -> dict:
    global _cache_data, _cache_path, _cache_mtime

    load_tracked_targets_from_disk(ensure_file=True)
    path = config.TRACKED_TARGETS_FILE

    try:
        mtime = os.path.getmtime(path)
    except OSError:
        mtime = 0.0

    if _cache_data is None or _cache_path != path or _cache_mtime != mtime:
        _cache_data = load_tracked_targets_from_disk(ensure_file=False)
        _cache_path = path
        _cache_mtime = mtime

    assert _cache_data is not None
    return _cache_data
