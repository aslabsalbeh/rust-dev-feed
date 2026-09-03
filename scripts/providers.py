import json

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


def parse_structured_summary(
    text,
    allowed_commit_ids,
):
    text = strip_code_fence(
        text
    )

    try:
        data = json.loads(
            text
        )
    except Exception as error:
        print(
            f"Could not parse AI JSON: "
            f"{error}"
        )
        return None

    # Normally the model returns {"sections": [...]}, as requested.
    # Some providers can still return the sections array itself even in
    # JSON mode. Treat that shape as a recoverable equivalent instead of
    # crashing with: AttributeError: 'list' object has no attribute 'get'.
    if isinstance(data, dict):
        raw_sections = data.get(
            "sections"
        )
    elif isinstance(data, list):
        print(
            "AI returned a top-level sections list; "
            "accepting it as structured summary data."
        )
        raw_sections = data
    else:
        return None

    if not isinstance(
        raw_sections,
        list,
    ):
        return None

    sections = []

    for raw_section in raw_sections:
        if not isinstance(
            raw_section,
            dict,
        ):
            continue

        title = str(
            raw_section.get(
                "title",
                "",
            )
        ).strip()

        raw_items = raw_section.get(
            "items",
            [],
        )

        if (
            not title
            or not isinstance(
                raw_items,
                list,
            )
        ):
            continue

        items = []

        for raw_item in raw_items:
            if not isinstance(
                raw_item,
                dict,
            ):
                continue

            item_text = str(
                raw_item.get(
                    "text",
                    "",
                )
            ).strip()

            raw_ids = raw_item.get(
                "commit_ids",
                [],
            )

            if (
                not item_text
                or not isinstance(
                    raw_ids,
                    list,
                )
            ):
                continue

            valid_ids = []

            for raw_id in raw_ids:
                try:
                    commit_id = str(
                        int(raw_id)
                    )
                except Exception:
                    continue

                if (
                    commit_id
                    in allowed_commit_ids
                    and commit_id
                    not in valid_ids
                ):
                    valid_ids.append(
                        commit_id
                    )

            if not valid_ids:
                print(
                    "Dropped AI bullet with no "
                    "valid source commit IDs: "
                    f"{item_text[:80]}"
                )
                continue

            items.append(
                {
                    "text": item_text,
                    "commit_ids": [
                        int(value)
                        for value in valid_ids
                    ],
                }
            )

        if items:
            sections.append(
                {
                    "title": title,
                    "items": items,
                }
            )

    if not sections:
        return None

    return sections


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
            f"{error}"
        )
        return None

    if response.status_code == 429:
        print(
            f"{provider_name} rate-limited."
        )
        return None

    if not response.ok:
        print(
            f"{provider_name} error "
            f"{response.status_code}: "
            f"{response.text[:300]}"
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
            "rejected AI output."
        )
        return None

    sections = parse_structured_summary(
        text,
        allowed_commit_ids,
    )

    if sections is None:
        print(
            f"{provider_name} returned "
            "invalid structured summary JSON."
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
