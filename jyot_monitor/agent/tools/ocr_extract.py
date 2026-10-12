"""
ocr_extract tool implementation.

Integrates the real Phase 2 OCR router and engine adapters.
Returns validated OCRResult schema without duplicate abstractions.
"""

from pathlib import Path
from typing import Any, Dict
from PIL import Image

from jyot_monitor.models import ToolName, ToolResult
from jyot_monitor.ocr.pdf_rendering import render_pdf_pages
from jyot_monitor.ocr.router import OCRRouter


def execute_ocr_extract(arguments: Dict[str, Any], context: Dict[str, Any]) -> ToolResult:
    """Execute real multi-engine OCR on image or PDF attachment."""
    local_path = arguments.get("local_path")
    attachment_id = arguments.get("attachment_id")
    language_hint = arguments.get("language_hint", "en")
    item_id = context.get("item_id", "unknown_item")

    # If local_path not directly supplied in arguments, look up in context attachments
    if not local_path:
        attachments = context.get("attachments", [])
        matched = next((a for a in attachments if getattr(a, "attachment_id", None) == attachment_id), None)
        if matched and getattr(matched, "local_path", None):
            local_path = matched.local_path

    # If still not found, check if fetch_attachment ran earlier in this item run
    if not local_path:
        fetch_res = context.get("completed_tool_data", {}).get("fetch_attachment")
        if fetch_res and fetch_res.get("local_path"):
            local_path = fetch_res["local_path"]

    if not local_path or not Path(local_path).is_file():
        return ToolResult(
            tool_name=ToolName.OCR_EXTRACT,
            status="error",
            error_message=f"FileNotFoundError: Target attachment not found at '{local_path}'.",
            is_evidence=False,
        )

    file_path = Path(local_path)
    router = context.get("ocr_router") or OCRRouter()

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
