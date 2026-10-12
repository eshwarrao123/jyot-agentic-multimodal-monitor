"""
Executive Top-N Markdown Digest Renderer.

Renders prioritized, clustered digests consuming SQLite persistent memory,
story clusters, score breakdowns, OCR evidence, and human approval status.
"""

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from jyot_monitor.models import (
    AlertProposal,
    ItemProcessingResult,
    ItemStatus,
    ProposalStatus,
    SourceItem,
    StoryCluster,
    utc_now,
)
from jyot_monitor.safety.redaction import redact_data, redact_text
from jyot_monitor.storage import Storage


class DigestRenderer:
    """Renderer for executive Markdown digests."""

    def __init__(self, top_n: int = 10):
        self.top_n = top_n

    def render(
        self,
        run_id: str,
        clusters: List[Dict[str, Any]],
        items_by_id: Dict[str, Dict[str, Any]],
        proposals: List[Dict[str, Any]],
        emitted_alerts: List[Dict[str, Any]],
        previous_clusters: Optional[List[Dict[str, Any]]] = None,
        run_mode: str = "Replay",
        timestamp: Optional[datetime] = None,
    ) -> str:
        """Render the complete executive Markdown digest."""
        ts = timestamp or datetime.now(timezone.utc)
        ts_str = ts.strftime("%Y-%m-%d %H:%M:%S UTC")

        # 1. Sort clusters descending by leader final score
        def get_cluster_score(c: Dict[str, Any]) -> float:
            leader_id = c.get("representative_item_id")
            item = items_by_id.get(leader_id, {})
            features = item.get("features", {})
            effective_urg = features.get("post_critique_urgency") if features.get("post_critique_urgency") is not None else features.get("urgency_score")
            return float(features.get("final_score") or effective_urg or 0.0)

        sorted_clusters = sorted(clusters, key=get_cluster_score, reverse=True)
        top_clusters = sorted_clusters[:self.top_n]

        # 2. Compute "What Changed Since Last Digest"
        new_stories = []
        escalated_stories = []
        repeat_stories = []

        prev_cluster_ids = {pc.get("cluster_id") for pc in (previous_clusters or [])}

        for c in sorted_clusters:
            cid = c.get("cluster_id")
            leader_id = c.get("representative_item_id")
            title = items_by_id.get(leader_id, {}).get("title") or cid
            status = c.get("reporting_status", "new")

            if cid not in prev_cluster_ids and status == "new":
                new_stories.append(f"**{title}** (`{cid}`): New incident cluster identified with {c.get('member_count', 1)} record(s).")
            elif status == "escalated":
                escalated_stories.append(f"**{title}** (`{cid}`): Escalated in urgency due to new corroborating evidence.")
            else:
                repeat_stories.append(f"**{title}** (`{cid}`): {c.get('member_count', 1)} total member records.")

        # Build Markdown
        md = []
        md.append(f"# Jyot Multimodal Monitor - Executive Safety Digest")
        md.append("")
        md.append(f"**Generated:** {ts_str}  ")
        md.append(f"**Run Identifier:** `{run_id}` ({run_mode} Mode)  ")
        md.append(f"**Scope:** Top-{self.top_n} Prioritized Story Clusters from {len(items_by_id)} Total Processed Items  ")
        md.append("")
        md.append("---")
        md.append("")

        # Section 1: Executive Overview
        md.append("## 1. Executive Summary & Incident Metrics")
        md.append("")
        md.append("| Metric | Count | Description |")
        md.append("| :--- | :---: | :--- |")
        md.append(f"| **Total Processed Items** | `{len(items_by_id)}` | Total raw records ingested or replayed |")
        md.append(f"| **Active Story Clusters** | `{len(clusters)}` | Deduplicated multimodal narrative groups |")
        md.append(f"| **Top-N Reported Clusters** | `{len(top_clusters)}` | Prioritized incidents included in this digest |")
        md.append(f"| **Pending Alert Proposals** | `{len(proposals)}` | High-urgency alerts awaiting human operator decision |")
        md.append(f"| **Emitted Alerts** | `{len(emitted_alerts)}` | Approved alerts formally emitted to audit channels |")
        md.append("")

        # Section 2: What Changed Since Last Digest
        md.append("## 2. What Changed Since Last Digest")
        md.append("")
        if new_stories:
            md.append("### 2.1 Newly Identified Incidents (NEW)")
            for s in new_stories[:5]:
                md.append(f"- {s}")
            md.append("")
        else:
            md.append("### 2.1 Newly Identified Incidents (NEW)")
            md.append("*No new story clusters formed during this polling cycle.*")
            md.append("")

        if escalated_stories:
            md.append("### 2.2 Escalated Incidents (ESCALATED)")
            for s in escalated_stories[:5]:
                md.append(f"- {s}")
            md.append("")

        if repeat_stories:
            md.append("### 2.3 Ongoing & Previously Reported Stories (MONITORED)")
            for s in repeat_stories[:5]:
                md.append(f"- {s}")
            md.append("")

        md.append("---")
        md.append("")

        # Section 3: Ranked Top-N Story Clusters
        md.append(f"## 3. Prioritized Top-{len(top_clusters)} Story Clusters")
        md.append("")

        for idx, c in enumerate(top_clusters, start=1):
            cid = c.get("cluster_id")
            leader_id = c.get("representative_item_id")
            item = items_by_id.get(leader_id, {})
            features = item.get("features", {})

            title = item.get("title") or "Untitled Regulatory Notice"
            source = item.get("source") or "Unknown"
            url = item.get("url") or "#"
            taxonomy = features.get("taxonomy") or "uncategorized"
            rel = float(features.get("relevance_score") or 0.0)
            urg = float(features.get("post_critique_urgency") if features.get("post_critique_urgency") is not None else (features.get("urgency_score") or 0.0))
            cred = float(features.get("credibility") or 50.0)
            rec = float(features.get("recency_boost") or 0.0)
            final_score = float(features.get("final_score") or round(0.45 * rel + 0.40 * urg + 0.10 * cred + 0.05 * rec, 2))

            status_badge = c.get("reporting_status", "new").upper()

            md.append(f"### {idx}. [{taxonomy.upper()}] {title}")
            md.append(f"**Cluster ID:** `{cid}` | **Status:** `{status_badge}` | **Priority Score:** `{final_score}/100`")
            md.append("")
            md.append(f"- **Primary Authority:** [{source}]({url}) (Item ID: `{leader_id}`)")
            md.append(f"- **Cluster Membership:** {c.get('member_count', 1)} item(s) joined via {c.get('match_type', 'new_leader')}")
            md.append("")

            # Score Breakdown Table
            md.append("**Score Component Breakdown:**")
            md.append("")
            md.append("| Relevance (45%) | Urgency (40%) | Authority (10%) | Recency (5%) | Final Priority |")
            md.append("| :---: | :---: | :---: | :---: | :---: |")
            md.append(f"| {rel:.1f} | {urg:.1f} | {cred:.1f} | {rec:.1f} | **{final_score:.2f}** |")
            md.append("")

            # Evidence & Flags
            flags = []
            ocr_conf = features.get("ocr_confidence")
            if ocr_conf is not None and ocr_conf < 0.70:
                flags.append("`[FLAG: LOW OCR CONFIDENCE]`")
            v_stat = features.get("verification_status")
            if v_stat in ("insufficient_evidence", "contradicted", "unverified") or (v_stat is None and features.get("is_unverified")):
                flags.append("`[FLAG: UNVERIFIED CLAIM]`")
            if item.get("status") == "partial" or features.get("has_partial_error"):
                flags.append("`[FLAG: PARTIAL PROCESSING]`")

            if flags:
                md.append(f"**Quality & Audit Flags:** {' '.join(flags)}")
                md.append("")

            # Snippet / Evidence
            snippet = features.get("evidence_snippet") or item.get("body") or ""
            redacted_snippet = redact_text(snippet)
            if len(redacted_snippet) > 300:
                redacted_snippet = redacted_snippet[:297] + "..."
            if redacted_snippet:
                md.append(f"> **Extracted Evidence (Redacted):**  \n> *\"{redacted_snippet}\"*")
                md.append("")

            # Member list
            member_ids = c.get("member_item_ids", [leader_id])
            if len(member_ids) > 1:
                md.append(f"**Corroborating Story Members ({len(member_ids)} total):**")
                for m_id in member_ids:
                    m_item = items_by_id.get(m_id, {})
                    m_src = m_item.get("source", "Source")
                    m_title = m_item.get("title", m_id)
                    md.append(f"- `{m_id}` ({m_src}): {m_title}")
                md.append("")

            md.append("---")
            md.append("")

        # Section 4: Human-in-the-Loop Alert Queue Status
        md.append("## 4. Human-in-the-Loop Alert Gate Status")
        md.append("")
        md.append("The monitoring agent operates under a strict bounded-autonomy principle. **It has no permission to send external messages directly.** All alerts require explicit human operator authorization.")
        md.append("")

        if proposals:
            md.append("### 4.1 Pending Operator Action Queue")
            md.append("")
            md.append("| Proposal ID | Item ID | Urgency | Proposed Title | Required Operator Action |")
            md.append("| :--- | :--- | :---: | :--- | :--- |")
            for p in proposals:
                pid = p.get("proposal_id")
                iid = p.get("item_id")
                urg_p = p.get("urgency", 0.0)
                ev = p.get("evidence_json", {})
                title_p = ev.get("title", "Urgent Alert")
                md.append(f"| `{pid}` | `{iid}` | {urg_p:.1f} | {title_p[:40]} | `python -m jyot_monitor approve {pid}` |")
            md.append("")
        else:
            md.append("### 4.1 Pending Operator Action Queue")
            md.append("*No pending alert proposals in the operator queue.*")
            md.append("")

        if emitted_alerts:
            md.append("### 4.2 Formally Emitted Alert Audit Log")
            md.append("")
            md.append("| Emission ID | Proposal ID | Emitted At | Approved By | Audit Destination |")
            md.append("| :--- | :--- | :--- | :--- | :--- |")
            for ea in emitted_alerts[:5]:
                eid = ea.get("emission_id")
                pid = ea.get("proposal_id")
                eat = ea.get("emitted_at", "N/A")[:19]
                by = ea.get("approved_by", "human_operator")
                md.append(f"| `{eid}` | `{pid}` | {eat} | `{by}` | `artifacts/alerts/emitted_alerts.jsonl` |")
            md.append("")

        md.append("---")
        md.append("*End of Digest — Jyot Agentic Multimodal Monitor (Track B Extended)*")
        return "\n".join(md)


