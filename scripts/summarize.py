import json
import os
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import requests


COMMITS_FILE = Path("site/commits.json")
SUMMARY_FILE = Path("site/summaries.json")

MODEL = "google/gemma-4-31b-it:free"
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"


def load_json(path, default):
    if not path.exists():
        return default

    with open(path, "r", encoding="utf-8") as file:
        return json.load(file)


def group_by_day(commits):
    grouped = defaultdict(list)

    for commit in commits:
        day = datetime.fromisoformat(commit["created"]).date().isoformat()
        grouped[day].append(commit)

    return grouped


def commit_signature(commits):
    ids = sorted(str(commit["id"]) for commit in commits)
    return ",".join(ids)


def summarize_day(api_key, day, commits):
    commit_text = []

    for commit in commits:
        branch = commit["branch"].replace("main/", "")

        commit_text.append(
            f"""
Branch: {branch}
Author: {commit['author']}
Message: {commit['message']}
""".strip()
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
- Preserve useful specifics such as item names, numbers, affected systems, and exact fixes.
- Be factual and neutral.
- Do not speculate.
- Do not say unfinished work is released or available to players.
- If work is experimental or development-only, say so clearly.
- Avoid phrases like "significant work has been done" or "has been implemented".
- Prefer wording like "Added", "Fixed", "Updated", "Continued work on", or "Experimental work on".
- Ignore merge/admin/build noise.
- Avoid developer names and internal branch names unless genuinely useful.
- Do not mention commit IDs.
- Keep the entire digest concise enough to skim in an RSS widget.
- Use Markdown headings and bullet points.
- Return only the finished digest.
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
        print(f"OpenRouter rate-limited {day}; keeping previous summary.")
        return None

    response.raise_for_status()

    data = response.json()
    text = data["choices"][0]["message"]["content"].strip()

    bad_markers = (
        "We need to produce",
        "Let's identify themes",
        "<unk>",
        "We have many commits",
    )

    if any(marker in text for marker in bad_markers):
        print(f"Rejected bad AI output for {day}; keeping previous summary.")
        return None

    return text


def main():
    api_key = os.environ.get("OPENROUTER_API_KEY")

    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY is not set.")

    commits = load_json(COMMITS_FILE, [])
    old_summaries = load_json(SUMMARY_FILE, {})

    grouped = group_by_day(commits)
    summaries = {}

    today = datetime.now().date().isoformat()

    for day in sorted(grouped.keys(), reverse=True):
        commits_for_day = grouped[day]
        signature = commit_signature(commits_for_day)

        old_entry = old_summaries.get(day)

        # Keep historical days unchanged if already summarized
        if day != today and old_entry:
            summaries[day] = old_entry
            print(f"Keeping cached summary for {day}.")
            continue

        # If today's commit set has not changed, reuse old summary
        if (
            old_entry
            and old_entry.get("commit_signature") == signature
        ):
            summaries[day] = old_entry
            print(f"No new commits for {day}; reusing cached summary.")
            continue

        print(
            f"New commits detected for {day}; "
            f"summarizing {len(commits_for_day)} commits..."
        )

        new_summary = summarize_day(
            api_key,
            day,
            commits_for_day,
        )

        # If AI fails or rate-limits, preserve the previous good summary
        if new_summary is None:
            if old_entry:
                summaries[day] = old_entry
            else:
                summaries[day] = {
                    "commit_count": len(commits_for_day),
                    "commit_signature": signature,
                    "summary": (
                        "AI summary temporarily unavailable. "
                        "The commit archive was updated successfully."
                    ),
                }

            continue

        summaries[day] = {
            "commit_count": len(commits_for_day),
            "commit_signature": signature,
            "summary": new_summary,
        }

    with open(SUMMARY_FILE, "w", encoding="utf-8") as file:
        json.dump(
            summaries,
            file,
            indent=2,
            ensure_ascii=False,
        )

    print(f"Saved {len(summaries)} daily summaries.")


if __name__ == "__main__":
    main()
