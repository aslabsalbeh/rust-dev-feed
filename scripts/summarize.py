import json
import os
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from google import genai


COMMITS_FILE = Path("site/commits.json")
SUMMARY_FILE = Path("site/summaries.json")

MODEL = "gemini-2.5-flash-lite"


def load_commits():
    with open(COMMITS_FILE, "r", encoding="utf-8") as file:
        return json.load(file)


def group_by_day(commits):
    grouped = defaultdict(list)

    for commit in commits:
        day = datetime.fromisoformat(commit["created"]).date().isoformat()
        grouped[day].append(commit)

    return grouped


def summarize_day(client, day, commits):
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
You are creating a concise daily development digest for the game Rust
using official Facepunch source-control commit messages.

Date:
{day}

Commits:

{chr(10).join(commit_text)}

Create a clean, player-friendly development summary.

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
- Avoid developer names and internal branch names unless they are genuinely useful.
- Do not mention commit IDs.
- Keep the entire digest concise enough to skim in an RSS widget.
- Use Markdown headings and bullet points.
- Return only the finished digest.
"""

    response = client.models.generate_content(
        model=MODEL,
        contents=prompt,
    )

    return response.text.strip()


def main():
    api_key = os.environ.get("GEMINI_API_KEY")

    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is not set.")

    client = genai.Client(api_key=api_key)

    commits = load_commits()
    grouped = group_by_day(commits)

    summaries = {}

    for day in sorted(grouped.keys(), reverse=True):
        commits_for_day = grouped[day]

        print(
            f"Summarizing {day} "
            f"({len(commits_for_day)} commits) in one Gemini request..."
        )

        summary = summarize_day(
            client,
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
