import json
from datetime import datetime
from types import SimpleNamespace

import pytest
import scripts.providers as providers
import scripts.summarize as summarize
import scripts.generate_rss as rss
from scripts import prompts


SECTIONS = [{"title": "Gameplay", "items": [{"text": "Changed gameplay.", "commit_ids": [1]}]}]
EMPTY = {"status": "no_significant_updates", "sections": []}


def response(content=None, status=200, body="", headers=None):
    return SimpleNamespace(status_code=status, ok=status < 400, text=body,
                           headers=headers or {},
                           json=lambda: {"choices": [{"message": {"content": json.dumps(content)}}]})


@pytest.mark.parametrize("payload, reason", [
    ('{', 'json_parse_failure'),
    ('null', 'wrong_top_level_type'),
    ('{}', 'missing_sections'),
    ('{"status": "no_significant_updates", "sections": [], "error": "failed"}', 'unexpected_empty_outcome_fields'),
    ('{"sections": {}}', 'sections_not_list'),
    ('{"sections": []}', 'empty_sections_without_explicit_outcome'),
    ('[]', 'empty_sections_without_explicit_outcome'),
    ('{"status": "ok", "sections": []}', 'empty_sections_without_explicit_outcome'),
    ('{"status": "unknown", "sections": []}', 'invalid_status'),
    ('{"sections": [null]}', 'all_sections_invalid'),
    ('{"sections": [{"title": "UI", "items": []}]}', 'all_items_removed'),
    ('{"sections": [{"title": "UI", "items": [null]}]}', 'invalid_items=1'),
])
def test_validation_reasons(payload, reason, capsys):
    assert providers.parse_structured_summary(payload, {"1"}) is None
    assert reason in capsys.readouterr().out


@pytest.mark.parametrize("ids, reason", [
    (None, 'items_missing_commit_ids'), ([], 'items_missing_commit_ids'),
    ('1', 'items_invalid_commit_ids'), ([True], 'items_invalid_commit_ids'),
    ([1.1], 'items_invalid_commit_ids'), (['bad'], 'items_invalid_commit_ids'),
    ([999], 'items_unknown_commit_ids'), ([1, 999], 'items_unknown_commit_ids'),
])
def test_invalid_ids_never_become_success(ids, reason, capsys):
    payload = {"sections": [{"title": "UI", "items": [{"text": "Change", "commit_ids": ids}]}]}
    assert providers.parse_structured_summary(json.dumps(payload), {"1"}) is None
    log = capsys.readouterr().out
    assert 'all_items_removed' in log and reason in log


def test_valid_outcomes_and_contradictory_empty(capsys):
    assert providers.parse_structured_summary(json.dumps({"status": "ok", "sections": SECTIONS}), {"1"}) == SECTIONS
    assert 'valid_structured_summary' in capsys.readouterr().out
    assert providers.parse_structured_summary(json.dumps(EMPTY), {"1"}) == []
    assert providers.parse_structured_summary(json.dumps({**EMPTY, "sections": SECTIONS}), {"1"}) is None


def test_mixed_invalid_items_still_fail():
    sections = [{"title": "UI", "items": SECTIONS[0]['items'] + [None]}]
    assert providers.parse_structured_summary(json.dumps({"sections": sections}), {"1"}) is None


@pytest.mark.parametrize("first, second, expected, count", [
    ({"sections": []}, {"status": "ok", "sections": SECTIONS}, SECTIONS, 2),
    (EMPTY, None, [], 1),
    ({"sections": []}, {"sections": []}, None, 2),
])
def test_provider_fallback(monkeypatch, first, second, expected, count):
    calls = []
    replies = iter([response(first), response(second)])
    def post(*args, **kwargs):
        calls.append(args[0])
        return next(replies)
    monkeypatch.setattr(providers.requests, 'post', post)
    assert providers.request_sections('groq-secret', 'router-secret', 'prompt', {'1'}, 'day') == expected
    assert len(calls) == count


@pytest.mark.parametrize('provider', ['Groq', 'OpenRouter'])
def test_rate_limit_logging_is_safe_and_bounded(monkeypatch, capsys, provider):
    monkeypatch.setenv('OPENROUTER_API_KEY', 'other-secret')
    r = response(status=429, body='Bearer hidden-token key-secret other-secret\n\x1b[31m' + 'x' * 5000,
                 headers={'Retry-After': '60', 'X-RateLimit-Remaining-Tokens': '0',
                          'Authorization': 'do-not-log', 'Set-Cookie': 'private'})
    monkeypatch.setattr(providers.requests, 'post', lambda *a, **k: r)
    assert providers.call_chat_api('url', 'key-secret', 'model', 'private-prompt', provider, {'1'}) is None
    log = capsys.readouterr().out
    assert f'{provider} HTTP 429' in log
    assert 'retry-after=60' in log and 'x-ratelimit-remaining-tokens=0' in log
    assert all(secret not in log for secret in ['hidden-token', 'key-secret', 'other-secret', 'do-not-log', 'private-prompt', '\x1b'])
    assert len(log) < 1100


