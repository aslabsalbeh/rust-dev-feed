import scripts.summarize as summarize


def make_commit(commit_id, message):
    return {
        "id": commit_id,
        "branch": "",
        "message": message,
        "created": "2026-08-25T12:00:00",
    }


def sections_for(commit_id, text="Existing summary"):
    return [
        {
            "title": "Gameplay & Balance",
            "items": [
                {
                    "text": text,
                    "commit_ids": [commit_id],
                }
            ],
        }
    ]


def test_represented_high_impact_commit_does_not_trigger_rescue(monkeypatch):
    commit = make_commit(1, "SAM site drone buff proximity fuse")

    monkeypatch.setattr(
        summarize,
        "player_relevance_score",
        lambda item: 12,
    )

    def fail_request(*args, **kwargs):
        raise AssertionError("Rescue should not be called.")

    monkeypatch.setattr(
        summarize,
        "request_sections",
        fail_request,
    )

    original = sections_for(1)

    result = summarize.rescue_missing_high_impact_commits(
        "groq",
        "openrouter",
        "2026-08-25",
        [commit],
        original,
    )

    assert result == original


def test_missing_high_impact_commit_triggers_rescue(monkeypatch):
    commit = make_commit(2, "Reduced grenade stack size from 5 to 3")

    monkeypatch.setattr(
        summarize,
        "player_relevance_score",
        lambda item: 12,
    )

    calls = []

    def fake_request(
        groq_key,
        openrouter_key,
        prompt,
        allowed_ids,
        label,
    ):
        calls.append((allowed_ids, label))
        return sections_for(2, "Reduced grenade stack sizes from 5 to 3.")

    monkeypatch.setattr(
        summarize,
        "request_sections",
        fake_request,
    )

    result = summarize.rescue_missing_high_impact_commits(
        "groq",
        "openrouter",
        "2026-08-25",
        [commit],
        [],
    )

    assert len(calls) == 1
    assert calls[0][0] == {"2"}
    assert "high-impact rescue" in calls[0][1]
    assert summarize.represented_section_commit_ids(result) == {"2"}


def test_low_impact_omission_does_not_trigger_rescue(monkeypatch):
    commit = make_commit(3, "Minor visible polish")

    monkeypatch.setattr(
        summarize,
        "player_relevance_score",
        lambda item: 4,
    )

    def fail_request(*args, **kwargs):
        raise AssertionError("Low-impact commit must not trigger rescue.")

    monkeypatch.setattr(
        summarize,
        "request_sections",
        fail_request,
    )

    assert summarize.rescue_missing_high_impact_commits(
        "groq",
        "openrouter",
        "2026-08-25",
        [commit],
        [],
    ) == []


def test_rescue_failure_preserves_existing_summary(monkeypatch):
    commit = make_commit(4, "Major gameplay nerf")

    monkeypatch.setattr(
        summarize,
        "player_relevance_score",
        lambda item: 15,
    )
    monkeypatch.setattr(
        summarize,
        "request_sections",
        lambda *args, **kwargs: None,
    )

    original = sections_for(99)

    result = summarize.rescue_missing_high_impact_commits(
        "groq",
        "openrouter",
        "2026-08-25",
        [commit],
        original,
    )

    assert result == original
