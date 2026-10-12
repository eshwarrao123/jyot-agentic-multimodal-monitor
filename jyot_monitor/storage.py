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

import json
from jyot_monitor.models import (
    SourceItem,
    Attachment,
    ItemStatus,
    ProposalStatus,
    AlertProposal,
    StoryCluster,
    utc_now,
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

            # Emitted alerts after explicit human approval
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS emitted_alerts (
                    emission_id TEXT PRIMARY KEY,
                    proposal_id TEXT UNIQUE NOT NULL,
                    item_id TEXT NOT NULL,
                    emitted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    alert_payload_json TEXT NOT NULL,
                    FOREIGN KEY (proposal_id) REFERENCES alert_proposals(proposal_id)
                )
            """)
            
            # Item features and reporting state for persistent memory & search
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS item_features (
                    item_id TEXT PRIMARY KEY,
                    image_phash TEXT,
                    ocr_text TEXT,
                    taxonomy TEXT,
                    relevance_score REAL,
                    urgency_score REAL,
                    post_critique_urgency REAL,
                    verification_status TEXT,
                    reporting_status TEXT DEFAULT 'new',
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (item_id) REFERENCES items(item_id)
                )
            """)
            
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_features_phash 
                ON item_features(image_phash)
            """)

            # Schema migration for existing databases: ensure post_critique_urgency and verification_status columns
            cursor.execute("PRAGMA table_info(item_features)")
            feature_cols = [row[1] for row in cursor.fetchall()]
            if "post_critique_urgency" not in feature_cols:
                cursor.execute("ALTER TABLE item_features ADD COLUMN post_critique_urgency REAL")
            if "verification_status" not in feature_cols:
                cursor.execute("ALTER TABLE item_features ADD COLUMN verification_status TEXT")

            # Deduplicate any existing duplicate proposals before creating unique index
            cursor.execute("""
                DELETE FROM alert_proposals 
                WHERE rowid NOT IN (
                    SELECT MIN(rowid) FROM alert_proposals GROUP BY item_id
                )
            """)

            cursor.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS idx_alert_proposals_item_id 
                ON alert_proposals(item_id)
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
                    title = excluded.title,
                    body = excluded.body,
                    content_hash = excluded.content_hash,
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
        """Save a new alert proposal (idempotent)."""
        with self.connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO alert_proposals (
                    proposal_id, item_id, urgency, evidence_json,
                    status, created_time
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(item_id) DO UPDATE SET
                    urgency = excluded.urgency,
                    evidence_json = excluded.evidence_json
                WHERE alert_proposals.status = 'pending'
            """, (
                proposal.proposal_id,
                proposal.item_id,
                proposal.urgency,
                proposal.model_dump_json(),
                proposal.status.value,
                proposal.created_time
            ))

    def get_alert_proposal_for_item_or_cluster(self, item_id: str) -> Optional[AlertProposal]:
        """Fetch existing alert proposal for an item or any member of its story cluster."""
        with self.connection() as conn:
            cursor = conn.cursor()
            # 1. Check item itself
            cursor.execute("""
                SELECT proposal_id FROM alert_proposals WHERE item_id = ? LIMIT 1
            """, (item_id,))
            row = cursor.fetchone()
            if row:
                return self.get_alert_proposal(row['proposal_id'])

            # 2. Check cluster members
            cluster = self.get_item_cluster(item_id)
            if cluster and cluster.member_item_ids:
                placeholders = ",".join("?" for _ in cluster.member_item_ids)
                cursor.execute(f"""
                    SELECT proposal_id FROM alert_proposals 
                    WHERE item_id IN ({placeholders}) LIMIT 1
                """, tuple(cluster.member_item_ids))
                row = cursor.fetchone()
                if row:
                    return self.get_alert_proposal(row['proposal_id'])

            return None
    
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

    def get_alert_proposal(self, proposal_id: str) -> Optional[AlertProposal]:
        """Fetch an alert proposal by ID."""
        with self.connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT proposal_id, item_id, urgency, evidence_json, status, created_time, approved_time
                FROM alert_proposals
                WHERE proposal_id = ?
            """, (proposal_id,))
            row = cursor.fetchone()
            if not row:
                return None
            try:
                raw_data = json.loads(row['evidence_json'])
                if isinstance(raw_data, dict) and 'evidence_json' in raw_data:
                    ev_dict = raw_data['evidence_json']
                else:
                    ev_dict = raw_data if isinstance(raw_data, dict) else {}
                return AlertProposal(
                    proposal_id=row['proposal_id'],
                    item_id=row['item_id'],
                    urgency=float(row['urgency']),
                    evidence_json=ev_dict,
                    status=ProposalStatus(row['status']),
                    created_time=row['created_time'],
                    approved_time=row['approved_time']
                )
            except Exception:
                return None


    # --- Story Clusters & Memory Management ---

    def save_cluster(self, cluster: StoryCluster) -> None:
        """Save or update a story cluster and its member associations."""
        with self.connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO clusters (cluster_id, representative_item_id, created_time, last_updated)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(cluster_id) DO UPDATE SET
                    representative_item_id = excluded.representative_item_id,
                    last_updated = excluded.last_updated
            """, (
                cluster.cluster_id,
                cluster.representative_item_id,
                cluster.created_time,
                cluster.last_updated
            ))

            for member_id in cluster.member_item_ids:
                # Remove stale membership in competing clusters to ensure consistency
                cursor.execute("""
                    DELETE FROM cluster_members 
                    WHERE item_id = ? AND cluster_id != ?
                """, (member_id, cluster.cluster_id))
                sim_score = cluster.similarity_evidence.get(member_id, {}).get("score", 1.0) if isinstance(cluster.similarity_evidence.get(member_id), dict) else 1.0
                cursor.execute("""
                    INSERT INTO cluster_members (cluster_id, item_id, similarity_score, join_time)
                    VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(cluster_id, item_id) DO UPDATE SET
                        similarity_score = excluded.similarity_score
                """, (cluster.cluster_id, member_id, sim_score))

    def get_cluster(self, cluster_id: str) -> Optional[StoryCluster]:
        """Retrieve a story cluster by ID."""
        with self.connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT cluster_id, representative_item_id, created_time, last_updated
                FROM clusters WHERE cluster_id = ?
            """, (cluster_id,))
            row = cursor.fetchone()
            if not row:
                return None

            cursor.execute("""
                SELECT item_id, similarity_score FROM cluster_members WHERE cluster_id = ?
            """, (cluster_id,))
            member_rows = cursor.fetchall()
            members = [r['item_id'] for r in member_rows]
            evidence = {r['item_id']: {"score": r['similarity_score']} for r in member_rows}

            return StoryCluster(
                cluster_id=row['cluster_id'],
                representative_item_id=row['representative_item_id'],
                member_item_ids=members,
                similarity_evidence=evidence,
                created_time=datetime.fromisoformat(str(row['created_time'])) if isinstance(row['created_time'], str) else row['created_time'],
                last_updated=datetime.fromisoformat(str(row['last_updated'])) if isinstance(row['last_updated'], str) else row['last_updated'],
            )

    def get_item_cluster(self, item_id: str) -> Optional[StoryCluster]:
        """Find the cluster containing a specific item."""
        with self.connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT cluster_id FROM cluster_members WHERE item_id = ? LIMIT 1
            """, (item_id,))
            row = cursor.fetchone()
            if not row:
                return None
            return self.get_cluster(row['cluster_id'])

    def get_all_clusters(self) -> List[StoryCluster]:
        """Retrieve all story clusters."""
        with self.connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT cluster_id FROM clusters ORDER BY last_updated DESC")
            cluster_ids = [row['cluster_id'] for row in cursor.fetchall()]
        
        clusters = []
        for cid in cluster_ids:
            c = self.get_cluster(cid)
            if c:
                clusters.append(c)
        return clusters

    # --- Item Features & Reporting State ---

    def save_item_features(
        self,
        item_id: str,
        image_phash: Optional[str] = None,
        ocr_text: Optional[str] = None,
        taxonomy: Optional[str] = None,
        relevance_score: Optional[float] = None,
        urgency_score: Optional[float] = None,
        post_critique_urgency: Optional[float] = None,
        verification_status: Optional[str] = None,
        reporting_status: str = "new",
    ) -> None:
        """Save or update extracted item features for memory search and digest generation."""
        with self.connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO item_features (
                    item_id, image_phash, ocr_text, taxonomy,
                    relevance_score, urgency_score, post_critique_urgency, verification_status,
                    reporting_status, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(item_id) DO UPDATE SET
                    image_phash = COALESCE(excluded.image_phash, item_features.image_phash),
                    ocr_text = COALESCE(excluded.ocr_text, item_features.ocr_text),
                    taxonomy = COALESCE(excluded.taxonomy, item_features.taxonomy),
                    relevance_score = COALESCE(excluded.relevance_score, item_features.relevance_score),
                    urgency_score = COALESCE(excluded.urgency_score, item_features.urgency_score),
                    post_critique_urgency = COALESCE(excluded.post_critique_urgency, item_features.post_critique_urgency),
                    verification_status = COALESCE(excluded.verification_status, item_features.verification_status),
                    reporting_status = excluded.reporting_status,
                    updated_at = CURRENT_TIMESTAMP
            """, (
                item_id, image_phash, ocr_text, taxonomy,
                relevance_score, urgency_score, post_critique_urgency, verification_status,
                reporting_status
            ))

    def get_item_features(self, item_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve features for an item."""
        with self.connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT item_id, image_phash, ocr_text, taxonomy,
                       relevance_score, urgency_score, post_critique_urgency, verification_status,
                       reporting_status, updated_at
                FROM item_features WHERE item_id = ?
            """, (item_id,))
            row = cursor.fetchone()
            if not row:
                return None
            return dict(row)

    def get_all_item_features(self) -> List[Dict[str, Any]]:
        """Retrieve all item features for memory search."""
        with self.connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT f.item_id, f.image_phash, f.ocr_text, f.taxonomy,
                       f.relevance_score, f.urgency_score, f.post_critique_urgency, f.verification_status,
                       f.reporting_status,
                       i.title, i.body, i.source, i.url, i.content_hash
                FROM item_features f
                JOIN items i ON f.item_id = i.item_id
            """)
            return [dict(r) for r in cursor.fetchall()]

    # --- Cache Operations ---

    def save_ocr_cache(
        self,
        content_hash: str,
        engine: str,
        preprocessing: Optional[str],
        text: str,
        confidence: Optional[float] = None,
        language: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Cache an OCR result by content hash and engine."""
        with self.connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO ocr_cache (
                    content_hash, engine, preprocessing, text,
                    confidence, language, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                content_hash, engine, preprocessing or "none", text,
                confidence, language, json.dumps(metadata or {})
            ))

    def get_ocr_cache(
        self,
        content_hash: str,
        engine: str,
        preprocessing: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Retrieve cached OCR result."""
        with self.connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT text, confidence, language, metadata_json
                FROM ocr_cache
                WHERE content_hash = ? AND engine = ? AND preprocessing = ?
            """, (content_hash, engine, preprocessing or "none"))
            row = cursor.fetchone()
            if not row:
                return None
            return {
                "text": row['text'],
                "confidence": row['confidence'],
                "language": row['language'],
                "metadata": json.loads(row['metadata_json']) if row['metadata_json'] else {}
            }

    def save_llm_cache(
        self,
        input_hash: str,
        model: str,
        response_json: str,
        prompt_version: Optional[str] = None,
        tokens_in: Optional[int] = None,
        tokens_out: Optional[int] = None,
        cost_usd: Optional[float] = None,
    ) -> None:
        """Cache an LLM response by input hash and model."""
        with self.connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO llm_cache (
                    input_hash, model, prompt_version, response_json,
                    tokens_in, tokens_out, cost_usd
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (input_hash, model, prompt_version, response_json, tokens_in, tokens_out, cost_usd))

    def get_llm_cache(self, input_hash: str, model: str) -> Optional[Dict[str, Any]]:
        """Retrieve cached LLM response."""
        with self.connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT response_json, tokens_in, tokens_out, cost_usd, prompt_version
                FROM llm_cache WHERE input_hash = ? AND model = ?
            """, (input_hash, model))
            row = cursor.fetchone()
            if not row:
                return None
            return dict(row)

    # --- Feed State Operations ---

    def save_feed_state(
        self,
        feed_name: str,
        last_cursor: Optional[str] = None,
        item_count: int = 0,
    ) -> None:
        """Save or update feed cursor state for incremental ingestion."""
        with self.connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO feed_state (feed_name, last_cursor, last_poll_time, item_count)
                VALUES (?, ?, CURRENT_TIMESTAMP, ?)
                ON CONFLICT(feed_name) DO UPDATE SET
                    last_cursor = COALESCE(excluded.last_cursor, feed_state.last_cursor),
                    last_poll_time = CURRENT_TIMESTAMP,
                    item_count = excluded.item_count
            """, (feed_name, last_cursor, item_count))

    def get_feed_state(self, feed_name: str) -> Optional[Dict[str, Any]]:
        """Retrieve persistent feed cursor state."""
        with self.connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT feed_name, last_cursor, last_poll_time, item_count
                FROM feed_state WHERE feed_name = ?
            """, (feed_name,))
            row = cursor.fetchone()
            if not row:
                return None
            return dict(row)

    # --- Emitted Alerts Operations ---

    def record_alert_emission(
        self,
        emission_id: str,
        proposal_id: str,
        item_id: str,
        alert_payload: Dict[str, Any],
    ) -> bool:
        """
        Record emitted alert after human approval.
        Returns True if newly recorded, False if already emitted (idempotent).
        """
        with self.connection() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute("""
                    INSERT INTO emitted_alerts (emission_id, proposal_id, item_id, emitted_at, alert_payload_json)
                    VALUES (?, ?, ?, CURRENT_TIMESTAMP, ?)
                """, (emission_id, proposal_id, item_id, json.dumps(alert_payload)))
                return True
            except sqlite3.IntegrityError:
                # Already emitted for this proposal_id
                return False

    def is_alert_emitted(self, proposal_id: str) -> bool:
        """Check if an alert proposal has already been emitted."""
        with self.connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT 1 FROM emitted_alerts WHERE proposal_id = ? LIMIT 1
            """, (proposal_id,))
            return cursor.fetchone() is not None

    def get_emitted_alert(self, proposal_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve record of an emitted alert."""
        with self.connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT emission_id, proposal_id, item_id, emitted_at, alert_payload_json
                FROM emitted_alerts WHERE proposal_id = ?
            """, (proposal_id,))
            row = cursor.fetchone()
            if not row:
                return None
            res = dict(row)
            res["alert_payload"] = json.loads(res.pop("alert_payload_json"))
            return res

    def get_all_pending_alert_proposals(self) -> List[Dict[str, Any]]:
        """Retrieve all pending alert proposals."""
        with self.connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT proposal_id, item_id, urgency, status, evidence_json, created_time, approved_time
                FROM alert_proposals WHERE status = 'pending' ORDER BY urgency DESC
            """)
            results = []
            for row in cursor.fetchall():
                r = dict(row)
                if isinstance(r.get("evidence_json"), str):
                    try:
                        r["evidence_json"] = json.loads(r["evidence_json"])
                    except Exception:
                        pass
                results.append(r)
            return results

    def get_all_emitted_alerts(self) -> List[Dict[str, Any]]:
        """Retrieve all emitted alerts."""
        with self.connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT emission_id, proposal_id, item_id, emitted_at, alert_payload_json
                FROM emitted_alerts ORDER BY emitted_at DESC
            """)
            results = []
            for row in cursor.fetchall():
                r = dict(row)
                if isinstance(r.get("alert_payload_json"), str):
                    try:
                        r["alert_payload"] = json.loads(r.pop("alert_payload_json"))
                    except Exception:
                        pass
                results.append(r)
            return results

