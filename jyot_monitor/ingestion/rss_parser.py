"""
RSS/Atom feed parsing and normalization module.

Uses defusedxml to securely parse XML feeds against XXE and expansion attacks.
Extracts:
- Canonical SourceItem fields with stable GUID-based IDs.
- Discovered attachments from <enclosure>, <media:content>, and embedded <img> tags.
- Feed cursor tokens for incremental polling.
"""

import hashlib
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
import urllib.parse

import defusedxml.ElementTree as ET
from bs4 import BeautifulSoup

from jyot_monitor.models import Attachment, ItemStatus, SourceItem, utc_now

# XML namespaces commonly found in RSS/Atom feeds
NAMESPACES = {
    "atom": "http://www.w3.org/2005/Atom",
    "media": "http://search.yahoo.com/mrss/",
    "dc": "http://purl.org/dc/elements/1.1/",
    "content": "http://purl.org/rss/1.0/modules/content/",
}

VALID_ATTACHMENT_EXTENSIONS = {".png", ".jpg", ".jpeg", ".pdf"}


def clean_html_text(raw_html: str) -> str:
    """Strip HTML markup and return clean human-readable text."""
    if not raw_html or not isinstance(raw_html, str):
        return ""
    try:
        soup = BeautifulSoup(raw_html, "html.parser")
        text = soup.get_text(separator=" ")
        return re.sub(r"\s+", " ", text).strip()
    except Exception:
        # Fallback simple regex strip
        clean = re.sub(r"<[^>]+>", " ", raw_html)
        return re.sub(r"\s+", " ", clean).strip()


def extract_attachment_links(
    item_element: ET.Element,
    raw_html: str,
    base_url: str,
    item_id: str,
) -> List[Attachment]:
    """
    Extract image and PDF attachment candidates from XML enclosures,
    media tags, and description HTML.
    """
    attachments: List[Attachment] = []
    seen_urls = set()

    def add_att(url: str, mime: Optional[str] = None):
        if not url:
            return
        # Resolve relative URLs
        full_url = urllib.parse.urljoin(base_url, url.strip())
        if full_url in seen_urls:
            return
        
        parsed = urllib.parse.urlparse(full_url)
        path_lower = parsed.path.lower()
        ext = ""
        for valid_ext in VALID_ATTACHMENT_EXTENSIONS:
            if path_lower.endswith(valid_ext):
                ext = valid_ext
                break

        # Only add if it has an allowed extension or explicit supported MIME
        if ext or (mime and any(m in mime.lower() for m in ("image/png", "image/jpeg", "application/pdf"))):
            seen_urls.add(full_url)
            att_hash = hashlib.sha256(full_url.encode()).hexdigest()[:12]
            attachments.append(
                Attachment(
                    attachment_id=f"att_{item_id}_{att_hash}",
                    item_id=item_id,
                    url=full_url,
                    mime_type=mime or ("application/pdf" if ext == ".pdf" else "image/png"),
                )
            )

    # 1. Enclosure tags: <enclosure url="..." type="..."/>
    for enc in item_element.findall("enclosure"):
        enc_url = enc.get("url")
        enc_type = enc.get("type")
        if enc_url:
            add_att(enc_url, enc_type)

    # Atom links with enclosure relation or image/pdf MIME: <link rel="enclosure" href="..." />
    for l_elem in item_element.findall(".//{http://www.w3.org/2005/Atom}link"):
        l_href = l_elem.get("href")
        l_rel = l_elem.get("rel")
        l_type = l_elem.get("type")
        if l_href and (l_rel == "enclosure" or (l_type and ("image" in l_type or "pdf" in l_type))):
            add_att(l_href, l_type)
    for l_elem in item_element.findall("link"):
        l_href = l_elem.get("href")
        l_rel = l_elem.get("rel")
        l_type = l_elem.get("type")
        if l_href and (l_rel == "enclosure" or (l_type and ("image" in l_type or "pdf" in l_type))):
            add_att(l_href, l_type)

    # 2. Media content tags: <media:content url="..." type="..."/>
    for media_elem in item_element.findall(".//{http://search.yahoo.com/mrss/}content"):
        m_url = media_elem.get("url")
        m_type = media_elem.get("type")
        if m_url:
            add_att(m_url, m_type)

    # 3. HTML <img> tags in description / content
    if raw_html:
        try:
            soup = BeautifulSoup(raw_html, "html.parser")
            for img in soup.find_all("img"):
                src = img.get("src")
                if src:
                    add_att(src, "image/png")
            # Also check <a> links pointing directly to PDFs
            for a in soup.find_all("a"):
                href = a.get("href")
                if href and href.lower().endswith(".pdf"):
                    add_att(href, "application/pdf")
        except Exception:
            pass

    return attachments


