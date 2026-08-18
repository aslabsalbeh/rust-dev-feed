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
        dt = datetime.now(LOCAL_TZ)
    else:
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

    today_date = datetime.now(
        LOCAL_TZ
    ).date()

    for day in dates:
        data = summaries[day]

        item_date = datetime.fromisoformat(day).date()
        days_ago = (today_date - item_date).days

        if days_ago == 0:
            label = "Today's Rust Updates"

        elif days_ago == 1:
            label = "Yesterday's Rust Updates"

        elif days_ago == 2:
            label = "Rust Updates — 2 Days Ago"

        else:
            label = "Rust Development Updates"

        display_date = item_date.strftime("%b %d")

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

new_summary = data.get(
    "new_summary",
    "",
).strip()

new_count = data.get(
    "new_relevant_count",
    0,
)

new_html = ""

if new_summary and new_count > 0:
    rendered_new = markdown_to_html(
        new_summary
    )

    new_html = f"""
<div class="rust-new-updates">
<h3>✨ NEW — LAST 3 HRS</h3>
{rendered_new}
</div>
"""

description_html = f"""
<div class="rust-dev-summary">
<p><strong>{data['commit_count']} development commits</strong></p>
{new_html}
{summary_html}
</div>
""".strip()

        SubElement(
            item,
            "description",
        ).text = description_html

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
            days_ago == 0,
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
