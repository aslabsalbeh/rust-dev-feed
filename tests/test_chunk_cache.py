import scripts.summarize as summarize


def make_commit(commit_id):
    return {
        "id": commit_id,
        "branch": "main/test",
        "message": f"Player-facing test change {commit_id}",
        "created": "2026-08-25T12:00:00",
    }


def fake_sections(label, commit_ids):
    return [
        {
            "title": label,
            "items": [
                {
                    "text": f"Summary for {label}",
                    "commit_ids": list(commit_ids),
                }
            ],
        }
    ]


def test_partial_failure_preserves_completed_chunks(monkeypatch):
    """
    If chunk 1 succeeds and chunk 2 fails, chunk 1 must be returned
    in the temporary cache for reuse on the next workflow run.
    """

    monkeypatch.setattr(
        summarize,
        "CHUNK_SIZE",
        2,
    )

    commits = [
        make_commit(1),
        make_commit(2),
        make_commit(3),
        make_commit(4),
        make_commit(5),
    ]

    calls = []

    def fake_request_sections(
        groq_key,
        openrouter_key,
        prompt,
        allowed_ids,
        label,
    ):
        calls.append(label)

        if "chunk 1/3" in label:
            return fake_sections(
                "Chunk 1",
                allowed_ids,
            )

        if "chunk 2/3" in label:
            return None

        raise AssertionError(
            "Chunk 3 should not run after chunk 2 fails."
        )

    monkeypatch.setattr(
        summarize,
        "request_sections",
        fake_request_sections,
    )

    result, cache = summarize.call_ai(
        "fake-groq-key",
        None,
        "2026-08-25",
        commits,
    )

    assert result is None

    first_chunk = commits[:2]

    first_key = summarize.commit_signature(
        first_chunk
    )

    assert first_key in cache
    assert cache[first_key]

    assert len(calls) == 2
    assert "chunk 1/3" in calls[0]
    assert "chunk 2/3" in calls[1]


def test_next_run_reuses_cached_chunk(monkeypatch):
    """
    A completed chunk from a previous failed run must not be sent
    to the AI again.
    """

    monkeypatch.setattr(
        summarize,
        "CHUNK_SIZE",
        2,
    )

    commits = [
        make_commit(1),
        make_commit(2),
        make_commit(3),
        make_commit(4),
        make_commit(5),
    ]

    first_chunk = commits[:2]

    first_key = summarize.commit_signature(
        first_chunk
    )

    old_cache = {
        first_key: fake_sections(
            "Cached Chunk 1",
            {"1", "2"},
        )
    }

    calls = []

    def fake_request_sections(
        groq_key,
        openrouter_key,
        prompt,
        allowed_ids,
        label,
    ):
        calls.append(label)

        if "chunk 1/3" in label:
            raise AssertionError(
                "Cached chunk 1 must not be regenerated."
            )

        if "chunk 2/3" in label:
            return fake_sections(
                "Chunk 2",
                allowed_ids,
            )

        if "chunk 3/3" in label:
            return fake_sections(
                "Chunk 3",
                allowed_ids,
            )

        if "final merge" in label:
            return fake_sections(
                "Final",
                {"1", "2", "3", "4", "5"},
            )

        raise AssertionError(
            f"Unexpected request: {label}"
        )

    monkeypatch.setattr(
        summarize,
        "request_sections",
        fake_request_sections,
    )

    result, cache = summarize.call_ai(
        "fake-groq-key",
        None,
        "2026-08-25",
        commits,
        old_chunk_cache=old_cache,
    )

    assert result is not None

    # Successful final merge clears the temporary cache.
    assert cache == {}

    assert not any(
        "chunk 1/3" in label
        for label in calls
    )

    assert any(
        "chunk 2/3" in label
        for label in calls
    )

    assert any(
        "chunk 3/3" in label
        for label in calls
    )

    assert any(
        "final merge" in label
        for label in calls
    )


def test_final_merge_failure_preserves_all_chunks(monkeypatch):
    """
    If every chunk succeeds but the final merge fails, all completed
    chunks must remain cached so the next run only retries the merge.
    """

    monkeypatch.setattr(
        summarize,
        "CHUNK_SIZE",
        2,
    )

    commits = [
        make_commit(1),
        make_commit(2),
        make_commit(3),
        make_commit(4),
        make_commit(5),
    ]

    def fake_request_sections(
        groq_key,
        openrouter_key,
        prompt,
        allowed_ids,
        label,
    ):
        if "final merge" in label:
            return None

        return fake_sections(
            label,
            allowed_ids,
        )

    monkeypatch.setattr(
        summarize,
        "request_sections",
        fake_request_sections,
    )

    result, cache = summarize.call_ai(
        "fake-groq-key",
        None,
        "2026-08-25",
        commits,
    )

    assert result is None

    expected_keys = {
        summarize.commit_signature(
            commits[0:2]
        ),
        summarize.commit_signature(
            commits[2:4]
        ),
        summarize.commit_signature(
            commits[4:5]
        ),
    }

    assert set(cache.keys()) == expected_keys

    for key in expected_keys:
        assert cache[key]


def test_successful_merge_clears_chunk_cache(monkeypatch):
    """
    Once all chunks and the final merge succeed, the temporary
    chunk cache is no longer needed.
    """

    monkeypatch.setattr(
        summarize,
        "CHUNK_SIZE",
        2,
    )

    commits = [
        make_commit(1),
        make_commit(2),
        make_commit(3),
        make_commit(4),
        make_commit(5),
    ]

    def fake_request_sections(
        groq_key,
        openrouter_key,
        prompt,
        allowed_ids,
        label,
    ):
        if "final merge" in label:
            return fake_sections(
                "Final",
                {"1", "2", "3", "4", "5"},
            )

        return fake_sections(
            label,
            allowed_ids,
        )

    monkeypatch.setattr(
        summarize,
        "request_sections",
        fake_request_sections,
    )

    result, cache = summarize.call_ai(
        "fake-groq-key",
        None,
        "2026-08-25",
        commits,
    )

    assert result is not None
    assert cache == {}


def test_small_day_does_not_use_chunk_cache(monkeypatch):
    """
    Days at or below CHUNK_SIZE should use the normal single-request
    path and return an empty temporary cache after success.
    """

    monkeypatch.setattr(
        summarize,
        "CHUNK_SIZE",
        25,
    )

    commits = [
        make_commit(1),
        make_commit(2),
    ]

    calls = []

    def fake_request_sections(
        groq_key,
        openrouter_key,
        prompt,
        allowed_ids,
        label,
    ):
        calls.append(label)

        return fake_sections(
            "Small Day",
            allowed_ids,
        )

    monkeypatch.setattr(
        summarize,
        "request_sections",
        fake_request_sections,
    )

    result, cache = summarize.call_ai(
        "fake-groq-key",
        None,
        "2026-08-25",
        commits,
    )

    assert result is not None
    assert cache == {}
    assert calls == ["2026-08-25"]
