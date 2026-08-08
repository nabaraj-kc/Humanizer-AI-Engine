"""
backend/app/services/token_restorer.py
======================================
Text Token Unmasking & Deshielding Service.
Restores original citations and math formulas back into rewritten humanized text blocks.
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

import re
import logging

logger = logging.getLogger("humanizer_token_restorer")


class UnmaskingError(Exception):
    """Raised when placeholder token unmasking fails or leaves residual placeholders."""
    pass


def restore_shielded_tokens(text: str, translation_dict: dict) -> str:
    """
    Parses text strings, matches placeholders like __CITATION_0__ or __MATH_BLOCK_1__,
    and replaces them with their original markup and citation strings.
    
    Enforces a strict check: if any placeholder remains, raises UnmaskingError.
    """
    if not text:
        return ""

    restored_text = text

    # Sort translation dict keys by length descending to prevent substring collisions
    # (e.g. replacing __CITATION_10__ before __CITATION_1__)
    sorted_placeholders = sorted(translation_dict.keys(), key=len, reverse=True)

    for p in sorted_placeholders:
        val = translation_dict[p]
        restored_text = restored_text.replace(p, val)

    # Compulsory guardrail: verify no residual citation/math placeholders remain
    residual_patterns = [
        r'__CITATION_[0-9]+__',
        r'__MATH_BLOCK_[0-9]+__'
    ]
    for pattern in residual_patterns:
        matches = re.findall(pattern, restored_text)
        if matches:
            logger.error(f"Residual placeholder tokens detected after unmasking: {matches}")
            raise UnmaskingError(
                f"Failed to unmask all placeholders. Leftovers: {', '.join(matches)}"
            )

    return restored_text


# ---------------------------------------------------------------------------
# Stage 38 Verification Guardrail Tests
# ---------------------------------------------------------------------------
def run_tests() -> None:
    print("=== Stage 38: Token Restorer Verification ===")
    print()

    # Test 1: Successful unmasking
    print("  --- Test 1: Successful citation and math unmasking ---")
    rewritten_text = "As shown in __CITATION_0__, the equation __MATH_BLOCK_0__ holds true."
    translation = {
        "__CITATION_0__": "[1]",
        "__MATH_BLOCK_0__": "$E=mc^2$"
    }
    
    restored = restore_shielded_tokens(rewritten_text, translation)
    assert restored == "As shown in [1], the equation $E=mc^2$ holds true."
    print("  [PASS] Unmasked all placeholder tokens correctly.")
    print()

    # Test 2: Substring collision protection (e.g. 10 and 1)
    print("  --- Test 2: Substring replacement collision safety ---")
    collision_text = "Compare __CITATION_1__ and __CITATION_10__."
    collision_translation = {
        "__CITATION_1__": "[SMITH]",
        "__CITATION_10__": "[JONES]"
    }
    restored_collision = restore_shielded_tokens(collision_text, collision_translation)
    assert restored_collision == "Compare [SMITH] and [JONES]."
    print("  [PASS] Handled substring collisions cleanly.")
    print()

    # Test 3: Residual placeholder check (must fail)
    print("  --- Test 3: Residual placeholder verification guardrail ---")
    incomplete_text = "Only __CITATION_0__ was unmasked, but __CITATION_1__ was forgotten."
    incomplete_translation = {
        "__CITATION_0__": "[1]"
    }
    try:
        restore_shielded_tokens(incomplete_text, incomplete_translation)
        assert False, "Expected UnmaskingError to be raised."
    except UnmaskingError as e:
        print(f"  [PASS] Correctly intercepted unfinished unmasking: {e}")
        
    print()
    print("Stage 38 verification: ALL CHECKS PASSED.")


if __name__ == "__main__":
    run_tests()
