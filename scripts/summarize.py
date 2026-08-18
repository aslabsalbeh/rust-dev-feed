import json
import os
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from google import genai


COMMITS_FILE = Path("site/commits.json")
SUMMARY_FILE = Path("site/summaries.json")

MODEL = "gemini-2.5-flash-lite"


def clean_branch(branch):
    branch = branch.replace("main/", "")
    branch = branch.replace("_", " ")
    return branch


def load_commits():
    with open(COMMITS_FILE, "r", encoding="utf-8") as file:
        return json.load(file)


def group_by_day_and_branch(commits):
    grouped = defaultdict(lambda: defaultdict(list))

    for commit in commits:
        day = datetime.fromisoformat(commit["created"]).date().isoformat()
        branch = clean_branch(commit["branch"])

        grouped[day][branch].append(commit)

    return grouped


def summarize_group(client, branch, commits):
    commit_text = "\n".join(
        f"- {commit['message']}"
        for commit in commits
    )

    prompt = f"""
You are summarizing Rust game development commits from Facepunch.

Feature or branch:
{branch}

Commits:
{commit_text}

Write a concise player-friendly summary.

Rules:
- Be factual.
- Do not speculate.
- Do not claim unfinished work is released.
- Combine closely related changes.
- Ignore internal merge/build noise.
- Prefer one bullet point.
- Use two bullet points only if the commits clearly describe separate changes.
- Keep technical details when they matter to players.
- Do not mention commit IDs.
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
    grouped = group_by_day_and_branch(commits)

    summaries = {}

    for day, branches in grouped.items():
        summaries[day] = []

        for branch, branch_commits in branches.items():
            summary = summarize_group(
                client,
                branch,
                branch_commits,
            )

            summaries[day].append(
                {
                    "feature": branch,
                    "summary": summary,
                    "commit_count": len(branch_commits),
                }
            )

            print(
                f"Summarized {day} / {branch} "
                f"({len(branch_commits)} commits)"
            )

    with open(SUMMARY_FILE, "w", encoding="utf-8") as file:
        json.dump(
            summaries,
            file,
            indent=2,
            ensure_ascii=False,
        )

    print(f"Saved summaries to {SUMMARY_FILE}")


if __name__ == "__main__":
    main()
