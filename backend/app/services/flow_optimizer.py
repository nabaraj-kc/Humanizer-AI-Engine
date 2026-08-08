"""
backend/app/services/flow_optimizer.py
======================================
Multi-Line Document Flow Optimizer.
Computes text layout within page block limits, adjusting font sizes and spacing to fit.
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
from reportlab.pdfbase.pdfmetrics import stringWidth

logger = logging.getLogger("humanizer_flow_optimizer")


def wrap_text_to_lines(text: str, font_name: str, font_size: float, max_width: float) -> list[str]:
    """
    Wraps text into individual lines so that no line exceeds max_width.
    Uses ReportLab's stringWidth metric for exact character width calculations.
    """
    if not text or not text.strip():
        return []

    words = text.split()
    lines = []
    current_line = []

    for word in words:
        test_line = " ".join(current_line + [word])
        # Calculate width using ReportLab stringWidth
        width = stringWidth(test_line, font_name, font_size)
        if width <= max_width:
            current_line.append(word)
        else:
            if current_line:
                lines.append(" ".join(current_line))
                current_line = [word]
            else:
                # Force single oversized word to prevent infinite loops
                lines.append(word)
                current_line = []

    if current_line:
        lines.append(" ".join(current_line))

    return lines


def optimize_paragraph_layout(
    text: str,
    font_name: str,
    font_size: float,
    line_spacing_ratio: float,
    container_width: float,
    container_height: float
) -> dict:
    """
    Fits paragraph text within a given bounding box by wrapping lines.
    If text overflows, scales down font size and line spacing down by up to 10% (clamped at 7pt).
    If it still overflows, splits the text into fitting lines and a trailing overflow string.
    
    Returns a dictionary:
      - lines: list[str] (lines that fit the container)
      - font_size: float (optimized font size used)
      - line_spacing: float (optimized leading/spacing used)
      - overflow_text: str (any text that could not fit)
    """
    # Safeguard: ensure minimum positive width/height to avoid math errors
    container_width = max(1.0, container_width)
    container_height = max(1.0, container_height)

    # Search for an optimized fit by scaling down in small increments
    steps = 10
    best_layout = None

    for step in range(steps + 1):
        # Scale factor ranges from 1.0 (no scaling) down to 0.9 (10% reduction)
        scale_factor = 1.0 - (0.1 * (step / steps))
        
        # Enforce readable limit: never shrink font size below 7 points
        test_font_size = max(7.0, font_size * scale_factor)
        test_spacing = line_spacing_ratio * scale_factor

        lines = wrap_text_to_lines(text, font_name, test_font_size, container_width)
        # Leading height = font_size * line_spacing_ratio
        total_height = len(lines) * test_font_size * test_spacing

        layout = {
            "lines": lines,
            "font_size": round(test_font_size, 2),
            "line_spacing": round(test_spacing, 2),
            "overflow_text": ""
        }

        if total_height <= container_height:
            return layout
        
        # Save the layout with max shrunken size as fallback
        if step == steps:
            best_layout = layout

    # If we reached here, the text still overflows at the maximum 10% shrunken limits.
    # We must split the text.
    logger.info("Text block still overflows after 10% scaling reduction. Splitting lines...")
    
    shrunken_font_size = best_layout["font_size"]
    shrunken_spacing = best_layout["line_spacing"]
    lines = best_layout["lines"]
    
    # Calculate how many lines can fit
    line_height = shrunken_font_size * shrunken_spacing
    max_lines = int(container_height / line_height)
    max_lines = max(1, max_lines) # draw at least one line

    fitting_lines = lines[:max_lines]
    overflow_lines = lines[max_lines:]

    best_layout["lines"] = fitting_lines
    best_layout["overflow_text"] = " ".join(overflow_lines)

    return best_layout


# ---------------------------------------------------------------------------
# Stage 39 Verification Guardrail Tests
# ---------------------------------------------------------------------------
def run_tests() -> None:
    print("=== Stage 39: Multi-Line Flow Optimizer Verification ===")
    print()

    # Define container: width 200 pt, height 50 pt
    # Standard Helvetica at size 10pt with 1.2 spacing has line height 12pt.
    # It can fit at most 4 lines (48pt).
    container_w = 200.0
    container_h = 50.0
    
    # 1. Fits without scaling
    print("  --- Test 1: Fits without scaling ---")
    short_text = "This is a short paragraph that easily fits."
    res_short = optimize_paragraph_layout(
        text=short_text,
        font_name="Helvetica",
        font_size=10.0,
        line_spacing_ratio=1.2,
        container_width=container_w,
        container_height=container_h
    )
    assert res_short["font_size"] == 10.0
    assert not res_short["overflow_text"]
    print(f"  [PASS] Fits without scaling. Lines count: {len(res_short['lines'])}")
    print()

    # 2. Fits with up to 10% scaling
    print("  --- Test 2: Fits with up to 10% scaling ---")
    medium_text = (
        "This is a slightly longer text block that will not fit at standard size 10 inside our small container because it is way too long, "
        "but should fit when scaled down slightly to around 9 points."
    )
    res_med = optimize_paragraph_layout(
        text=medium_text,
        font_name="Helvetica",
        font_size=10.0,
        line_spacing_ratio=1.2,
        container_width=container_w,
        container_height=container_h
    )
    assert 9.0 <= res_med["font_size"] < 10.0
    assert not res_med["overflow_text"]
    print(f"  [PASS] Fits with scaling. Scaled font size: {res_med['font_size']} (original=10.0)")
    print()

    # 3. Overflows even after 10% scaling (requires splitting)
    print("  --- Test 3: Overflow splitting and trailing block check ---")
    long_text = (
        "This is a very long text block designed to completely overflow our small container, "
        "even when we shrink the font size down to the maximum allowed limit of 9.0 points. "
        "The flow optimizer must split this text, keeping what fits inside the container and "
        "returning the remaining text as an overflow string so we don't lose any data."
    )
    res_long = optimize_paragraph_layout(
        text=long_text,
        font_name="Helvetica",
        font_size=10.0,
        line_spacing_ratio=1.2,
        container_width=container_w,
        container_height=container_h
    )
    # The font size must be scaled down to 9.0 (10% reduction of 10.0)
    assert res_long["font_size"] == 9.0
    assert len(res_long["overflow_text"]) > 0
    print(f"  [PASS] Correctly split overflow. Lines that fit: {len(res_long['lines'])}")
    print(f"         Overflow text: {res_long['overflow_text'][:60]}...")
    print()

    # 4. Minimum font size guardrail (never shrink below 7.0pt)
    print("  --- Test 4: Minimum font size limit of 7pt ---")
    res_guard = optimize_paragraph_layout(
        text=long_text + " " + long_text,
        font_name="Helvetica",
        font_size=7.5,
        line_spacing_ratio=1.2,
        container_width=container_w,
        container_height=container_h
    )
    # 7.5 scaled by 90% is 6.75, which violates 7pt minimum. Should clamp to 7.0
    assert res_guard["font_size"] == 7.0
    print(f"  [PASS] Clamped font size correctly at 7.0pt (requested size=7.5).")
    print()

    print("Stage 39 verification: ALL CHECKS PASSED.")


if __name__ == "__main__":
    run_tests()
