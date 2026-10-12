"""
Command-line interface for the Jyot monitor.

Implements the required CLI contract:
- run --live --sources CONFIG --top-n N
- run --replay FIXTURES --top-n N --budget-usd AMOUNT
- run --replay FIXTURES --fault-injection
- eval --gold GOLD_DIR
- approve PROPOSAL_ID
"""

import argparse
import os
import sys
import uuid
from pathlib import Path
from typing import Optional

from jyot_monitor import __version__


class CLIError(Exception):
    """CLI-specific errors with user-friendly messages."""
    pass


def create_parser() -> argparse.ArgumentParser:
    """Create the main argument parser."""
    parser = argparse.ArgumentParser(
        prog="jyot_monitor",
        description="Jyot Agentic Multimodal Monitor - Track B (Extended)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}"
    )
    
    subparsers = parser.add_subparsers(dest="command", help="Available commands")
    subparsers.required = True
    
    # run command
    run_parser = subparsers.add_parser(
        "run",
        help="Run the monitoring pipeline"
    )
    
    # Mode selection (mutually exclusive)
    mode_group = run_parser.add_mutually_exclusive_group(required=True)
    mode_group.add_argument(
        "--live",
        action="store_true",
        help="Run in live mode (fetch from sources)"
    )
    mode_group.add_argument(
        "--replay",
        type=Path,
        metavar="FIXTURES_DIR",
        help="Run in replay mode on recorded fixtures (offline)"
    )
    
    # Run options
    run_parser.add_argument(
        "--sources",
        type=Path,
        metavar="CONFIG",
        help="Path to sources.yaml (required for --live)"
    )
    run_parser.add_argument(
        "--top-n",
        type=int,
        default=10,
        metavar="N",
        help="Number of top items to include in digest (default: 10)"
    )
    run_parser.add_argument(
        "--budget-usd",
        type=float,
        metavar="AMOUNT",
        help="Override per-run budget in USD"
    )
    run_parser.add_argument(
        "--fault-injection",
        action="store_true",
        help="Enable deterministic fault injection for testing"
    )
    run_parser.add_argument(
        "--strict-llm",
        action="store_true",
        help="Disallow fallback; raise error if LLM fails or is unavailable"
    )
    run_parser.add_argument(
        "--item-id",
        type=str,
        help="Target specific item ID for replay execution"
    )
    
    # eval command
    eval_parser = subparsers.add_parser(
        "eval",
        help="Run evaluation harness on gold dataset"
    )
    eval_parser.add_argument(
        "--gold",
        type=Path,
        required=True,
        metavar="GOLD_DIR",
        help="Path to gold evaluation dataset"
    )
    
    # approve command
    approve_parser = subparsers.add_parser(
        "approve",
        help="Approve a pending alert proposal"
    )
    approve_parser.add_argument(
        "proposal_id",
        help="ID of the proposal to approve"
    )
    
    # reject command (bonus)
    reject_parser = subparsers.add_parser(
        "reject",
        help="Reject a pending alert proposal"
    )
    reject_parser.add_argument(
        "proposal_id",
        help="ID of the proposal to reject"
    )
    
    return parser


def validate_run_args(args: argparse.Namespace) -> None:
    """Validate run command arguments."""
    if args.live and not args.sources:
        raise CLIError("--live mode requires --sources CONFIG")
    
    if args.sources and not args.sources.exists():
        raise CLIError(f"Sources config not found: {args.sources}")
    
    if args.replay and not args.replay.exists():
        raise CLIError(f"Fixtures directory not found: {args.replay}")
    
    if args.top_n < 1:
        raise CLIError("--top-n must be at least 1")
    
    if args.budget_usd is not None and args.budget_usd <= 0:
        raise CLIError("--budget-usd must be positive")


