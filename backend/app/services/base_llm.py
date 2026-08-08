"""
backend/app/services/base_llm.py
================================
Base Model Abstract API Integration Framework.
Defines the abstract interface for all downstream LLM provider integrations.
"""

# Hotpatch typing module for Python 3.11 alpha compatibility issues with Pydantic / AnyIO
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

import abc
import re
import sys
from pathlib import Path

# Resolve project root path
sys.path.append(str(Path(__file__).resolve().parents[3]))


class ExternalApiThrottleException(Exception):
    """
    Exception raised when an external LLM provider API throttles the client (429)
    or experiences a service drop (503), triggering a failover sequence.
    """
    pass


class BaseLLMProvider(abc.ABC):
    """
    Abstract Base Class defining standard execution interfaces and utility
    parsers for AI rewrite providers (Google, Groq, DeepSeek).
    """

    @abc.abstractmethod
    async def execute_text_rewrite(self, prompt: str, context_chunk: str) -> str:
        """
        Executes an asynchronous rewrite request against the provider API.
        
        Args:
            prompt: The full instruction prompt including formatting constraints.
            context_chunk: The specific block of text to be humanized.
            
        Returns:
            The raw text rewritten by the LLM.
        """
        pass

    def clean_response(self, response_text: str) -> str:
        """
        Helper method to sanitize model response formatting, such as stripping out
        markdown wrappers (e.g. ```markdown ... ```) often added by chat models.
        """
        if not response_text:
            return ""
            
        cleaned = response_text.strip()
        
        # Strip markdown block wrappers if present (e.g. ```markdown ... ``` or ``` ... ```)
        pattern = r"^```(?:[a-zA-Z0-9-]*\n)?(.*?)```$"
        match = re.match(pattern, cleaned, re.DOTALL)
        if match:
            cleaned = match.group(1).strip()
            
        return cleaned


# ---------------------------------------------------------------------------
# Stage 22 Verification Guardrail Test
# ---------------------------------------------------------------------------

def run_tests() -> None:
    print("=== Stage 22: Base Model Provider Interface Verification ===")
    print()

    # 1. Assert attempting to instantiate abstract base class raises TypeError
    print("  --- Test 1: Direct abstract class instantiation constraint ---")
    try:
        provider = BaseLLMProvider()  # type: ignore
        assert False, "Expected TypeError when instantiating abstract base class directly."
    except TypeError as e:
        print(f"  [PASS] Successfully blocked base class instantiation: {e}")
        
    print()

    # 2. Verify concrete class instantiation and clean_response helper function
    print("  --- Test 2: Concrete implementation and clean response parser ---")
    
    class MockLLMProvider(BaseLLMProvider):
        async def execute_text_rewrite(self, prompt: str, context_chunk: str) -> str:
            return f"rewritten: {context_chunk}"

    mock_provider = MockLLMProvider()
    
    # Check execution interface
    async def test_execution():
        res = await mock_provider.execute_text_rewrite("Prompt instructions", "Original Chunk Text")
        assert res == "rewritten: Original Chunk Text"
        
    asyncio.run(test_execution())
    print("  [PASS] Concrete subclass successfully implements rewrite interface.")

    # Check clean_response method
    dirty_text_1 = "```markdown\nThis is the actual text content.\n```"
    dirty_text_2 = "```\nThis is another text block without language tag.\n```"
    clean_text = "This is clean text."
    
    assert mock_provider.clean_response(dirty_text_1) == "This is the actual text content."
    assert mock_provider.clean_response(dirty_text_2) == "This is another text block without language tag."
    assert mock_provider.clean_response(clean_text) == "This is clean text."
    print("  [PASS] Markdown code wrappers stripped successfully by helper.")
    print()
    
    print("Stage 22 verification: ALL CHECKS PASSED.")


if __name__ == "__main__":
    run_tests()
