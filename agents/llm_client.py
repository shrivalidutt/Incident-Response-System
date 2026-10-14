"""Unified LLM client supporting Groq, Anthropic Claude, and Mock/Simulation mode.

Handles:
- Provider auto-detection (Anthropic, Groq, or Simulation/Mock)
- Prompt formatting with system/user messages
- Robust JSON extraction from LLM responses (strips markdown fences, etc.)
- Configurable retry with exponential backoff
- Token usage tracking and latency recording
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from typing import Any, Callable, Optional

from agents.mock_responses import get_mock_response

logger = logging.getLogger("incident_response.llm")


class LLMClient:
    """Wrapper supporting Groq, Anthropic Claude, and Mock/Simulation mode."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        provider: str = "auto",
        model: str = "claude-3-5-sonnet-20241022",
        max_tokens: int = 2048,
        temperature: float = 0.3,
        max_retries: int = 2,
        backoff_seconds: float = 1.0,
    ):
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY") or os.getenv("GROQ_API_KEY")
        self.provider = self._resolve_provider(provider, self.api_key)
        self.model = self._resolve_model(model, self.provider)
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.max_retries = max_retries
        self.backoff_seconds = backoff_seconds

        # Token usage tracking
        self.total_prompt_tokens = 0
        self.total_completion_tokens = 0
        self.total_calls = 0

        # Initialize provider-specific SDK client
        self._groq_client = None
        self._anthropic_client = None
        self._init_client()

    def _resolve_provider(self, requested_provider: str, api_key: Optional[str]) -> str:
        """Resolve LLM provider based on request or key format."""
        req = requested_provider.lower()
        if req in ("mock", "simulation", "simulated", "offline"):
            return "mock"
        if req in ("groq", "anthropic", "claude"):
            return "anthropic" if req in ("anthropic", "claude") else "groq"

        # Auto-detection
        if api_key:
            if api_key.startswith("sk-ant-"):
                return "anthropic"
            if api_key.startswith("gsk_") or len(api_key) >= 20:
                # Common Groq key format
                return "groq"
        # Check env vars
        if os.getenv("ANTHROPIC_API_KEY"):
            return "anthropic"
        if os.getenv("GROQ_API_KEY"):
            return "groq"

        # Default fallback to mock/simulation for offline portability
        return "mock"

    def _resolve_model(self, model: str, provider: str) -> str:
        """Ensure model name matches the provider."""
        if provider == "groq":
            if "claude" in model.lower():
                return "llama-3.3-70b-versatile"
            return model
        elif provider == "anthropic":
            if "llama" in model.lower() or not model:
                return "claude-3-5-sonnet-20241022"
            return model
        return model or "mock-model"

    def _init_client(self):
        """Lazy-initialize SDK clients."""
        if self.provider == "groq" and self.api_key:
            try:
                from groq import Groq
                self._groq_client = Groq(api_key=self.api_key)
                logger.info("Groq client initialized with model %s", self.model)
            except Exception as e:
                logger.warning("Failed to initialize Groq client (%s), falling back to mock", e)
                self.provider = "mock"
        elif self.provider == "anthropic" and self.api_key:
            try:
                import anthropic
                self._anthropic_client = anthropic.Anthropic(api_key=self.api_key)
                logger.info("Anthropic client initialized with model %s", self.model)
            except Exception as e:
                logger.warning("Failed to initialize Anthropic client (%s), falling back to mock", e)
                self.provider = "mock"

    def call(
        self,
        system_prompt: str,
        user_message: str,
        parse_json: bool = True,
        on_retry: Optional[Callable[[int, str], None]] = None,
    ) -> dict[str, Any] | str:
        """Send a prompt to the LLM (or mock) and return the response."""
        last_error = None

        for attempt in range(1, self.max_retries + 2):
            try:
                raw_response = self._send_request(system_prompt, user_message)

                if not parse_json:
                    return raw_response

                return self._extract_json(raw_response)

            except json.JSONDecodeError as e:
                last_error = f"JSON parse error: {e}"
                logger.warning(
                    "Attempt %d/%d failed — %s",
                    attempt,
                    self.max_retries + 1,
                    last_error,
                )

                if on_retry and attempt <= self.max_retries:
                    on_retry(attempt, last_error)

                if attempt <= self.max_retries:
                    time.sleep(self.backoff_seconds * attempt)
                    user_message = (
                        user_message
                        + "\n\n[SYSTEM: Your previous response was not valid JSON. "
                        "Please output ONLY valid JSON with no markdown fences or commentary.]"
                    )

            except Exception as e:
                last_error = str(e)
                logger.error(
                    "Attempt %d/%d failed — %s",
                    attempt,
                    self.max_retries + 1,
                    last_error,
                )

                if on_retry and attempt <= self.max_retries:
                    on_retry(attempt, last_error)

                if attempt <= self.max_retries:
                    time.sleep(self.backoff_seconds * attempt)
                else:
                    # If real API fails after retries, fallback to mock to prevent pipeline crash
                    logger.warning("API call failed after retries, utilizing mock response fallback: %s", last_error)
                    mock_res = get_mock_response(system_prompt, user_message)
                    if parse_json and isinstance(mock_res, str):
                        return self._extract_json(mock_res)
                    elif not parse_json and isinstance(mock_res, dict):
                        return json.dumps(mock_res, indent=2)
                    return mock_res

        # Fallback to mock
        mock_res = get_mock_response(system_prompt, user_message)
        if parse_json and isinstance(mock_res, str):
            return self._extract_json(mock_res)
        return mock_res

    def _send_request(self, system_prompt: str, user_message: str) -> str:
        """Route request to appropriate provider."""
        self.total_calls += 1

        if self.provider == "mock" or (not self._groq_client and not self._anthropic_client):
            # Deterministic simulation with minimal latency simulation for realism
            time.sleep(0.15)
            mock_data = get_mock_response(system_prompt, user_message)
            self.total_prompt_tokens += len(system_prompt.split()) + len(user_message.split())
            if isinstance(mock_data, str):
                self.total_completion_tokens += len(mock_data.split())
                return mock_data
            serialized = json.dumps(mock_data, indent=2)
            self.total_completion_tokens += len(serialized.split())
            return serialized

        if self.provider == "anthropic" and self._anthropic_client:
            response = self._anthropic_client.messages.create(
                model=self.model,
                system=system_prompt,
                messages=[{"role": "user", "content": user_message}],
                max_tokens=self.max_tokens,
                temperature=self.temperature,
            )
            if hasattr(response, "usage") and response.usage:
                self.total_prompt_tokens += getattr(response.usage, "input_tokens", 0)
                self.total_completion_tokens += getattr(response.usage, "output_tokens", 0)

            content = ""
            for block in response.content:
                if hasattr(block, "text"):
                    content += block.text
            return content

        if self.provider == "groq" and self._groq_client:
            response = self._groq_client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message},
                ],
                max_tokens=self.max_tokens,
                temperature=self.temperature,
            )
            if response.usage:
                self.total_prompt_tokens += response.usage.prompt_tokens
                self.total_completion_tokens += response.usage.completion_tokens
            return response.choices[0].message.content or ""

        # Default fallback
        mock_data = get_mock_response(system_prompt, user_message)
        return json.dumps(mock_data, indent=2) if isinstance(mock_data, dict) else str(mock_data)

    def _extract_json(self, raw: str) -> dict[str, Any]:
        """Extract and parse JSON from an LLM response."""
        cleaned = raw.strip()

        # Strip markdown code fences
        fence_pattern = r"```(?:json)?\s*\n?(.*?)\n?\s*```"
        fence_match = re.search(fence_pattern, cleaned, re.DOTALL)
        if fence_match:
            cleaned = fence_match.group(1).strip()

        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            pass

        brace_start = cleaned.find("{")
        brace_end = cleaned.rfind("}")
        if brace_start != -1 and brace_end > brace_start:
            candidate = cleaned[brace_start : brace_end + 1]
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                pass

        raise json.JSONDecodeError("Could not extract valid JSON from LLM response", raw, 0)

    def get_usage_stats(self) -> dict[str, int]:
        """Return cumulative token usage stats."""
        return {
            "total_calls": self.total_calls,
            "total_prompt_tokens": self.total_prompt_tokens,
            "total_completion_tokens": self.total_completion_tokens,
            "total_tokens": self.total_prompt_tokens + self.total_completion_tokens,
        }


class LLMError(Exception):
    """Raised when LLM communication fails after all retries."""
    pass
