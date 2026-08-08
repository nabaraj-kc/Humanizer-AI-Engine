"""
backend/app/services/pdf_merger.py
==================================
Structural PDF Layout Merger.
Redacts template text blocks, then overlays ReportLab canvas text pages using PyMuPDF.
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
import fitz

# Resolve project root path
sys.path.append(str(Path(__file__).resolve().parents[3]))

logger = logging.getLogger("humanizer_pdf_merger")


class PageCountMismatchError(Exception):
    """Raised when page counts of template and canvas PDFs do not match."""
    pass


def merge_pdf_layers(
    template_pdf_path: str,
    canvas_pdf_path: str,
    output_pdf_path: str,
    original_blocks: list[dict] = None
) -> None:
    """
    Merges vector text canvas layer onto redacted original PDF background pages.
    
    Args:
      template_pdf_path: Path to the original uploaded PDF.
      canvas_pdf_path: Path to the generated ReportLab vector text PDF.
      output_pdf_path: Path to save the merged result document.
      original_blocks: Optional list of original text blocks coordinates to redact from template.
    """
    template_doc = fitz.open(template_pdf_path)
    canvas_doc = fitz.open(canvas_pdf_path)

    # Compulsory verification guardrail: assert page counts match exactly
    if len(template_doc) != len(canvas_doc):
        t_len = len(template_doc)
        c_len = len(canvas_doc)
        template_doc.close()
        canvas_doc.close()
        logger.error(f"Merge aborted due to page count mismatch. Template pages={t_len}, Canvas pages={c_len}")
        raise PageCountMismatchError(
            f"Page count mismatch: template doc has {t_len} pages, but canvas doc has {c_len} pages."
        )

    # 1. Apply redaction to erase old text layout blocks on the template pages
    if original_blocks:
        logger.info("Applying redactions to remove original text layouts...")
        
        # Group original blocks by page_no
        blocks_by_page: dict[int, list[dict]] = {}
        for block in original_blocks:
            p_no = block.get("page_no", 0)
            blocks_by_page.setdefault(p_no, []).append(block)

        for page_no in sorted(blocks_by_page.keys()):
            if page_no >= len(template_doc):
                continue
            
            page = template_doc[page_no]
            for block in blocks_by_page[page_no]:
                x0 = float(block.get("x0", 0.0))
                y0 = float(block.get("y0", 0.0))
                x1 = float(block.get("x1", 0.0))
                y1 = float(block.get("y1", 0.0))
                
                # Expand box slightly by 0.5 points to ensure no text outlines bleed
                rect = fitz.Rect(x0 - 0.5, y0 - 0.5, x1 + 0.5, y1 + 0.5)
                page.add_redact_annot(rect)

            # Apply redactions, preserving non-text vector illustrations and images
            # images=2 (fitz.PDF_REDACT_IMAGE_NONE) prevents erasing background pictures
            try:
                page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE)
            except AttributeError:
                # Fallback if specific enum mapping is missing in alpha runtime API binding
                page.apply_redactions()

    # 2. Overlay new text canvas layer page by page onto template page
    logger.info("Blending ReportLab vector text canvas onto template background graphics...")
    for page_num in range(len(template_doc)):
        template_page = template_doc[page_num]
        rect = template_page.rect
        # show_pdf_page overlays canvas page vector graphics on top
        template_page.show_pdf_page(rect, canvas_doc, page_num)

    # 3. Save combined output document
    template_doc.save(output_pdf_path)
    template_doc.close()
    canvas_doc.close()
    logger.info(f"Layer blending completed successfully. Output saved to: {output_pdf_path}")


# ---------------------------------------------------------------------------
# Stage 40 Verification Guardrail Tests
# ---------------------------------------------------------------------------
def run_tests() -> None:
    print("=== Stage 40: Structural PDF Layout Merger Verification ===")
    print()

    # Create two temporary files representing page-count mismatch
    doc_1 = fitz.open()
    doc_1.new_page(width=100, height=100)
    doc_1.save("temp_doc1.pdf")
    doc_1.close()

    doc_2 = fitz.open()
    doc_2.new_page(width=100, height=100)
    doc_2.new_page(width=100, height=100)  # Has 2 pages (mismatch!)
    doc_2.save("temp_doc2.pdf")
    doc_2.close()

    # 1. Page count mismatch check
    print("  --- Test 1: Mismatch page counts abort check ---")
    try:
        merge_pdf_layers("temp_doc1.pdf", "temp_doc2.pdf", "temp_merged.pdf")
        assert False, "Expected PageCountMismatchError"
    except PageCountMismatchError as e:
        print(f"  [PASS] Successfully aborted and raised error: {e}")
    print()

    # 2. Merging execution test
    print("  --- Test 2: Sequential merging with clean page parity ---")
    
    # Recreate doc_2 as single-page PDF to match page counts
    doc_2_ok = fitz.open()
    p = doc_2_ok.new_page(width=100, height=100)
    # Add dummy text block
    p.insert_textbox(fitz.Rect(10, 10, 90, 40), "Original Text")
    doc_2_ok.save("temp_doc2.pdf")
    doc_2_ok.close()

    dummy_blocks = [{"page_no": 0, "x0": 10.0, "y0": 10.0, "x1": 90.0, "y1": 40.0}]

    try:
        # Run merging
        merge_pdf_layers("temp_doc2.pdf", "temp_doc1.pdf", "temp_merged.pdf", original_blocks=dummy_blocks)
        
        # Verify page count is correct (should be 1 page)
        verify_doc = fitz.open("temp_merged.pdf")
        assert len(verify_doc) == 1
        verify_doc.close()
        
        print("  [PASS] Successfully merged layer with page count parity.")
    finally:
        # Clean up temporary PDFs
        for path in ["temp_doc1.pdf", "temp_doc2.pdf", "temp_merged.pdf"]:
            p = Path(path)
            if p.exists():
                p.unlink()
                
    print()
    print("Stage 40 verification: ALL CHECKS PASSED.")


if __name__ == "__main__":
    run_tests()
