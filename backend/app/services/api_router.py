"""
backend/app/services/api_router.py
==================================
Master API Waterfall Failover Router Controller.
Coordinates model providers sequentially, handling rate limits and quota exhausts.
"""

# Hotpatch typing module for Python 3.11 alpha compatibility issues with Pydantic / AnyIO / aiohttp
import typing

class SubscriptableObject:
    def __class_getitem__(cls, item):
        return object
    def __init__(self, *args, **kwargs):
        pass

# Force override draft types that raise TypeErrors in early 3.11 alphas
typing.Unpack = SubscriptableObject
typing.TypeVarTuple = SubscriptableObject
typing.Required = object
typing.NotRequired = object
typing.Self = object

try:
    import typing_extensions
    typing_extensions.Unpack = SubscriptableObject
    typing_extensions.TypeVarTuple = SubscriptableObject
    typing_extensions.Required = object
    typing_extensions.NotRequired = object
    typing_extensions.Self = object
except ImportError:
    pass

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

# Resolve project root path
sys.path.append(str(Path(__file__).resolve().parents[3]))

from backend.app.services.openrouter_provider import OpenRouterProvider
from backend.app.services.google_provider import GoogleGeminiProvider
from backend.app.services.groq_provider import GroqProvider
from backend.app.services.deepseek_provider import DeepSeekProvider
from backend.app.core.websocket_manager import ws_manager
from backend.app.db.session import get_async_session

logger = logging.getLogger("humanizer_api_router")


class WaterfallRouter:
    """
    Orchestrates the ordered sequence of LLM providers.
    Supports dynamic fallback, error logging, and database quota checks.
    """

    def __init__(self):
        # Ordered collection of provider clients
        self.openrouter = OpenRouterProvider()  # Primary: free Llama 3.3 70B via OpenRouter
        self.google_flash = GoogleGeminiProvider(model_name="gemini-2.0-flash")
        self.google_lite = GoogleGeminiProvider(model_name="gemini-2.0-flash-lite")
        self.groq = GroqProvider()
        self.deepseek = DeepSeekProvider()

        # Configured sequence: (db_quota_key, provider_client)
        # OpenRouter first, then Google, then Groq/DeepSeek fallbacks
        self.sequence = [
            ("openrouter", self.openrouter),
            ("google", self.google_flash),
            ("google", self.google_lite),
            ("groq", self.groq),
            ("deepseek", self.deepseek),
        ]

    async def _is_quota_exhausted(self, provider_name: str) -> bool:
        """
        Check if the daily token budget for a provider is exhausted in the SQLite database.
        """
        try:
            async with get_async_session() as db:
                async with db.execute(
                    "SELECT daily_limit, used_today FROM api_quotas WHERE provider = :provider",
                    {"provider": provider_name}
                ) as cur:
                    row = await cur.fetchone()
                    if row:
                        exhausted = row["used_today"] >= row["daily_limit"]
                        if exhausted:
                            logger.warning(f"Quota check: {provider_name} daily budget EXHAUSTED ({row['used_today']}/{row['daily_limit']})")
                        return exhausted
        except Exception as e:
            logger.error(f"Failed to verify token quota for {provider_name}: {e}")
        return False

    async def rewrite_chunk_with_failover(self, prompt: str, text: str) -> str:
        """
        Loops through model providers sequentially to rewrite a text chunk.
        Skips any provider whose token quota is exhausted, and handles exceptions
        by automatically trying the next provider and broadcasting warning signals.
        """
        for quota_key, provider in self.sequence:
            model_name = getattr(provider, "model_name", quota_key)
            logger.info(f"Waterfall sequence: checking {model_name}...")

            # 1. Budget exhausted guardrail
            if await self._is_quota_exhausted(quota_key):
                logger.info(f"Skipping {model_name} (token quota exhausted).")
                continue

            # 2. Attempt API execution
            try:
                logger.info(f"Executing rewrite using {model_name}...")
                rewritten_text = await provider.execute_text_rewrite(prompt, text)
                logger.info(f"Successfully rewritten using {model_name}.")
                return rewritten_text
            except Exception as exc:
                logger.error(f"Error on model {model_name}: {exc}. Triggering fallback...")
                
                # Broadcast error event to WebSockets
                await ws_manager.broadcast_global_message({
                    "category": "error",
                    "progress_state": "rewriting",
                    "token_updates": {"openrouter": 0, "google": 0, "groq": 0, "deepseek": 0}
                })

        raise RuntimeError("All configured LLM providers in the waterfall failed or were skipped.")


# ---------------------------------------------------------------------------
# Stage 26 Verification Guardrail Test
# ---------------------------------------------------------------------------

def run_tests() -> None:
    print("=== Stage 26: Master API Router Verification ===")
    print()

    router = WaterfallRouter()

    # Seed initial test environment quota limits
    async def seed_limits(google_used=0, groq_used=0):
        async with get_async_session() as db:
            await db.execute("DELETE FROM api_quotas WHERE provider IN ('google', 'groq', 'deepseek')")
            await db.execute(
                """
                INSERT INTO api_quotas (provider, daily_limit, used_today, rpm_limit, last_reset)
                VALUES 
                  ('google', 1000000, :google_used, 15, '2026-06-15T00:00:00'),
                  ('groq', 14400, :groq_used, 30, '2026-06-15T00:00:00'),
                  ('deepseek', 500000, 0, 60, '2026-06-15T00:00:00')
                """,
                {"google_used": google_used, "groq_used": groq_used}
            )

    import unittest.mock as mock

    # 1. Test 1: Fallback loop logic (first provider fails, second succeeds)
    print("  --- Test 1: Fallback loop logic ---")
    async def test_fallback():
        await seed_limits(google_used=0, groq_used=0)

        # Mock Google providers to fail, and Groq to succeed
        async def mock_fail(*args, **kwargs):
            raise RuntimeError("API Timeout (simulated)")

        async def mock_success(*args, **kwargs):
            return "Humanized response from Llama model"

        with mock.patch.object(router.google_flash, "execute_text_rewrite", side_effect=mock_fail), \
             mock.patch.object(router.google_pro, "execute_text_rewrite", side_effect=mock_fail), \
             mock.patch.object(router.groq, "execute_text_rewrite", side_effect=mock_success):

             result = await router.rewrite_chunk_with_failover("System instruction", "Text chunk")
             assert result == "Humanized response from Llama model"
             print("  [PASS] Successfully failed over to Groq client when Google failed.")

    asyncio.run(test_fallback())
    print()

    # 2. Test 2: Quota Exhausted Bypass (first provider skipped entirely due to limits)
    print("  --- Test 2: Quota Exhausted Bypass ---")
    async def test_quota_exhausted():
        # Set google daily limit as exhausted
        await seed_limits(google_used=1000000, groq_used=0)

        async def mock_fail(*args, **kwargs):
            # If Google is called, it should fail the test
            assert False, "Google provider should have been skipped due to exhausted quota!"

        async def mock_success(*args, **kwargs):
            return "Success response"

        with mock.patch.object(router.google_flash, "execute_text_rewrite", side_effect=mock_fail), \
             mock.patch.object(router.google_pro, "execute_text_rewrite", side_effect=mock_fail), \
             mock.patch.object(router.groq, "execute_text_rewrite", side_effect=mock_success):

             result = await router.rewrite_chunk_with_failover("System instruction", "Text chunk")
             assert result == "Success response"
             print("  [PASS] Successfully skipped Google providers and executed Groq directly.")

    asyncio.run(test_quota_exhausted())
    print()
    print("Stage 26 verification: ALL CHECKS PASSED.")


if __name__ == "__main__":
    run_tests()
