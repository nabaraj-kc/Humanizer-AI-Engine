"""
backend/app/services/groq_provider.py
====================================
Groq Cloud LPU Client Connector.
Interfaces with Groq Cloud's Llama models asynchronously.
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
import sys
from pathlib import Path
import aiohttp

# Resolve project root path
sys.path.append(str(Path(__file__).resolve().parents[3]))

from backend.app.core.config import get_settings
from backend.app.services.base_llm import BaseLLMProvider, ExternalApiThrottleException
from backend.app.db.session import get_async_session

logger = logging.getLogger("humanizer_groq_provider")


class GroqProvider(BaseLLMProvider):
    """
    Client connector for Groq Cloud API LPU endpoints.
    """

    def __init__(self):
        self.settings = get_settings()
        self.model_name = "llama-3.3-70b-versatile"
        self.api_url = "https://api.groq.com/openai/v1/chat/completions"

    async def _update_token_quota(self, tokens_used: int) -> None:
        """Update active usage stats for Groq in the quotas database table."""
        try:
            async with get_async_session() as db:
                await db.execute(
                    """
                    UPDATE api_quotas
                    SET used_today = used_today + :tokens_used
                    WHERE provider = 'groq'
                    """,
                    {"tokens_used": tokens_used}
                )
                await db.commit()
        except Exception as e:
            logger.error(f"Failed to update token quota in database for groq: {e}")

    async def _mark_quota_exhausted(self) -> None:
        """Mark Groq quota as fully exhausted (e.g. after a 429 rate-limit response)."""
        try:
            async with get_async_session() as db:
                await db.execute(
                    """
                    UPDATE api_quotas
                    SET used_today = daily_limit
                    WHERE provider = 'groq'
                    """
                )
                await db.commit()
                logger.warning("Groq quota marked as exhausted in database due to 429 rate-limit.")
        except Exception as e:
            logger.error(f"Failed to mark Groq quota exhausted: {e}")

    async def execute_text_rewrite(self, prompt: str, context_chunk: str) -> str:
        """
        Executes a rewrite request using Groq Cloud API completions asynchronously.
        """
        api_key = self.settings.GROQ_API_KEY
        if not api_key:
            raise RuntimeError("GROQ_API_KEY is not configured in settings.")

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }

        # Build standard OpenAI-compatible chat completion payload
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

                    # Intercept rate limiting (429) or service outages (503)
                    if status == 429 or status == 503:
                        logger.warning(f"Groq provider throttled with status {status}. Raising failover exception.")
                        # Mark quota as exhausted so UI shows 0% remaining
                        await self._mark_quota_exhausted()
                        raise ExternalApiThrottleException(f"Groq API throttled: status={status}")

                    if status != 200:
                        err_text = await response.text()
                        logger.error(f"Groq API error: status={status}, response={err_text}")
                        raise RuntimeError(f"Groq API error: status={status}")

                    response_json = await response.json()

                    # Extract rewritten message content
                    try:
                        text = response_json["choices"][0]["message"]["content"]
                    except (KeyError, IndexError) as parse_err:
                        logger.error(f"Failed to parse Groq response content: {parse_err}. JSON: {response_json}")
                        raise RuntimeError("Failed to parse Groq response payload structure.") from parse_err

                    # Compulsory Guardrail: Extract token metrics, fall back to estimates if missing
                    usage = response_json.get("usage", {})
                    prompt_tokens = usage.get("prompt_tokens")
                    completion_tokens = usage.get("completion_tokens")

                    if prompt_tokens is None or completion_tokens is None:
                        logger.warning("Groq usage metadata missing. Applying fallback token estimation.")
                        # Standard fallback rule: 1 token ~ 4 characters
                        prompt_tokens = len(prompt) // 4
                        completion_tokens = len(text) // 4

                    total_tokens = prompt_tokens + completion_tokens
                    logger.info(f"Groq tokens consumed: prompt={prompt_tokens}, completion={completion_tokens}, total={total_tokens}")

                    # Persist usage to the database
                    await self._update_token_quota(total_tokens)

                    return self.clean_response(text)

        except aiohttp.ClientError as client_err:
            logger.error(f"Aiohttp connection error during Groq API request: {client_err}")
            raise ExternalApiThrottleException("Groq network connection failure.") from client_err


# ---------------------------------------------------------------------------
# Stage 24 Verification Guardrail Test
# ---------------------------------------------------------------------------

def run_tests() -> None:
    print("=== Stage 24: Groq Client Connector Verification ===")
    print()

    provider = GroqProvider()

    # Define mock response factory to intercept HTTP requests
    class MockClientSession:
        def __init__(self, response_status: int, response_json: dict):
            self.response_status = response_status
            self.response_json = response_json

        def post(self, url: str, json: dict, headers: dict):
            # Assert headers match Groq spec
            assert headers["Authorization"].startswith("Bearer "), "Missing Authorization header"
            # Assert payload matches Groq chat completion schema
            assert json["model"] == "llama-3.1-70b-versatile"
            assert len(json["messages"]) == 2
            assert json["messages"][0]["role"] == "system"
            assert json["messages"][1]["role"] == "user"

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

    import unittest.mock as mock

    # 1. Test 1: Standard successful response with usage tokens
    print("  --- Test 1: Successful response parsing and quota tracking ---")
    success_payload = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": "```\nHumanized text output from Llama model.\n```"
                }
            }
        ],
        "usage": {
            "prompt_tokens": 120,
            "completion_tokens": 30,
            "total_tokens": 150
        }
    }

    async def test_success():
        # Get baseline used_today
        async with get_async_session() as db:
            async with db.execute("SELECT used_today FROM api_quotas WHERE provider = 'groq'") as cur:
                row = await cur.fetchone()
                baseline = row["used_today"] if row else 0

        with mock.patch("aiohttp.ClientSession", return_value=MockClientSession(200, success_payload)):
            res = await provider.execute_text_rewrite("System instructions", "User content chunk")
            assert res == "Humanized text output from Llama model."
            print("  [PASS] Parsed text cleanly and stripped code blocks.")

        # Confirm database was updated by 150 tokens
        async with get_async_session() as db:
            async with db.execute("SELECT used_today FROM api_quotas WHERE provider = 'groq'") as cur:
                row = await cur.fetchone()
                new_used = row["used_today"] if row else 0
                assert new_used == baseline + 150, f"Expected {baseline + 150}, got {new_used}"
                print(f"  [PASS] Quota usage tracked in DB: baseline={baseline} -> new={new_used}")

    asyncio.run(test_success())
    print()

    # 2. Test 2: Successful response with missing usage statistics -> fallback estimation
    print("  --- Test 2: Fallback token estimation check ---")
    payload_missing_usage = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": "Est text."
                }
            }
        ]
        # usage is missing
    }

    async def test_fallback():
        async with get_async_session() as db:
            async with db.execute("SELECT used_today FROM api_quotas WHERE provider = 'groq'") as cur:
                row = await cur.fetchone()
                baseline = row["used_today"] if row else 0

        prompt = "System prompt instruction"
        chunk = "Est text."

        with mock.patch("aiohttp.ClientSession", return_value=MockClientSession(200, payload_missing_usage)):
            res = await provider.execute_text_rewrite(prompt, chunk)
            assert res == "Est text."

        expected_fallback = (len(prompt) // 4) + (len(res) // 4)
        async with get_async_session() as db:
            async with db.execute("SELECT used_today FROM api_quotas WHERE provider = 'groq'") as cur:
                row = await cur.fetchone()
                new_used = row["used_today"] if row else 0
                assert new_used == baseline + expected_fallback
                print(f"  [PASS] Missing metadata fallback calculated tokens cleanly: +{expected_fallback} tokens.")

    asyncio.run(test_fallback())
    print()

    # 3. Test 3: Catch 429 Throttle Exception
    print("  --- Test 3: Rate Limiting (429) -> ExternalApiThrottleException ---")
    async def test_throttle():
        with mock.patch("aiohttp.ClientSession", return_value=MockClientSession(429, {})):
            try:
                await provider.execute_text_rewrite("System prompt", "Content chunk")
                assert False, "Expected ExternalApiThrottleException"
            except ExternalApiThrottleException as throttle_exc:
                print(f"  [PASS] Raised expected ExternalApiThrottleException on 429: {throttle_exc}")

    asyncio.run(test_throttle())
    print()

    print("Stage 24 verification: ALL CHECKS PASSED.")


if __name__ == "__main__":
    run_tests()
