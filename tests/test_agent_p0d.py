"""
P0-D Automated Regression Tests.

Demonstrates:
1. Disallowed planner actions and repeated completed actions are rejected or safely handled.
2. Repeated proposal requests create at most one proposal for an item.
3. Proposal uniqueness survives a repeated processing run.
4. Unrelated records and duplicate reposts do not count as independent verification.
5. A genuine independent corroborating record can support a claim.
6. Failed mandatory processing leaves the item partial or failed, not falsely completed.
7. An unchanged completed item is not needlessly reprocessed.
8. Changed content is reprocessed without duplicating its identity.
9. Post-critique urgency and verification status persist correctly.
10. Existing approval/rejection safeguards continue to work.
"""

from pathlib import Path
import tempfile
import shutil
import uuid
import pytest

from jyot_monitor.agent.controller import AgentController
from jyot_monitor.agent.planner import LLMPlanner, DeterministicFallbackPlanner
from jyot_monitor.agent.tools.registry import get_default_tool_registry, ToolRegistry
from jyot_monitor.digest import build_digest_from_storage
from jyot_monitor.llm.client import MockLLMClient
from jyot_monitor.models import (
    ActionRequest,
    AlertProposal,
    Attachment,
    ItemProcessingResult,
    ItemStatus,
    ProposalStatus,
    RecallTaxonomy,
    SourceItem,
    StoryCluster,
    ToolName,
    ToolResult,
    utc_now,
)
from jyot_monitor.replay import run_replay
from jyot_monitor.storage import Storage
from jyot_monitor.trace import Tracer


@pytest.fixture
def temp_env():
    """Temporary workspace environment for tests."""
    d = tempfile.mkdtemp()
    temp_path = Path(d)
    db_path = temp_path / "test_p0d.db"
    traces_dir = temp_path / "traces"
    traces_dir.mkdir(parents=True, exist_ok=True)
    storage = Storage(db_path)
    tracer = Tracer(traces_dir, "test_p0d_run")
    yield {"temp_path": temp_path, "storage": storage, "tracer": tracer, "db_path": db_path}
    shutil.rmtree(d, ignore_errors=True)


# =========================================================================
# 1. Disallowed Planner Actions and Repeated Completed Actions
# =========================================================================

def test_1_disallowed_actions_and_repeated_actions_rejected(temp_env):
    """Verify disallowed arguments, premature proposals, and repeated actions are rejected."""
    storage = temp_env["storage"]
    tracer = temp_env["tracer"]

    item = SourceItem(
        item_id="item_disallowed_1",
        source="CPSC",
        url="https://cpsc.gov/disallowed",
        title="Disallowed Test Notice",
        content_hash="hash_disallowed_1",
    )

    # Sub-case A: Disallowed arguments
    item_a = SourceItem(
        item_id="item_disallowed_1a",
        source="CPSC",
        url="https://cpsc.gov/disallowed_a",
        title="Disallowed Test Notice A",
        content_hash="hash_disallowed_1a",
    )
    mock_client_a = MockLLMClient([
        {"action": "classify_score", "rationale": "valid", "arguments": {"unauthorized_arg": 123}},
    ])
    ctrl_a = AgentController(
        planner=LLMPlanner(llm_client=mock_client_a),
        storage=storage,
        tracer=tracer,
        max_steps_per_item=1,
    )
    with tracer:
        res_a = ctrl_a.process_item(item_a)
    assert res_a.status == ItemStatus.PARTIAL
    assert ToolName.CLASSIFY_SCORE not in res_a.completed_tools
    assert "DisallowedArgumentsError" in (res_a.error_message or "")

    # Sub-case B: Premature alert proposal (before classify/verify/critique)
    item_b = SourceItem(
        item_id="item_disallowed_1b",
        source="CPSC",
        url="https://cpsc.gov/disallowed_b",
        title="Disallowed Test Notice B",
        content_hash="hash_disallowed_1b",
    )
    mock_client_b = MockLLMClient([
        {"action": "propose_alert", "rationale": "premature proposal", "arguments": {}},
    ])
    ctrl_b = AgentController(
        planner=LLMPlanner(llm_client=mock_client_b),
        storage=storage,
        tracer=tracer,
        max_steps_per_item=1,
    )
    with tracer:
        res_b = ctrl_b.process_item(item_b)
    assert res_b.status == ItemStatus.PARTIAL
    assert ToolName.PROPOSE_ALERT not in res_b.completed_tools
    assert "PrematureAlertProposalError" in (res_b.error_message or "")

    # Sub-case C: Repeated completed action without supported reason
    item_c = SourceItem(
        item_id="item_disallowed_1c",
        source="CPSC",
        url="https://cpsc.gov/disallowed_c",
        title="Disallowed Test Notice C",
        content_hash="hash_disallowed_1c",
    )
    mock_client_c = MockLLMClient([
        {"action": "classify_score", "rationale": "first classify", "arguments": {}},
        {"action": "classify_score", "rationale": "duplicate classify", "arguments": {}},
    ])
    ctrl_c = AgentController(
        planner=LLMPlanner(llm_client=mock_client_c),
        storage=storage,
        tracer=tracer,
        max_steps_per_item=2,
    )
    with tracer:
        res_c = ctrl_c.process_item(item_c)
    assert res_c.status == ItemStatus.PARTIAL
    # classify_score was executed exactly once, not twice
    assert res_c.completed_tools.count(ToolName.CLASSIFY_SCORE) == 1
    assert "RepeatedActionError" in (res_c.error_message or "")


