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
import sys
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
    print(f"[Phase 3] Run command recognized: mode={mode}, top_n={args.top_n}")
    
    if args.fault_injection:
        print("[Phase 3] Fault injection flag noted (handled in Phase 4 fault suite)")
    
    if args.budget_usd:
        print(f"[Phase 3] Budget override: ${args.budget_usd:.2f}")

    if mode == "replay":
        from jyot_monitor.replay import run_replay
        print(f"\n[+] Executing Offline Replay on: {args.replay}")
        summary = run_replay(
            fixtures_dir=args.replay,
            budget_usd=args.budget_usd,
            top_n=args.top_n,
            strict_llm=args.strict_llm,
            target_item_id=args.item_id,
        )
        print("\n=== Replay Execution Summary ===")
        print(f"Run ID:            {summary.run_id}")
        print(f"Total Items:       {summary.total_items}")
        print(f"Completed Items:   {summary.completed_count}")
        print(f"Partial Items:     {summary.partial_count}")
        print(f"Error Items:       {summary.error_count}")
        print(f"Alert Proposals:   {summary.proposals_count}")
        print(f"Total Cost USD:    ${summary.total_cost_usd:.6f}")
        print(f"Duration:          {summary.duration_seconds:.2f}s")
        if summary.trace_file:
            print(f"JSONL Trace File:  {summary.trace_file}")
        print("================================")
        return 0

    print("\n[!] LIVE INGESTION MODE")
    print("Live network RSS/HTML ingestion is scheduled for Phase 4.")
    return 0


def cmd_eval(args: argparse.Namespace) -> int:
    """Execute the eval command."""
    if not args.gold.exists():
        raise CLIError(f"Gold dataset not found: {args.gold}")
    
    print(f"[Phase 2] Eval command recognized: gold={args.gold}")
    
    manifest_file = args.gold / "manifest.json"
    if manifest_file.is_file():
        from jyot_monitor.evaluation.ocr_eval import run_ocr_eval_and_save
        artifacts_dir = Path("artifacts/eval")
        print("\n[+] Running Offline OCR Evaluation on Gold Fixtures...")
        results, report = run_ocr_eval_and_save(args.gold, artifacts_dir)
        print("\n" + report)
        print("\n[Note] Phase 2 OCR evaluation complete. Full agent/classification evaluation will be expanded in Phase 5.")
        return 0
    else:
        print("\n[!] Evaluation manifest not found in gold directory.")
        print(f"Expected manifest at: {manifest_file}")
        return 1


def cmd_approve(args: argparse.Namespace) -> int:
    """Execute the approve command."""
    from jyot_monitor.storage import Storage
    from jyot_monitor.models import ProposalStatus
    
    db_path = Path("artifacts/monitor.db")
    if not db_path.exists():
        print(f"Error: Database not found at {db_path}", file=sys.stderr)
        return 1
    
    storage = Storage(db_path)
    proposal = storage.get_alert_proposal(args.proposal_id)
    if not proposal:
        print(f"Error: Proposal '{args.proposal_id}' not found.", file=sys.stderr)
        return 1
    
    updated = storage.update_proposal_status(args.proposal_id, ProposalStatus.APPROVED)
    if updated:
        print(f"[+] Alert Proposal '{args.proposal_id}' APPROVED successfully by human operator.")
        return 0
    else:
        print(f"[!] Proposal '{args.proposal_id}' was not pending (status: {proposal.status.value}).", file=sys.stderr)
        return 1


def cmd_reject(args: argparse.Namespace) -> int:
    """Execute the reject command."""
    from jyot_monitor.storage import Storage
    from jyot_monitor.models import ProposalStatus
    
    db_path = Path("artifacts/monitor.db")
    if not db_path.exists():
        print(f"Error: Database not found at {db_path}", file=sys.stderr)
        return 1
    
    storage = Storage(db_path)
    proposal = storage.get_alert_proposal(args.proposal_id)
    if not proposal:
        print(f"Error: Proposal '{args.proposal_id}' not found.", file=sys.stderr)
        return 1
    
    updated = storage.update_proposal_status(args.proposal_id, ProposalStatus.REJECTED)
    if updated:
        print(f"[+] Alert Proposal '{args.proposal_id}' REJECTED successfully by human operator.")
        return 0
    else:
        print(f"[!] Proposal '{args.proposal_id}' was not pending (status: {proposal.status.value}).", file=sys.stderr)
        return 1



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
