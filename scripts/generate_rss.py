import json
import xml.etree.ElementTree as ET
from datetime import datetime, time
from email.utils import format_datetime
from pathlib import Path
from xml.etree.ElementTree import Element, SubElement, ElementTree
from zoneinfo import ZoneInfo

import markdown


SUMMARY_FILE = Path("site/summaries.json")
OUTPUT_FILE = Path("site/feed.xml")

LOCAL_TZ = ZoneInfo("America/Toronto")

SITE_URL = "https://aslabsalbeh.github.io/rust-dev-feed/"
FEED_URL = SITE_URL + "feed.xml"


def load_summaries():
    with open(
        SUMMARY_FILE,
        "r",
        encoding="utf-8",
    ) as file:
        return json.load(file)


def markdown_to_html(text):
    return markdown.markdown(
        text,
        extensions=[
            "extra",
            "sane_lists",
        ],
    )


def make_pub_date(day, is_today):
    day_date = datetime.fromisoformat(day).date()

    if is_today:
        # Today's entry carries the current local time.
        dt = datetime.now(LOCAL_TZ)
    else:
        # Historical entries use noon rather than midnight.
        # This avoids timezone/display weirdness in RSS readers.
        dt = datetime.combine(
            day_date,
            time(hour=12),
            tzinfo=LOCAL_TZ,
        )

    return format_datetime(dt)


def main():
    summaries = load_summaries()

    rss = Element(
        "rss",
        version="2.0",
    )

    channel = SubElement(rss, "channel")

    SubElement(
        channel,
        "title",
    ).text = "Rust Development Updates"

    SubElement(
        channel,
        "link",
    ).text = SITE_URL

    SubElement(
        channel,
        "description",
    ).text = (
        "AI-summarized daily Rust development updates "
        "from Facepunch source-control commits."
    )

    SubElement(
        channel,
        "language",
    ).text = "en-ca"

    SubElement(
        channel,
        "ttl",
    ).text = "15"

    SubElement(
        channel,
        "lastBuildDate",
    ).text = format_datetime(
        datetime.now(LOCAL_TZ)
    )

    dates = sorted(
        summaries.keys(),
        reverse=True,
    )[:3]

    today = datetime.now(
        LOCAL_TZ
    ).date().isoformat()

    for position, day in enumerate(dates):
        data = summaries[day]

        date_obj = datetime.fromisoformat(day)
        display_date = date_obj.strftime("%b %d")

        if day == today:
            label = "Today's Rust Updates"

        elif position == 1:
            label = "Yesterday's Rust Updates"

        else:
            label = "Rust Updates — 2 Days Ago"

        item = SubElement(
            channel,
            "item",
        )

        SubElement(
            item,
            "title",
        ).text = (
            f"{label} — {display_date}"
        )

        summary_html = markdown_to_html(
            data["summary"]
        )

        description_html = f"""
<div class="rust-dev-summary">
<p><strong>{data['commit_count']} development commits</strong></p>
{summary_html}
</div>
""".strip()

        SubElement(
            item,
            "description",
        ).text = description_html

        SubElement(
            item,
            "link",
        ).text = SITE_URL

        # Stable GUID per calendar day.
        # Today's item can therefore update without appearing
        # as a completely new RSS item each run.
        SubElement(
            item,
            "guid",
            isPermaLink="false",
        ).text = f"rust-dev-{day}"

        SubElement(
            item,
            "pubDate",
        ).text = make_pub_date(
            day,
            day == today,
        )

    tree = ElementTree(rss)

    ET.indent(
        tree,
        space="  ",
    )

    tree.write(
        OUTPUT_FILE,
        encoding="utf-8",
        xml_declaration=True,
    )

    print(
        f"Generated RSS feed with "
        f"{len(dates)} daily items."
    )


if __name__ == "__main__":
    main()
