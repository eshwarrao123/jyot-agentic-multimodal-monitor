"""
Generate the 3 required sample digests for Phase 5.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from jyot_monitor.digest import build_digest_from_storage
from jyot_monitor.storage import Storage

def main():
    db_path = Path("artifacts/monitor.db")
    if not db_path.exists():
        print(f"Error: {db_path} does not exist")
        return

    storage = Storage(db_path)
    digests_dir = Path("artifacts/digests")
    digests_dir.mkdir(parents=True, exist_ok=True)

    # 1. Live Digest (from real ingested CPSC items)
    live_digest_path = digests_dir / "live_digest.md"
    build_digest_from_storage(
        storage=storage,
        run_id="live_9e0d7422",
        run_mode="Live Ingestion (CPSC Recalls)",
        top_n=5,
        output_path=live_digest_path,
    )
    print(f"[+] Generated: {live_digest_path} ({live_digest_path.stat().st_size} bytes)")

    # 2. Replay Digest (from recorded fixtures)
    replay_digest_path = digests_dir / "replay_digest.md"
    build_digest_from_storage(
        storage=storage,
        run_id="replay_71f99dfa",
        run_mode="Offline Replay",
        top_n=5,
        output_path=replay_digest_path,
    )
    print(f"[+] Generated: {replay_digest_path} ({replay_digest_path.stat().st_size} bytes)")

    # 3. Fault-Injection Digest (from run exercising injected faults)
    fault_digest_path = digests_dir / "fault_injection_digest.md"
    build_digest_from_storage(
        storage=storage,
        run_id="replay_1d06e3e4",
        run_mode="Fault-Injection Offline Replay",
        top_n=5,
        output_path=fault_digest_path,
    )
    print(f"[+] Generated: {fault_digest_path} ({fault_digest_path.stat().st_size} bytes)")

if __name__ == "__main__":
    main()