# =========================================================================
# 2. Repeated Proposal Requests Create At Most One Proposal
# =========================================================================

def test_2_repeated_proposal_requests_create_single_proposal(temp_env):
    """Verify repeated propose_alert calls return existing proposal without creating duplicates."""
    storage = temp_env["storage"]
    registry = get_default_tool_registry()

    item = SourceItem(
        item_id="item_single_prop",
        source="FDA",
        url="https://fda.gov/single_prop",
        title="Immediate Recall: Lethal Nitrosamines in Blood Pressure Medicine",
        content_hash="hash_single_prop",
    )
    storage.save_item(item)

    ctx = {
        "storage": storage,
        "item": item,
        "urgency_alert_threshold": 85.0,
        "completed_tool_data": {
            "classify_score": {"urgency_score": 95.0, "evidence_snippets": ["Lethal contamination"]},
            "critique_item": {"post_critique_urgency": 92.0, "should_propose_alert": True, "critique_rationale": "Passed"},
            "verify_claim": {"status": "supported", "independent_sources_count": 2, "rationale": "Corroborated"},
        },
    }

    # Call 1: First proposal creation
    res_1 = registry.execute(ToolName.PROPOSE_ALERT, {}, ctx)
    assert res_1.status == "success"
    prop_id_1 = res_1.data["proposal_id"]
    assert res_1.data["is_existing"] is False

    # Call 2: Repeated propose_alert call
    res_2 = registry.execute(ToolName.PROPOSE_ALERT, {}, ctx)
    assert res_2.status == "success"
    prop_id_2 = res_2.data["proposal_id"]
    assert res_2.data["is_existing"] is True
    assert prop_id_1 == prop_id_2

    # Verify SQLite storage has strictly one proposal row for this item
    pending = storage.get_pending_proposals()
    matching_props = [p for p in pending if p[1] == item.item_id]
    assert len(matching_props) == 1


# =========================================================================
# 3. Proposal Uniqueness Survives Repeated Processing Run
# =========================================================================

