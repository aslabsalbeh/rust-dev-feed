import scripts.summarize as summarize


def make_commit(commit_id, message):
    return {
        "id": commit_id,
        "branch": "main",
        "message": message,
        "created": "2026-09-03T12:00:00",
    }


def section(commit_id, text="Existing"):
    return [{
        "title": "Bug Fixes",
        "items": [{"text": text, "commit_ids": [commit_id]}],
    }]


def test_previously_published_missing_commit_is_detected(monkeypatch):
    commit = make_commit(7, "Fixed vehicle collision exploit")
    monkeypatch.setattr(
        summarize, "player_relevance_score",
        lambda item: summarize.RELEVANCE_THRESHOLD,
    )
    missing = summarize.previously_published_missing_commits(
        [commit], section(7), []
    )
    assert [item["id"] for item in missing] == [7]


def test_published_stability_rescue_merges_result(monkeypatch):
    commit = make_commit(8, "Fixed storage item loss bug")
    monkeypatch.setattr(
        summarize, "player_relevance_score",
        lambda item: summarize.RELEVANCE_THRESHOLD,
    )
    monkeypatch.setattr(
        summarize, "request_sections",
        lambda *args, **kwargs: section(8, "Fixed storage item loss bug."),
    )
    result = summarize.rescue_previously_published_commits(
        "groq", "openrouter", "2026-09-03",
        [commit], section(8, "Previously published wording."), []
    )
    assert summarize.represented_commit_ids_from_sections(result) == {"8"}
