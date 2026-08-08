"""
backend/app/services/deepseek_provider.py
========================================
DeepSeek Deep Reasoning Client Connector.
Interfaces with DeepSeek's chat and reasoning models asynchronously.
"""

# Hotpatch typing module for Python 3.11 alpha compatibility issues with Pydantic / AnyIO / aiohttp
import typing
if not hasattr(typing, "Required"):
    typing.Required = object
if not hasattr(typing, "NotRequired"):
    typing.NotRequired = object
if not hasattr(typing, "TypeVarTuple"):
    class DummyTypeVarTuple:
        def __init__(self, *args, **kwargs):
            pass
    typing.TypeVarTuple = DummyTypeVarTuple
if not hasattr(typing, "Unpack"):
    class SubscriptableObject:
        def __class_getitem__(cls, item):
            return object
    typing.Unpack = SubscriptableObject
if not hasattr(typing, "Self"):
    typing.Self = object

# Hotpatch asyncio.Timeout for aiohttp compatibility in Python 3.11 alpha
import asyncio
if not hasattr(asyncio, "Timeout"):
    class Timeout:
        def __init__(self, deadline):
            self.deadline = deadline
        def __enter__(self):
            return self
        def __exit__(self, exc_type, exc_val, exc_tb):
            pass
        def when(self):
            return self.deadline
        def reschedule(self, when):
            self.deadline = when
        def expired(self):
            return False
    asyncio.Timeout = Timeout

# Hotpatch asyncio.current_task for Python 3.11 alpha compatibility issues with anyio's cancel scope
import asyncio.tasks
_real_current_task = asyncio.current_task

class TaskWrapper:
    def __init__(self, task):
        self.__dict__['_task'] = task
    def __getattr__(self, name):
        if name == 'uncancel':
            return getattr(self._task, 'uncancel', lambda: getattr(self._task, '_cancelling', 0))
        if name == 'cancelling':
            return getattr(self._task, 'cancelling', lambda: getattr(self._task, '_cancelling', 0))
        return getattr(self._task, name)
    def __setattr__(self, name, value):
        setattr(self._task, name, value)
    @property
    def __class__(self):
        return self._task.__class__
    def __eq__(self, other):
        if isinstance(other, TaskWrapper):
            return self._task is other._task
        return self._task is other
    def __hash__(self):
        return hash(self._task)

def wrapped_current_task(loop=None):
    t = _real_current_task(loop)
    if t is None:
        return None
    if isinstance(t, TaskWrapper):
        return t
    if hasattr(t, "_wrapper"):
        return t._wrapper
    
    wrapper = TaskWrapper(t)
    try:
        t._wrapper = wrapper
    except Exception:
        pass
    return wrapper

asyncio.current_task = wrapped_current_task
asyncio.tasks.current_task = wrapped_current_task

import logging
import re
import sys
from pathlib import Path
import aiohttp

# Resolve project root path
sys.path.append(str(Path(__file__).resolve().parents[3]))

from backend.app.core.config import get_settings
from backend.app.services.base_llm import BaseLLMProvider, ExternalApiThrottleException
from backend.app.db.session import get_async_session

logger = logging.getLogger("humanizer_deepseek_provider")