def build_digest_from_storage(
    storage: Storage,
    run_id: str,
    run_mode: str = "Replay",
    top_n: int = 10,
    output_path: Optional[Path] = None,
) -> str:
    """Load state from SQLite database and render the digest."""
    raw_clusters = storage.get_all_clusters()
    clusters = []
    for c in raw_clusters:
        if hasattr(c, "model_dump"):
            clusters.append(c.model_dump())
        elif hasattr(c, "dict"):
            clusters.append(c.dict())
        elif isinstance(c, dict):
            clusters.append(c)
        else:
            clusters.append(dict(c))

    proposals = storage.get_all_pending_alert_proposals()
    emitted = storage.get_all_emitted_alerts()

    # Load item details
    items_by_id: Dict[str, Dict[str, Any]] = {}
    for c in clusters:
        for item_id in c.get("member_item_ids", []):
            if item_id not in items_by_id:
                item_row = storage.get_item(item_id)
                features_row = storage.get_item_features(item_id)
                items_by_id[item_id] = {
                    "item_id": item_id,
                    "title": item_row.title if item_row else item_id,
                    "source": item_row.source if item_row else "Unknown",
                    "url": item_row.url if item_row else None,
                    "body": item_row.body if item_row else None,
                    "features": features_row or {},
                }

    renderer = DigestRenderer(top_n=top_n)
    md_content = renderer.render(
        run_id=run_id,
        clusters=clusters,
        items_by_id=items_by_id,
        proposals=proposals,
        emitted_alerts=emitted,
        run_mode=run_mode,
    )

    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(md_content, encoding="utf-8")

    return md_content
