import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

try:
    from scripts.timeutil import parse_utc_timestamp
except ModuleNotFoundError:
    from timeutil import parse_utc_timestamp


URL = "https://commits.facepunch.com/r/rust_reboot?format=json"
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


def fetch_latest():
    response = requests.get(URL, timeout=30)
    response.raise_for_status()
    payload = response.json()
    results = payload.get("results", []) if isinstance(payload, dict) else []
    if not isinstance(results, list):
        raise RuntimeError("Facepunch API returned an invalid results payload.")

    commits = []
    for raw in results:
        if not isinstance(raw, dict):
            print("Skipping malformed Facepunch commit record: not an object.")
            continue
        try:
            commit_id = int(raw["id"])
            created = str(raw["created"]).strip()
            message = str(raw.get("message", "")).strip()
        except (KeyError, TypeError, ValueError) as error:
            print(f"Skipping malformed Facepunch commit record: {error}")
            continue

        if not created or is_noise(message):
            continue

        user = raw.get("user")
        if not isinstance(user, dict):
            user = {}

        commits.append({
            "id": commit_id,
            "branch": str(raw.get("branch", "")),
            "changeset": str(raw.get("changeset", "")),
            "created": created,
            "message": message,
            "user": str(user.get("name", "Unknown")),
        })

    return commits


def atomic_write_json(path, data):
    temp_path = path.with_name(path.name + ".tmp")
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(temp_path, "w", encoding="utf-8") as file:
        json.dump(data, file, indent=2, ensure_ascii=False)
        file.flush()
        os.fsync(file.fileno())
    os.replace(temp_path, path)


def main():
    existing = load_existing()
    latest = fetch_latest()

    by_id = {}
    for commit in existing + latest:
        try:
            by_id[str(int(commit["id"]))] = commit
        except (KeyError, TypeError, ValueError):
            print("Skipping malformed cached commit record with no valid id.")

    cutoff = datetime.now(timezone.utc) - RETENTION
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
        f"Saved {len(retained)} commits inside the rolling 3-day archive."
    )


if __name__ == "__main__":
    main()
