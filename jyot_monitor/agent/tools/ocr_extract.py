"""
ocr_extract tool implementation.

Integrates the real Phase 2 OCR router and engine adapters.
Returns validated OCRResult schema without duplicate abstractions.

Security: local_path is validated against explicit permitted roots before any
file access.  The planner cannot read arbitrary filesystem paths via this tool.
"""

import os
from pathlib import Path
from typing import Any, Dict, Optional
from PIL import Image

from jyot_monitor.models import ToolName, ToolResult
from jyot_monitor.ocr.pdf_rendering import render_pdf_pages
from jyot_monitor.ocr.router import OCRRouter


def _resolve_trusted_path(
    raw_path: str,
    fixture_root: Path,
    downloads_root: Optional[Path],
) -> Optional[Path]:
    """
    Resolve *raw_path* to an absolute Path only if it is contained within one
    of the two permitted roots.

    Permitted roots:
      1. fixture_root  — offline recorded fixtures directory.
      2. downloads_root — directory for live-downloaded attachments (may be None).

    Returns None if the path is outside both roots, contains traversal, or is a
    symlink that escapes the permitted tree.
    """
    raw_p = Path(raw_path)
    try:
        # Resolve relative paths against fixture_root first, then cwd
        if raw_p.is_absolute():
            candidate = raw_p.resolve(strict=False)
        else:
            candidate = (fixture_root / raw_p).resolve(strict=False)
            if not candidate.exists():
                candidate = (Path(os.getcwd()) / raw_p).resolve(strict=False)

        # Resolve symlinks fully to catch symlink escapes
        if candidate.exists():
            candidate = candidate.resolve(strict=True)

        # Containment check against permitted roots
        if candidate.is_relative_to(fixture_root.resolve()):
            return candidate
        if downloads_root is not None and candidate.is_relative_to(downloads_root.resolve()):
            return candidate
        return None
    except (OSError, ValueError):
        return None