def cmd_run(args: argparse.Namespace) -> int:
    """Execute the run command."""
    validate_run_args(args)
    
    mode = "live" if args.live else "replay"
    print(f"[Phase 4] Run command recognized: mode={mode}, top_n={args.top_n}")
    
    if args.budget_usd:
        print(f"[Phase 4] Budget override: ${args.budget_usd:.2f}")

    if mode == "replay":
        from jyot_monitor.replay import run_replay
        print(f"\n[+] Executing Offline Replay on: {args.replay}")
        if args.fault_injection:
            print("[+] Fault injection ENABLED (deterministic scenarios active)")
        summary = run_replay(
            fixtures_dir=args.replay,
            budget_usd=args.budget_usd,
            top_n=args.top_n,
            strict_llm=args.strict_llm,
            target_item_id=args.item_id,
            fault_injection=args.fault_injection,
        )
        print("\n=== Replay Execution Summary ===")
        print(f"Run ID:            {summary.run_id}")
        print(f"Total Items:       {summary.total_items}")
        print(f"Completed Items:   {summary.completed_count}")
        print(f"Partial Items:     {summary.partial_count}")
        print(f"Error Items:       {summary.error_count}")
        print(f"Alert Proposals:   {summary.proposals_count}")
        print(f"Total Cost USD:    ${summary.total_cost_usd:.6f}")
        db_path = Path("artifacts/monitor.db")
        if db_path.exists():
            try:
                from jyot_monitor.digest import build_digest_from_storage
                from jyot_monitor.storage import Storage
                storage = Storage(db_path)
                digest_file = Path("artifacts/digests") / f"digest_{summary.run_id}.md"
                build_digest_from_storage(storage, summary.run_id, run_mode="Replay", top_n=args.top_n, output_path=digest_file)
                print(f"Digest File:       {digest_file}")
            except Exception as dig_err:
                print(f"Digest Error:      {dig_err}")
        if summary.trace_file:
            print(f"JSONL Trace File:  {summary.trace_file}")
        print("================================")
        return 0

    # Live Mode
    import yaml
    from jyot_monitor.ingestion.network import SafeHttpClient
    from jyot_monitor.ingestion.fetcher import SourceFetcher
    from jyot_monitor.storage import Storage
    from jyot_monitor.trace import Tracer
    from jyot_monitor.ocr.router import OCRRouter
    from jyot_monitor.agent.controller import AgentController
    from jyot_monitor.agent.planner import LLMPlanner, DeterministicFallbackPlanner
    from jyot_monitor.agent.tools.registry import get_default_tool_registry
    from jyot_monitor.llm.client import OllamaClient

    print(f"\n[+] Executing Live Ingestion using config: {args.sources}")
    with open(args.sources, "r", encoding="utf-8") as f:
        config_data = yaml.safe_load(f) or {}

    sources = config_data.get("sources", [])
    limits = config_data.get("limits", {})
    http_timeout = limits.get("http_timeout_seconds", 30)
    max_download_bytes = limits.get("max_download_bytes", 10 * 1024 * 1024)
    max_retries = limits.get("max_retries", 3)

    artifacts_dir = Path("artifacts")
    db_path = artifacts_dir / "monitor.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    storage = Storage(db_path)

    http_client = SafeHttpClient(
        read_timeout=float(http_timeout),
        max_bytes=max_download_bytes,
        max_retries=max_retries,
    )
    fetcher = SourceFetcher(
        storage=storage,
        http_client=http_client,
        attachment_dir=artifacts_dir / "downloads",
    )

    run_id = f"live_{uuid.uuid4().hex[:8]}"
    tracer = Tracer(artifacts_dir / "traces", run_id)
    ocr_router = OCRRouter()

    # Planner setup
    ollama_model = os.getenv("JYOT_PLANNER_MODEL", "qwen2.5:3b")
    client = OllamaClient(model=ollama_model)
    if client.is_available():
        planner = LLMPlanner(llm_client=client, allow_fallback=not args.strict_llm)
    else:
        if args.strict_llm:
            raise RuntimeError(f"Ollama model '{ollama_model}' unavailable in strict LLM mode.")
        planner = DeterministicFallbackPlanner()

    controller = AgentController(
        planner=planner,
        tool_registry=get_default_tool_registry(),
        storage=storage,
        ocr_router=ocr_router,
        tracer=tracer,
        run_id=run_id,
        per_item_usd=config_data.get("budgets", {}).get("per_item_usd", 0.10),
        per_run_usd=args.budget_usd or config_data.get("budgets", {}).get("per_run_usd", 5.00),
    )

    total_new_items = 0
    total_downloaded_attachments = 0
    proposals_generated = 0

    with tracer:
        for src in sources:
            src_name = src.get("name")
            print(f"\n[*] Polling live source: {src_name} ({src.get('url')})")
            try:
                new_items, item_atts = fetcher.poll_source(src, max_items=args.top_n)
                print(f"    Received {len(new_items)} new/updated item(s)")
                total_new_items += len(new_items)

                for item in new_items:
                    atts = item_atts.get(item.item_id, [])
                    valid_atts = []
                    for att in atts:
                        try:
                            downloaded_path = fetcher.download_attachment(
                                att,
                                allowed_hosts=src.get("allowed_hosts"),
                                max_bytes=max_download_bytes,
                            )
                            valid_atts.append(att)
                            total_downloaded_attachments += 1
                        except Exception as dl_err:
                            print(f"    [-] Attachment download skipped for {att.url}: {dl_err}")

                    res = controller.process_item(item, attachments=valid_atts)
                    item.status = res.status
                    if res.error_message:
                        item.error_code = res.error_message[:100]
                    storage.save_item(item)
                    if res.alert_proposal:
                        proposals_generated += 1

            except Exception as src_err:
                print(f"    [-] Error polling source {src_name}: {src_err}")

    print("\n=== Live Ingestion Summary ===")
    print(f"Run ID:                 {run_id}")
    print(f"Sources Polled:         {len(sources)}")
    print(f"New Items Processed:    {total_new_items}")
    print(f"Attachments Downloaded: {total_downloaded_attachments}")
    print(f"Alert Proposals:        {proposals_generated}")
    db_path = Path("artifacts/monitor.db")
    if db_path.exists():
        try:
            from jyot_monitor.digest import build_digest_from_storage
            digest_dir = Path("artifacts/digests")
            digest_file = digest_dir / f"digest_{run_id}.md"
            build_digest_from_storage(storage, run_id, run_mode="Live", top_n=args.top_n, output_path=digest_file)
            print(f"Digest File:            {digest_file}")
        except Exception as dig_err:
            print(f"Digest Error:           {dig_err}")
    if tracer.trace_file:
        print(f"JSONL Trace File:       {tracer.trace_file}")
    print("================================")
    return 0


