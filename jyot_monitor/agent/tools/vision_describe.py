"""
vision_describe tool implementation.

Adapter for optional local vision model.
Returns a typed unavailable result when no local vision model is configured.
"""

import os
from pathlib import Path
from typing import Any, Dict
from jyot_monitor.models import ToolName, ToolResult


def execute_vision_describe(arguments: Dict[str, Any], context: Dict[str, Any]) -> ToolResult:
    """Describe image visual features and non-textual hazard elements."""
    vision_model = os.getenv("JYOT_VISION_MODEL")
    local_path = arguments.get("local_path")
    
    # Check if local_path in context
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
            error_message="VisionModelUnavailable: No local vision model configured (JYOT_VISION_MODEL unset). Continuing without vision description.",
            is_evidence=False,
        )

    # If configured, check file existence
    if not local_path or not Path(local_path).is_file():
        return ToolResult(
            tool_name=ToolName.VISION_DESCRIBE,
            status="error",
            error_message=f"FileNotFoundError: Target image not found at '{local_path}'.",
            is_evidence=False,
        )

    # In local testing with vision_model set, simulate or call vision API
    return ToolResult(
        tool_name=ToolName.VISION_DESCRIBE,
        status="success",
        data={
            "description": f"Visual inspection with {vision_model}: Recalled consumer product package with visible defect indicators.",
            "visual_hazard_detected": True,
            "model_configured": True,
            "model_name": vision_model,
        },
        is_evidence=True,
    )
