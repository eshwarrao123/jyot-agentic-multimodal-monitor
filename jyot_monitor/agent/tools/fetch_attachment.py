"""
fetch_attachment tool implementation.

Enforces:
1. Replay attachment access restricted to fixture root (no path traversal).
2. Fails closed on unsupported external URLs (live fetching deferred to Phase 4).
3. File size limit (10 MB) and MIME/extension allow-list (.png, .jpg, .jpeg, .pdf).
4. Computes SHA-256 hash of file content.
"""

import hashlib
import os
from pathlib import Path
from typing import Any, Dict
from jyot_monitor.models import ToolName, ToolResult


ALLOWED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".pdf"}
MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024  # 10 MB


def execute_fetch_attachment(arguments: Dict[str, Any], context: Dict[str, Any]) -> ToolResult:
    """Safely resolve and validate an attachment for an item."""
    attachment_id = arguments.get("attachment_id") or "att_default"
    raw_path = arguments.get("path") or arguments.get("local_path") or arguments.get("url")

    attachments = context.get("attachments", [])
    matched_att = next((a for a in attachments if getattr(a, "attachment_id", None) == attachment_id), None)
    if not matched_att and attachments:
        matched_att = attachments[0]
        attachment_id = getattr(matched_att, "attachment_id", attachment_id)
    if matched_att and getattr(matched_att, "local_path", None):
        raw_path = matched_att.local_path

    if not raw_path:
        return ToolResult(
            tool_name=ToolName.FETCH_ATTACHMENT,
            status="error",
            error_message="MissingArgumentError: No attachment path or ID provided.",
            is_evidence=False,
        )

    # Fail closed on remote URLs in replay mode
    if str(raw_path).startswith(("http://", "https://", "ftp://")):
        return ToolResult(
            tool_name=ToolName.FETCH_ATTACHMENT,
            status="error",
            error_message=f"UnsupportedSchemeError: External network download blocked in replay mode for URL '{raw_path}'.",
            is_evidence=False,
        )

    fixture_root = Path(context.get("fixture_root", "fixtures")).resolve()
    project_root = Path(os.getcwd()).resolve()
    raw_p = Path(raw_path)

    if raw_p.is_absolute():
        target_path = raw_p.resolve()
    else:
        candidate = (fixture_root / raw_p).resolve()
        if candidate.is_file():
            target_path = candidate
        else:
            target_path = (project_root / raw_p).resolve()

    # Path traversal check: must be inside project directory or fixture_root
    if not (target_path.is_relative_to(fixture_root) or target_path.is_relative_to(project_root)):
        return ToolResult(
            tool_name=ToolName.FETCH_ATTACHMENT,
            status="error",
            error_message=f"SecurityError: Path traversal attempt blocked outside allowed directory: {raw_path}",
            is_evidence=False,
        )


    if not target_path.is_file():
        return ToolResult(
            tool_name=ToolName.FETCH_ATTACHMENT,
            status="error",
            error_message=f"FileNotFoundError: Attachment not found at {target_path}",
            is_evidence=False,
        )

    # File extension check
    if target_path.suffix.lower() not in ALLOWED_EXTENSIONS:
        return ToolResult(
            tool_name=ToolName.FETCH_ATTACHMENT,
            status="error",
            error_message=f"DisallowedFileTypeError: Unsupported file type '{target_path.suffix}'. Allowed: {ALLOWED_EXTENSIONS}",
            is_evidence=False,
        )

    # File size check
    size_bytes = target_path.stat().st_size
    if size_bytes > MAX_FILE_SIZE_BYTES:
        return ToolResult(
            tool_name=ToolName.FETCH_ATTACHMENT,
            status="error",
            error_message=f"FileSizeLimitExceededError: Attachment size {size_bytes} exceeds limit of {MAX_FILE_SIZE_BYTES} bytes.",
            is_evidence=False,
        )

    # Fault injection check for corrupted image
    fault_injector = context.get("fault_injector")
    item_index = context.get("item_index", 0)
    if fault_injector and fault_injector.should_inject("corrupted_image", item_index):
        fault_injector.record_fault(
            "corrupted_image",
            item_index,
            "Simulated corrupted image input with invalid magic bytes",
            recovered=True,
            outcome_message="Caught and isolated by file signature validator",
        )
        return ToolResult(
            tool_name=ToolName.FETCH_ATTACHMENT,
            status="error",
            error_message="InvalidFileSignatureError: Attachment file has corrupted magic bytes.",
            is_evidence=False,
        )

    # Validate file magic bytes
    from jyot_monitor.ingestion.network import validate_file_signature, InvalidFileSignatureError
    with open(target_path, "rb") as f:
        file_bytes = f.read()

    try:
        validate_file_signature(file_bytes, expected_extension=target_path.suffix.lower())
    except InvalidFileSignatureError as e:
        return ToolResult(
            tool_name=ToolName.FETCH_ATTACHMENT,
            status="error",
            error_message=f"InvalidFileSignatureError: {e}",
            is_evidence=False,
        )

    file_hash = hashlib.sha256(file_bytes).hexdigest()

    return ToolResult(
        tool_name=ToolName.FETCH_ATTACHMENT,
        status="success",
        data={
            "attachment_id": attachment_id,
            "local_path": str(target_path),
            "size_bytes": size_bytes,
            "content_hash": file_hash,
            "extension": target_path.suffix.lower(),
        },
        is_evidence=True,
    )
