import json
import os
import re
from collections import Counter

import requests


GROQ_MODEL = "openai/gpt-oss-120b"
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
OPENROUTER_MODEL = "google/gemma-4-31b-it:free"
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

BAD_MARKERS = (
    "We need to produce",
    "Let's identify themes",
    "We have many commits",
    "<unk>",
    "AI summary temporarily unavailable",
)


def is_bad_summary(text):
    if not text:
        return True
    lowered = text.lower()
    return any(marker.lower() in lowered for marker in BAD_MARKERS)



def strip_code_fence(text):
    text = text.strip()

    if text.startswith("```"):
        lines = text.splitlines()

        if lines:
            lines = lines[1:]

        if (
            lines
            and lines[-1].strip() == "```"
        ):
            lines = lines[:-1]

        text = "\n".join(
            lines
        ).strip()

    return text


def safe_excerpt(value, api_key="", limit=750):
    """Single-line, bounded diagnostics; never include known credentials."""
    text = str(value)
    for secret in (api_key, os.getenv("GROQ_API_KEY"), os.getenv("OPENROUTER_API_KEY")):
        if secret:
            text = text.replace(secret, "[REDACTED]")
    text = re.sub(r"(?i)bearer\s+[^\s\"',}]+", "Bearer [REDACTED]", text)
    text = re.sub(r"\b(?:sk-|gsk_)[A-Za-z0-9_-]+", "[REDACTED]", text)
    # Escape control characters, including terminal escapes and newlines.
    text = json.dumps(text, ensure_ascii=True)[1:-1]
    return text[:limit] + ("..." if len(text) > limit else "")


RATE_LIMIT_HEADERS = (
    "retry-after", "ratelimit-limit", "ratelimit-remaining", "ratelimit-reset",
    "x-ratelimit-limit", "x-ratelimit-remaining", "x-ratelimit-reset",
    "x-ratelimit-limit-requests", "x-ratelimit-remaining-requests",
    "x-ratelimit-reset-requests", "x-ratelimit-limit-tokens",
    "x-ratelimit-remaining-tokens", "x-ratelimit-reset-tokens",
)


def parse_structured_summary(text, allowed_commit_ids):
    """Return sections, [] for explicit intentional emptiness, or None on failure.

    Emit one bounded diagnostic with a reason and aggregate removal counts.
    Legacy nonempty objects/lists remain supported; implicit emptiness is invalid.
    """
    counts = Counter()

    def finish(result, reason):
        detail = ", ".join(f"{key}={value}" for key, value in sorted(counts.items()))
        print(f"Structured validation: {reason}" + (f" ({detail})" if detail else ""))
        return result

    try:
        data = json.loads(strip_code_fence(text))
    except (ValueError, TypeError):
        return finish(None, "json_parse_failure")

    status = None
    if isinstance(data, dict):
        if "status" in data:
            status = data["status"]
            if status not in ("ok", "no_significant_updates"):
                return finish(None, "invalid_status")
        if "sections" not in data:
            return finish(None, "missing_sections")
        raw_sections = data["sections"]
    elif isinstance(data, list):
        raw_sections = data
    else:
        return finish(None, "wrong_top_level_type")
    if not isinstance(raw_sections, list):
        return finish(None, "sections_not_list")
    if status == "no_significant_updates":
        if raw_sections:
            return finish(None, "no_significant_updates_with_nonempty_sections")
        if set(data) != {"status", "sections"}:
            return finish(None, "unexpected_empty_outcome_fields")
        return finish([], "no_significant_updates")
    if not raw_sections:
        return finish(None, "empty_sections_without_explicit_outcome")

    sections = []
    valid_section_count = 0
    for section in raw_sections:
        if (not isinstance(section, dict)
                or not isinstance(section.get("title"), str)
                or not section["title"].strip()
                or not isinstance(section.get("items"), list)):
            counts["invalid_sections"] += 1
            continue
        valid_section_count += 1
        items = []
        for item in section["items"]:
            if (not isinstance(item, dict)
                    or not isinstance(item.get("text"), str)
                    or not item["text"].strip()):
                counts["invalid_items"] += 1
                continue
            raw_ids = item.get("commit_ids")
            if raw_ids is None or raw_ids == []:
                counts["items_missing_commit_ids"] += 1
                continue
            if not isinstance(raw_ids, list):
                counts["items_invalid_commit_ids"] += 1
                continue
            ids = []
            invalid = False
            unknown = False
            for value in raw_ids:
                # Never truncate floats or accept bool as an integer ID.
                if type(value) is int and value >= 0:
                    commit_id = str(value)
                elif isinstance(value, str) and re.fullmatch(r"[0-9]+", value):
                    commit_id = value.lstrip("0") or "0"
                else:
                    invalid = True
                    continue
                if commit_id not in allowed_commit_ids:
                    unknown = True
                elif int(commit_id) not in ids:
                    ids.append(int(commit_id))
            if invalid or unknown:
                counts["items_invalid_commit_ids"] += int(invalid)
                counts["items_unknown_commit_ids"] += int(unknown)
                continue
            items.append({"text": item["text"].strip(), "commit_ids": ids})
        if items:
            sections.append({"title": section["title"].strip(), "items": items})
    if not valid_section_count:
        return finish(None, "all_sections_invalid")
    if not sections:
        return finish(None, "all_items_removed")
    if any(counts.values()):
        return finish(None, "partially_invalid_summary")
    return finish(sections, "valid_structured_summary")


