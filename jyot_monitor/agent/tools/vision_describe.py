"""
vision_describe tool implementation.

Adapter for optional local vision model.
Returns a typed unavailable result when no local vision model is configured OR when
no genuine adapter implementation exists for the configured model.

Security: this tool must never fabricate a description and attribute it to a model
that did not actually process the image.  Hard-coded descriptions are forbidden.
"""

import os
from pathlib import Path
from typing import Any, Dict
from jyot_monitor.models import ToolName, ToolResult


def execute_vision_describe(arguments: Dict[str, Any], context: Dict[str, Any]) -> ToolResult:
    """Describe image visual features and non-textual hazard elements.

    Returns:
        ToolResult with status="unavailable" when no vision model is configured
        or when the configured model does not have a real adapter.
        ToolResult with status="error" when the image file cannot be found.
    """
    vision_model = os.getenv("JYOT_VISION_MODEL")
    local_path = arguments.get("local_path")

    # Resolve path from completed fetch_attachment if not directly supplied
    if not local_path:
        fetch_res = context.get("completed_tool_data", {}).get("fetch_attachment")
        if fetch_res and fetch_res.get("local_path"):
            local_path = fetch_res["local_path"]

    if not vision_model:
        return ToolResult(
            tool_name=ToolName.VISION_DESCRIBE,
            status="unavailable",
            data={
                "description": None,
                "visual_hazard_detected": False,
                "model_configured": False,
            },
            error_message=(
                "VisionModelUnavailable: No local vision model configured "
                "(JYOT_VISION_MODEL unset). Continuing without vision description."
            ),
            is_evidence=False,
        )

    # Model is configured — check file existence before proceeding
    if not local_path or not Path(local_path).is_file():
        return ToolResult(
            tool_name=ToolName.VISION_DESCRIBE,
            status="error",
            error_message=f"FileNotFoundError: Target image not found at '{local_path}'.",
            is_evidence=False,
        )

    # A model name is configured but no genuine local adapter is implemented yet.
    # Return an honest unavailable result rather than a fabricated description.
    return ToolResult(
        tool_name=ToolName.VISION_DESCRIBE,
        status="unavailable",
        data={
            "description": None,
            "visual_hazard_detected": False,
            "model_configured": True,
            "model_name": vision_model,
            "reason": "not_implemented",
        },
        error_message=(
            f"VisionModelNotImplemented: Model '{vision_model}' is configured but no "
            "real local adapter is available. Install and configure a supported vision "
            "model adapter before using vision_describe."
        ),
        is_evidence=False,
    )
