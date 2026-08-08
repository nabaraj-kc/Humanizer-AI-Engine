"""
backend/app/services/canvas_builder.py
======================================
Canvas Layout Reconstruction Engine.
Generates a PDF canvas layer using ReportLab containing rewritten text at exact coordinates.
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
from reportlab.pdfgen import canvas

# Resolve project root path
sys.path.append(str(Path(__file__).resolve().parents[3]))

from backend.app.services.token_restorer import restore_shielded_tokens
from backend.app.services.flow_optimizer import optimize_paragraph_layout

logger = logging.getLogger("humanizer_canvas_builder")


class RenderingError(Exception):
    """Raised when placeholder tokens remain during canvas drawing operations."""
    pass


class CanvasReconstructor:
    """
    Renders humanized, unmasked text blocks onto a fresh ReportLab vector canvas.
    Handles coordinate spaces, font mappings, and flow layout positioning.
    """

    def __init__(self):
        pass

    def draw_canvas_layer(
        self,
        mapped_blocks: list[dict],
        output_pdf_path: str,
        page_dimensions: dict[int, tuple[float, float]],
        translation_dict: dict
    ) -> None:
        """
        Creates a PDF file at output_pdf_path containing vector text elements.
        
        Args:
          mapped_blocks: list of dictionaries representing text blocks with layout coordinates.
          output_pdf_path: file path to write the generated vector PDF text layer.
          page_dimensions: mapping of page_no to (width, height).
          translation_dict: translation mappings to unmask placeholders.
        """
        if not mapped_blocks:
            logger.warning("No mapped blocks provided to CanvasReconstructor. Generating empty pages matching dimensions.")
            c = canvas.Canvas(output_pdf_path)
            pages = sorted(page_dimensions.keys()) if page_dimensions else [0]
            for page_no in pages:
                page_w, page_h = page_dimensions.get(page_no, (595.0, 842.0))
                c.setPageSize((page_w, page_h))
                c.showPage()
            c.save()
            return

        c = canvas.Canvas(output_pdf_path)

        # Group blocks by page_no
        blocks_by_page: dict[int, list[dict]] = {}
        for block in mapped_blocks:
            p_no = block.get("page_no", 0)
            blocks_by_page.setdefault(p_no, []).append(block)

        # Process page by page in sorted order
        for page_no in sorted(blocks_by_page.keys()):
            # Get dimensions, defaulting to standard A4 (595x842)
            page_w, page_h = page_dimensions.get(page_no, (595.0, 842.0))
            c.setPageSize((page_w, page_h))

            logger.info(f"Reconstructing page {page_no} (size={page_w}x{page_h}) on canvas...")

            for block in blocks_by_page[page_no]:
                # 1. Unmask tokens and verify placeholder integrity
                raw_rewritten = block.get("rewritten_text", "")
                try:
                    unmasked_text = restore_shielded_tokens(raw_rewritten, translation_dict)
                except Exception as unmask_err:
                    logger.error(f"Unmasking error during canvas drawing: {unmask_err}")
                    raise RenderingError(f"Rendering halted: {unmask_err}") from unmask_err

                # Compulsory Guardrail: halt rendering immediately if raw placeholders remain
                if "__CITATION_" in unmasked_text or "__MATH_BLOCK_" in unmasked_text:
                    logger.error(f"Protected formatting placeholder survived unmasking: {unmasked_text}")
                    raise RenderingError(
                        f"Rendering halted: unmasked text contains raw placeholder tokens in block {block.get('block_no')}."
                    )

                # 2. Extract block spatial coordinates (PyMuPDF space)
                x0 = float(block.get("x0", 0.0))
                y0 = float(block.get("y0", 0.0))
                x1 = float(block.get("x1", 0.0))
                y1 = float(block.get("y1", 0.0))

                w_box = x1 - x0
                h_box = y1 - y0

                # 3. Determine font styling properties
                # Check original font attributes if available, else default
                orig_text = block.get("original_text", "")
                font_name = "Helvetica"
                
                # Rudimentary bold detection based on block text capitalization or length
                # In standard papers, headers are often uppercase or bold
                if orig_text.isupper() and len(orig_text) < 100:
                    font_name = "Helvetica-Bold"

                # 4. Fit text inside block boundary
                layout = optimize_paragraph_layout(
                    text=unmasked_text,
                    font_name=font_name,
                    font_size=10.0,  # Default standard body size
                    line_spacing_ratio=1.2,
                    container_width=w_box,
                    container_height=h_box
                )

                # 5. Translate coordinates from PyMuPDF space (top-left) to ReportLab space (bottom-left)
                # Bounding box top is translated as (page_h - y0)
                # Drawing cursor starts at y0-offset by one font size height
                # ReportLab drawString coordinates reference bottom-left of character baseline.
                c.setFont(font_name, layout["font_size"])
                line_height = layout["font_size"] * layout["line_spacing"]
                
                y_cursor = (page_h - y0) - layout["font_size"]

                for line in layout["lines"]:
                    c.drawString(x0, y_cursor, line)
                    y_cursor -= line_height

                # Handle overflow logs/warnings if any
                if layout["overflow_text"]:
                    logger.warning(
                        f"Block {block.get('block_no')} on page {page_no} has layout overflow text: "
                        f"{layout['overflow_text'][:50]}..."
                    )

            # Commit current page canvas layer
            c.showPage()

        # Save finished document
        c.save()
        logger.info(f"Vector text canvas layer saved to: {output_pdf_path}")


# ---------------------------------------------------------------------------
# Stage 37 Verification Guardrail Tests
# ---------------------------------------------------------------------------
def run_tests() -> None:
    print("=== Stage 37: Canvas Layout Reconstructor Verification ===")
    print()

    import os
    
    reconstructor = CanvasReconstructor()
    temp_pdf = "temp_canvas_test.pdf"

    # Define page dimensions: page 0 is standard A4
    dimensions = {0: (595.0, 842.0)}

    # Mock translation dictionary
    translation = {
        "__CITATION_0__": "[1]",
        "__MATH_BLOCK_0__": "$E=mc^2$"
    }

    # 1. Test case: successful drawing
    print("  --- Test 1: Generate canvas layer with coordinates ---")
    mapped_blocks = [
        {
            "page_no": 0,
            "block_no": 1,
            "x0": 50.0,
            "y0": 100.0,
            "x1": 500.0,
            "y1": 200.0,
            "original_text": "Introduction block",
            "rewritten_text": "Rewritten introduction with __CITATION_0__ and equation __MATH_BLOCK_0__."
        }
    ]

    try:
        reconstructor.draw_canvas_layer(mapped_blocks, temp_pdf, dimensions, translation)
        assert os.path.exists(temp_pdf)
        print(f"  [PASS] Vector canvas PDF generated successfully: {temp_pdf}")
    finally:
        if os.path.exists(temp_pdf):
            os.remove(temp_pdf)
    print()

    # 2. Test case: halt rendering on unmasked placeholders
    print("  --- Test 2: Halt rendering on unmasked placeholders guardrail ---")
    bad_blocks = [
        {
            "page_no": 0,
            "block_no": 2,
            "x0": 50.0,
            "y0": 100.0,
            "x1": 500.0,
            "y1": 200.0,
            "original_text": "Intro block",
            "rewritten_text": "Text block with forgotten __CITATION_1__ placeholder."
        }
    ]
    try:
        reconstructor.draw_canvas_layer(bad_blocks, temp_pdf, dimensions, translation)
        assert False, "Expected RenderingError to be raised."
    except RenderingError as e:
        print(f"  [PASS] Rendering interrupted correctly: {e}")
    finally:
        if os.path.exists(temp_pdf):
            os.remove(temp_pdf)

    print()
    print("Stage 37 verification: ALL CHECKS PASSED.")


if __name__ == "__main__":
    run_tests()