def test_3_proposal_uniqueness_survives_repeated_processing_run(temp_env):
    """Verify proposal uniqueness is retained when process_item is re-executed on the same item."""
    storage = temp_env["storage"]
    tracer = temp_env["tracer"]

    # Inject independent corroborating source in persistent memory
    corrob = SourceItem(
        item_id="corrob_cpsc_3",
        source="CPSC",
        url="https://cpsc.gov/corrob3",
        title="Official CPSC Notice on Defective Carbon Monoxide Detectors Fire Risk",
        body="Laboratory testing confirms alarm failure and lethal fire risk in carbon monoxide detectors.",
        content_hash="hash_corrob_3",
    )
    storage.save_item(corrob)
    storage.save_item_features(
        item_id="corrob_cpsc_3",
        taxonomy="consumer_product",
        relevance_score=90.0,
        urgency_score=95.0,
        reporting_status="new",
    )

    item = SourceItem(
        item_id="item_detector_3",
        source="REUTERS",
        url="https://reuters.com/detector3",
        title="Lethal Fire Risk in Defective Carbon Monoxide Detectors",
        body="Alarm sensors fail to activate during carbon monoxide leaks across thousands of homes, posing fatal fire risk.",
        content_hash="hash_detector_3",
    )

    mock_planner = MockLLMClient([
        {"action": "classify_score", "rationale": "c", "arguments": {}},
        {"action": "search_memory", "rationale": "m", "arguments": {}},
        {"action": "verify_claim", "rationale": "v", "arguments": {"claim_text": item.title}},
        {"action": "critique_item", "rationale": "cr", "arguments": {}},
        {"action": "propose_alert", "rationale": "p", "arguments": {}},
        {"action": "finish", "rationale": "f", "arguments": {}},
    ])

    ctrl = AgentController(planner=LLMPlanner(llm_client=mock_planner), storage=storage, tracer=tracer)

    # First run
    with tracer:
        res_run1 = ctrl.process_item(item)
    assert res_run1.status == ItemStatus.COMPLETED
    assert res_run1.alert_proposal is not None
    first_prop_id = res_run1.alert_proposal.proposal_id

    # Second run on the same item with fresh controller
    mock_planner_2 = MockLLMClient([
        {"action": "classify_score", "rationale": "c", "arguments": {}},
        {"action": "search_memory", "rationale": "m", "arguments": {}},
        {"action": "verify_claim", "rationale": "v", "arguments": {"claim_text": item.title}},
        {"action": "critique_item", "rationale": "cr", "arguments": {}},
        {"action": "propose_alert", "rationale": "p", "arguments": {}},
        {"action": "finish", "rationale": "f", "arguments": {}},
    ])
    ctrl_2 = AgentController(planner=LLMPlanner(llm_client=mock_planner_2), storage=storage, tracer=tracer)
    with tracer:
        res_run2 = ctrl_2.process_item(item)
    assert res_run2.status == ItemStatus.COMPLETED
    assert res_run2.alert_proposal is not None
    assert res_run2.alert_proposal.proposal_id == first_prop_id

    # Verify SQLite table has exactly 1 proposal for item
    with storage.connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM alert_proposals WHERE item_id = ?", (item.item_id,))
        count = cursor.fetchone()[0]
        assert count == 1


# =========================================================================
# 4. Unrelated Records and Duplicate Reposts Do Not Count As Verification
# =========================================================================

def test_4_unrelated_and_duplicate_records_rejected_by_verify_claim(temp_env):
    """Verify duplicate reposts, same story cluster members, spam items, same-source records, and generic-word matches are rejected."""
    storage = temp_env["storage"]
    registry = get_default_tool_registry()

    item = SourceItem(
        item_id="item_target_4",
        source="FDA",
        url="https://fda.gov/target4",
        title="FDA Safety Recall on Beef Contaminated with E. Coli",
        body="Ground beef contaminated with deadly Shiga toxin-producing E. coli.",
        content_hash="hash_beef_target",
    )
    storage.save_item(item)
    storage.save_item_features(item_id="item_target_4", reporting_status="new")

    # 1. Duplicate repost (exact same content hash)
    repost = SourceItem(
        item_id="item_repost_4",
        source="NEWS_WIRE",
        url="https://wire.com/repost",
        title="FDA Safety Recall on Beef Contaminated with E. Coli",
        content_hash="hash_beef_target",  # identical hash
    )
    storage.save_item(repost)
    storage.save_item_features(item_id="item_repost_4", reporting_status="duplicate")

    # 2. Duplicate story cluster member
    cluster_dup = SourceItem(
        item_id="item_cluster_dup_4",
        source="BLOGGER",
        url="https://blog.com/beef",
        title="E. Coli in Ground Beef",
        content_hash="hash_beef_diff",
    )
    storage.save_item(cluster_dup)
    storage.save_item_features(item_id="item_cluster_dup_4", reporting_status="monitored")
    cluster = StoryCluster(
        cluster_id="cluster_beef_4",
        representative_item_id=item.item_id,
        member_item_ids=[item.item_id, cluster_dup.item_id],
        similarity_evidence={cluster_dup.item_id: {"score": 0.95}},
    )
    storage.save_cluster(cluster)

    # 3. Spam / manipulation item
    spam_item = SourceItem(
        item_id="item_spam_4",
        source="SPAMBOT",
        url="https://spam.com/beef",
        title="Deadly E. Coli Ground Beef Alert",
        content_hash="hash_spam_4",
    )
    storage.save_item(spam_item)
    storage.save_item_features(item_id="item_spam_4", taxonomy=RecallTaxonomy.SPAM_MANIPULATION.value, reporting_status="new")

    # 4. Same underlying source (FDA)
    same_src_item = SourceItem(
        item_id="item_same_src_4",
        source="FDA",  # same source as target
        url="https://fda.gov/target4_copy",
        title="FDA Notice on E. Coli Beef Outbreak",
        content_hash="hash_same_src_4",
    )
    storage.save_item(same_src_item)
    storage.save_item_features(item_id="item_same_src_4", reporting_status="new")

    # 5. Unrelated record that merely shares generic words ("FDA", "safety", "recall")
    unrelated_item = SourceItem(
        item_id="item_unrelated_4",
        source="USDA",
        url="https://usda.gov/lettuce",
        title="FDA Safety Alert: Consumer Warning on Packaged Salad Lettuce",
        body="Routine safety inspection notice regarding packaged lettuce leaves.",
        content_hash="hash_lettuce_4",
    )
    storage.save_item(unrelated_item)
    storage.save_item_features(item_id="item_unrelated_4", taxonomy="food_safety", reporting_status="new")

    # Execute verify_claim on target item
    ctx = {"storage": storage, "item": item, "completed_tool_data": {}}
    res = registry.execute(ToolName.VERIFY_CLAIM, {"claim_text": item.title}, ctx)

    assert res.data["status"] == "insufficient_evidence"
    assert res.data["independent_sources_count"] == 1
    assert res.data["corroborating_item_ids"] == []


