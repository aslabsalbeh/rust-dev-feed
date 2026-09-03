import json

from scripts.providers import parse_structured_summary


def test_parse_structured_summary_accepts_normal_object_shape():
    text = json.dumps(
        {
            "sections": [
                {
                    "title": "Vehicles",
                    "items": [
                        {
                            "text": "Fixed attack helicopter collider damage.",
                            "commit_ids": [619743],
                        }
                    ],
                }
            ]
        }
    )

    assert parse_structured_summary(text, {"619743"}) == [
        {
            "title": "Vehicles",
            "items": [
                {
                    "text": "Fixed attack helicopter collider damage.",
                    "commit_ids": [619743],
                }
            ],
        }
    ]


def test_parse_structured_summary_accepts_top_level_sections_list():
    # Groq has occasionally returned this valid JSON shape during the
    # large-day final merge even though the prompt asks for an object.
    text = json.dumps(
        [
            {
                "title": "Vehicles",
                "items": [
                    {
                        "text": "Fixed attack helicopter collider damage.",
                        "commit_ids": [619743],
                    }
                ],
            }
        ]
    )

    assert parse_structured_summary(text, {"619743"}) == [
        {
            "title": "Vehicles",
            "items": [
                {
                    "text": "Fixed attack helicopter collider damage.",
                    "commit_ids": [619743],
                }
            ],
        }
    ]


def test_parse_structured_summary_rejects_unrelated_top_level_type():
    assert parse_structured_summary('"not sections"', {"619743"}) is None
