"""
Tests for RSS/Atom ingestion, feed normalization, and attachment discovery.
"""

from pathlib import Path
import pytest
import respx
import httpx

from jyot_monitor.ingestion.fetcher import SourceFetcher, SourceUnavailableError
from jyot_monitor.ingestion.network import SafeHttpClient
from jyot_monitor.ingestion.rss_parser import parse_feed_xml
from jyot_monitor.models import Attachment, SourceItem
from jyot_monitor.storage import Storage


SAMPLE_RSS_2_XML = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:media="http://search.yahoo.com/mrss/">
  <channel>
    <title>CPSC Recalls Feed</title>
    <link>https://www.cpsc.gov/recalls</link>
    <description>Official CPSC product safety recalls</description>
    <item>
      <title>Children's Sleepwear Recalled Due to Burn Hazard</title>
      <link>https://www.cpsc.gov/recalls/2026/sleepwear-burn-hazard</link>
      <guid isPermaLink="true">https://www.cpsc.gov/recalls/2026/sleepwear-burn-hazard</guid>
      <pubDate>Mon, 18 May 2026 10:00:00 GMT</pubDate>
      <description><![CDATA[<p>The recalled garments fail to meet flammability standards. Contact firm for refund.</p><img src="https://www.cpsc.gov/images/sleepwear.jpg" />]]></description>
      <enclosure url="https://www.cpsc.gov/docs/sleepwear-notice.pdf" type="application/pdf" length="102400" />
    </item>
  </channel>
</rss>
"""

SAMPLE_ATOM_XML = """<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>FDA Recalls Atom</title>
  <link href="https://www.fda.gov/recalls"/>
  <updated>2026-06-18T12:00:00Z</updated>
  <entry>
    <title>Salad Kits Recalled for Listeria Risk</title>
    <id>urn:uuid:fda-recall-salad-2026</id>
    <link href="https://www.fda.gov/safety/recalls/salad-kits"/>
    <updated>2026-06-18T12:00:00Z</updated>
    <summary type="html">&lt;p&gt;Potential contamination with Listeria monocytogenes.&lt;/p&gt;</summary>
    <link rel="enclosure" type="image/png" href="https://www.fda.gov/media/salad-label.png"/>
  </entry>
</feed>
"""


def test_parse_rss_2_normalization_and_attachments():
    """Verify parse_feed_xml correctly extracts and normalizes RSS 2.0 items and attachments."""
    items, new_cursor = parse_feed_xml(
        SAMPLE_RSS_2_XML,
        source_name="CPSC Recalls",
        base_url="https://www.cpsc.gov/recalls",
    )

    assert len(items) == 1
    item, attachments = items[0]

    assert item.source == "CPSC Recalls"
    assert "Children's Sleepwear" in item.title
    assert "The recalled garments fail to meet flammability standards." in item.body
    assert item.url == "https://www.cpsc.gov/recalls/2026/sleepwear-burn-hazard"
    assert item.item_id.startswith("cpsc_r_")

    # Verify attachment discovery: enclosure PDF + img tag JPG
    assert len(attachments) == 2
    att_urls = [a.url for a in attachments]
    assert "https://www.cpsc.gov/docs/sleepwear-notice.pdf" in att_urls
    assert "https://www.cpsc.gov/images/sleepwear.jpg" in att_urls


def test_parse_atom_normalization_and_attachments():
    """Verify parse_feed_xml extracts and normalizes Atom feed items."""
    items, new_cursor = parse_feed_xml(
        SAMPLE_ATOM_XML,
        source_name="FDA Recalls",
        base_url="https://www.fda.gov/recalls",
    )

    assert len(items) == 1
    item, attachments = items[0]

    assert item.source == "FDA Recalls"
    assert "Salad Kits Recalled" in item.title
    assert "Potential contamination with Listeria" in item.body
    assert item.item_id.startswith("fda_re_")

    assert len(attachments) == 1
    assert attachments[0].url == "https://www.fda.gov/media/salad-label.png"
    assert attachments[0].mime_type == "image/png"


def test_parse_malformed_xml_handling():
    """Verify parse_feed_xml raises actionable error on broken XML."""
    broken_xml = "<rss><channel><item><title>Unclosed tag"
    with pytest.raises(ValueError, match="Malformed or unsafe XML"):
        parse_feed_xml(broken_xml, source_name="Bad Source")


@respx.mock
def test_source_fetcher_polling_and_cursor_persistence(tmp_path: Path):
    """Verify SourceFetcher updates persistent feed cursors and skips duplicates."""
    db_path = tmp_path / "test_ingest.db"
    storage = Storage(db_path)
    client = SafeHttpClient()
    fetcher = SourceFetcher(storage=storage, http_client=client)

    feed_url = "https://www.cpsc.gov/feed.xml"
    respx.get(feed_url).respond(
        status_code=200,
        text=SAMPLE_RSS_2_XML,
        headers={"Content-Type": "application/rss+xml"},
    )

    source_cfg = {
        "name": "CPSC Recalls",
        "url": feed_url,
        "allowed_hosts": ["www.cpsc.gov"],
    }

    # 1. First poll: item is new
    new_items, att_map = fetcher.poll_source(source_cfg)
    assert len(new_items) == 1
    assert storage.get_item(new_items[0].item_id) is not None

    feed_state = storage.get_feed_state("CPSC Recalls")
    assert feed_state is not None
    assert feed_state["item_count"] == 1

    # 2. Second poll: duplicate item skipped
    new_items_2, att_map_2 = fetcher.poll_source(source_cfg)
    assert len(new_items_2) == 0


@respx.mock
def test_source_fetcher_download_attachment_validation(tmp_path: Path):
    """Verify download_attachment enforces allowed hosts and validates file signatures."""
    db_path = tmp_path / "test_dl.db"
    storage = Storage(db_path)
    downloads_dir = tmp_path / "downloads"
    fetcher = SourceFetcher(storage=storage, http_client=SafeHttpClient(), attachment_dir=downloads_dir)

    att_url = "https://www.cpsc.gov/images/crib.png"
    valid_png_content = b"\x89PNG\r\n\x1a\n" + b"\x00" * 40
    respx.get(att_url).respond(
        status_code=200,
        content=valid_png_content,
        headers={"Content-Type": "image/png"},
    )

    attachment = Attachment(
        attachment_id="att_crib_01",
        item_id="item_01",
        url=att_url,
        mime_type="image/png",
    )

    # Allowed download
    saved_path = fetcher.download_attachment(attachment, allowed_hosts=["www.cpsc.gov"])
    assert saved_path.exists()
    assert saved_path.read_bytes() == valid_png_content
    assert attachment.size_bytes == len(valid_png_content)
