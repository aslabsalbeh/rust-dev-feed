import json
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

import scripts.generate_rss as generate_rss
import scripts.providers as providers
import scripts.summarize as summarize


SECTIONS = [
    {
        "title": "Gameplay",
        "items": [
            {
                "text": "Changed gameplay.",
                "commit_ids": [1],
            }
        ],
    }
]


def make_commit(commit_id, created=None):
    return {
        "id": commit_id,
        "branch": "main",
        "message": f"Relevant change {commit_id}",
        "created": created or "2026-11-16T12:00:00",
    }


def explicit_empty_entry(signature=""):
    return {
        "commit_count": 0,
        "relevant_commit_count": 0,
        "relevant_signature": signature,
        "prompt_version": summarize.PROMPT_VERSION,
        "chunk_cache": {},
        "sections": [],
        "status": "no_significant_updates",
        "summary": summarize.NO_SIGNIFICANT_UPDATES,
        "new_items": [],
        "new_relevant_count": 0,
        "new_summary": "",
    }


def good_entry(commit_id=1, signature=None, prompt_version=None, text="Previous good summary"):
    return {
        "commit_count": 1,
        "relevant_commit_count": 1,
        "relevant_signature": signature if signature is not None else str(commit_id),
        "prompt_version": prompt_version or summarize.PROMPT_VERSION,
        "chunk_cache": {},
        "sections": [
            {
                "title": "Gameplay",
                "items": [
                    {
                        "text": text,
                        "commit_ids": [commit_id],
                    }
                ],
            }
        ],
        "status": "ok",
        "summary": "### Gameplay\n- " + text,
        "new_items": [],
        "new_relevant_count": 0,
        "new_summary": "",
    }


def rate_limited_response():
    return SimpleNamespace(
        status_code=429,
        ok=False,
        text='{"error":"rate limit"}',
        headers={},
        json=lambda: {},
    )


def setup_day(monkeypatch, tmp_path, commits, old=None):
    day = datetime.now(summarize.LOCAL_TZ).date().isoformat()
    for commit in commits:
        commit.setdefault("created", f"{day}T12:00:00")

    commits_path = tmp_path / "commits.json"
    summaries_path = tmp_path / "summaries.json"
    commits_path.write_text(json.dumps(commits), encoding="utf-8")
    summaries_path.write_text(
        json.dumps({day: old} if old else {}),
        encoding="utf-8",
    )
    monkeypatch.setattr(summarize, "COMMITS_FILE", commits_path)
    monkeypatch.setattr(summarize, "SUMMARY_FILE", summaries_path)
    monkeypatch.setattr(
        summarize,
        "filter_player_relevant_commits",
        lambda items, **kwargs: items,
    )
    monkeypatch.setenv("GROQ_API_KEY", "groq-secret")
    monkeypatch.setenv("OPENROUTER_API_KEY", "router-secret")
    return day, summaries_path


def read_entry(path, day):
    return json.loads(path.read_text(encoding="utf-8"))[day]


def test_previous_empty_summary_is_pending_not_current_after_failed_batch(monkeypatch, tmp_path):
    """An old explicit-empty result must not describe a 100+ commit day."""
    commits = [make_commit(commit_id) for commit_id in range(1, 121)]
    day, path = setup_day(monkeypatch, tmp_path, commits, explicit_empty_entry())
    monkeypatch.setattr(
        providers.requests,
        "post",
        lambda *args, **kwargs: rate_limited_response(),
    )

    summarize.main()

    entry = read_entry(path, day)
    assert entry["status"] == "pending"
    assert entry["summary"] == summarize.PENDING_SUMMARY
    assert summarize.NO_SIGNIFICANT_UPDATES not in entry["summary"]
    assert entry["relevant_signature"] == ""
    assert entry["pending_relevant_count"] == 120
    assert entry["relevant_commit_count"] == 120


