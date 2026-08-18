import json
from datetime import datetime
from email.utils import format_datetime
from pathlib import Path
from xml.etree.ElementTree import Element, SubElement, ElementTree

SUMMARY_FILE = Path("site/summaries.json")
OUTPUT_FILE = Path("site/feed.xml")

SITE_URL = "https://aslabsalbeh.github.io/rust-dev-feed/"
FEED_URL = SITE_URL + "feed.xml"


def main():
    with open(SUMMARY_FILE, "r", encoding="utf-8") as file:
        summaries = json.load(file)

    rss = Element("rss", version="2.0")
    channel = SubElement(rss, "channel")

    SubElement(channel, "title").text = "Rust Development Updates"
    SubElement(channel, "link").text = SITE_URL
    SubElement(channel, "description").text = (
        "AI-summarized daily development updates from "
        "Facepunch's Rust commits."
    )
    SubElement(channel, "language").text = "en-ca"
    SubElement(channel, "ttl").text = "15"

    dates = sorted(summaries.keys(), reverse=True)[:3]

    for position, day in enumerate(dates):
        data = summaries[day]

        date_obj = datetime.fromisoformat(day)

        if position == 0:
            label = "Today's Rust Updates"
        elif position == 1:
            label = "Yesterday's Rust Updates"
        else:
            label = "Rust Updates — 2 Days Ago"

        display_date = date_obj.strftime("%b %d")

        item = SubElement(channel, "item")

        SubElement(item, "title").text = (
            f"{label} — {display_date}"
        )

        SubElement(item, "description").text = (
            f"{data['commit_count']} development commits\n\n"
            f"{data['summary']}"
        )

        SubElement(item, "link").text = SITE_URL

        # Stable ID for each calendar day
        SubElement(
            item,
            "guid",
            isPermaLink="false"
        ).text = f"rust-dev-{day}"

        SubElement(item, "pubDate").text = format_datetime(
            date_obj.astimezone()
        )

    tree = ElementTree(rss)
    ElementTree.indent(tree, space="  ")

    tree.write(
        OUTPUT_FILE,
        encoding="utf-8",
        xml_declaration=True,
    )

    print(f"Generated RSS feed with {len(dates)} daily items.")


if __name__ == "__main__":
    main()
