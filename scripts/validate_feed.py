import json
import xml.etree.ElementTree as ET
from pathlib import Path


SUMMARY_FILE = Path("site/summaries.json")
FEED_FILE = Path("site/feed.xml")


def validate_summaries():
    with open(
        SUMMARY_FILE,
        "r",
        encoding="utf-8",
    ) as file:
        summaries = json.load(file)

    if not isinstance(summaries, dict):
        raise ValueError(
            "summaries.json must contain an object."
        )

    if not summaries:
        raise ValueError(
            "summaries.json contains no daily summaries."
        )

    for day, data in summaries.items():
        if not isinstance(data, dict):
            raise ValueError(
                f"{day}: summary entry is not an object."
            )

        summary = str(
            data.get("summary", "")
        ).strip()

        if not summary:
            raise ValueError(
                f"{day}: summary is empty."
            )

        sections = data.get(
            "sections",
            []
        )

        if not isinstance(sections, list):
            raise ValueError(
                f"{day}: sections must be a list."
            )

        for section in sections:
            title = str(
                section.get("title", "")
            ).strip()

            if not title:
                raise ValueError(
                    f"{day}: section has an empty title."
                )

            items = section.get(
                "items",
                []
            )

            if not isinstance(items, list):
                raise ValueError(
                    f"{day}: section items must be a list."
                )

            for item in items:
                text = str(
                    item.get("text", "")
                ).strip()

                if not text:
                    raise ValueError(
                        f"{day}: summary bullet has empty text."
                    )

                commit_ids = item.get(
                    "commit_ids",
                    []
                )

                if not isinstance(
                    commit_ids,
                    list,
                ):
                    raise ValueError(
                        f"{day}: commit_ids must be a list."
                    )

                if not commit_ids:
                    raise ValueError(
                        f"{day}: structured bullet has no commit IDs."
                    )

    print(
        f"Validated {len(summaries)} "
        "summary day(s)."
    )


def validate_rss():
    tree = ET.parse(
        FEED_FILE
    )

    root = tree.getroot()

    if root.tag != "rss":
        raise ValueError(
            "feed.xml root is not <rss>."
        )

    channel = root.find(
        "channel"
    )

    if channel is None:
        raise ValueError(
            "feed.xml has no <channel>."
        )

    items = channel.findall(
        "item"
    )

    if not 1 <= len(items) <= 3:
        raise ValueError(
            f"feed.xml contains {len(items)} items; "
            "expected between 1 and 3."
        )

    for item in items:
        title = item.findtext(
            "title",
            default="",
        ).strip()

        description = item.findtext(
            "description",
            default="",
        ).strip()

        guid = item.findtext(
            "guid",
            default="",
        ).strip()

        pub_date = item.findtext(
            "pubDate",
            default="",
        ).strip()

        if not title:
            raise ValueError(
                "RSS item has no title."
            )

        if not description:
            raise ValueError(
                f"{title}: RSS description is empty."
            )

        if not guid:
            raise ValueError(
                f"{title}: RSS GUID is empty."
            )

        if not pub_date:
            raise ValueError(
                f"{title}: RSS pubDate is empty."
            )

    print(
        f"Validated RSS feed with "
        f"{len(items)} item(s)."
    )


def main():
    validate_summaries()
    validate_rss()

    print(
        "Feed validation passed."
    )


if __name__ == "__main__":
    main()
