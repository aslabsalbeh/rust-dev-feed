import json
from datetime import datetime, timedelta
from pathlib import Path

import requests


URL = "https://commits.facepunch.com/r/rust_reboot?format=json"

OUTPUT_DIR = Path("site")
OUTPUT_FILE = OUTPUT_DIR / "commits.json"


def is_noise(message):
    text = message.strip().lower()

    noise_prefixes = (
        "merge from ",
        "~merge from ",
        "merge: from ",
        "update from main",
    )

    return text.startswith(noise_prefixes)


def load_existing():
    if not OUTPUT_FILE.exists():
        return []

    try:
        with open(OUTPUT_FILE, "r", encoding="utf-8") as file:
            return json.load(file)
    except Exception:
        return []


def fetch_latest():
    response = requests.get(URL, timeout=30)
    response.raise_for_status()

    data = response.json()

    useful = []

    for commit in data["results"]:
        message = commit.get("message", "").strip()

        if not message:
            continue

        if is_noise(message):
            continue

        useful.append(
            {
                "id": commit["id"],
                "branch": commit["branch"],
                "changeset": commit["changeset"],
                "created": commit["created"],
                "message": message,
                "author": commit["user"]["name"],
            }
        )

    return useful


def main():
    OUTPUT_DIR.mkdir(exist_ok=True)

    existing = load_existing()
    latest = fetch_latest()

    by_id = {}

    for commit in existing:
        by_id[commit["id"]] = commit

    for commit in latest:
        by_id[commit["id"]] = commit

    cutoff = datetime.now() - timedelta(days=3)

    kept = []

    for commit in by_id.values():
        created = datetime.fromisoformat(commit["created"])

        if created >= cutoff:
            kept.append(commit)

    kept.sort(
        key=lambda commit: commit["created"],
        reverse=True
    )

    with open(OUTPUT_FILE, "w", encoding="utf-8") as file:
        json.dump(
            kept,
            file,
            indent=2,
            ensure_ascii=False,
        )

    print(f"Fetched {len(latest)} useful commits.")
    print(f"Stored {len(kept)} commits from the last 3 days.")


if __name__ == "__main__":
    main()
