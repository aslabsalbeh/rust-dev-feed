from datetime import datetime, timezone
import scripts.build_feed as build_feed


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload
    def raise_for_status(self):
        return None
    def json(self):
        return self.payload


def test_malformed_record_fails_closed(monkeypatch):
    monkeypatch.setattr(build_feed.requests, "get", lambda *args, **kwargs:
                        FakeResponse({"total": 1, "skip": 0, "take": 50,
                                      "results": [{"message": "missing id"}]}))
    try:
        build_feed.fetch_source("Rust", datetime(2026, 9, 1, tzinfo=timezone.utc))
    except RuntimeError as error:
        assert "invalid ID/date" in str(error)
    else:
        raise AssertionError("Malformed source records must not cause a partial archive.")


def test_is_noise_keeps_multiline_merge_with_real_content():
    assert build_feed.is_noise("Merge from main") is True
    assert build_feed.is_noise(
        "Merge from main\nFixed sprinkler not watering"
    ) is False


def test_load_existing_corruption_fails_loudly(tmp_path, monkeypatch):
    path = tmp_path / "commits.json"
    path.write_text("{broken", encoding="utf-8")
    monkeypatch.setattr(build_feed, "OUTPUT_FILE", path)
    try:
        build_feed.load_existing()
    except RuntimeError:
        pass
    else:
        raise AssertionError("Corrupt existing state must fail loudly.")


def test_offset_timestamp_is_converted_not_relabelled():
    parsed = build_feed.parse_utc_timestamp("2026-09-02T20:00:00-04:00")
    assert parsed == datetime(2026, 9, 3, 0, 0, tzinfo=timezone.utc)