def cmd_eval(args: argparse.Namespace) -> int:
    """Execute the eval command."""
    if not args.gold.exists():
        raise CLIError(f"Gold dataset not found: {args.gold}")
    
    print(f"\n[+] Executing Offline Evaluation on Gold Directory: {args.gold}")
    
    manifest_file = args.gold / "manifest.json"
    if not manifest_file.is_file():
        print(f"\n[!] Evaluation manifest not found in gold directory: {manifest_file}", file=sys.stderr)
        return 1

    artifacts_dir = Path("artifacts/eval")
    from jyot_monitor.evaluation.eval_harness import FullEvaluationHarness
    harness = FullEvaluationHarness(gold_dir=args.gold, artifacts_dir=artifacts_dir)
    results, report = harness.run_full_evaluation()
    print("\n" + report)
    print(f"\n[+] Evaluation artifacts saved to {artifacts_dir}")
    print(f"    - Report: {artifacts_dir / 'evaluation_report.md'}")
    print(f"    - Machine-readable JSON: {artifacts_dir / 'eval_results.json'}")
    return 0


def cmd_approve(args: argparse.Namespace) -> int:
    """Execute the approve command."""
    from jyot_monitor.storage import Storage
    from jyot_monitor.models import ProposalStatus, utc_now
    from jyot_monitor.safety.redaction import redact_data, redact_text
    import json
    
    db_path = Path(getattr(args, "db_path", None) or "artifacts/monitor.db")
    if not db_path.exists():
        print(f"Error: Database not found at {db_path}", file=sys.stderr)
        return 1
    
    storage = Storage(db_path)
    proposal = storage.get_alert_proposal(args.proposal_id)
    if not proposal:
        print(f"Error: Proposal '{args.proposal_id}' not found.", file=sys.stderr)
        return 1
    
    # 1. Idempotence check: check if already emitted
    if storage.is_alert_emitted(args.proposal_id):
        existing = storage.get_emitted_alert(args.proposal_id)
        print(f"[!] Proposal '{args.proposal_id}' was ALREADY approved and emitted.")
        print(f"    Emission ID: {existing.get('emission_id')}, Timestamp: {existing.get('emitted_at')}")
        print("    No duplicate alert will be sent.")
        return 0

    # 2. Gate check: must be pending
    if proposal.status != ProposalStatus.PENDING:
        print(f"Error: Cannot approve proposal with status '{proposal.status.value}'.", file=sys.stderr)
        return 1

    # 3. Update status in database
    storage.update_proposal_status(args.proposal_id, ProposalStatus.APPROVED)

    # 4. Redact sensitive contact details (PII) before alert emission
    ev = getattr(proposal, "evidence_json", {}) or {}
    raw_summary = getattr(proposal, "summary", None) or ev.get("evidence_snippet") or ev.get("title") or "Notice Alert"
    raw_action = getattr(proposal, "recommended_action", None) or ev.get("recommended_action") or "Review safety notice and verify item disposition."
    raw_taxonomy = getattr(getattr(proposal, "taxonomy", None), "value", None) or ev.get("taxonomy") or "product_recall"
    urgency_val = getattr(proposal, "urgency_score", None) or getattr(proposal, "urgency", 0.0)

    redacted_summary = redact_text(str(raw_summary))
    redacted_action = redact_text(str(raw_action))

    alert_payload = {
        "emission_id": f"emit_{uuid.uuid4().hex[:8]}",
        "proposal_id": proposal.proposal_id,
        "item_id": proposal.item_id,
        "taxonomy": raw_taxonomy,
        "urgency_score": urgency_val,
        "summary": redacted_summary,
        "recommended_action": redacted_action,
        "evidence_json": redact_data(ev),
        "approved_by": "human_operator",
        "emitted_at": utc_now().isoformat(),
        "channel": "console_file",
    }

    # 5. Persist emission record for resumability & idempotency
    storage.record_alert_emission(
        emission_id=alert_payload["emission_id"],
        proposal_id=proposal.proposal_id,
        item_id=proposal.item_id,
        alert_payload=alert_payload,
    )

    # 6. Append to local audit file
    alerts_file = Path("artifacts/alerts/emitted_alerts.jsonl")
    alerts_file.parent.mkdir(parents=True, exist_ok=True)
    with open(alerts_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(alert_payload) + "\n")

    # 7. Print human-approved alert emission audit card
    print("\n=======================================================")
    print("       [HUMAN-APPROVED ALERT EMISSION RECORD]          ")
    print("=======================================================")
    print(f"Proposal ID:        {proposal.proposal_id}")
    print(f"Item ID:            {proposal.item_id}")
    print(f"Taxonomy:           {raw_taxonomy}")
    print(f"Urgency Score:      {urgency_val:.1f}/100")
    print(f"Approved By:        human_operator")
    print(f"Emitted To:         {alerts_file}")
    print("--- Redacted Alert Summary ---")
    print(redacted_summary)
    print("--- Recommended Action ---")
    print(redacted_action)
    print("=======================================================\n")
    return 0


