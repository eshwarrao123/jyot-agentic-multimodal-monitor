"""
LLM Client module for local Ollama models and mock adapters.

Implements:
1. Standardized LLMResponse with token and latency tracking.
2. Configurable Ollama adapter using HTTP POST to /api/generate.
3. Strict timeout enforcement, structured JSON mode, and graceful error handling.
4. MockLLMClient for deterministic unit tests and adversarial safety checks.
"""

from dataclasses import dataclass, field
import json
import os
import time
from typing import Any, Dict, List, Optional, Protocol, Union
import urllib.error
import urllib.request


@dataclass
class LLMResponse:
    """Standardized response from an LLM call."""
    content: str
    parsed_json: Optional[Dict[str, Any]] = None
    tokens_in: Optional[int] = None
    tokens_out: Optional[int] = None
    cost_usd: Optional[float] = 0.0  # 0.0 for local models
    latency_ms: Optional[float] = None
    model: str = "unknown"
    error: Optional[str] = None
    is_fallback: bool = False


class BaseLLMClient(Protocol):
    """Protocol for LLM adapters."""
    def generate(
        self,
        prompt: str,
        system: Optional[str] = None,
        json_format: bool = True,
        temperature: float = 0.0,
    ) -> LLMResponse:
        ...


class OllamaClient:
    """
    HTTP client for locally hosted Ollama instances.
    
    Adheres to offline requirements:
    - Only connects to local URL (default: http://localhost:11434).
    - Enforces configurable timeout.
    - Captures actual runtime tokens and latency metrics.
    - Returns structured error on unavailable daemon/model without crashing.
    """
    
    def __init__(
        self,
        model: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout_seconds: Optional[float] = None,
    ):
        self.model = model or os.getenv("JYOT_LLM_MODEL", "qwen2.5:3b")
        self.base_url = (base_url or os.getenv("JYOT_OLLAMA_HOST", "http://localhost:11434")).rstrip("/")
        if timeout_seconds is not None:
            self.timeout_seconds = timeout_seconds
        else:
            self.timeout_seconds = float(os.getenv("JYOT_OLLAMA_TIMEOUT", "60.0"))

    def is_available(self) -> bool:
        """Check if local Ollama daemon is reachable and model is available."""
        url = f"{self.base_url}/api/tags"
        req = urllib.request.Request(url, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=1.5) as resp:
                if resp.status == 200:
                    data = json.loads(resp.read().decode("utf-8"))
                    models = [m.get("name", "") for m in data.get("models", [])]
                    # Check if requested model exists
                    return any(self.model in m or m.startswith(self.model.split(":")[0]) for m in models)
        except Exception:
            return False
        return False

    def generate(
        self,
        prompt: str,
        system: Optional[str] = None,
        json_format: bool = True,
        temperature: float = 0.0,
    ) -> LLMResponse:
        """Send prompt to Ollama /api/generate endpoint."""
        url = f"{self.base_url}/api/generate"
        payload: Dict[str, Any] = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": temperature,
            }
        }
        if system:
            payload["system"] = system
        if json_format:
            payload["format"] = "json"

        start_time = time.perf_counter()
        data_bytes = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data_bytes,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=self.timeout_seconds) as resp:
                elapsed_ms = (time.perf_counter() - start_time) * 1000.0
                resp_body = resp.read().decode("utf-8")
                resp_json = json.loads(resp_body)
                
                raw_text = resp_json.get("response", "").strip()
                tokens_in = resp_json.get("prompt_eval_count")
                tokens_out = resp_json.get("eval_count")
                
                parsed = None
                if json_format and raw_text:
                    try:
                        parsed = json.loads(raw_text)
                    except json.JSONDecodeError:
                        pass

                return LLMResponse(
                    content=raw_text,
                    parsed_json=parsed,
                    tokens_in=tokens_in,
                    tokens_out=tokens_out,
                    cost_usd=0.0,  # Local inference
                    latency_ms=round(elapsed_ms, 2),
                    model=self.model,
                    error=None,
                )

        except urllib.error.URLError as ue:
            elapsed_ms = (time.perf_counter() - start_time) * 1000.0
            return LLMResponse(
                content="",
                parsed_json=None,
                latency_ms=round(elapsed_ms, 2),
                model=self.model,
                error=f"OllamaUnavailable: Connection failed to {url} ({ue.reason})",
            )
        except Exception as e:
            elapsed_ms = (time.perf_counter() - start_time) * 1000.0
            return LLMResponse(
                content="",
                parsed_json=None,
                latency_ms=round(elapsed_ms, 2),
                model=self.model,
                error=f"OllamaExecutionError: {e}",
            )


class MockLLMClient:
    """
    Deterministic mock LLM client for unit tests and safety injection checks.
    """
    def __init__(
        self,
        responses: Optional[List[Union[str, Dict[str, Any]]]] = None,
        model_name: str = "mock-qwen2.5:3b",
    ):
        self.responses = list(responses or [])
        self.call_history: List[Dict[str, Any]] = []
        self.model_name = model_name

    def add_response(self, resp: Union[str, Dict[str, Any]]) -> None:
        """Queue a mock response."""
        self.responses.append(resp)

    def generate(
        self,
        prompt: str,
        system: Optional[str] = None,
        json_format: bool = True,
        temperature: float = 0.0,
    ) -> LLMResponse:
        """Return next queued mock response or a default finish action."""
        self.call_history.append({
            "prompt": prompt,
            "system": system,
            "json_format": json_format,
            "temperature": temperature,
        })

        if self.responses:
            next_resp = self.responses.pop(0)
            if isinstance(next_resp, dict):
                raw_text = json.dumps(next_resp)
                parsed = next_resp
            else:
                raw_text = str(next_resp)
                try:
                    parsed = json.loads(raw_text)
                except Exception:
                    parsed = None

            return LLMResponse(
                content=raw_text,
                parsed_json=parsed,
                tokens_in=50,
                tokens_out=25,
                cost_usd=0.0,
                latency_ms=10.0,
                model=self.model_name,
                error=None,
            )

        # Default fallback action
        default_dict = {
            "action": "finish",
            "rationale": "Default mock finished item processing",
            "arguments": {},
        }
        return LLMResponse(
            content=json.dumps(default_dict),
            parsed_json=default_dict,
            tokens_in=30,
            tokens_out=15,
            cost_usd=0.0,
            latency_ms=5.0,
            model=self.model_name,
            error=None,
        )
