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


def load_commits():
    with open(COMMITS_FILE, "r", encoding="utf-8") as file:
        return json.load(file)


def group_by_day(commits):
    grouped = defaultdict(list)

    for commit in commits:
        day = datetime.fromisoformat(commit["created"]).date().isoformat()
        grouped[day].append(commit)

    return grouped


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

    response.raise_for_status()

    data = response.json()

    return data["choices"][0]["message"]["content"].strip()


def main():
    api_key = os.environ.get("OPENROUTER_API_KEY")

    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY is not set.")

    commits = load_commits()
    grouped = group_by_day(commits)

    summaries = {}

    for day in sorted(grouped.keys(), reverse=True):
        commits_for_day = grouped[day]

        print(
            f"Summarizing {day} "
            f"({len(commits_for_day)} commits) with OpenRouter..."
        )

        summary = summarize_day(
            api_key,
            day,
            commits_for_day,
        )

        summaries[day] = {
            "commit_count": len(commits_for_day),
            "summary": summary,
        }

    with open(SUMMARY_FILE, "w", encoding="utf-8") as file:
        json.dump(
            summaries,
            file,
            indent=2,
            ensure_ascii=False,
        )

    print(
        f"Saved {len(summaries)} daily summaries "
        f"to {SUMMARY_FILE}"
    )


if __name__ == "__main__":
    main()
