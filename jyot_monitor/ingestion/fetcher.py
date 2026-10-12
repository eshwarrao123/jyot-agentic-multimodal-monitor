"""
Source fetcher and incremental polling orchestrator.

Manages:
- Polling configured public feeds (CPSC, FDA) via SafeHttpClient.
- Persistent feed cursors to fetch only new items.
- Attachment discovery, safe downloading, and file signature validation.
- SQLite persistence of items and attachments.
- Actionable error isolation.
"""

import hashlib
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import httpx

from jyot_monitor.ingestion.network import (
    SafeHttpClient,
    SecurityError,
    validate_file_signature,
    check_pdf_page_limit,
)
from jyot_monitor.ingestion.rss_parser import parse_feed_xml
from jyot_monitor.models import Attachment, SourceItem, ItemStatus
from jyot_monitor.storage import Storage


class SourceUnavailableError(Exception):
    """Raised when a public feed source is unreachable or returns an error."""
    pass


class SourceFetcher:
    """
    Coordinates live polling across configured public sources.
    """

    def __init__(
        self,
        storage: Storage,
        http_client: Optional[SafeHttpClient] = None,
        attachment_dir: Optional[Path] = None,
    ):
        self.storage = storage
        self.http_client = http_client or SafeHttpClient()
        self.attachment_dir = attachment_dir or Path("artifacts/downloads")
        self.attachment_dir.mkdir(parents=True, exist_ok=True)

    def poll_source(
        self,
        source_config: Dict[str, Any],
        max_items: int = 10,
    ) -> Tuple[List[SourceItem], Dict[str, List[Attachment]]]:
        """
        Poll a single public source feed incrementally.
        
        Args:
            source_config: Dictionary containing 'name', 'url', 'allowed_hosts'
            max_items: Maximum new items to return
            
        Returns:
            Tuple of (new_items_list, {item_id: attachments_list})
        """
        source_name = source_config.get("name", "Unknown Source")
        feed_url = source_config.get("url")
        allowed_hosts = source_config.get("allowed_hosts", [])

        if not feed_url:
            raise ValueError(f"Source '{source_name}' is missing required 'url'.")

        # 1. Fetch persistent cursor state
        feed_state = self.storage.get_feed_state(source_name)
        last_cursor = feed_state.get("last_cursor") if feed_state else None

        # 2. Safely fetch feed XML with network defense
        try:
            response = self.http_client.get(feed_url, allowed_hosts=allowed_hosts)
            if not response.is_success:
                raise SourceUnavailableError(
                    f"Source '{source_name}' at {feed_url} returned HTTP {response.status_code}"
                )
        except Exception as e:
            raise SourceUnavailableError(f"Failed to fetch source '{source_name}': {e}") from e

        # 3. Parse XML safely using defusedxml
        parsed_entries, new_cursor = parse_feed_xml(
            response.text,
            source_name=source_name,
            base_url=feed_url,
        )

        new_items: List[SourceItem] = []
        item_attachments: Dict[str, List[Attachment]] = {}

        # 4. Filter only new or changed items
        for item, atts in parsed_entries:
            if len(new_items) >= max_items:
                break

            existing_item = self.storage.get_item(item.item_id)
            if existing_item:
                # If content hash hasn't changed, skip duplicate
                if existing_item.content_hash == item.content_hash:
                    continue

            # Save new item to database
            self.storage.save_item(item)
            for att in atts:
                self.storage.save_attachment(att)

            new_items.append(item)
            item_attachments[item.item_id] = atts

        # 5. Update feed cursor state
        updated_count = (feed_state.get("item_count", 0) if feed_state else 0) + len(new_items)
        if new_cursor or new_items:
            self.storage.save_feed_state(
                feed_name=source_name,
                last_cursor=new_cursor or last_cursor,
                item_count=updated_count,
            )

        return new_items, item_attachments

    def download_attachment(
        self,
        attachment: Attachment,
        allowed_hosts: Optional[List[str]] = None,
        max_bytes: int = 10 * 1024 * 1024,
    ) -> Path:
        """
        Safely download and validate an attachment binary (image or PDF).
        
        Args:
            attachment: Attachment metadata with URL
            allowed_hosts: Allowed hosts for attachment origin
            max_bytes: Maximum size cap
            
        Returns:
            Local Path to the saved attachment file.
        """
        if attachment.local_path and Path(attachment.local_path).exists():
            return Path(attachment.local_path)

        response = self.http_client.get(
            attachment.url,
            allowed_hosts=allowed_hosts,
            max_bytes=max_bytes,
        )
        if not response.is_success:
            raise SourceUnavailableError(
                f"Attachment download failed with status {response.status_code} for {attachment.url}"
            )

        content = response.content

        # Determine extension
        url_path = attachment.url.split("?")[0].lower()
        ext = ".png"
        if url_path.endswith(".jpg") or url_path.endswith(".jpeg"):
            ext = ".jpg"
        elif url_path.endswith(".pdf"):
            ext = ".pdf"
        elif attachment.mime_type and "pdf" in attachment.mime_type:
            ext = ".pdf"

        # Validate file signature magic bytes
        validate_file_signature(content, expected_extension=ext, mime_type=attachment.mime_type)

        # Enforce PDF page limit if PDF
        if ext == ".pdf":
            check_pdf_page_limit(content, max_pages=10)

        # Save to local attachment directory
        dest_path = self.attachment_dir / f"{attachment.attachment_id}{ext}"
        dest_path.write_bytes(content)

        # Update attachment metadata
        content_hash = hashlib.sha256(content).hexdigest()
        attachment.local_path = str(dest_path)
        attachment.size_bytes = len(content)
        attachment.content_hash = content_hash

        self.storage.save_attachment(attachment)
        return dest_path
