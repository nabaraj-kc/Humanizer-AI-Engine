"""
backend/app/services/openrouter_provider.py
===========================================
OpenRouter API Client Connector.
OpenRouter provides a unified OpenAI-compatible API that routes to many
models (Claude, GPT-4, Llama, Mistral, etc.) with a single API key.
Used as the primary provider in the WaterfallRouter.
"""

import typing
if not hasattr(typing, "Required"):
    typing.Required = object
if not hasattr(typing, "NotRequired"):
    typing.NotRequired = object
if not hasattr(typing, "TypeVarTuple"):
    typing.TypeVarTuple = object
if not hasattr(typing, "Unpack"):
    typing.Unpack = object
if not hasattr(typing, "Self"):
    typing.Self = object

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

sys.path.append(str(Path(__file__).resolve().parents[3]))

from backend.app.core.config import get_settings
from backend.app.services.base_llm import BaseLLMProvider, ExternalApiThrottleException
from backend.app.db.session import get_async_session

logger = logging.getLogger("humanizer_openrouter_provider")


class OpenRouterProvider(BaseLLMProvider):
    """
    Client connector for OpenRouter — a unified API gateway to hundreds of LLMs.
    Uses OpenAI-compatible chat completions endpoint.
    Default model: meta-llama/llama-3.3-70b-instruct (free tier available).
    """

    def __init__(self, model_name: str = None):
        self.settings = get_settings()
        import os
        self.model_name = model_name or os.environ.get("OPENROUTER_MODEL") or "meta-llama/llama-3.3-70b-instruct"
        self.api_url = "https://openrouter.ai/api/v1/chat/completions"

    async def _update_token_quota(self, tokens_used: int) -> None:
        """Update active usage stats for OpenRouter in the quotas database table."""
        try:
            async with get_async_session() as db:
                await db.execute(
                    """
                    UPDATE api_quotas
                    SET used_today = used_today + :tokens_used
                    WHERE provider = 'openrouter'
                    """,
                    {"tokens_used": tokens_used}
                )
                await db.commit()
        except Exception as e:
            logger.error(f"Failed to update token quota in database for openrouter: {e}")

    async def _mark_quota_exhausted(self) -> None:
        """Mark OpenRouter quota as fully exhausted (e.g. after a 429 rate-limit response)."""
        try:
            async with get_async_session() as db:
                await db.execute(
                    """
                    UPDATE api_quotas
                    SET used_today = daily_limit
                    WHERE provider = 'openrouter'
                    """
                )
                await db.commit()
                logger.warning("OpenRouter quota marked as exhausted due to 429 rate-limit.")
        except Exception as e:
            logger.error(f"Failed to mark OpenRouter quota exhausted: {e}")

    async def execute_text_rewrite(self, prompt: str, context_chunk: str) -> str:
        """
        Executes a rewrite request using OpenRouter's OpenAI-compatible API.
        """
        api_key = self.settings.OPENROUTER_API_KEY
        if not api_key:
            raise RuntimeError("OPENROUTER_API_KEY is not configured in settings.")

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://humanizer-ai.local",  # Required by OpenRouter
            "X-Title": "Humanizer AI Engine",
        }

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
            "top_p": 0.95,
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self.api_url,
                    json=payload,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=60)
                ) as response:
                    status = response.status

                    # Rate limit / server overload
                    if status == 429 or status == 503:
                        logger.warning(f"OpenRouter throttled with status {status}. Raising failover exception.")
                        await self._mark_quota_exhausted()
                        raise ExternalApiThrottleException(f"OpenRouter throttled: status={status}")

                    if status != 200:
                        err_text = await response.text()
                        logger.error(f"OpenRouter API error: status={status}, response={err_text[:500]}")
                        raise RuntimeError(f"OpenRouter API error: status={status}")

                    response_json = await response.json()

                    # Extract content (OpenAI-compatible format)
                    try:
                        text = response_json["choices"][0]["message"]["content"]
                    except (KeyError, IndexError) as parse_err:
                        logger.error(f"Failed to parse OpenRouter response: {parse_err}. JSON: {response_json}")
                        raise RuntimeError("Failed to parse OpenRouter response payload.") from parse_err

                    # Track token usage
                    usage = response_json.get("usage", {})
                    prompt_tokens = usage.get("prompt_tokens", len(prompt) // 4)
                    completion_tokens = usage.get("completion_tokens", len(text) // 4)
                    total_tokens = prompt_tokens + completion_tokens
                    logger.info(f"OpenRouter tokens consumed: prompt={prompt_tokens}, completion={completion_tokens}, total={total_tokens}, model={self.model_name}")

                    await self._update_token_quota(total_tokens)

                    return self.clean_response(text)

        except aiohttp.ClientError as client_err:
            logger.error(f"Aiohttp connection error during OpenRouter request: {client_err}")
            raise ExternalApiThrottleException("OpenRouter network connection failure.") from client_err
