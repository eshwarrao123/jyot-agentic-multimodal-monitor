import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

trace_path = Path("submission_evidence/traces/replay_sample.jsonl")
fault_trace_path = Path("submission_evidence/traces/fault_injection_sample.jsonl")

def inspect_trace(p):
    print(f"=== {p} ===")
    with open(p, "r", encoding="utf-8") as f:
        lines = [json.loads(line) for line in f]
    
    by_item = {}
    for idx, e in enumerate(lines, 1):
        item_id = e.get("item_id", "unknown")
        if item_id not in by_item:
            by_item[item_id] = []
        by_item[item_id].append((idx, e))
        
    for item_id, events in by_item.items():
        print(f"\n--- Item: {item_id} ({len(events)} events) ---")
        for line_num, ev in events:
            step = ev.get("step_index")
            tool = ev.get("tool")
            status = ev.get("status")
            lat = ev.get("latency_ms")
            cost = ev.get("cost_usd")
            budget = ev.get("budget_remaining")
            rat = ev.get("decision_rationale")
            res = ev.get("result_summary")
            mode = ev.get("planner_mode")
            fb = ev.get("fallback_used")
            print(f"  Line {line_num} | Step {step} | Tool: {tool} | Mode: {mode} (fallback={fb}) | Status: {status} | Latency: {lat}ms | Cost: ${cost} | Budget: ${budget}")
            print(f"    Rationale: {rat}")
            print(f"    Result: {res}")

inspect_trace(trace_path)
inspect_trace(fault_trace_path)