# =========================================================================
# 5. Genuine Independent Corroborating Record Supports Claim
# =========================================================================

def test_5_genuine_independent_corroborating_record_supports_claim(temp_env):
    """Verify a genuine independent authority with substantive claim similarity confirms the claim."""
    storage = temp_env["storage"]
    registry = get_default_tool_registry()

    item = SourceItem(
        item_id="item_crib_target",
        source="CONSUMER_REPORTS",
        url="https://consumerreports.org/cribs",
        title="Dangerous Defect in DreamTime Infant Bassinet Entrapment Risk",
        body="Infant suffocation risk discovered due to structural collapse in DreamTime bassinet model 500.",
        content_hash="hash_crib_target",
    )
    storage.save_item(item)
    storage.save_item_features(item_id="item_crib_target", reporting_status="new")

    # Genuine independent corroborating record from CPSC
    cpsc_record = SourceItem(
        item_id="cpsc_dreamtime_corrob",
        source="CPSC",
        url="https://cpsc.gov/recalls/dreamtime-bassinet",
        title="CPSC Urges Immediate Stop Use of DreamTime Infant Bassinets Due to Entrapment Risk",
        body="Investigation confirms structural collapse and infant suffocation entrapment hazards in DreamTime models.",
        content_hash="hash_dreamtime_cpsc",
    )
    storage.save_item(cpsc_record)
    storage.save_item_features(
        item_id="cpsc_dreamtime_corrob",
        taxonomy="consumer_product",
        relevance_score=95.0,
        urgency_score=92.0,
        reporting_status="new",
    )

    ctx = {"storage": storage, "item": item, "completed_tool_data": {}}
    res = registry.execute(ToolName.VERIFY_CLAIM, {"claim_text": item.title}, ctx)

    assert res.data["status"] == "supported"
    assert res.data["independent_sources_count"] >= 2
    assert "cpsc_dreamtime_corrob" in res.data["corroborating_item_ids"]


# =========================================================================
# 6. Failed Mandatory Processing Leaves Item Partial or Failed
# =========================================================================

def test_6_failed_mandatory_processing_leaves_item_partial(temp_env):
    """Verify required tool failure followed by finish does not falsely mark item COMPLETED."""
    storage = temp_env["storage"]
    tracer = temp_env["tracer"]

    # Custom registry with a failing classify_score handler
    failing_reg = ToolRegistry()
    failing_reg.register(
        ToolName.CLASSIFY_SCORE,
        lambda args, ctx: ToolResult(
            tool_name=ToolName.CLASSIFY_SCORE,
            status="error",
            error_message="ClassificationEngineError: Service timed out",
        )
    )
    failing_reg.register(
        ToolName.FINISH,
        lambda args, ctx: ToolResult(tool_name=ToolName.FINISH, status="success", data={"finished": True})
    )

    mock_client = MockLLMClient([
        {"action": "classify_score", "rationale": "score", "arguments": {}},
        {"action": "finish", "rationale": "attempt finish after error", "arguments": {}},
    ])

    ctrl = AgentController(
        planner=LLMPlanner(llm_client=mock_client),
        tool_registry=failing_reg,
        storage=storage,
        tracer=tracer,
    )

    item = SourceItem(
        item_id="item_fail_mandatory",
        source="CPSC",
        url="https://cpsc.gov/fail",
        title="Flammable Pajamas Notice",
        content_hash="hash_pajamas_fail",
    )

    with tracer:
        res = ctrl.process_item(item)

    assert res.status == ItemStatus.PARTIAL
    assert res.status != ItemStatus.COMPLETED
    assert "IncompleteProcessingError" in (res.error_message or "")


