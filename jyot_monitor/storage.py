"""
SQLite persistence layer.

Implements:
- Schema creation and migrations
- Item and attachment storage
- OCR and LLM caching
- Cluster management
- Alert proposal queue
- Digest run tracking
- Idempotent operations
"""

import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple

from jyot_monitor.models import (
    SourceItem,
    Attachment,
    ItemStatus,
    ProposalStatus,
    AlertProposal
)


class StorageError(Exception):
    """Storage operation errors."""
    pass


class Storage:
    """
    SQLite-backed persistent storage.
    
    Provides idempotent operations and transaction support.
    """
    
    SCHEMA_VERSION = 1
    
    def __init__(self, db_path: Path):
        """
        Initialize storage.
        
        Args:
            db_path: Path to SQLite database file
        """
        self.db_path = db_path
        self._ensure_schema()
    
    @contextmanager
    def connection(self):
        """Context manager for database connections."""
        conn = sqlite3.connect(
            self.db_path,
            detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES
        )
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
    
    def _ensure_schema(self) -> None:
        """Create tables and indexes if they don't exist."""
        with self.connection() as conn:
            cursor = conn.cursor()
            
            # Schema version tracking
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS schema_version (
                    version INTEGER PRIMARY KEY,
                    applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Feed state for incremental ingestion
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS feed_state (
                    feed_name TEXT PRIMARY KEY,
                    last_cursor TEXT,
                    last_poll_time TIMESTAMP,
                    item_count INTEGER DEFAULT 0
                )
            """)
            
            # Items (source posts/notices)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS items (
                    item_id TEXT PRIMARY KEY,
                    source TEXT NOT NULL,
                    url TEXT NOT NULL,
                    title TEXT NOT NULL,
                    body TEXT,
                    content_hash TEXT NOT NULL,
                    fetch_time TIMESTAMP NOT NULL,
                    status TEXT NOT NULL,
                    error_code TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_items_content_hash 
                ON items(content_hash)
            """)
            
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_items_status 
                ON items(status)
            """)
            
            # Attachments
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS attachments (
                    attachment_id TEXT PRIMARY KEY,
                    item_id TEXT NOT NULL,
                    url TEXT NOT NULL,
                    local_path TEXT,
                    mime_type TEXT,
                    size_bytes INTEGER,
                    content_hash TEXT,
                    FOREIGN KEY (item_id) REFERENCES items(item_id)
                )
            """)
            
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_attachments_content_hash 
                ON attachments(content_hash)
            """)
            
            # OCR cache
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS ocr_cache (
                    content_hash TEXT NOT NULL,
                    engine TEXT NOT NULL,
                    preprocessing TEXT,
                    text TEXT NOT NULL,
                    confidence REAL,
                    language TEXT,
                    metadata_json TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (content_hash, engine, preprocessing)
                )
            """)
            
            # LLM cache
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS llm_cache (
                    input_hash TEXT NOT NULL,
                    model TEXT NOT NULL,
                    prompt_version TEXT,
                    response_json TEXT NOT NULL,
                    tokens_in INTEGER,
                    tokens_out INTEGER,
                    cost_usd REAL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (input_hash, model)
                )
            """)
            
            # Clusters for deduplication
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS clusters (
                    cluster_id TEXT PRIMARY KEY,
                    representative_item_id TEXT,
                    created_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (representative_item_id) REFERENCES items(item_id)
                )
            """)
            
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS cluster_members (
                    cluster_id TEXT NOT NULL,
                    item_id TEXT NOT NULL,
                    similarity_score REAL,
                    join_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (cluster_id, item_id),
                    FOREIGN KEY (cluster_id) REFERENCES clusters(cluster_id),
                    FOREIGN KEY (item_id) REFERENCES items(item_id)
                )
            """)
            
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_cluster_members_item 
                ON cluster_members(item_id)
            """)
            
            # Digest runs
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS digest_runs (
                    run_id TEXT PRIMARY KEY,
                    run_time TIMESTAMP NOT NULL,
                    item_count INTEGER DEFAULT 0,
                    digest_path TEXT,
                    budget_used_usd REAL DEFAULT 0.0
                )
            """)
            
            # Alert proposals
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS alert_proposals (
                    proposal_id TEXT PRIMARY KEY,
                    item_id TEXT NOT NULL,
                    urgency REAL NOT NULL,
                    evidence_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    approved_time TIMESTAMP,
                    FOREIGN KEY (item_id) REFERENCES items(item_id)
                )
            """)
            
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_alert_proposals_status 
                ON alert_proposals(status)
            """)
            
            # Mark schema as initialized
            cursor.execute("""
                INSERT OR IGNORE INTO schema_version (version) VALUES (?)
            """, (self.SCHEMA_VERSION,))
            
            conn.commit()
    
    def save_item(self, item: SourceItem) -> None:
        """
        Save or update an item (idempotent).
        
        Args:
            item: Source item to save
        """
        with self.connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO items (
                    item_id, source, url, title, body, content_hash,
                    fetch_time, status, error_code, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(item_id) DO UPDATE SET
                    status = excluded.status,
                    error_code = excluded.error_code,
                    updated_at = CURRENT_TIMESTAMP
            """, (
                item.item_id,
                item.source,
                item.url,
                item.title,
                item.body,
                item.content_hash,
                item.fetch_time,
                item.status.value,
                item.error_code
            ))
    
    def get_item(self, item_id: str) -> Optional[SourceItem]:
        """
        Retrieve an item by ID.
        
        Args:
            item_id: Item identifier
            
        Returns:
            SourceItem if found, None otherwise
        """
        with self.connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT item_id, source, url, title, body, content_hash,
                       fetch_time, status, error_code
                FROM items WHERE item_id = ?
            """, (item_id,))
            
            row = cursor.fetchone()
            if not row:
                return None
            
            return SourceItem(
                item_id=row['item_id'],
                source=row['source'],
                url=row['url'],
                title=row['title'],
                body=row['body'],
                content_hash=row['content_hash'],
                fetch_time=row['fetch_time'],
                status=ItemStatus(row['status']),
                error_code=row['error_code']
            )
    
    def item_exists(self, item_id: str) -> bool:
        """Check if an item exists."""
        with self.connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT 1 FROM items WHERE item_id = ? LIMIT 1
            """, (item_id,))
            return cursor.fetchone() is not None
    
    def get_items_by_content_hash(self, content_hash: str) -> List[str]:
        """
        Find items with the same content hash (duplicates).
        
        Args:
            content_hash: SHA-256 content hash
            
        Returns:
            List of item IDs
        """
        with self.connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT item_id FROM items WHERE content_hash = ?
            """, (content_hash,))
            return [row['item_id'] for row in cursor.fetchall()]
    
    def save_attachment(self, attachment: Attachment) -> None:
        """Save or update an attachment (idempotent)."""
        with self.connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO attachments (
                    attachment_id, item_id, url, local_path,
                    mime_type, size_bytes, content_hash
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(attachment_id) DO UPDATE SET
                    local_path = excluded.local_path,
                    content_hash = excluded.content_hash
            """, (
                attachment.attachment_id,
                attachment.item_id,
                attachment.url,
                attachment.local_path,
                attachment.mime_type,
                attachment.size_bytes,
                attachment.content_hash
            ))
    
    def save_alert_proposal(self, proposal: AlertProposal) -> None:
        """Save a new alert proposal."""
        with self.connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO alert_proposals (
                    proposal_id, item_id, urgency, evidence_json,
                    status, created_time
                ) VALUES (?, ?, ?, ?, ?, ?)
            """, (
                proposal.proposal_id,
                proposal.item_id,
                proposal.urgency,
                proposal.model_dump_json(),
                proposal.status.value,
                proposal.created_time
            ))
    
    def update_proposal_status(
        self,
        proposal_id: str,
        new_status: ProposalStatus
    ) -> bool:
        """
        Update proposal status (approve/reject).
        
        Returns:
            True if proposal was found and updated
        """
        with self.connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE alert_proposals
                SET status = ?,
                    approved_time = CURRENT_TIMESTAMP
                WHERE proposal_id = ? AND status = 'pending'
            """, (new_status.value, proposal_id))
            return cursor.rowcount > 0
    
    def get_pending_proposals(self) -> List[Tuple[str, str, float]]:
        """
        Get all pending proposals.
        
        Returns:
            List of (proposal_id, item_id, urgency) tuples
        """
        with self.connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT proposal_id, item_id, urgency
                FROM alert_proposals
                WHERE status = 'pending'
                ORDER BY urgency DESC, created_time ASC
            """)
            return [(row['proposal_id'], row['item_id'], row['urgency'])
                    for row in cursor.fetchall()]
