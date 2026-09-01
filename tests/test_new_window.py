import json
from datetime import datetime, timezone

import scripts.summarize as summarize


def commit(commit_id, created):
    return {
        "id": commit_id,
        "branch": "main",
        "message": "Fixed a race condition that could cause items in display box storage to disappear when saving.",
        "created": created,
    }


def test_recent_commit_ids_uses_true_rolling_three_hour_window():
    now = datetime(2026, 9, 1, 18, 0, tzinfo=timezone.utc)
    commits = [
        commit(1, "2026-09-01T17:59:59"),
        commit(2, "2026-09-01T15:00:00"),
        commit(3, "2026-09-01T14:59:59"),
        commit(4, "2026-09-01T18:00:01"),
    ]

    assert summarize.recent_commit_ids(commits, now) == {"1", "2"}


def test_recent_commit_ids_accepts_z_and_offset_timestamps():
    now = datetime(2026, 9, 1, 18, 0, tzinfo=timezone.utc)
    commits = [
        commit(1, "2026-09-01T17:00:00Z"),
        commit(2, "2026-09-01T13:30:00-04:00"),
    ]

    assert summarize.recent_commit_ids(commits, now) == {"1", "2"}


def _write_reuse_fixture(tmp_path):
    site = tmp_path / "site"
    site.mkdir()
    commits = [commit(619919, "2026-09-01T15:03:00")]
    (site / "commits.json").write_text(json.dumps(commits), encoding="utf-8")

    sections = [{
        "title": "Bug Fixes",
        "items": [{
            "text": "Fixed display box storage race condition.",
            "commit_ids": [619919],
        }],
    }]
    summaries = {
        "2026-09-01": {
            "commit_count": 1,
            "relevant_commit_count": 1,
            "relevant_signature": "619919",
            "new_baseline_signature": "619919",
            "prompt_version": summarize.PROMPT_VERSION,
            "chunk_cache": {},
            "sections": sections,
            "summary": "### Bug Fixes\n- Fixed display box storage race condition.",
            "new_items": [{
                "text": "stale prior NEW value",
                "commit_ids": [619919],
                "section": "Bug Fixes",
            }],
            "new_relevant_count": 1,
            "new_summary": "- stale prior NEW value",
        }
    }
    (site / "summaries.json").write_text(json.dumps(summaries), encoding="utf-8")
    return site


def test_new_items_recalculated_when_daily_summary_is_reused(tmp_path, monkeypatch):
    site = _write_reuse_fixture(tmp_path)
    monkeypatch.setattr(summarize, "COMMITS_FILE", site / "commits.json")
    monkeypatch.setattr(summarize, "SUMMARY_FILE", site / "summaries.json")
    monkeypatch.setenv("GROQ_API_KEY", "test")
    monkeypatch.setattr(summarize, "recent_commit_ids", lambda commits: {"619919"})

    summarize.main()

    saved = json.loads((site / "summaries.json").read_text(encoding="utf-8"))
    today = saved["2026-09-01"]
    assert today["new_items"] == [{
        "text": "Fixed display box storage race condition.",
        "commit_ids": [619919],
        "section": "Bug Fixes",
    }]


def test_expired_new_items_are_cleared_even_when_summary_is_reused(tmp_path, monkeypatch):
    site = _write_reuse_fixture(tmp_path)
    monkeypatch.setattr(summarize, "COMMITS_FILE", site / "commits.json")
    monkeypatch.setattr(summarize, "SUMMARY_FILE", site / "summaries.json")
    monkeypatch.setenv("GROQ_API_KEY", "test")
    monkeypatch.setattr(summarize, "recent_commit_ids", lambda commits: set())

    summarize.main()

    saved = json.loads((site / "summaries.json").read_text(encoding="utf-8"))
    today = saved["2026-09-01"]
    assert today["new_items"] == []
    assert today["new_summary"] == ""
    assert today["new_relevant_count"] == 0