# =========================================================================
# 7. Unchanged Completed Item Is Not Needlessly Reprocessed
# =========================================================================

def test_7_unchanged_completed_item_not_reprocessed(temp_env):
    """Verify replay skips reprocessing for already completed item with unchanged content hash."""
    storage = temp_env["storage"]
    fixtures_dir = temp_env["temp_path"] / "fixtures"
    fixtures_dir.mkdir(parents=True, exist_ok=True)

    # Save completed item
    completed_item = SourceItem(
        item_id="item_skip_test",
        source="CPSC",
        url="https://cpsc.gov/skip",
        title="Unchanged Safety Notice",
        body="No changes made to this product warning.",
        content_hash=SourceItem.compute_content_hash("Unchanged Safety Notice", "No changes made to this product warning."),
        status=ItemStatus.COMPLETED,
    )
    storage.save_item(completed_item)

    # Create recorded fixture manifest with identical content
    import json
    fixture_data = {
        "items": [{
            "item_id": "item_skip_test",
            "source": "CPSC",
            "url": "https://cpsc.gov/skip",
            "title": "Unchanged Safety Notice",
            "body": "No changes made to this product warning.",
            "attachments": [],
        }]
    }
    manifest_file = fixtures_dir / "manifest.json"
    manifest_file.write_text(json.dumps(fixture_data), encoding="utf-8")

    # Run replay with a tracking planner
    mock_client = MockLLMClient()
    summary = run_replay(
        fixtures_dir=fixtures_dir,
        db_path=temp_env["db_path"],
        artifacts_dir=temp_env["temp_path"] / "artifacts",
        planner=LLMPlanner(llm_client=mock_client),
    )

    assert summary.total_items == 1
    assert summary.results[0].status == ItemStatus.COMPLETED
    # Planner was never invoked because the completed item was skipped from execution
    assert len(mock_client.call_history) == 0
    assert summary.results[0].steps_taken == 0


# =========================================================================
# 8. Changed Content Is Reprocessed Without Duplicating Its Identity
# =========================================================================

def test_8_changed_content_reprocessed_without_duplicating_identity(temp_env):
    """Verify updated item content triggers safe reprocessing without duplicating identity in storage."""
    storage = temp_env["storage"]
    fixtures_dir = temp_env["temp_path"] / "fixtures_changed"
    fixtures_dir.mkdir(parents=True, exist_ok=True)

    # 1. Initially completed item
    v1_body = "Preliminary notice of potential flaw."
    v1_item = SourceItem(
        item_id="item_evolve_8",
        source="FDA",
        url="https://fda.gov/evolve",
        title="Evolving Contamination Warning",
        body=v1_body,
        content_hash=SourceItem.compute_content_hash("Evolving Contamination Warning", v1_body),
        status=ItemStatus.COMPLETED,
    )
    storage.save_item(v1_item)

    # 2. Content changes: body has critical new information
    v2_body = "CRITICAL UPDATE: 14 fatalities confirmed across multiple hospitals."
    v2_hash = SourceItem.compute_content_hash("Evolving Contamination Warning", v2_body)

    import json
    fixture_data = {
        "items": [{
            "item_id": "item_evolve_8",
            "source": "FDA",
            "url": "https://fda.gov/evolve",
            "title": "Evolving Contamination Warning",
            "body": v2_body,
            "attachments": [],
        }]
    }
    manifest_file = fixtures_dir / "manifest.json"
    manifest_file.write_text(json.dumps(fixture_data), encoding="utf-8")

    summary = run_replay(
        fixtures_dir=fixtures_dir,
        db_path=temp_env["db_path"],
        artifacts_dir=temp_env["temp_path"] / "artifacts",
        planner=DeterministicFallbackPlanner(),
    )

    assert summary.total_items == 1
    # Check item in storage
    stored_item = storage.get_item("item_evolve_8")
    assert stored_item is not None
    assert stored_item.content_hash == v2_hash
    assert stored_item.body == v2_body

    # Verify no duplicate item rows created in SQLite
    with storage.connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM items WHERE item_id = ?", ("item_evolve_8",))
        assert cursor.fetchone()[0] == 1


