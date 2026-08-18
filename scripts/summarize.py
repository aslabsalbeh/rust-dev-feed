import json
import os
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import requests


COMMITS_FILE = Path("site/commits.json")
SUMMARY_FILE = Path("site/summaries.json")

LOCAL_TZ = ZoneInfo("America/Toronto")

MODEL = "google/gemma-4-31b-it:free"
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"


BAD_MARKERS = (
    "We need to produce",
    "Let's identify themes",
    "We have many commits",
    "<unk>",
)


def load_json(path, default):
    if not path.exists():
        return default

    try:
        with open(path, "r", encoding="utf-8") as file:
            return json.load(file)
    except Exception:
        return default


def commit_local_date(commit):
    """
    Facepunch timestamps have no timezone suffix.
    Treat them as UTC, then convert to Ottawa/Toronto time.
    """

    created_utc = datetime.fromisoformat(
        commit["created"]
    ).replace(tzinfo=timezone.utc)

    created_local = created_utc.astimezone(LOCAL_TZ)

    return created_local.date().isoformat()


def group_by_day(commits):
    grouped = defaultdict(list)

    for commit in commits:
        day = commit_local_date(commit)
        grouped[day].append(commit)

    return grouped


def commit_signature(commits):
    """
    Stable signature used to determine whether the day's
    commit collection changed since the previous run.
    """

    ids = sorted(str(commit["id"]) for commit in commits)
    return ",".join(ids)


def is_bad_summary(text):
    if not text:
        return True

    lowered = text.lower()

    for marker in BAD_MARKERS:
        if marker.lower() in lowered:
            return True

    return False


def summarize_day(api_key, day, commits):
    commit_text = []

    for commit in commits:
        branch = commit["branch"]

        if branch.startswith("main/"):
            branch = branch[5:]

        commit_text.append(
            "\n".join(
                [
                    f"Branch: {branch}",
                    f"Author: {commit['author']}",
                    f"Message: {commit['message']}",
                ]
            )
        )

    prompt = f"""
You are creating a compact daily development digest for the game Rust
using official Facepunch source-control commit messages.

Date:
{day}

Commits:

{chr(10).join(commit_text)}

Create a compact daily Rust development digest for an RSS/start-page widget.

Rules:
- Group related commits into 3 to 6 clear topic sections.
- Use short, human-friendly section names.
- Prefer concise bullets over paragraphs.
- Keep most bullets to one sentence.
- Combine closely related commits into one bullet.
- Preserve useful specifics such as item names, numbers, affected systems,
  and exact fixes.
- Be factual and neutral.
- Do not speculate.
- Do not claim unfinished work is released or available to players.
- If work is experimental, internal, testing-related, or development-only,
  make that clear.
- Prefer wording such as "Added", "Fixed", "Updated",
  "Continued work on", or "Experimental work on".
- Ignore merge, administrative, build, and source-control noise.
- Avoid developer names unless genuinely useful.
- Avoid internal branch names unless genuinely useful.
- Do not mention commit IDs.
- Do not include a title or date at the beginning.
- Start directly with the first topic heading.
- Use Markdown headings and bullet points.
- Keep the entire digest concise enough to skim in an RSS widget.
- Return ONLY the finished digest.
"""

    response = requests.post(
        OPENROUTER_URL,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": MODEL,
            "messages": [
                {
                    "role": "user",
                    "content": prompt,
                }
            ],
            "temperature": 0.2,
        },
        timeout=90,
    )

    if response.status_code == 429:
        print(
            f"OpenRouter rate-limited {day}; "
            "keeping previous summary."
        )
        return None

    if not response.ok:
        print(
            f"OpenRouter error {response.status_code} "
            f"for {day}: {response.text[:300]}"
        )
        return None

    data = response.json()

    try:
        text = (
            data["choices"][0]["message"]["content"]
            .strip()
        )
    except Exception:
        print(f"Invalid OpenRouter response for {day}.")
        return None

    if is_bad_summary(text):
        print(
            f"Rejected bad AI output for {day}; "
            "keeping previous summary."
        )
        return None

    return text


def main():
    api_key = os.environ.get("OPENROUTER_API_KEY")

    if not api_key:
        raise RuntimeError(
            "OPENROUTER_API_KEY is not set."
        )

    commits = load_json(COMMITS_FILE, [])
    old_summaries = load_json(SUMMARY_FILE, {})

    grouped = group_by_day(commits)

    now_local = datetime.now(LOCAL_TZ)
    today = now_local.date().isoformat()

    # Only keep the newest 3 calendar days that actually
    # contain collected commits.
    valid_days = sorted(
        grouped.keys(),
        reverse=True,
    )[:3]

    summaries = {}

    for day in valid_days:
        commits_for_day = grouped[day]
        signature = commit_signature(commits_for_day)

        old_entry = old_summaries.get(day)

        old_is_good = (
            old_entry
            and not is_bad_summary(
                old_entry.get("summary", "")
            )
        )

        # Historical day:
        # reuse it if we already have a valid cached summary
        # with the same commit signature.
        if (
            day != today
            and old_is_good
            and old_entry.get("commit_signature") == signature
        ):
            summaries[day] = old_entry
            print(
                f"Keeping cached summary for {day}."
            )
            continue

        # Today's commits have not changed.
        if (
            day == today
            and old_is_good
            and old_entry.get("commit_signature") == signature
        ):
            summaries[day] = old_entry
            print(
                f"No new commits for {day}; "
                "reusing cached summary."
            )
            continue

        print(
            f"New or changed commits detected for {day}; "
            f"summarizing {len(commits_for_day)} commits..."
        )

        new_summary = summarize_day(
            api_key,
            day,
            commits_for_day,
        )

        if new_summary is not None:
            summaries[day] = {
                "commit_count": len(commits_for_day),
                "commit_signature": signature,
                "summary": new_summary,
            }

            print(
                f"Saved new summary for {day}."
            )

        elif old_is_good:
            # IMPORTANT:
            # Keep the OLD signature when AI fails.
            # This makes the next workflow run try again.
            summaries[day] = old_entry

            print(
                f"Preserved previous good summary "
                f"for {day}."
            )

        else:
            # No usable AI summary exists yet.
            #
            # We intentionally don't pretend this signature
            # has been summarized successfully.
            summaries[day] = {
                "commit_count": len(commits_for_day),
                "commit_signature": "",
                "summary": (
                    "AI summary temporarily unavailable. "
                    "The development commit archive was "
                    "updated successfully."
                ),
            }

            print(
                f"No previous valid summary available "
                f"for {day}."
            )

    with open(
        SUMMARY_FILE,
        "w",
        encoding="utf-8",
    ) as file:
        json.dump(
            summaries,
            file,
            indent=2,
            ensure_ascii=False,
        )

    print(
        f"Saved {len(summaries)} daily summaries."
    )


if __name__ == "__main__":
    main()