def execute_ocr_extract(arguments: Dict[str, Any], context: Dict[str, Any]) -> ToolResult:
    """Execute real multi-engine OCR on image or PDF attachment.

    Resolution order for local_path (most-trusted first):
    1. Attachment record in context (set by controller from trusted fixture manifest).
    2. Result of a previously completed fetch_attachment tool call.
    3. Planner-supplied argument — accepted only after containment validation.
    """
    attachment_id = arguments.get("attachment_id")
    language_hint = arguments.get("language_hint", "en")
    item_id = context.get("item_id", "unknown_item")

    fixture_root = Path(context.get("fixture_root", "fixtures")).resolve()
    downloads_root_raw = context.get("downloads_root")
    downloads_root = Path(downloads_root_raw).resolve() if downloads_root_raw else None

    # --- Step 1: trusted context attachment record ---
    local_path: Optional[str] = None
    attachments = context.get("attachments", [])
    matched = next((a for a in attachments if getattr(a, "attachment_id", None) == attachment_id), None)
    if matched and getattr(matched, "local_path", None):
        local_path = matched.local_path

    # --- Step 2: result of a previously completed fetch_attachment ---
    if not local_path:
        fetch_res = context.get("completed_tool_data", {}).get("fetch_attachment")
        if fetch_res and fetch_res.get("local_path"):
            local_path = fetch_res["local_path"]

    # --- Step 3: planner-supplied argument (requires containment check) ---
    if not local_path:
        raw_arg = arguments.get("local_path")
        if raw_arg:
            resolved = _resolve_trusted_path(raw_arg, fixture_root, downloads_root)
            if resolved is None:
                return ToolResult(
                    tool_name=ToolName.OCR_EXTRACT,
                    status="error",
                    error_message=(
                        f"SecurityError: Requested path '{raw_arg}' is outside permitted "
                        "attachment roots or contains a traversal / symlink escape."
                    ),
                    is_evidence=False,
                )
            local_path = str(resolved)

    if not local_path or not Path(local_path).is_file():
        return ToolResult(
            tool_name=ToolName.OCR_EXTRACT,
            status="error",
            error_message=f"FileNotFoundError: Target attachment not found at '{local_path}'.",
            is_evidence=False,
        )

    file_path = Path(local_path)
    router = context.get("ocr_router") or OCRRouter()
    storage = context.get("storage")

    # Fault injection check
    fault_injector = context.get("fault_injector")
    item_index = context.get("item_index", 0)
    if fault_injector and fault_injector.should_inject("ocr_crash", item_index):
        fault_injector.record_fault("ocr_crash", item_index, "Simulated fatal OCR engine crash", recovered=True, outcome_message="Isolated by tool error boundary")
        return ToolResult(
            tool_name=ToolName.OCR_EXTRACT,
            status="error",
            error_message="InjectedFaultError: OCR engine process crashed unexpectedly.",
            is_evidence=False,
        )

    # Check OCR cache by file content hash
    import hashlib
    try:
        content_hash = hashlib.sha256(file_path.read_bytes()).hexdigest()
    except Exception:
        content_hash = "hash_unknown"

    if storage and content_hash != "hash_unknown":
        cached = storage.get_ocr_cache(content_hash, engine="tesseract") or storage.get_ocr_cache(content_hash, engine="easyocr")
        if cached:
            context["cache_hit"] = True
            cached_meta = cached.get("metadata") or {}
            cached_data = {
                "text": cached["text"],
                "engine": cached_meta.get("engine", "cached_engine"),
                "normalized_confidence": cached.get("confidence", 0.95),
                "language": cached.get("language", language_hint),
                "operations_applied": cached_meta.get("operations_applied", []),
                "cached": True,
            }
            cached_data.update({k: v for k, v in cached_meta.items() if k not in cached_data})
            return ToolResult(
                tool_name=ToolName.OCR_EXTRACT,
                status="success",
                data=cached_data,
                is_evidence=True,
            )

    try:
        # Check if PDF
        if file_path.suffix.lower() == ".pdf":
            pages = render_pdf_pages(file_path, dpi=200)
            page_texts = []
            final_engine = "tesseract"
            avg_conf = 0.0
            total_ops = []
            
            for page in pages:
                res = router.route_and_extract(
                    page.image,
                    language_hint=language_hint,
                    item_id=item_id,
                    attachment_id=f"{attachment_id}_p{page.page_number}",
                )
                page_texts.append(f"--- PAGE {page.page_number} ---\n{res.final_result.text}")
                final_engine = res.selected_engine
                avg_conf += res.final_result.normalized_confidence or 0.0
                total_ops.extend(res.final_result.preprocessing_operations)

            extracted_text = "\n\n".join(page_texts)
            norm_conf = round(avg_conf / max(len(pages), 1), 4)
            data = {
                "text": extracted_text,
                "engine": final_engine,
                "normalized_confidence": norm_conf,
                "page_count": len(pages),
                "is_pdf": True,
                "operations_applied": list(set(total_ops)),
                "needs_second_opinion": False,
            }
        else:
            # Standard image
            img = Image.open(str(file_path)).convert("RGB")
            res = router.route_and_extract(
                img,
                language_hint=language_hint,
                item_id=item_id,
                attachment_id=attachment_id,
            )
            data = {
                "text": res.final_result.text,
                "engine": res.selected_engine,
                "engine_version": res.final_result.engine_version,
                "raw_confidence": res.final_result.raw_confidence,
                "normalized_confidence": res.final_result.normalized_confidence,
                "confidence_semantics": res.final_result.confidence_semantics,
                "language": res.final_result.language,
                "image_dimensions": res.final_result.image_dimensions,
                "quality_signals": res.final_result.quality_signals,
                "preprocessing_applied": res.final_result.preprocessing_applied,
                "operations_applied": res.final_result.preprocessing_operations,
                "needs_second_opinion": res.final_result.needs_second_opinion,
                "second_opinion_reason": res.final_result.second_opinion_reason,
                "trajectory_name": res.trajectory_name,
                "decision_rationale": res.decision_rationale,
            }

        # Save to persistent OCR cache
        if storage and content_hash != "hash_unknown":
            try:
                storage.save_ocr_cache(
                    content_hash=content_hash,
                    engine=data.get("engine", "tesseract"),
                    preprocessing=",".join(data.get("operations_applied", [])),
                    text=data.get("text", ""),
                    confidence=data.get("normalized_confidence"),
                    language=data.get("language", language_hint),
                    metadata=data,
                )
            except Exception:
                pass

        return ToolResult(
            tool_name=ToolName.OCR_EXTRACT,
            status="success",
            data=data,
            is_evidence=True,
        )

    except Exception as e:
        return ToolResult(
            tool_name=ToolName.OCR_EXTRACT,
            status="error",
            error_message=f"OCRExtractError: {e}",
            is_evidence=False,
        )
