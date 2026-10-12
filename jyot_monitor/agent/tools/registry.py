"""
Tool registry and dispatcher for the agent controller.

Enforces:
1. Allow-listed tool execution.
2. Argument type and boundary validation.
3. Safe execution with structured error returns.
4. Data/instruction separation.
"""

from typing import Any, Callable, Dict, Optional
from jyot_monitor.models import ToolName, ToolResult


class ToolRegistry:
    """Registry of allowed agent tools."""

    def __init__(self):
        self._tools: Dict[ToolName, Callable[[Dict[str, Any], Dict[str, Any]], ToolResult]] = {}

    def register(self, tool_name: ToolName, func: Callable[[Dict[str, Any], Dict[str, Any]], ToolResult]) -> None:
        """Register a handler function for an allowed tool."""
        self._tools[tool_name] = func

    def is_allowed(self, tool_name: str) -> bool:
        """Check if tool name is an allowed ToolName enum member."""
        try:
            name_enum = ToolName(tool_name)
            return name_enum in self._tools
        except ValueError:
            return False

    def execute(
        self,
        tool_name: ToolName,
        arguments: Dict[str, Any],
        context: Dict[str, Any],
    ) -> ToolResult:
        """
        Validate and execute the requested tool with error containment.
        """
        if tool_name not in self._tools:
            return ToolResult(
                tool_name=tool_name,
                status="error",
                error_message=f"DisallowedToolError: Tool '{tool_name}' is not registered or permitted.",
                is_evidence=False,
            )

        handler = self._tools[tool_name]
        try:
            return handler(arguments, context)
        except Exception as e:
            return ToolResult(
                tool_name=tool_name,
                status="error",
                error_message=f"ToolExecutionError in {tool_name.value}: {e}",
                is_evidence=False,
            )


def get_default_tool_registry() -> ToolRegistry:
    """Build and return a ToolRegistry with all registered tool handlers."""
    from jyot_monitor.agent.tools.fetch_attachment import execute_fetch_attachment
    from jyot_monitor.agent.tools.ocr_extract import execute_ocr_extract
    from jyot_monitor.agent.tools.vision_describe import execute_vision_describe
    from jyot_monitor.agent.tools.search_memory import execute_search_memory
    from jyot_monitor.agent.tools.verify_claim import execute_verify_claim
    from jyot_monitor.agent.tools.classify_score import execute_classify_score
    from jyot_monitor.agent.tools.critique_item import execute_critique_item
    from jyot_monitor.agent.tools.propose_alert import execute_propose_alert

    registry = ToolRegistry()
    registry.register(ToolName.FETCH_ATTACHMENT, execute_fetch_attachment)
    registry.register(ToolName.OCR_EXTRACT, execute_ocr_extract)
    registry.register(ToolName.VISION_DESCRIBE, execute_vision_describe)
    registry.register(ToolName.SEARCH_MEMORY, execute_search_memory)
    registry.register(ToolName.VERIFY_CLAIM, execute_verify_claim)
    registry.register(ToolName.CLASSIFY_SCORE, execute_classify_score)
    registry.register(ToolName.CRITIQUE_ITEM, execute_critique_item)
    registry.register(ToolName.PROPOSE_ALERT, execute_propose_alert)
    registry.register(
        ToolName.FINISH,
        lambda args, ctx: ToolResult(tool_name=ToolName.FINISH, status="success", data={"finished": True})
    )
    return registry