def test_failed_large_batch_preserves_completed_chunks_and_recovers(monkeypatch, tmp_path):
    """Successful chunks survive a failure and are reused on the next run."""
    commits = [make_commit(commit_id) for commit_id in range(1, 121)]
    day, path = setup_day(monkeypatch, tmp_path, commits, explicit_empty_entry())
    calls = []

    def fake_request(groq_key, openrouter_key, prompt, allowed_ids, label):
        calls.append(label)
        if "chunk 1/5" in label or "chunk 2/5" in label:
            return [
                {
                    "title": "Gameplay",
                    "items": [
                        {
                            "text": "Summarized chunk.",
                            "commit_ids": sorted(int(value) for value in allowed_ids),
                        }
                    ],
                }
            ]
        return None

    monkeypatch.setattr(summarize, "request_sections", fake_request)

    summarize.main()

    pending = read_entry(path, day)
    assert pending["status"] == "pending"
    assert len(pending["chunk_cache"]) == 2
    assert pending["relevant_signature"] == ""

    # The next run keeps the two completed chunks and only asks for the rest.
    retry_calls = []

    def retry_request(groq_key, openrouter_key, prompt, allowed_ids, label):
        retry_calls.append(label)
        if "final merge" in label:
            return [
                {
                    "title": "Gameplay",
                    "items": [
                        {
                            "text": "Merged daily summary.",
                            "commit_ids": sorted(int(value) for value in allowed_ids),
                        }
                    ],
                }
            ]
        return [
            {
                "title": "Gameplay",
                "items": [
                    {
                        "text": "Summarized chunk.",
                        "commit_ids": sorted(int(value) for value in allowed_ids),
                    }
                ],
            }
        ]

    monkeypatch.setattr(summarize, "request_sections", retry_request)

    summarize.main()

    recovered = read_entry(path, day)
    assert recovered["status"] == "ok"
    assert recovered["sections"]
    assert recovered["chunk_cache"] == {}
    assert recovered["relevant_signature"] == summarize.commit_signature(commits)
    assert not any("chunk 1/5" in label for label in retry_calls)
    assert not any("chunk 2/5" in label for label in retry_calls)
    assert any("chunk 3/5" in label for label in retry_calls)
    assert any("final merge" in label for label in retry_calls)


def test_previous_content_is_preserved_with_stale_notice(monkeypatch, tmp_path):
    commits = [make_commit(commit_id) for commit_id in range(1, 121)]
    old = good_entry(commit_id=1, signature="1", text="Previously published change.")
    day, path = setup_day(monkeypatch, tmp_path, commits, old)
    monkeypatch.setattr(
        providers.requests,
        "post",
        lambda *args, **kwargs: rate_limited_response(),
    )

    summarize.main()

    entry = read_entry(path, day)
    assert entry["status"] == "partial"
    assert entry["sections"] == old["sections"]
    assert entry["summary"] == old["summary"]
    assert entry["relevant_signature"] == "1"
    assert entry["pending_relevant_count"] == 119
    assert "119 relevant commit(s) are not yet included" in entry["notice"]
    # Stale content must not be advertised as a fresh rolling NEW window.
    assert entry["new_items"] == []
    assert entry["new_relevant_count"] == 0


def test_same_signature_prompt_refresh_failure_stays_complete(monkeypatch, tmp_path):
    """A failed prompt-version refresh must not mark complete content pending."""
    commits = [make_commit(1)]
    old = good_entry(
        commit_id=1,
        signature="1",
        prompt_version="structured-read-state-old",
        text="Previously published change.",
    )
    day, path = setup_day(monkeypatch, tmp_path, commits, old)
    monkeypatch.setattr(
        providers.requests,
        "post",
        lambda *args, **kwargs: rate_limited_response(),
    )

    summarize.main()

    entry = read_entry(path, day)
    assert entry["status"] == "ok"
    assert entry["notice"] == ""
    assert entry["sections"] == old["sections"]
    assert entry["relevant_signature"] == "1"
    # Keep the old version so a later run can still attempt the refresh.
    assert entry["prompt_version"] == "structured-read-state-old"


def test_stale_signature_with_full_coverage_is_promoted_to_complete(monkeypatch, tmp_path):
    """A stale stored signature alone must not create a false partial state."""
    commits = [make_commit(1), make_commit(2)]
    old = good_entry(commit_id=1, signature="1")
    old["sections"][0]["items"].append(
        {
            "text": "Second change.",
            "commit_ids": [2],
        }
    )
    old["summary"] = "### Gameplay\n- Previous good summary\n- Second change."
    day, path = setup_day(monkeypatch, tmp_path, commits, old)
    monkeypatch.setattr(
        providers.requests,
        "post",
        lambda *args, **kwargs: rate_limited_response(),
    )

    summarize.main()

    entry = read_entry(path, day)
    assert entry["status"] == "ok"
    assert entry["relevant_signature"] == "1,2"
    assert entry["pending_relevant_count"] == 0
    assert entry["notice"] == ""
    assert entry["sections"] == old["sections"]


def test_new_commits_no_longer_invalidate_every_cached_chunk():
    base = datetime(2026, 11, 16, 0, 0, 0)
    commits = [
        make_commit(
            commit_id,
            (base + timedelta(minutes=commit_id)).isoformat(),
        )
        for commit_id in range(125, 0, -1)  # Facepunch newest-first order.
    ]
    old_chunks = summarize.chronological_chunks(commits, 25)
    assert [commit["id"] for commit in old_chunks[0]] == list(range(1, 26))

    newer = [
        make_commit(
            commit_id,
            (base + timedelta(minutes=commit_id)).isoformat(),
        )
        for commit_id in range(130, 125, -1)
    ]
    all_chunks = summarize.chronological_chunks(newer + commits, 25)

    old_keys = {summarize.commit_signature(chunk) for chunk in old_chunks}
    new_keys = {summarize.commit_signature(chunk) for chunk in all_chunks}
    assert old_keys <= new_keys
    assert [commit["id"] for commit in all_chunks[-1]] == [126, 127, 128, 129, 130]