# =========================================================================
# 9. Post-Critique Urgency and Verification Status Persist Correctly
# =========================================================================

def test_9_post_critique_urgency_and_verification_status_persist(temp_env):
    """Verify post-critique urgency reduction and verification status are persisted and read by digest."""
    storage = temp_env["storage"]
    tracer = temp_env["tracer"]

    item = SourceItem(
        item_id="item_digest_critique",
        source="RUMOR_MILL",
        url="https://rumor.com/hazard",
        title="Lethal Salmonella Contamination Outbreak in Baby Formula",
        body="Unconfirmed rumors of severe bacterial contamination across local daycare centers.",
        content_hash="hash_rumor_9",
    )
    storage.save_item(item)

    # Urgent claim that lacks independent corroboration
    # classify -> urgency 90.0, verify -> insufficient_evidence, critique -> lowers urgency by 15 to 75.0
    mock_client = MockLLMClient([
        {"action": "classify_score", "rationale": "c", "arguments": {}},
        {"action": "search_memory", "rationale": "m", "arguments": {}},
        {"action": "verify_claim", "rationale": "v", "arguments": {"claim_text": item.title}},
        {"action": "critique_item", "rationale": "cr", "arguments": {}},
        {"action": "finish", "rationale": "f", "arguments": {}},
    ])

    ctrl = AgentController(planner=LLMPlanner(llm_client=mock_client), storage=storage, tracer=tracer)
    with tracer:
        res = ctrl.process_item(item)

    assert res.status == ItemStatus.COMPLETED
    assert res.critique is not None
    assert res.critique.post_critique_urgency < res.critique.pre_critique_urgency

    # Verify persisted in item_features table
    features = storage.get_item_features(item.item_id)
    assert features is not None
    assert features["post_critique_urgency"] == res.critique.post_critique_urgency
    assert features["verification_status"] == "insufficient_evidence"

    # Build executive Markdown digest and verify it flags unverified claim and reflects post-critique score
    digest_md = build_digest_from_storage(storage, run_id="digest_p0d_run", top_n=5)
    assert "[FLAG: UNVERIFIED CLAIM]" in digest_md


# =========================================================================
# 10. Existing Approval/Rejection Safeguards Continue to Work
# =========================================================================

def test_10_approval_rejection_safeguards_continue_to_work(temp_env):
    """Verify human approval and rejection flow, duplicate emission prevention, and proposal status transitions."""
    storage = temp_env["storage"]

    proposal = AlertProposal(
        proposal_id="prop_guard_10",
        item_id="item_guard_10",
        urgency=95.0,
        evidence_json={"source_url": "https://cpsc.gov/guard10", "title": "High Severity Incident", "details": "Critical"},
        status=ProposalStatus.PENDING,
        created_time=utc_now(),
    )
    storage.save_alert_proposal(proposal)

    # 1. Ensure alert is not emitted yet
    assert not storage.is_alert_emitted("prop_guard_10")
    pending = storage.get_pending_proposals()
    assert any(p[0] == "prop_guard_10" for p in pending)

    # 2. Approve proposal
    updated = storage.update_proposal_status("prop_guard_10", ProposalStatus.APPROVED)
    assert updated is True

    # 3. Record emission
    emitted = storage.record_alert_emission(
        emission_id="emit_10",
        proposal_id="prop_guard_10",
        item_id="item_guard_10",
        alert_payload={"alert": "payload"},
    )
    assert emitted is True
    assert storage.is_alert_emitted("prop_guard_10") is True

    # 4. Duplicate emission rejected idempotently
    duplicate_emitted = storage.record_alert_emission(
        emission_id="emit_10_dup",
        proposal_id="prop_guard_10",
        item_id="item_guard_10",
        alert_payload={"alert": "payload"},
    )
    assert duplicate_emitted is False

    # 5. Rejection flow on second proposal
    prop_reject = AlertProposal(
        proposal_id="prop_reject_10",
        item_id="item_reject_10",
        urgency=88.0,
        evidence_json={"source_url": "https://cpsc.gov/reject10", "title": "False Alarm"},
        status=ProposalStatus.PENDING,
        created_time=utc_now(),
    )
    storage.save_alert_proposal(prop_reject)
    rejected = storage.update_proposal_status("prop_reject_10", ProposalStatus.REJECTED)
    assert rejected is True

    rejected_prop = storage.get_alert_proposal("prop_reject_10")
    assert rejected_prop.status == ProposalStatus.REJECTED
    assert not storage.is_alert_emitted("prop_reject_10")
