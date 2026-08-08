"""
backend/app/tests/test_e2e_main.py
==================================
Comprehensive End-to-End System Integration Test Suite.
Validates file ingestion, LLM failover simulation, loop processing,
reconstruction, layer blending, and database tracking updates.
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

import os
import sys
import uuid
import logging
import unittest.mock as mock
from pathlib import Path
import fitz
from fastapi.testclient import TestClient

# Resolve project root path
project_root = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(project_root))

from backend.app.main import app
from backend.app.db.session import get_async_session
from backend.app.core.config import get_settings
from backend.app.services.pdf_extractor import PdfLayoutExtractor
from backend.app.services.citation_shield import shield_citations, deshield_citations
from backend.app.services.math_shield import shield_math, deshield_math
from backend.app.services.chunker import SemanticChunker
from backend.app.services.layout_mapper import DocumentStructureMap
from backend.app.services.loop_controller import FeedbackLoopController
from backend.app.services.canvas_builder import CanvasReconstructor
from backend.app.services.pdf_merger import merge_pdf_layers
from backend.app.services.file_janitor import FileJanitor

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("test_e2e_main")


def create_sample_academic_pdf(path: Path):
    """Creates a sample academic document on the filesystem for parsing integration."""
    doc = fitz.open()
    p1 = doc.new_page(width=595, height=842)
    
    # Bounding blocks matching academic coordinates
    p1.insert_textbox(
        fitz.Rect(50, 50, 500, 100),
        "Title: Deep Learning and Layout Coordinates Reconstruction System.",
        fontname="hebo", fontsize=14
    )
    p1.insert_textbox(
        fitz.Rect(50, 110, 500, 300),
        "Abstract: Traditional text extraction techniques ignore formatting vectors [1]. "
        "We address this by keeping layout coordinates. Let our page bounding boxes be represented "
        "by coordinate variables $$B = (x_0, y_0, x_1, y_1)$$. The regression formula is defined "
        "by the inline representation $\\text{Loss} = \\sum ||B_i - \\hat{B}_i||^2$. This enables "
        "reconstruction of academic outputs.",
        fontname="helv", fontsize=10
    )
    doc.save(str(path))
    doc.close()


def test_end_to_end_pipeline():
    print("=== Stage 50: Full End-to-End System Integration Test ===")
    print()

    settings = get_settings()
    client = TestClient(app)
    
    # 1. Setup paths
    uploaded_pdf = settings.storage_dir / "e2e_uploaded.pdf"
    canvas_pdf = settings.storage_dir / "e2e_canvas.pdf"
    final_output_pdf = settings.storage_dir / "e2e_final.pdf"
    
    # Ensure folder is clean
    settings.storage_dir.mkdir(parents=True, exist_ok=True)
    uploaded_pdf.unlink(missing_ok=True)
    canvas_pdf.unlink(missing_ok=True)
    final_output_pdf.unlink(missing_ok=True)

    print("  --- Step 1: Create and ingest academic PDF via POST /api/upload ---")
    create_sample_academic_pdf(uploaded_pdf)
    assert uploaded_pdf.exists(), "Sample PDF could not be written to disk"

    # POST file upload request with background tasks mocked to prevent double execution
    with mock.patch("backend.app.api.upload.BackgroundTasks.add_task") as mock_add_task:
        with open(uploaded_pdf, "rb") as f:
            response = client.post(
                "/api/upload",
                files={"file": ("e2e_uploaded.pdf", f, "application/pdf")}
            )

    assert response.status_code == 200, f"Expected 200 upload status, got {response.status_code}"
    data = response.json()
    assert data["status"] == "success"
    run_id = data["run_id"]
    print(f"  [PASS] PDF successfully ingested. Assigned run_id: {run_id}")

    # Verify run record in the database
    async def get_db_record():
        async with get_async_session() as db:
            async with db.execute(
                "SELECT filename, status FROM paper_runs WHERE run_id = :run_id",
                {"run_id": run_id}
            ) as cur:
                return await cur.fetchone()

    row = asyncio.run(get_db_record())
    assert row is not None
    assert row["filename"] == "e2e_uploaded.pdf"
    assert row["status"] in ("running", "completed")
    print(f"  [PASS] Database record validated: Status is '{row['status']}'.")
    print()

    # 2. Extract block layouts
    print("  --- Step 2: Extract spatial page coordinates ---")
    extractor = PdfLayoutExtractor(uploaded_pdf)
    with extractor:
        raw_blocks = extractor.extract_all_blocks()
    
    blocks = [b.to_dict() if hasattr(b, "to_dict") else b for b in raw_blocks]
    assert len(blocks) >= 2, "Expected at least 2 coordinate blocks"
    print(f"  [PASS] Extracted {len(blocks)} layout coordinate blocks.")
    print()

    # 3. Apply Token Shields
    print("  --- Step 3: Apply Citation and Math shielding ---")
    all_texts = [b["text"].strip() for b in blocks if b["block_type"] == 0]
    combined_plain_text = "\n\n".join(all_texts)
    
    shielded_cit, citation_map = shield_citations(combined_plain_text)
    shielded_both, math_map = shield_math(shielded_cit)
    
    paragraphs = shielded_both.split("\n\n")
    assert len(paragraphs) == len(blocks), f"Split count mismatch: {len(paragraphs)} vs {len(blocks)}"
    
    shielded_blocks = []
    for idx, b in enumerate(blocks):
        sb = dict(b)
        sb["text"] = paragraphs[idx]
        shielded_blocks.append(sb)

    print(f"  [PASS] Tokens registered: citations={len(citation_map)} | math={len(math_map)}")
    print()

    # 4. Semantic Chunking & Structuring
    print("  --- Step 4: Run Semantic Chunker & map document structure ---")
    chunker = SemanticChunker(target_words=100, max_words=200)
    chunks = chunker.chunk_document(shielded_blocks)
    assert len(chunks) > 0, "No semantic chunks generated"
    
    mapper = DocumentStructureMap(blocks)
    mapper.register_chunks(chunks)
    print(f"  [PASS] Generated {len(chunks)} chunk(s) mapped to structural layout.")
    print()

    # Seed master summary in DB for the prompt factory
    async def seed_master_summary():
        async with get_async_session() as db:
            await db.execute(
                "UPDATE paper_runs SET master_summary = :summary WHERE run_id = :run_id",
                {"summary": "Dummy academic paper summary for testing", "run_id": run_id}
            )
            await db.commit()
    asyncio.run(seed_master_summary())

    # 5. Loop Controller & Mock Router Failover
    print("  --- Step 5: Execute loop controller with API failover mocking ---")
    
    # We mock:
    # 1. Router failover output (returns text in uppercase, keeping formatting masks intact)
    # 2. Detector scoring loops (first is 95%, second is 12% early success)
    async def mock_failover_rewrite(prompt, text):
        return text.upper()

    scores_list = [95.0, 12.0]
    async def mock_detect(*args, **kwargs):
        return scores_list.pop(0) if scores_list else 10.0

    feedback_loop_controller = FeedbackLoopController()
    
    # Apply mocks to prompt router and adversarial detector layers
    with mock.patch.object(feedback_loop_controller.router, "rewrite_chunk_with_failover", side_effect=mock_failover_rewrite), \
         mock.patch.object(feedback_loop_controller.detector, "calculate_ai_probability", side_effect=mock_detect):

        # Run loop orchestrator synchronously for our chunks
        rewritten_chunk_map = {}
        for chunk in chunks:
            # Seed chunk record in DB
            async def seed_chunk_db():
                async with get_async_session() as db:
                    await db.execute(
                        """
                        INSERT INTO text_chunks 
                            (chunk_id, run_id, sequence_no, raw_text, clean_text, processed, iterations)
                        VALUES 
                            (:chunk_id, :run_id, :sequence_no, :raw_text, :clean_text, NULL, 0)
                        """,
                        {
                            "chunk_id": str(uuid.uuid4()),
                            "run_id": run_id,
                            "sequence_no": chunk["chunk_id"],
                            "raw_text": chunk["text"],
                            "clean_text": chunk["text"]
                        }
                    )
                    await db.commit()
            asyncio.run(seed_chunk_db())

            # Trigger loop controller step
            res = asyncio.run(feedback_loop_controller.humanize_chunk(
                raw_text=chunk["text"],
                clean_text=chunk["text"],
                run_id=run_id,
                sequence_no=chunk["chunk_id"]
            ))
            assert res["success"] is True
            rewritten_chunk_map[chunk["chunk_id"]] = res["processed"]

    # Assert db contains loop updates
    async def get_chunks_db():
        async with get_async_session() as db:
            async with db.execute(
                "SELECT processed, iterations FROM text_chunks WHERE run_id = :run_id",
                {"run_id": run_id}
            ) as cur:
                return await cur.fetchall()
                
    db_chunks = asyncio.run(get_chunks_db())
    assert len(db_chunks) == len(chunks)
    for c in db_chunks:
        assert c["processed"] is not None
        assert c["iterations"] == 1
        
    print("  [PASS] Loop controller executed and saved rewritten text and complexity scores.")
    print()

    # 6. Final PDF Reconstruction and Blending
    print("  --- Step 6: Layout reconstruction & PyMuPDF redaction blending ---")
    
    # Map rewritten chunks back to layout blocks
    mapped_blocks = mapper.map_rewritten_chunks(rewritten_chunk_map)

    # Invert the citation and math notation tokens
    translation = {}
    translation.update(citation_map)
    translation.update(math_map)

    dimensions = {0: (595.0, 842.0)} # Single-page document dimensions
    
    # Build Canvas Layer
    reconstructor = CanvasReconstructor()
    reconstructor.draw_canvas_layer(mapped_blocks, str(canvas_pdf), dimensions, translation)
    assert canvas_pdf.exists(), "Reconstructed canvas layer PDF not written to disk"
    
    # Merge layers
    merge_pdf_layers(str(uploaded_pdf), str(canvas_pdf), str(final_output_pdf), blocks)
    assert final_output_pdf.exists(), "Final output blended PDF not written to disk"

    # Open final PDF and scan text
    doc = fitz.open(str(final_output_pdf))
    assert len(doc) == 1, f"Expected 1 page, got {len(doc)}"
    p1_text = doc[0].get_text()
    doc.close()

    logger.info(f"Extracted page text: {p1_text!r}")

    # Assert unmasking took place correctly and original tokens exist
    assert "[1]" in p1_text, "Citation unmasking failed in E2E output"
    assert "B_I" in p1_text or "LOSS" in p1_text or "B =" in p1_text or "Loss =" in p1_text or "x_0" in p1_text, "Math unmasking failed in E2E output"
    assert "__CITATION_" not in p1_text, "Raw citation placeholder leaked in E2E output"
    assert "__MATH_BLOCK_" not in p1_text, "Raw math placeholder leaked in E2E output"

    print("  [PASS] Layout reconstruction layer blend verified: Tokens unmasked and placeholders absent.")
    print()

    # 7. Safety Cleanup and DB completion check
    print("  --- Step 7: Environment cleanup & database finalize verification ---")
    
    # Finalize db record
    async def finalize_db():
        async with get_async_session() as db:
            await db.execute(
                "UPDATE paper_runs SET status='completed' WHERE run_id = :run_id",
                {"run_id": run_id}
            )
            await db.commit()
    asyncio.run(finalize_db())

    # Check database status is completed
    row_final = asyncio.run(get_db_record())
    assert row_final["status"] == "completed"
    print("  [PASS] Database record updated to status='completed'.")

    # Run FileJanitor
    janitor = FileJanitor()
    janitor.clean_temp_assets([canvas_pdf], uploaded_pdf, final_output_pdf)
    assert not canvas_pdf.exists(), "FileJanitor failed to remove temp canvas layer"

    # Clean up test artifacts
    uploaded_pdf.unlink(missing_ok=True)
    final_output_pdf.unlink(missing_ok=True)
    
    # Clear DB records for clean workspace state
    async def cleanup_db():
        async with get_async_session() as db:
            await db.execute("DELETE FROM paper_runs WHERE run_id = :run_id", {"run_id": run_id})
            await db.execute("DELETE FROM text_chunks WHERE run_id = :run_id", {"run_id": run_id})
            await db.commit()
    asyncio.run(cleanup_db())
    print("  [PASS] Test directories cleaned and SQLite test records pruned.")

    print()
    print("Stage 50 integration check: ALL PASSED.")


if __name__ == "__main__":
    test_end_to_end_pipeline()