def test_call_ai_keeps_cached_chunks_when_new_commits_arrive(monkeypatch):
    monkeypatch.setattr(summarize, "CHUNK_SIZE", 2)
    commits = [make_commit(commit_id) for commit_id in range(1, 6)]

    def first_request(groq_key, openrouter_key, prompt, allowed_ids, label):
        if "final merge" in label:
            return None
        return [
            {
                "title": "Gameplay",
                "items": [
                    {
                        "text": label,
                        "commit_ids": sorted(int(value) for value in allowed_ids),
                    }
                ],
            }
        ]

    monkeypatch.setattr(summarize, "request_sections", first_request)
    result, cache = summarize.call_ai("groq", None, "2026-11-16", commits)
    assert result is None
    assert len(cache) == 3

    newer_commits = commits + [make_commit(6), make_commit(7)]
    calls = []

    def second_request(groq_key, openrouter_key, prompt, allowed_ids, label):
        calls.append(label)
        return [
            {
                "title": "Gameplay",
                "items": [
                    {
                        "text": label,
                        "commit_ids": sorted(int(value) for value in allowed_ids),
                    }
                ],
            }
        ]

    monkeypatch.setattr(summarize, "request_sections", second_request)
    result, cache = summarize.call_ai(
        "groq",
        None,
        "2026-11-16",
        newer_commits,
        cache,
    )

    assert result is not None
    assert cache == {}
    assert not any("chunk 1/4" in label for label in calls)
    assert not any("chunk 2/4" in label for label in calls)
    assert any("chunk 3/4" in label for label in calls)
    assert any("chunk 4/4" in label for label in calls)
    assert any("final merge" in label for label in calls)


def test_cached_chunk_with_foreign_commit_ids_is_rejected(monkeypatch):
    monkeypatch.setattr(summarize, "CHUNK_SIZE", 2)
    commits = [make_commit(1), make_commit(2), make_commit(3), make_commit(4)]
    first_chunk = commits[:2]
    cache = {
        summarize.commit_signature(first_chunk): [
            {
                "title": "Gameplay",
                "items": [
                    {
                        "text": "Wrong commit.",
                        "commit_ids": [999],
                    }
                ],
            }
        ]
    }
    calls = []

    def request(groq_key, openrouter_key, prompt, allowed_ids, label):
        calls.append(label)
        if "final merge" in label:
            return [
                {
                    "title": "Gameplay",
                    "items": [
                        {
                            "text": "Merged.",
                            "commit_ids": [1, 2, 3, 4],
                        }
                    ],
                }
            ]
        return [
            {
                "title": "Gameplay",
                "items": [
                    {
                        "text": "Chunk.",
                        "commit_ids": sorted(int(value) for value in allowed_ids),
                    }
                ],
            }
        ]

    monkeypatch.setattr(summarize, "request_sections", request)
    result, _ = summarize.call_ai("groq", None, "2026-11-16", commits, cache)

    assert result is not None
    assert any("chunk 1/2" in label for label in calls)


def test_explicit_empty_result_still_applies_to_current_signature(monkeypatch, tmp_path):
    commits = [make_commit(1), make_commit(2)]
    day, path = setup_day(monkeypatch, tmp_path, commits, explicit_empty_entry())
    monkeypatch.setattr(summarize, "request_sections", lambda *args: [])

    summarize.main()

    entry = read_entry(path, day)
    assert entry["status"] == "no_significant_updates"
    assert entry["summary"] == summarize.NO_SIGNIFICANT_UPDATES
    assert entry["relevant_signature"] == "1,2"


@pytest.mark.parametrize(
    "entry, expected",
    [
        (
            {
                "commit_count": 10,
                "sections": [],
                "status": "pending",
                "summary": summarize.PENDING_SUMMARY,
            },
            summarize.PENDING_SUMMARY,
        ),
        (
            {
                "commit_count": 10,
                "sections": SECTIONS,
                "status": "partial",
                "summary": "### Gameplay\n- Changed gameplay.",
                "notice": "This summary covers an earlier commit set; 9 relevant commit(s) are not yet included.",
            },
            "rust-summary-notice",
        ),
    ],
)
def test_rss_renders_pending_and_stale_notices(tmp_path, monkeypatch, entry, expected):
    summaries = tmp_path / "summaries.json"
    output = tmp_path / "feed.xml"
    summaries.write_text(json.dumps({"2026-11-16": entry}), encoding="utf-8")
    monkeypatch.setattr(generate_rss, "SUMMARY_FILE", summaries)
    monkeypatch.setattr(generate_rss, "OUTPUT_FILE", output)

    generate_rss.main()

    text = output.read_text(encoding="utf-8")
    assert expected in text
    assert "No notable player-facing changes" not in text
