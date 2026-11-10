import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

try:
    from scripts.timeutil import parse_utc_timestamp
except ModuleNotFoundError:
    from timeutil import parse_utc_timestamp


# Facepunch started writing new Rust commits to /r/Rust on November 8, 2026.
# Keep the former stream for commits still inside the retention window.
SOURCE_URLS = {
    "Rust": "https://commits.facepunch.com/r/Rust?format=json",
    "rust_reboot": "https://commits.facepunch.com/r/rust_reboot?format=json",
}
URL = SOURCE_URLS["rust_reboot"]  # Legacy public endpoint.
MAX_PAGES = 200
MAX_SOURCE_AGE = timedelta(hours=36)
OUTPUT_FILE = Path("site/commits.json")
RETENTION = timedelta(days=3)

NOISE_PREFIXES = (
    "merge from ",
    "merge: from ",
    "~merge from ",
    "update from main",
)


def load_existing():
    if not OUTPUT_FILE.exists():
        return []
    try:
        with open(OUTPUT_FILE, "r", encoding="utf-8") as file:
            data = json.load(file)
    except (json.JSONDecodeError, UnicodeDecodeError, OSError) as error:
        raise RuntimeError(
            f"Existing commit archive is unreadable: {OUTPUT_FILE}"
        ) from error
    if not isinstance(data, list):
        raise RuntimeError("Existing commit archive must be a JSON list.")
    return data


def is_noise(message):
    text = str(message or "").strip()
    if not text:
        return True
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return True
    first = lines[0].lower()
    matches = any(first.startswith(prefix) for prefix in NOISE_PREFIXES)
    return matches and len(lines) == 1


def parse_record(raw, source):
    if not isinstance(raw, dict):
        raise RuntimeError(f"Facepunch {source} returned a non-object commit.")
    try:
        commit_id = int(raw["id"])
        created = str(raw["created"]).strip()
        created_at = parse_utc_timestamp(created)
    except (KeyError, TypeError, ValueError) as error:
        raise RuntimeError(f"Facepunch {source} returned a commit with invalid ID/date.") from error
    if not created or commit_id <= 0:
        raise RuntimeError(f"Facepunch {source} returned a commit with invalid ID/date.")
    if raw.get("repo") not in (None, source):
        raise RuntimeError(f"Facepunch {source} returned a record from another repository.")
    user = raw.get("user")
    if not isinstance(user, dict):
        user = {}
    return ({
        "id": commit_id,
        "branch": str(raw.get("branch", "")),
        "changeset": str(raw.get("changeset", "")),
        "created": created,
        "message": str(raw.get("message", "")).strip(),
        "user": str(user.get("name", "Unknown")),
    }, created_at)


