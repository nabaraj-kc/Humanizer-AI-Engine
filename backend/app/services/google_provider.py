"""
backend/app/services/google_provider.py
======================================
Google Gemini Free-Tier Client Connector.
Interfaces with Google AI Studio's Gemini 1.5 Flash model asynchronously.
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
import asyncio
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
import sys
from pathlib import Path
import aiohttp

# Resolve project root path
sys.path.append(str(Path(__file__).resolve().parents[3]))

from backend.app.core.config import get_settings
from backend.app.services.base_llm import BaseLLMProvider, ExternalApiThrottleException
from backend.app.db.session import get_async_session

logger = logging.getLogger("humanizer_google_provider")


class GoogleGeminiProvider(BaseLLMProvider):
    """
    Client connector for Google AI Studio's Gemini models.
    """

    def __init__(self, model_name: str = "gemini-1.5-flash"):
        self.settings = get_settings()
        self.model_name = model_name
        self.api_url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model_name}:generateContent"

    async def _update_token_quota(self, tokens_used: int) -> None:
        """Update active usage stats for Google in the quotas database table."""
        try:
            async with get_async_session() as db:
                await db.execute(
                    """
                    UPDATE api_quotas
                    SET used_today = used_today + :tokens_used
                    WHERE provider = 'google'
                    """,
                    {"tokens_used": tokens_used}
                )
                await db.commit()
        except Exception as e:
            logger.error(f"Failed to update token quota in database for google: {e}")

    async def _mark_quota_exhausted(self) -> None:
        """Mark Google quota as fully exhausted (e.g. after a 429 rate-limit response)."""
        try:
            async with get_async_session() as db:
                await db.execute(
                    """
                    UPDATE api_quotas
                    SET used_today = daily_limit
                    WHERE provider = 'google'
                    """
                )
                await db.commit()
                logger.warning("Google quota marked as exhausted in database due to 429 rate-limit.")
        except Exception as e:
            logger.error(f"Failed to mark Google quota exhausted: {e}")

    async def execute_text_rewrite(self, prompt: str, context_chunk: str) -> str:
        """
        Calls Gemini 1.5 Flash asynchronously with the given prompt and context chunk.
        """
        api_key = self.settings.GOOGLE_API_KEY
        if not api_key:
            raise RuntimeError("GOOGLE_API_KEY is not configured in settings.")

        url = f"{self.api_url}?key={api_key}"
        headers = {"Content-Type": "application/json"}
        
        # Build standard Gemini generateContent request payload
        payload = {
            "contents": [
                {
                    "parts": [
                        {"text": f"{prompt}\n\nTarget Content:\n{context_chunk}"}
                    ]
                }
            ],
            "generationConfig": {
                "temperature": 0.85,
                "topP": 0.95
            }
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload, headers=headers) as response:
                    status = response.status

                    # Enforce rate limit (429) and server drop (503) failover rules
                    if status == 429 or status == 503:
                        logger.warning(f"Google Gemini returned throttle status {status}. Raising failover exception.")
                        # Mark quota as exhausted so UI shows 0% remaining
                        await self._mark_quota_exhausted()
                        raise ExternalApiThrottleException(f"Google Gemini throttled: status={status}")

                    if status != 200:
                        err_text = await response.text()
                        logger.error(f"Google Gemini API error: status={status}, response={err_text}")
                        raise RuntimeError(f"Google Gemini API error: status={status}")

                    response_json = await response.json()
                    
                    # Parse contents according to Gemini JSON schema
                    try:
                        text = response_json["candidates"][0]["content"]["parts"][0]["text"]
                    except (KeyError, IndexError) as parse_err:
                        logger.error(f"Failed to parse Gemini response schema: {parse_err}. Raw: {response_json}")
                        raise RuntimeError("Failed to parse Gemini response payload structure.") from parse_err

                    # Track token usage - Gemini returns usageMetadata
                    usage = response_json.get("usageMetadata", {})
                    prompt_tokens = usage.get("promptTokenCount")
                    completion_tokens = usage.get("candidatesTokenCount")
                    if prompt_tokens is None or completion_tokens is None:
                        # Fallback: estimate from character count
                        prompt_tokens = len(prompt) // 4
                        completion_tokens = len(text) // 4
                    total_tokens = prompt_tokens + completion_tokens
                    logger.info(f"Google tokens consumed: prompt={prompt_tokens}, completion={completion_tokens}, total={total_tokens}")
                    await self._update_token_quota(total_tokens)

                    return self.clean_response(text)

        except aiohttp.ClientError as client_err:
            logger.error(f"Aiohttp connection error during Google Gemini request: {client_err}")
            # Network drop acts as server downtime -> trigger failover
            raise ExternalApiThrottleException("Google Gemini network connection failure.") from client_err


# ---------------------------------------------------------------------------
# Stage 23 Verification Guardrail Test
# ---------------------------------------------------------------------------

def run_tests() -> None:
    print("=== Stage 23: Google Gemini Client Connector Verification ===")
    print()

    provider = GoogleGeminiProvider()

    # Define mock response factory to intercept HTTP requests
    class MockClientSession:
        def __init__(self, response_status: int, response_json: dict):
            self.response_status = response_status
            self.response_json = response_json

        def post(self, url: str, json: dict, headers: dict):
            # Inner helper to act as context manager for session.post
            class PostContext:
                def __init__(self, status_code: int, json_data: dict):
                    self.status = status_code
                    self.json_data = json_data

                async def __aenter__(self):
                    return self

                async def __aexit__(self, exc_type, exc_val, exc_tb):
                    pass

                async def json(self):
                    return self.json_data

                async def text(self):
                    return "raw mock response text"
            return PostContext(self.response_status, self.response_json)

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

    # 1. Test 1: Successful response parsing
    print("  --- Test 1: Standard successful API response ---")
    success_payload = {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {"text": "```markdown\nHumanized version text candidate.\n```"}
                    ]
                }
            }
        ]
    }
    
    # Patch ClientSession
    import unittest.mock as mock
    
    async def test_success():
        with mock.patch("aiohttp.ClientSession", return_value=MockClientSession(200, success_payload)):
            res = await provider.execute_text_rewrite("Please rewrite", "Raw text block")
            assert res == "Humanized version text candidate.", f"Expected clean text, got {res}"
            print("  [PASS] Successfully parsed and cleaned Google Gemini response.")

    asyncio.run(test_success())
    print()

    # 2. Test 2: Catch Rate Limit (429) -> raise ExternalApiThrottleException
    print("  --- Test 2: Caught 429 (Rate Limit) -> ExternalApiThrottleException ---")
    async def test_rate_limit():
        with mock.patch("aiohttp.ClientSession", return_value=MockClientSession(429, {})):
            try:
                await provider.execute_text_rewrite("Please rewrite", "Raw text block")
                assert False, "Expected ExternalApiThrottleException"
            except ExternalApiThrottleException as throttle_exc:
                print(f"  [PASS] Correctly raised ExternalApiThrottleException on 429: {throttle_exc}")

    asyncio.run(test_rate_limit())
    print()

    # 3. Test 3: Catch Server Drop (503) -> raise ExternalApiThrottleException
    print("  --- Test 3: Caught 503 (Server Drop) -> ExternalApiThrottleException ---")
    async def test_server_drop():
        with mock.patch("aiohttp.ClientSession", return_value=MockClientSession(503, {})):
            try:
                await provider.execute_text_rewrite("Please rewrite", "Raw text block")
                assert False, "Expected ExternalApiThrottleException"
            except ExternalApiThrottleException as throttle_exc:
                print(f"  [PASS] Correctly raised ExternalApiThrottleException on 503: {throttle_exc}")

    asyncio.run(test_server_drop())
    print()

    print("Stage 23 verification: ALL CHECKS PASSED.")


if __name__ == "__main__":
    run_tests()