def parse_feed_xml(
    xml_content: str | bytes,
    source_name: str,
    base_url: str = "",
) -> Tuple[List[Tuple[SourceItem, List[Attachment]]], Optional[str]]:
    """
    Parse RSS 2.0 or Atom XML content safely into normalized items and attachments.
    
    Args:
        xml_content: Raw XML string or bytes
        source_name: e.g. "CPSC" or "FDA"
        base_url: Base feed URL for resolving relative links
        
    Returns:
        Tuple of (list_of_tuples[(SourceItem, List[Attachment])], latest_cursor_token)
    """
    if not xml_content:
        return [], None

    try:
        root = ET.fromstring(xml_content)
    except Exception as e:
        raise ValueError(f"Malformed or unsafe XML feed: {e}")

    results: List[Tuple[SourceItem, List[Attachment]]] = []
    latest_cursor: Optional[str] = None

    # Detect RSS 2.0 vs Atom
    tag_clean = root.tag.lower()
    is_atom = "feed" in tag_clean or root.tag.startswith("{http://www.w3.org/2005/Atom}")

    if is_atom:
        # Atom feed: <feed><entry>...
        entries = root.findall("{http://www.w3.org/2005/Atom}entry")
        if not entries:
            entries = root.findall("entry")

        for entry in entries:
            id_elem = entry.find("{http://www.w3.org/2005/Atom}id")
            if id_elem is None:
                id_elem = entry.find("id")

            title_elem = entry.find("{http://www.w3.org/2005/Atom}title")
            if title_elem is None:
                title_elem = entry.find("title")

            link_elem = entry.find("{http://www.w3.org/2005/Atom}link")
            if link_elem is None:
                link_elem = entry.find("link")

            summary_elem = entry.find("{http://www.w3.org/2005/Atom}summary")
            if summary_elem is None:
                summary_elem = entry.find("{http://www.w3.org/2005/Atom}content")
            if summary_elem is None:
                summary_elem = entry.find("summary")
            if summary_elem is None:
                summary_elem = entry.find("content")

            raw_guid = id_elem.text.strip() if id_elem is not None and id_elem.text else ""
            title = title_elem.text.strip() if title_elem is not None and title_elem.text else "Untitled Notice"
            
            link = ""
            if link_elem is not None:
                link = link_elem.get("href") or (link_elem.text.strip() if link_elem.text else "")

            raw_body = summary_elem.text.strip() if summary_elem is not None and summary_elem.text else ""
            clean_body = clean_html_text(raw_body)

            guid = raw_guid or link or title
            if not latest_cursor:
                latest_cursor = guid

            id_hash = hashlib.sha256(guid.encode()).hexdigest()[:12]
            source_slug = source_name.lower().replace(" ", "_")[:6]
            item_id = f"{source_slug}_{id_hash}"

            item = SourceItem(
                item_id=item_id,
                source=source_name,
                url=link or base_url,
                title=title,
                body=clean_body,
                content_hash=SourceItem.compute_content_hash(title, clean_body),
                fetch_time=utc_now(),
                status=ItemStatus.PENDING,
            )

            attachments = extract_attachment_links(entry, raw_body, link or base_url, item_id)
            results.append((item, attachments))

    else:
        # RSS 2.0: <rss><channel><item>...
        channel = root.find("channel")
        items = channel.findall("item") if channel is not None else root.findall(".//item")

        for elem in items:
            guid_elem = elem.find("guid")
            title_elem = elem.find("title")
            link_elem = elem.find("link")
            desc_elem = elem.find("description")

            raw_guid = guid_elem.text.strip() if guid_elem is not None and guid_elem.text else ""
            title = title_elem.text.strip() if title_elem is not None and title_elem.text else "Untitled Notice"
            link = link_elem.text.strip() if link_elem is not None and link_elem.text else ""
            raw_desc = desc_elem.text.strip() if desc_elem is not None and desc_elem.text else ""
            clean_body = clean_html_text(raw_desc)

            guid = raw_guid or link or title
            if not latest_cursor:
                latest_cursor = guid

            id_hash = hashlib.sha256(guid.encode()).hexdigest()[:12]
            source_slug = source_name.lower().replace(" ", "_")[:6]
            item_id = f"{source_slug}_{id_hash}"

            item = SourceItem(
                item_id=item_id,
                source=source_name,
                url=link or base_url,
                title=title,
                body=clean_body,
                content_hash=SourceItem.compute_content_hash(title, clean_body),
                fetch_time=utc_now(),
                status=ItemStatus.PENDING,
            )

            attachments = extract_attachment_links(elem, raw_desc, link or base_url, item_id)
            results.append((item, attachments))

    return results, latest_cursor
