import xml.etree.ElementTree as ET
import scripts.generate_rss as generate_rss


def test_markdown_fallback_escapes_raw_html():
    rendered = generate_rss.markdown_to_html(
        '- Fixed <script>alert("x")</script> & item'
    )
    assert "<script>" not in rendered
    assert "&lt;script&gt;" in rendered


def test_main_tolerates_missing_optional_summary_fields(tmp_path, monkeypatch):
    summaries = tmp_path / "summaries.json"
    output = tmp_path / "feed.xml"
    summaries.write_text(
        '{"2026-09-03":{"sections":[]}}',
        encoding="utf-8",
    )
    monkeypatch.setattr(generate_rss, "SUMMARY_FILE", summaries)
    monkeypatch.setattr(generate_rss, "OUTPUT_FILE", output)
    generate_rss.main()
    ET.parse(output)
    text = output.read_text(encoding="utf-8")
    assert "No significant player-facing updates." in text
