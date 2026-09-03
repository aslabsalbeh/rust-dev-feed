from datetime import datetime, timezone
import scripts.build_feed as build_feed


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload
    def raise_for_status(self):
        return None
    def json(self):
        return self.payload


def test_fetch_latest_skips_one_malformed_record(monkeypatch):
    payload = {"results": [
        {"id": 1, "branch": "main", "changeset": "100",
         "created": "2026-09-03T12:00:00",
         "message": "Fixed player inventory bug", "user": {"name": "Dev"}},
        {"branch": "main", "created": "2026-09-03T12:01:00",
         "message": "missing id"},
        {"id": 2, "branch": "main", "changeset": "101",
         "created": "2026-09-03T12:02:00",
         "message": "Fixed vehicle bug"},
    ]}
    monkeypatch.setattr(
        build_feed.requests, "get",
        lambda *args, **kwargs: FakeResponse(payload),
    )
    result = build_feed.fetch_latest()
    assert [item["id"] for item in result] == [1, 2]
    assert result[1]["user"] == "Unknown"


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