class DeepSeekProvider(BaseLLMProvider):
    """
    Client connector for DeepSeek API endpoints.
    Handles final response parsing, stripping out chain-of-thought blocks.
    """

    def __init__(self):
        self.settings = get_settings()
        self.model_name = "deepseek-chat"
        self.api_url = "https://api.deepseek.com/chat/completions"

    async def _update_token_quota(self, tokens_used: int) -> None:
        """Update active usage stats for DeepSeek in the quotas database table."""
        try:
            async with get_async_session() as db:
                await db.execute(
                    """
                    UPDATE api_quotas
                    SET used_today = used_today + :tokens_used
                    WHERE provider = 'deepseek'
                    """,
                    {"tokens_used": tokens_used}
                )
                await db.commit()
        except Exception as e:
            logger.error(f"Failed to update token quota in database for deepseek: {e}")

    async def _mark_quota_exhausted(self) -> None:
        """Mark DeepSeek quota as fully exhausted (e.g. after a 429 rate-limit response)."""
        try:
            async with get_async_session() as db:
                await db.execute(
                    """
                    UPDATE api_quotas
                    SET used_today = daily_limit
                    WHERE provider = 'deepseek'
                    """
                )
                await db.commit()
                logger.warning("DeepSeek quota marked as exhausted in database due to 429 rate-limit.")
        except Exception as e:
            logger.error(f"Failed to mark DeepSeek quota exhausted: {e}")

    def strip_reasoning(self, text: str) -> str:
        """
        Strips internal reasoning/chain-of-thought blocks wrapped in <think>...</think> tags.
        Safely matches multi-line patterns and parses nested content without cutoffs.
        """
        if not text:
            return ""
        # Match <think>...</think> tag case-insensitively and multi-line
        cleaned = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL | re.IGNORECASE)
        return cleaned.strip()

    async def execute_text_rewrite(self, prompt: str, context_chunk: str) -> str:
        """
        Executes a rewrite request using DeepSeek completions asynchronously.
        """
        api_key = self.settings.DEEPSEEK_API_KEY
        if not api_key:
            raise RuntimeError("DEEPSEEK_API_KEY is not configured in settings.")

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }

        # Build DeepSeek request payload (chat completion standard)
        payload = {
            "model": self.model_name,
            "messages": [
                {
                    "role": "system",
                    "content": prompt
                },
                {
                    "role": "user",
                    "content": context_chunk
                }
            ],
            "temperature": 0.85,
            "top_p": 0.95
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(self.api_url, json=payload, headers=headers) as response:
                    status = response.status

                    # Enforce rate limit (429) and server drop (503) failover rules
                    if status == 429 or status == 503:
                        logger.warning(f"DeepSeek provider throttled with status {status}. Raising failover exception.")
                        # Mark quota as exhausted so UI shows 0% remaining
                        await self._mark_quota_exhausted()
                        raise ExternalApiThrottleException(f"DeepSeek API throttled: status={status}")

                    if status != 200:
                        err_text = await response.text()
                        logger.error(f"DeepSeek API error: status={status}, response={err_text}")
                        raise RuntimeError(f"DeepSeek API error: status={status}")

                    response_json = await response.json()

                    # Extract content
                    try:
                        message_obj = response_json["choices"][0]["message"]
                        text = message_obj.get("content") or ""
                    except (KeyError, IndexError) as parse_err:
                        logger.error(f"Failed to parse DeepSeek response content: {parse_err}. JSON: {response_json}")
                        raise RuntimeError("Failed to parse DeepSeek response payload structure.") from parse_err

                    # Enforce reasoning cleanups:
                    # 1. Ignore API-level reasoning_content if returned
                    # 2. Strip inline <think> tags from text content
                    clean_text = self.strip_reasoning(text)

                    # Extract usage metrics
                    usage = response_json.get("usage", {})
                    prompt_tokens = usage.get("prompt_tokens")
                    completion_tokens = usage.get("completion_tokens")

                    if prompt_tokens is None or completion_tokens is None:
                        logger.warning("DeepSeek usage metadata missing. Applying fallback token estimation.")
                        prompt_tokens = len(prompt) // 4
                        completion_tokens = len(clean_text) // 4

                    total_tokens = prompt_tokens + completion_tokens
                    logger.info(f"DeepSeek tokens consumed: prompt={prompt_tokens}, completion={completion_tokens}, total={total_tokens}")

                    # Save usage metrics to SQLite
                    await self._update_token_quota(total_tokens)

                    return self.clean_response(clean_text)

        except aiohttp.ClientError as client_err:
            logger.error(f"Aiohttp connection error during DeepSeek API request: {client_err}")
            raise ExternalApiThrottleException("DeepSeek network connection failure.") from client_err


# ---------------------------------------------------------------------------
# Stage 25 Verification Guardrail Test
# ---------------------------------------------------------------------------

def run_tests() -> None:
    print("=== Stage 25: DeepSeek Client Connector Verification ===")
    print()

    provider = DeepSeekProvider()

    # 1. Test strip_reasoning parser method
    print("  --- Test 1: Strip reasoning tags (<think>...</think>) ---")
    reasoning_text = (
        "<think>\n"
        "Let's analyze the input block.\n"
        "The tone is too academic. We should add perplexity.\n"
        "Wait, the coordinates need to stay unchanged.\n"
        "</think>\n"
        "This is the actual final response text."
    )
    result = provider.strip_reasoning(reasoning_text)
    assert result == "This is the actual final response text."
    print("  [PASS] Successfully stripped reasoning block and isolated final text.")

    # 2. Test response payload mock containing reasoning fields
    print("  --- Test 2: Mock API response with reasoning_content and <think> ---")
    mock_payload = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": "<THINK>Thinking logic</THINK>\n```markdown\nClean humanized text.\n```",
                    "reasoning_content": "Chain of thought logic"
                }
            }
        ],
        "usage": {
            "prompt_tokens": 100,
            "completion_tokens": 50,
            "total_tokens": 150
        }
    }

    class MockClientSession:
        def post(self, url: str, json: dict, headers: dict):
            class PostContext:
                def __init__(self):
                    self.status = 200
                async def __aenter__(self):
                    return self
                async def __aexit__(self, exc_type, exc_val, exc_tb):
                    pass
                async def json(self):
                    return mock_payload
                async def text(self):
                    return "raw text"
            return PostContext()

        async def __aenter__(self):
            return self
        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

    import unittest.mock as mock

    async def test_api_parsing():
        async with get_async_session() as db:
            async with db.execute("SELECT used_today FROM api_quotas WHERE provider = 'deepseek'") as cur:
                row = await cur.fetchone()
                baseline = row["used_today"] if row else 0

        with mock.patch("aiohttp.ClientSession", return_value=MockClientSession()):
            res = await provider.execute_text_rewrite("Prompt", "Original")
            assert res == "Clean humanized text."
            print("  [PASS] Extracted clean text, ignored reasoning_content, and stripped <think> and markdown tags.")

        # Check DB update
        async with get_async_session() as db:
            async with db.execute("SELECT used_today FROM api_quotas WHERE provider = 'deepseek'") as cur:
                row = await cur.fetchone()
                new_used = row["used_today"] if row else 0
                assert new_used == baseline + 150
                print(f"  [PASS] DB quota update verified: baseline={baseline} -> new={new_used}")

    asyncio.run(test_api_parsing())
    print()
    print("Stage 25 verification: ALL CHECKS PASSED.")


if __name__ == "__main__":
    run_tests()
