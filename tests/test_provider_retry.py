import json
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from types import SimpleNamespace

import pytest

from scripts import providers


SECTIONS = [{"title": "Gameplay", "items": [{"text": "A useful change.", "commit_ids": [1]}]}]


def reply(status, retry_after=None):
    headers = {} if retry_after is None else {"Retry-After": retry_after}
    return SimpleNamespace(
        status_code=status, ok=status == 200, headers=headers,
        text='{"error":"rate limit"}' if status == 429 else '',
        json=lambda: {"choices": [{"message": {"content": json.dumps({"status": "ok", "sections": SECTIONS})}}]},
    )


def test_sixteen_second_rate_limit_retries_groq_and_recovers(monkeypatch):
    """Production Groq 429s return Retry-After: 16 (token-per-minute limit)."""
    calls = []
    sleeps = []
    responses = iter([reply(429, '16'), reply(200)])

    def post(url, **kwargs):
        calls.append((url, kwargs))
        return next(responses)

    monkeypatch.setattr(providers.requests, 'post', post)
    monkeypatch.setattr(providers.time, 'sleep', sleeps.append)

    result = providers.request_sections('groq-key', 'openrouter-key', 'prompt', {'1'}, 'day')

    assert result == SECTIONS
    assert sleeps == [16]
    assert len(calls) == 2
    assert all(url == providers.GROQ_URL for url, _ in calls)
    assert calls[0][1] == calls[1][1]


def test_twenty_second_rate_limit_is_supported(monkeypatch):
    calls = []
    sleeps = []
    responses = iter([reply(429, '20'), reply(200)])
    monkeypatch.setattr(providers.requests, 'post', lambda url, **kw: (calls.append(url), next(responses))[1])
    monkeypatch.setattr(providers.time, 'sleep', sleeps.append)

    assert providers.request_sections('groq-key', 'router-key', 'prompt', {'1'}, 'day') == SECTIONS
    assert calls == [providers.GROQ_URL] * 2
    assert sleeps == [20]
    assert providers.MAX_RETRY_AFTER_SECONDS >= 20


def test_two_short_rate_limits_allow_two_retries_then_success(monkeypatch):
    calls = []
    sleeps = []
    responses = iter([reply(429, '0.5'), reply(429, '2'), reply(200)])
    monkeypatch.setattr(providers.requests, 'post', lambda url, **kw: (calls.append(url), next(responses))[1])
    monkeypatch.setattr(providers.time, 'sleep', sleeps.append)
    assert providers.request_sections('groq-key', 'router-key', 'prompt', {'1'}, 'day') == SECTIONS
    assert calls == [providers.GROQ_URL] * 3
    assert sleeps == [0.5, 2]


@pytest.mark.parametrize('header', [None, '', 'garbage', 'nan', '-1', '31', '60'])
def test_missing_malformed_or_excessive_delay_falls_back_without_wait(monkeypatch, header):
    calls = []
    sleeps = []

    def post(url, **kwargs):
        calls.append(url)
        return reply(429, header) if url == providers.GROQ_URL else reply(200)

    monkeypatch.setattr(providers.requests, 'post', post)
    monkeypatch.setattr(providers.time, 'sleep', sleeps.append)
    assert providers.request_sections('groq-key', 'router-key', 'prompt', {'1'}, 'day') == SECTIONS
    assert calls == [providers.GROQ_URL, providers.OPENROUTER_URL]
    assert sleeps == []


def test_persistent_groq_429_falls_back_after_at_most_three_retries(monkeypatch):
    calls = []
    sleeps = []

    def post(url, **kwargs):
        calls.append(url)
        return reply(429, '1') if url == providers.GROQ_URL else reply(200)

    monkeypatch.setattr(providers.requests, 'post', post)
    monkeypatch.setattr(providers.time, 'sleep', sleeps.append)
    assert providers.request_sections('groq-key', 'router-key', 'prompt', {'1'}, 'day') == SECTIONS
    assert calls == [providers.GROQ_URL] * 4 + [providers.OPENROUTER_URL]
    assert sleeps == [1, 1, 1]


def test_total_retry_wait_budget_is_bounded(monkeypatch):
    """Long-but-valid Retry-After values cannot sleep past the total budget."""
    calls = []
    sleeps = []

    def post(url, **kwargs):
        calls.append(url)
        return reply(429, '25') if url == providers.GROQ_URL else reply(200)

    monkeypatch.setattr(providers.requests, 'post', post)
    monkeypatch.setattr(providers.time, 'sleep', sleeps.append)
    monkeypatch.setattr(providers, 'MAX_TOTAL_RETRY_WAIT_SECONDS', 45)

    assert providers.request_sections('groq-key', 'router-key', 'prompt', {'1'}, 'day') == SECTIONS
    assert sleeps == [25]
    assert calls == [providers.GROQ_URL] * 2 + [providers.OPENROUTER_URL]


def test_permanent_error_never_retries(monkeypatch):
    calls = []
    sleeps = []

    def post(url, **kwargs):
        calls.append(url)
        return reply(401, '3') if url == providers.GROQ_URL else reply(200)

    monkeypatch.setattr(providers.requests, 'post', post)
    monkeypatch.setattr(providers.time, 'sleep', sleeps.append)
    assert providers.request_sections('groq-key', 'router-key', 'prompt', {'1'}, 'day') == SECTIONS
    assert calls == [providers.GROQ_URL, providers.OPENROUTER_URL]
    assert sleeps == []


def test_retry_after_http_dates_are_bounded_by_the_same_limit():
    soon = format_datetime(datetime.now(timezone.utc) + timedelta(seconds=3))
    supported = format_datetime(datetime.now(timezone.utc) + timedelta(seconds=25))
    later = format_datetime(datetime.now(timezone.utc) + timedelta(seconds=35))
    assert 0 <= providers.bounded_retry_after({'retry-after': soon}) <= 3
    assert 0 <= providers.bounded_retry_after({'retry-after': supported}) <= 30
    assert providers.bounded_retry_after({'retry-after': later}) is None