def fetch_source(source, cutoff):
    """Read every page intersecting the retained window, failing on gaps."""
    url = SOURCE_URLS[source]
    commits = []
    seen = set()
    previous_date = None
    first_id = None
    total = None
    take = None
    page_count = 0
    raw_fetched = 0
    source_newest = None
    for page in range(1, MAX_PAGES + 1):
        response = requests.get(url, params={"p": page}, timeout=30)
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise RuntimeError(f"Facepunch {source} returned a non-object page.")
        results = payload.get("results")
        page_total, page_skip, page_take = (payload.get(key) for key in ("total", "skip", "take"))
        if (not isinstance(results, list) or type(page_total) is not int
                or type(page_skip) is not int or type(page_take) is not int
                or page_total < 0 or page_take <= 0 or page_skip != (page - 1) * page_take
                or (take is not None and page_take != take)):
            raise RuntimeError(f"Facepunch {source} returned incomplete pagination metadata on page {page}.")
        if total is not None and page_total != total:
            raise RuntimeError(f"Facepunch {source} page count changed during collection.")
        total, take = page_total, page_take
        expected = min(take, max(total - page_skip, 0))
        if len(results) != expected:
            raise RuntimeError(f"Facepunch {source} returned an incomplete page {page}: {len(results)}/{expected} records.")
        page_count = page
        raw_fetched += len(results)
        reached_cutoff = False
        for raw in results:
            commit, created_at = parse_record(raw, source)
            if previous_date is not None and created_at > previous_date:
                raise RuntimeError(f"Facepunch {source} returned out-of-order dates on page {page}.")
            previous_date = created_at
            if first_id is None:
                first_id = commit["id"]
                source_newest = created_at
            if created_at < cutoff:
                reached_cutoff = True
                continue
            if commit["id"] in seen:
                continue
            seen.add(commit["id"])
            if not is_noise(commit["message"]):
                commits.append(commit)
        if reached_cutoff or page_skip + len(results) >= total:
            break
    else:
        raise RuntimeError(f"Facepunch {source} exceeded the {MAX_PAGES}-page safety limit.")

    # A page boundary can shift if new commits arrive during pagination.
    # Abort instead of silently missing records and retry on a later run.
    check = requests.get(url, params={"p": 1}, timeout=30)
    check.raise_for_status()
    check_payload = check.json()
    check_results = check_payload.get("results") if isinstance(check_payload, dict) else None
    if not isinstance(check_results, list) or (check_results and check_results[0].get("id") != first_id):
        raise RuntimeError(f"Facepunch {source} changed during pagination; retry later.")
    print(f"Facepunch {source}: pages={page_count}, fetched={raw_fetched}, "
          f"accepted={len(commits)}, newest_source={first_id if first_id else 'none'} "
          f"({source_newest.isoformat() if source_newest else 'none'}).")
    return commits


def fetch_latest(cutoff=None):
    if cutoff is None:
        cutoff = datetime.now(timezone.utc) - RETENTION
    by_id = {}
    for source in SOURCE_URLS:
        for commit in fetch_source(source, cutoff):
            by_id[str(commit["id"])] = commit
    return sorted(by_id.values(), key=lambda item: parse_utc_timestamp(item["created"]), reverse=True)


def atomic_write_json(path, data):
    temp_path = path.with_name(path.name + ".tmp")
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(temp_path, "w", encoding="utf-8") as file:
        json.dump(data, file, indent=2, ensure_ascii=False)
        file.flush()
        os.fsync(file.fileno())
    os.replace(temp_path, path)


def main(now=None):
    if now is None:
        now = datetime.now(timezone.utc)
    elif now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    else:
        now = now.astimezone(timezone.utc)
    cutoff = now - RETENTION
    existing = load_existing()
    latest = fetch_latest(cutoff)
    if not latest:
        raise RuntimeError("Facepunch returned no Rust commits in the retention window; archive preserved.")
    newest = parse_utc_timestamp(latest[0]["created"])
    age = now - newest
    print(f"Source freshness: newest={latest[0]['id']} at {newest.isoformat()}, "
          f"age={age}, fetched={len(latest)}, archive_before={len(existing)}.")
    if age > MAX_SOURCE_AGE:
        raise RuntimeError("Facepunch Rust source is stale; archive preserved.")
    existing_dates = [parse_utc_timestamp(item["created"]) for item in existing]
    if existing_dates and max(existing_dates) > newest:
        raise RuntimeError("Facepunch source regressed behind the saved archive; archive preserved.")

    by_id = {}
    for commit in existing + latest:
        try:
            by_id[str(int(commit["id"]))] = commit
        except (KeyError, TypeError, ValueError):
            print("Skipping malformed cached commit record with no valid id.")

    retained = []
    for commit in by_id.values():
        try:
            created = parse_utc_timestamp(commit["created"])
        except (KeyError, TypeError, ValueError):
            print(
                "Skipping cached commit with invalid created timestamp: "
                f"{commit.get('id', '?')}"
            )
            continue
        if created >= cutoff:
            retained.append(commit)

    retained.sort(
        key=lambda item: parse_utc_timestamp(item["created"]),
        reverse=True,
    )
    atomic_write_json(OUTPUT_FILE, retained)
    print(
        f"Saved {len(retained)} commits inside the rolling 3-day archive "
        f"(fetched={len(latest)}, newest_source={latest[0]['id']})."
    )


if __name__ == "__main__":
    main()