def test_rejected_content_excerpt_is_safe(monkeypatch, capsys):
    r = response({'bad': 'key-secret\n\x1b' + 'x' * 5000})
    monkeypatch.setattr(providers.requests, 'post', lambda *a, **k: r)
    assert providers.call_chat_api('url', 'key-secret', 'model', 'private-prompt', 'Groq', {'1'}) is None
    log = capsys.readouterr().out
    assert 'missing_sections' in log and 'bad' in log
    assert 'key-secret' not in log and '\x1b' not in log and len(log) < 1000


def setup_day(monkeypatch, tmp_path, old=None):
    day = datetime.now(summarize.LOCAL_TZ).date().isoformat()
    commits = [{'id': 1, 'created': f'{day}T12:00:00', 'branch': 'main', 'message': 'Sound polish'}]
    commits_path = tmp_path / 'commits.json'
    summaries_path = tmp_path / 'summaries.json'
    commits_path.write_text(json.dumps(commits))
    summaries_path.write_text(json.dumps({day: old} if old else {}))
    monkeypatch.setattr(summarize, 'COMMITS_FILE', commits_path)
    monkeypatch.setattr(summarize, 'SUMMARY_FILE', summaries_path)
    monkeypatch.setattr(summarize, 'filter_player_relevant_commits', lambda c, **kw: c)
    monkeypatch.setenv('GROQ_API_KEY', 'groq-secret')
    monkeypatch.setenv('OPENROUTER_API_KEY', 'router-secret')
    return day, summaries_path


def test_empty_success_cached_and_rendered(monkeypatch, tmp_path):
    day, path = setup_day(monkeypatch, tmp_path)
    calls = []
    def post(*a, **kw):
        calls.append(a)
        return response(EMPTY)
    monkeypatch.setattr(providers.requests, 'post', post)
    summarize.main()
    entry = json.loads(path.read_text())[day]
    assert entry['relevant_signature'] == '1'
    assert entry['status'] == 'no_significant_updates'
    assert entry['sections'] == [] and entry['summary'] == summarize.NO_SIGNIFICANT_UPDATES
    assert entry['commit_count'] == entry['relevant_commit_count'] == 1
    summarize.main()
    assert len(calls) == 1
    monkeypatch.setattr(rss, 'SUMMARY_FILE', path)
    monkeypatch.setattr(rss, 'OUTPUT_FILE', tmp_path / 'feed.xml')
    rss.main()
    feed = (tmp_path / 'feed.xml').read_text()
    assert summarize.NO_SIGNIFICANT_UPDATES in feed
    assert 'temporarily unavailable' not in feed


@pytest.mark.parametrize('old_good', [False, True])
def test_failure_fallback_or_preservation(monkeypatch, tmp_path, old_good):
    old = {'summary': 'Previous good summary', 'sections': SECTIONS,
           'relevant_signature': 'old', 'prompt_version': summarize.PROMPT_VERSION} if old_good else None
    day, path = setup_day(monkeypatch, tmp_path, old)
    monkeypatch.setattr(providers.requests, 'post', lambda *a, **kw: response(status=429))
    summarize.main()
    entry = json.loads(path.read_text())[day]
    if old_good:
        assert entry['summary'] == old['summary'] and entry['sections'] == SECTIONS
        assert entry['relevant_signature'] == 'old'
    else:
        assert entry['summary'].startswith('AI summary temporarily unavailable.')
        assert entry['relevant_signature'] == ''
        assert entry['status'] == 'unavailable'


def test_empty_chunks_are_cached_and_skip_empty_merge(monkeypatch):
    monkeypatch.setattr(summarize, 'CHUNK_SIZE', 1)
    commits = [{'id': 1}, {'id': 2}]
    calls = []
    def request(*args):
        calls.append(args[-1])
        return []
    monkeypatch.setattr(summarize, 'request_sections', request)
    assert summarize.call_ai('key', None, 'day', commits, {'1': []}) == ([], {})
    assert calls == ['day chunk 2/2']


def test_all_prompts_define_explicit_outcomes():
    commit = {'id': 1, 'message': 'Sound polish'}
    for prompt in [prompts.build_full_prompt('day', [commit]), prompts.build_chunk_prompt('day', [commit]),
                   prompts.build_merge_prompt('day', SECTIONS), prompts.build_rescue_prompt('day', [commit])]:
        assert '"status": "no_significant_updates", "sections": []' in prompt
        assert '"status": "ok"' in prompt