def call_chat_api(
    url,
    api_key,
    model,
    prompt,
    provider_name,
    allowed_commit_ids,
):
    payload = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": prompt,
            }
        ],
        "temperature": 0.1,
    }

    # Groq supports JSON mode, which makes large structured
    # responses much more reliable.
    if provider_name == "Groq":
        payload[
            "response_format"
        ] = {
            "type": "json_object"
        }

    try:
        response = requests.post(
            url,
            headers={
                "Authorization": (
                    f"Bearer {api_key}"
                ),
                "Content-Type": (
                    "application/json"
                ),
            },
            json=payload,
            timeout=90,
        )

    except requests.RequestException as error:
        print(
            f"{provider_name} network error: "
            f"{safe_excerpt(error, api_key)}"
        )
        return None

    if response.status_code == 429:
        headers = {key.lower(): value for key, value in response.headers.items()}
        details = " ".join(
            f"{key}={safe_excerpt(headers[key], api_key, 100)}"
            for key in RATE_LIMIT_HEADERS if key in headers
        )
        print(f"{provider_name} HTTP 429 rate-limited: {details} "
              f"body={safe_excerpt(response.text, api_key)}")
        return None

    if not response.ok:
        print(
            f"{provider_name} error "
            f"{response.status_code}: "
            f"{safe_excerpt(response.text, api_key)}"
        )
        return None

    try:
        data = response.json()

        text = (
            data["choices"][0]
            ["message"]["content"]
            .strip()
        )

    except Exception:
        print(
            f"{provider_name} returned "
            "an invalid API response."
        )
        return None

    if is_bad_summary(text):
        print(
            f"{provider_name} returned "
            f"rejected AI output: {safe_excerpt(text, api_key)}"
        )
        return None

    sections = parse_structured_summary(
        text,
        allowed_commit_ids,
    )

    if sections is None:
        print(
            f"{provider_name} returned "
            f"invalid structured summary JSON: {safe_excerpt(text, api_key)}"
        )
        return None

    return sections


def request_sections(
    groq_key,
    openrouter_key,
    prompt,
    allowed_ids,
    label,
):
    if groq_key:
        print(
            f"Trying Groq for {label}..."
        )

        sections = call_chat_api(
            GROQ_URL,
            groq_key,
            GROQ_MODEL,
            prompt,
            "Groq",
            allowed_ids,
        )

        if sections is not None:
            print(
                f"Groq succeeded for {label}."
            )
            return sections

    if openrouter_key:
        print(
            f"Trying OpenRouter fallback "
            f"for {label}..."
        )

        sections = call_chat_api(
            OPENROUTER_URL,
            openrouter_key,
            OPENROUTER_MODEL,
            prompt,
            "OpenRouter",
            allowed_ids,
        )

        if sections is not None:
            print(
                f"OpenRouter succeeded "
                f"for {label}."
            )
            return sections

    return None