def cmd_reject(args: argparse.Namespace) -> int:
    """Execute the reject command."""
    from jyot_monitor.storage import Storage
    from jyot_monitor.models import ProposalStatus
    
    db_path = Path(getattr(args, "db_path", None) or "artifacts/monitor.db")
    if not db_path.exists():
        print(f"Error: Database not found at {db_path}", file=sys.stderr)
        return 1
    
    storage = Storage(db_path)
    proposal = storage.get_alert_proposal(args.proposal_id)
    if not proposal:
        print(f"Error: Proposal '{args.proposal_id}' not found.", file=sys.stderr)
        return 1

    if storage.is_alert_emitted(args.proposal_id):
        print(f"Error: Proposal '{args.proposal_id}' was already approved and emitted; cannot reject.", file=sys.stderr)
        return 1

    if proposal.status == ProposalStatus.REJECTED:
        print(f"[!] Proposal '{args.proposal_id}' is already REJECTED.")
        return 0

    if proposal.status != ProposalStatus.PENDING:
        print(f"Error: Cannot reject proposal with status '{proposal.status.value}'.", file=sys.stderr)
        return 1

    storage.update_proposal_status(args.proposal_id, ProposalStatus.REJECTED)
    print(f"[+] Alert Proposal '{args.proposal_id}' REJECTED by human operator.")
    print("    Strict Safety Boundary: NO alert was emitted to any channel or file.")
    return 0



def main() -> int:
    """Main entry point."""
    # Ensure Windows console uses UTF-8 to prevent charmap encoding errors
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass
    if hasattr(sys.stderr, "reconfigure"):
        try:
            sys.stderr.reconfigure(encoding="utf-8")
        except Exception:
            pass

    parser = create_parser()
    
    try:
        args = parser.parse_args()
        
        # Dispatch to command handler
        if args.command == "run":
            return cmd_run(args)
        elif args.command == "eval":
            return cmd_eval(args)
        elif args.command == "approve":
            return cmd_approve(args)
        elif args.command == "reject":
            return cmd_reject(args)
        else:
            parser.print_help()
            return 1
            
    except CLIError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nInterrupted by user", file=sys.stderr)
        return 130
    except Exception as e:
        print(f"Unexpected error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
