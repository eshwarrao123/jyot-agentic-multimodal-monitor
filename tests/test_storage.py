"""Tests for SQLite storage."""

import pytest
from pathlib import Path
import tempfile
import shutil

from jyot_monitor.storage import Storage
from jyot_monitor.models import (
    SourceItem,
    ItemStatus,
    Attachment,
    AlertProposal,
    ProposalStatus,
)


@pytest.fixture
def temp_db():
    """Create a temporary database for testing."""
    temp_dir = tempfile.mkdtemp()
    db_path = Path(temp_dir) / "test.sqlite3"
    
    yield db_path
    
    # Cleanup
    shutil.rmtree(temp_dir)


def test_storage_initialization(temp_db):
    """Test storage creates schema on initialization."""
    storage = Storage(temp_db)
    
    assert temp_db.exists()
    
    # Verify tables exist by attempting a query
    with storage.connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT name FROM sqlite_master 
            WHERE type='table' AND name='items'
        """)
        assert cursor.fetchone() is not None


def test_save_and_retrieve_item(temp_db):
    """Test saving and retrieving an item."""
    storage = Storage(temp_db)
    
    item = SourceItem(
        item_id="test_001",
        source="CPSC",
        url="https://example.com/1",
        title="Test Item",
        body="Test body",
        content_hash="hash123"
    )
    
    storage.save_item(item)
    
    retrieved = storage.get_item("test_001")
    assert retrieved is not None
    assert retrieved.item_id == "test_001"
    assert retrieved.title == "Test Item"
    assert retrieved.status == ItemStatus.PENDING


def test_item_exists(temp_db):
    """Test checking if item exists."""
    storage = Storage(temp_db)
    
    assert not storage.item_exists("nonexistent")
    
    item = SourceItem(
        item_id="test_001",
        source="CPSC",
        url="https://example.com/1",
        title="Test",
        content_hash="hash123"
    )
    storage.save_item(item)
    
    assert storage.item_exists("test_001")


def test_idempotent_item_save(temp_db):
    """Test saving the same item twice is idempotent."""
    storage = Storage(temp_db)
    
    item = SourceItem(
        item_id="test_001",
        source="CPSC",
        url="https://example.com/1",
        title="Test",
        content_hash="hash123",
        status=ItemStatus.PENDING
    )
    
    storage.save_item(item)
    
    # Update status and save again
    item.status = ItemStatus.COMPLETED
    storage.save_item(item)
    
    # Should have updated status
    retrieved = storage.get_item("test_001")
    assert retrieved.status == ItemStatus.COMPLETED


def test_get_items_by_content_hash(temp_db):
    """Test finding duplicate items by content hash."""
    storage = Storage(temp_db)
    
    hash_value = "duplicate_hash"
    
    item1 = SourceItem(
        item_id="item_001",
        source="CPSC",
        url="https://example.com/1",
        title="Item 1",
        content_hash=hash_value
    )
    
    item2 = SourceItem(
        item_id="item_002",
        source="FDA",
        url="https://example.com/2",
        title="Item 2",
        content_hash=hash_value
    )
    
    storage.save_item(item1)
    storage.save_item(item2)
    
    duplicates = storage.get_items_by_content_hash(hash_value)
    assert len(duplicates) == 2
    assert "item_001" in duplicates
    assert "item_002" in duplicates


def test_save_attachment(temp_db):
    """Test saving attachments."""
    storage = Storage(temp_db)
    
    # Save parent item first
    item = SourceItem(
        item_id="test_001",
        source="CPSC",
        url="https://example.com/1",
        title="Test",
        content_hash="hash123"
    )
    storage.save_item(item)
    
    attachment = Attachment(
        attachment_id="att_001",
        item_id="test_001",
        url="https://example.com/image.jpg",
        local_path="/path/to/image.jpg",
        mime_type="image/jpeg",
        size_bytes=1024,
        content_hash="att_hash"
    )
    
    storage.save_attachment(attachment)
    
    # Verify saved (basic check via raw query)
    with storage.connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT attachment_id, local_path 
            FROM attachments 
            WHERE attachment_id = ?
        """, ("att_001",))
        row = cursor.fetchone()
        assert row is not None
        assert row['local_path'] == "/path/to/image.jpg"


def test_save_and_update_alert_proposal(temp_db):
    """Test alert proposal workflow."""
    storage = Storage(temp_db)
    
    # Save parent item
    item = SourceItem(
        item_id="test_001",
        source="CPSC",
        url="https://example.com/1",
        title="Urgent recall",
        content_hash="hash123"
    )
    storage.save_item(item)
    
    # Create proposal
    proposal = AlertProposal(
        proposal_id="prop_001",
        item_id="test_001",
        urgency=90.0,
        evidence_json={
            "source_url": "https://example.com/1",
            "snippet": "Critical safety issue"
        }
    )
    
    storage.save_alert_proposal(proposal)
    
    # Verify it's pending
    pending = storage.get_pending_proposals()
    assert len(pending) == 1
    assert pending[0][0] == "prop_001"
    
    # Approve it
    updated = storage.update_proposal_status("prop_001", ProposalStatus.APPROVED)
    assert updated is True
    
    # Should no longer be pending
    pending = storage.get_pending_proposals()
    assert len(pending) == 0


def test_update_nonexistent_proposal(temp_db):
    """Test updating a nonexistent proposal returns False."""
    storage = Storage(temp_db)
    
    updated = storage.update_proposal_status("nonexistent", ProposalStatus.APPROVED)
    assert updated is False


def test_schema_version_tracking(temp_db):
    """Test schema version is tracked."""
    storage = Storage(temp_db)
    
    with storage.connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT version FROM schema_version")
        row = cursor.fetchone()
        assert row is not None
        assert row['version'] == Storage.SCHEMA_VERSION
