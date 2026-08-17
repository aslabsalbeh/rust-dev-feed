import json
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


def main():
    response = requests.get(URL, timeout=30)
    response.raise_for_status()

    data = response.json()
    commits = data["results"]

    useful_commits = []

    for commit in commits:
        message = commit.get("message", "").strip()

        if not message:
            continue

        if is_noise(message):
            continue

        useful_commits.append(
            {
                "id": commit["id"],
                "branch": commit["branch"],
                "changeset": commit["changeset"],
                "created": commit["created"],
                "message": message,
                "author": commit["user"]["name"],
            }
        )

    OUTPUT_DIR.mkdir(exist_ok=True)

    with open(OUTPUT_FILE, "w", encoding="utf-8") as file:
        json.dump(
            useful_commits,
            file,
            indent=2,
            ensure_ascii=False,
        )

    print(f"Saved {len(useful_commits)} useful commits.")


if __name__ == "__main__":
    main()
