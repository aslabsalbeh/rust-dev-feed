import json
from datetime import datetime, timezone

import pytest
import scripts.build_feed as feed
import scripts.summarize as summarize


def record(id, created, repo='Rust', message='Gameplay change'):
    return {'id': id, 'repo': repo, 'created': created, 'message': message,
            'branch': 'main', 'changeset': str(id), 'user': {'name': 'Dev'}}


class Reply:
    def __init__(self, results, *, total=None, skip=0, take=50):
        self.payload = {'total': len(results) if total is None else total,
                        'skip': skip, 'take': take, 'results': results}
    def raise_for_status(self):
        pass
    def json(self):
        return self.payload


def serve(monkeypatch, pages):
    calls = []
    def get(url, *, params, timeout):
        source = 'Rust' if '/r/Rust?' in url else 'rust_reboot'
        page = params['p']
        calls.append((source, page))
        return pages[(source, page)]
    monkeypatch.setattr(feed.requests, 'get', get)
    return calls


def test_dual_source_backfill_paginates_deduplicates_and_preserves_existing(monkeypatch, tmp_path, capsys):
    now = datetime(2026, 11, 9, 23, tzinfo=timezone.utc)
    old = record(10, '2026-11-08T01:00:00', 'rust_reboot')
    path = tmp_path / 'commits.json'
    path.write_text(json.dumps([old]))
    monkeypatch.setattr(feed, 'OUTPUT_FILE', path)
    pages = {
        ('Rust', 1): Reply([record(13,'2026-11-09T22:00:00'), record(12,'2026-11-09T21:00:00')], total=3, take=2),
        ('Rust', 2): Reply([record(11,'2026-11-08T18:00:00')], total=3, skip=2, take=2),
        ('rust_reboot', 1): Reply([old], total=1),
    }
    calls = serve(monkeypatch, pages)
    feed.main(now)
    data = json.loads(path.read_text())
    assert [x['id'] for x in data] == [13,12,11,10]
    assert ('Rust',2) in calls and ('rust_reboot',1) in calls
    diagnostics = capsys.readouterr().out
    assert 'Source freshness' in diagnostics
    assert 'archive_before=1' in diagnostics
    # The legacy source can overlap the new source without duplicating IDs.
    pages[('rust_reboot',1)] = Reply([record(11,'2026-11-08T18:00:00','rust_reboot'), old], total=2)
    feed.main(now)
    assert len(json.loads(path.read_text())) == 4


@pytest.mark.parametrize('broken', [
    Reply([record(12,'2026-11-09T21:00:00')],total=2,take=2),
    Reply([record(12,'2026-11-09T21:00:00')],total=1,skip=50),
    Reply([{'id':12,'repo':'Rust','message':'Missing created'}]),
    Reply([record(12,'bad-date')]),
])
def test_incomplete_or_missing_dates_never_overwrite_archive(monkeypatch, tmp_path, broken):
    path = tmp_path / 'commits.json'
    original = json.dumps([record(10,'2026-11-09T20:00:00')])
    path.write_text(original)
    monkeypatch.setattr(feed,'OUTPUT_FILE',path)
    serve(monkeypatch,{('Rust',1):broken})
    with pytest.raises(RuntimeError):
        feed.main(datetime(2026,11,9,23,tzinfo=timezone.utc))
    assert path.read_text()==original


def test_stale_both_sources_preserves_archive(monkeypatch,tmp_path):
    path=tmp_path/'commits.json'
    original=json.dumps([record(10,'2026-11-08T01:00:00')])
    path.write_text(original)
    monkeypatch.setattr(feed,'OUTPUT_FILE',path)
    serve(monkeypatch,{
        ('Rust',1):Reply([record(11,'2026-11-08T02:00:00')]),
        ('rust_reboot',1):Reply([record(10,'2026-11-08T01:00:00','rust_reboot')]),
    })
    with pytest.raises(RuntimeError,match='stale'):
        feed.main(datetime(2026,11,9,20,tzinfo=timezone.utc))
    assert path.read_text()==original


def test_regressed_source_preserves_newer_saved_commit(monkeypatch,tmp_path):
    path=tmp_path/'commits.json'
    original=json.dumps([record(20,'2026-11-09T22:00:00')])
    path.write_text(original)
    monkeypatch.setattr(feed,'OUTPUT_FILE',path)
    serve(monkeypatch,{
        ('Rust',1):Reply([record(11,'2026-11-09T21:00:00')]),
        ('rust_reboot',1):Reply([record(10,'2026-11-08T01:00:00','rust_reboot')]),
    })
    with pytest.raises(RuntimeError,match='regressed'):
        feed.main(datetime(2026,11,9,23,tzinfo=timezone.utc))
    assert path.read_text()==original


def test_timezone_boundaries_keep_correct_local_day_and_cutoff(monkeypatch,tmp_path):
    # UTC midnight on Nov 10 is still Nov 9 in Toronto.
    commit=record(11,'2026-11-10T00:30:00+00:00')
    assert summarize.commit_local_date(commit)=='2026-11-09'
    assert feed.parse_utc_timestamp('2026-11-06T18:59:59-04:00') < datetime(2026,11,6,23,tzinfo=timezone.utc)
    path=tmp_path/'commits.json';path.write_text('[]');monkeypatch.setattr(feed,'OUTPUT_FILE',path)
    serve(monkeypatch,{
        ('Rust',1):Reply([commit,record(9,'2026-11-06T22:59:59')],total=2),
        ('rust_reboot',1):Reply([record(8,'2026-11-06T23:00:00','rust_reboot'),
                                  record(7,'2026-11-06T22:59:59','rust_reboot')],total=2),
    })
    feed.main(datetime(2026,11,9,23,tzinfo=timezone.utc))
    assert [x['id'] for x in json.loads(path.read_text())]==[11,8]


def test_page_shift_is_rejected(monkeypatch):
    replies=iter([Reply([record(2,'2026-11-09T20:00:00')]),
                  Reply([record(3,'2026-11-09T21:00:00')])])
    monkeypatch.setattr(feed.requests,'get',lambda *a,**k:next(replies))
    with pytest.raises(RuntimeError,match='changed during pagination'):
        feed.fetch_source('Rust',datetime(2026,11,6,tzinfo=timezone.utc))
