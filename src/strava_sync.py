"""
Incremental Strava sync → local activities_raw.json.

Uses refresh token to renew access tokens (expire ~6h), then pulls only
activities newer than the latest stored one via the `after` parameter.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests
from dotenv import load_dotenv

TOKEN_URL = "https://www.strava.com/oauth/token"
ACTIVITIES_URL = "https://www.strava.com/api/v3/athlete/activities"
RUN_TYPES = {"Run", "TrailRun", "VirtualRun"}


def _root() -> Path:
    return Path(__file__).resolve().parents[1]


def _load_env() -> None:
    load_dotenv(_root() / ".env")


def _env(name: str) -> str:
    v = os.getenv(name)
    if not v:
        raise RuntimeError(f"Missing {name} in .env")
    return v


def _write_env_tokens(access: str, refresh: str, expires_at: int) -> None:
    """Update token fields in .env while preserving other keys."""
    path = _root() / ".env"
    lines = path.read_text().splitlines() if path.exists() else []
    kv = {}
    order = []
    for line in lines:
        if not line.strip() or line.strip().startswith("#") or "=" not in line:
            order.append(("raw", line))
            continue
        k, val = line.split("=", 1)
        kv[k.strip()] = val.strip()
        order.append(("key", k.strip()))

    kv["STRAVA_ACCESS_TOKEN"] = access
    kv["STRAVA_REFRESH_TOKEN"] = refresh
    kv["STRAVA_EXPIRES_AT"] = str(expires_at)

    seen = set()
    out = []
    for kind, item in order:
        if kind == "raw":
            out.append(item)
        else:
            out.append(f"{item}={kv[item]}")
            seen.add(item)
    for k, v in kv.items():
        if k not in seen:
            out.append(f"{k}={v}")
    path.write_text("\n".join(out) + "\n")


def ensure_access_token() -> str:
    _load_env()
    access = _env("STRAVA_ACCESS_TOKEN")
    refresh = _env("STRAVA_REFRESH_TOKEN")
    expires_at = int(os.getenv("STRAVA_EXPIRES_AT") or "0")
    # refresh 5 minutes early
    if time.time() < expires_at - 300:
        return access

    resp = requests.post(
        TOKEN_URL,
        data={
            "client_id": _env("STRAVA_CLIENT_ID"),
            "client_secret": _env("STRAVA_CLIENT_SECRET"),
            "grant_type": "refresh_token",
            "refresh_token": refresh,
        },
        timeout=30,
    )
    if not resp.ok:
        raise RuntimeError(f"Token refresh failed ({resp.status_code}): {resp.text}")
    data = resp.json()
    access = data["access_token"]
    refresh = data.get("refresh_token", refresh)
    expires_at = int(data["expires_at"])
    _write_env_tokens(access, refresh, expires_at)
    # also refresh process env
    os.environ["STRAVA_ACCESS_TOKEN"] = access
    os.environ["STRAVA_REFRESH_TOKEN"] = refresh
    os.environ["STRAVA_EXPIRES_AT"] = str(expires_at)
    print("Access token refreshed.")
    return access


def _data_path() -> Path:
    return _root() / "data" / "activities_raw.json"


def _load_local() -> List[Dict[str, Any]]:
    path = _data_path()
    if not path.exists():
        return []
    with open(path) as f:
        data = json.load(f)
    return data if isinstance(data, list) else data.get("activities", [])


def _latest_start_epoch(activities: List[Dict[str, Any]]) -> Optional[int]:
    if not activities:
        return None
    best = None
    for a in activities:
        s = a.get("start_date") or a.get("start_date_local")
        if not s:
            continue
        # Strava returns ISO UTC
        from datetime import datetime

        try:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
            epoch = int(dt.timestamp())
        except ValueError:
            continue
        if best is None or epoch > best:
            best = epoch
    return best


def fetch_activities_after(after_epoch: Optional[int], access_token: str) -> List[Dict[str, Any]]:
    headers = {"Authorization": f"Bearer {access_token}"}
    out: List[Dict[str, Any]] = []
    page = 1
    while True:
        params: Dict[str, Any] = {"per_page": 200, "page": page}
        if after_epoch is not None:
            params["after"] = after_epoch
        resp = requests.get(ACTIVITIES_URL, headers=headers, params=params, timeout=60)
        if resp.status_code == 401:
            # force refresh once
            token = ensure_access_token()
            headers = {"Authorization": f"Bearer {token}"}
            resp = requests.get(ACTIVITIES_URL, headers=headers, params=params, timeout=60)
        resp.raise_for_status()
        batch = resp.json()
        if not batch:
            break
        out.extend(batch)
        if len(batch) < 200:
            break
        page += 1
    return out


def merge_activities(
    existing: List[Dict[str, Any]], new: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    by_id = {a["id"]: a for a in existing if "id" in a}
    for a in new:
        by_id[a["id"]] = a
    merged = list(by_id.values())
    merged.sort(key=lambda a: a.get("start_date") or "", reverse=True)
    return merged


def sync(full: bool = False) -> Dict[str, Any]:
    """
    Incremental sync (default) or full re-pull.
    Returns summary stats.
    """
    access = ensure_access_token()
    existing = [] if full else _load_local()
    after = None if full else _latest_start_epoch(existing)
    fresh = fetch_activities_after(after, access)
    # Strava `after` is exclusive on start; still merge by id
    merged = merge_activities(existing, fresh)
    _data_path().parent.mkdir(parents=True, exist_ok=True)
    _data_path().write_text(json.dumps(merged, indent=2))

    n_runs = sum(1 for a in merged if (a.get("type") in RUN_TYPES or a.get("sport_type") in RUN_TYPES))
    summary = {
        "fetched_new": len(fresh),
        "total_activities": len(merged),
        "total_runs": n_runs,
        "after_epoch": after,
        "path": str(_data_path()),
    }
    print(
        f"Sync complete: +{summary['fetched_new']} new → "
        f"{summary['total_activities']} activities ({summary['total_runs']} runs) "
        f"at {summary['path']}"
    )
    return summary


if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser(description="Sync Strava activities into data/activities_raw.json")
    p.add_argument("--full", action="store_true", help="Re-pull all activities (ignore local latest)")
    args = p.parse_args()
    sync(full=args.full)
