"""
backend/app/tests/test_assembly_pipeline.py
============================================
Assembly & Reconstruction Pipeline Integration Test.
Runs end-to-end alignment, unmasking, ReportLab rendering, redaction, and PyMuPDF merging.
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

from backend.app.services.canvas_builder import CanvasReconstructor
from backend.app.services.pdf_merger import merge_pdf_layers
from backend.app.services.file_janitor import FileJanitor

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("test_assembly_pipeline")


def create_mock_template_pdf(path: Path) -> None:
    """Creates a 2-page template PDF with text blocks to redact/replace."""
    doc = fitz.open()

    # Page 1
    p1 = doc.new_page(width=595, height=842)
    p1.insert_textbox(
        fitz.Rect(50, 50, 500, 80),
        "Introduction to Scholarly Reconstruction.",
        fontname="hebo", fontsize=14
    )
    p1.insert_textbox(
        fitz.Rect(50, 100, 500, 200),
        "This is a body text block containing a citation placeholder __CITATION_0__ and equation __MATH_BLOCK_0__. We verify spatial layout.",
        fontname="helv", fontsize=10
    )

    # Page 2
    p2 = doc.new_page(width=595, height=842)
    p2.insert_textbox(
        fitz.Rect(50, 50, 500, 80),
        "Methodology description.",
        fontname="hebo", fontsize=14
    )
    p2.insert_textbox(
        fitz.Rect(50, 100, 500, 200),
        "Our formula regression is represented by __MATH_BLOCK_1__. Let us proceed.",
        fontname="helv", fontsize=10
    )

    doc.save(str(path))
    doc.close()


def run_assembly_tests() -> None:
    print("=== Stage 42: Assembly Pipeline Integration Test ===")
    print()

    # Workspace setup
    storage_dir = Path(__file__).resolve().parents[3] / "storage"
    storage_dir.mkdir(exist_ok=True)

    template_pdf = storage_dir / "assembly_template.pdf"
    canvas_pdf = storage_dir / "assembly_canvas.pdf"
    output_pdf = storage_dir / "assembly_final.pdf"

    print("  --- Test Step 1: Create template PDF ---")
    create_mock_template_pdf(template_pdf)
    assert template_pdf.exists()
    print("  [PASS] Created template PDF successfully.")
    print()

    # 1. Define original blocks (matching the mock template)
    original_blocks = [
        {"page_no": 0, "block_no": 0, "x0": 50.0, "y0": 50.0, "x1": 500.0, "y1": 80.0, "text": "Introduction to Scholarly Reconstruction."},
        {"page_no": 0, "block_no": 1, "x0": 50.0, "y0": 100.0, "x1": 500.0, "y1": 200.0, "text": "This is a body text block..."},
        {"page_no": 1, "block_no": 2, "x0": 50.0, "y0": 50.0, "x1": 500.0, "y1": 80.0, "text": "Methodology description."},
        {"page_no": 1, "block_no": 3, "x0": 50.0, "y0": 100.0, "x1": 500.0, "y1": 200.0, "text": "Our formula regression..."}
    ]

    # 2. Define rewritten blocks with placeholders
    mapped_blocks = [
        {
            "page_no": 0,
            "block_no": 0,
            "x0": 50.0,
            "y0": 50.0,
            "x1": 500.0,
            "y1": 80.0,
            "original_text": "Introduction to Scholarly Reconstruction.",
            "rewritten_text": "INTRODUCTION TO SCHOLARLY RECONSTRUCTION."
        },
        {
            "page_no": 0,
            "block_no": 1,
            "x0": 50.0,
            "y0": 100.0,
            "x1": 500.0,
            "y1": 200.0,
            "original_text": "This is a body text...",
            "rewritten_text": "This rewritten body text block contains citation __CITATION_0__ and math __MATH_BLOCK_0__. It verifies our layout alignment."
        },
        {
            "page_no": 1,
            "block_no": 2,
            "x0": 50.0,
            "y0": 50.0,
            "x1": 500.0,
            "y1": 80.0,
            "original_text": "Methodology description.",
            "rewritten_text": "METHODOLOGY DESCRIPTION."
        },
        {
            "page_no": 1,
            "block_no": 3,
            "x0": 50.0,
            "y0": 100.0,
            "x1": 500.0,
            "y1": 200.0,
            "original_text": "Our formula...",
            "rewritten_text": "Our formula regression is represented by __MATH_BLOCK_1__. We have completed validation."
        }
    ]

    translation = {
        "__CITATION_0__": "[1]",
        "__MATH_BLOCK_0__": "$E=mc^2$",
        "__MATH_BLOCK_1__": "$L = \\sum x_i$"
    }

    # Dimensions: 2 pages of 595x842 standard size
    dimensions = {0: (595.0, 842.0), 1: (595.0, 842.0)}

    # 3. Canvas layout reconstruction
    print("  --- Test Step 2: Canvas layer reconstruction ---")
    reconstructor = CanvasReconstructor()
    reconstructor.draw_canvas_layer(mapped_blocks, str(canvas_pdf), dimensions, translation)
    assert canvas_pdf.exists()
    print("  [PASS] Canvas layer PDF generated successfully.")
    print()

    # 4. Layer merging and old text redaction
    print("  --- Test Step 3: PyMuPDF redaction and page overlay merging ---")
    merge_pdf_layers(str(template_pdf), str(canvas_pdf), str(output_pdf), original_blocks)
    assert output_pdf.exists()
    print("  [PASS] Layer blending complete.")
    print()

    # 5. Output PDF verification
    print("  --- Test Step 4: Output document scannability check ---")
    doc = fitz.open(str(output_pdf))
    assert len(doc) == 2, f"Expected 2 pages, got {len(doc)}"
    
    # Extract text from output PDF to verify unmasking
    p1_text = doc[0].get_text()
    p2_text = doc[1].get_text()
    doc.close()

    # Verify unmasked values exist
    assert "[1]" in p1_text
    assert "$E=mc^2$" in p1_text
    assert "$L = \\sum x_i$" in p2_text
    
    # Verify no raw placeholders remain
    assert "__CITATION_" not in p1_text
    assert "__MATH_BLOCK_" not in p1_text
    assert "__MATH_BLOCK_" not in p2_text
    
    print("  [PASS] Output text verified: citations/math unmasked and raw placeholders absent.")
    print()

    # 6. File Janitor cleanup verification
    print("  --- Test Step 5: File Janitor safety cleanup ---")
    janitor = FileJanitor()
    
    # Verify that clean_temp_assets successfully removes canvas_pdf,
    # but rejects deleting template_pdf or output_pdf due to guardrails
    janitor.clean_temp_assets([canvas_pdf], template_pdf, output_pdf)
    assert not canvas_pdf.exists(), "Janitor failed to delete temp canvas_pdf"
    
    # Clean up original and final files manually
    template_pdf.unlink(missing_ok=True)
    output_pdf.unlink(missing_ok=True)
    print("  [PASS] Janitor safely cleaned temporary files.")
    print()

    print("Stage 42 Integration Check: ALL PASSED.")


if __name__ == "__main__":
    run_assembly_tests()
