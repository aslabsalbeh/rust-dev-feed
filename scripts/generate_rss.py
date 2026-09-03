import json
import xml.etree.ElementTree as ET
from datetime import datetime, time
from email.utils import format_datetime
from html import escape
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
    safe_text = escape(str(text))
    return markdown.markdown(
        safe_text,
        extensions=[
            "extra",
            "sane_lists",
        ],
    )


def structured_items_to_html(items):
    rendered_items = []

    for item in items:
        commit_ids = ",".join(
            str(commit_id)
            for commit_id in item.get(
                "commit_ids",
                [],
            )
        )
        rendered_items.append(
            '<li data-rust-commits="'
            f'{escape(commit_ids, quote=True)}">'
            f'{escape(str(item.get("text", "")))}'
            "</li>"
        )

    if not rendered_items:
        return ""

    return "<ul>\n" + "\n".join(rendered_items) + "\n</ul>"


def structured_sections_to_html(sections):
    rendered_sections = []

    for section in sections:
        items_html = structured_items_to_html(
            section.get(
                "items",
                [],
            )
        )
        if not items_html:
            continue

        title = escape(
            str(
                section.get(
                    "title",
                    "",
                )
            )
        )
        rendered_sections.append(
            f"<h3>{title}</h3>\n{items_html}"
        )

    return "\n".join(rendered_sections)


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

    rendered_days = 0

    for day in dates:
        data = summaries.get(day)
        if not isinstance(data, dict):
            print(f"Skipping malformed summary day {day}: not an object.")
            continue
        try:
            item_date = datetime.fromisoformat(day).date()
        except (TypeError, ValueError):
            print(f"Skipping malformed summary day key: {day!r}")
            continue
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

        sections = data.get(
            "sections",
        )
        if isinstance(sections, list) and sections:
            summary_html = structured_sections_to_html(
                sections
            )
        else:
            summary_html = markdown_to_html(
                data.get(
                    "summary",
                    "No significant player-facing updates.",
                )
            )

        new_html = ""
        if "new_items" in data:
            new_items = data.get(
                "new_items",
            )
            if isinstance(new_items, list) and new_items:
                rendered_new = structured_items_to_html(
                    new_items
                )
                if rendered_new:
                    new_html = f"""
<div class="rust-new-updates">
<h3>✨ NEW — LAST 3 HRS</h3>
{rendered_new}
</div>
""".strip()
        else:
            # Backward compatibility for summaries generated before
            # structured NEW metadata was added.
            new_summary = data.get(
                "new_summary",
                "",
            ).strip()

            new_count = data.get(
                "new_relevant_count",
                0,
            )

            if new_summary and new_count > 0:
                rendered_new = markdown_to_html(
                    new_summary
                )
                new_html = f"""
<div class="rust-new-updates">
<h3>✨ NEW — LAST 3 HRS</h3>
{rendered_new}
</div>
""".strip()

        description_html = f"""
<div class="rust-dev-summary">
<p><strong>{data.get('commit_count', 0)} development commits</strong></p>
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
        rendered_days += 1

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
        f"{rendered_days} daily items."
    )


if __name__ == "__main__":
    main()
