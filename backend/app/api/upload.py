"""
backend/app/api/upload.py
=========================
PDF Upload API Core Processing Router.
Validates uploaded documents, logs active runs, and saves files asynchronously.
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

import uuid
import logging
from datetime import datetime
import sys
from pathlib import Path
import aiofiles
import fitz
from fastapi import APIRouter, UploadFile, File, HTTPException, status, BackgroundTasks, Request
from pydantic import BaseModel

# Resolve project root path
sys.path.append(str(Path(__file__).resolve().parents[3]))

from backend.app.core.config import get_settings
from backend.app.db.session import get_async_session

logger = logging.getLogger("humanizer_upload")

router = APIRouter()
settings = get_settings()

MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB

active_background_tasks: dict[str, asyncio.Task] = {}


# Background pipeline task coordinating E2E execution steps asynchronously
async def run_pipeline_in_background(run_id: str, file_path: Path):
    from backend.app.core.websocket_manager import ws_manager
    from backend.app.services.pdf_extractor import PdfLayoutExtractor
    from backend.app.services.citation_shield import shield_citations
    from backend.app.services.math_shield import shield_math
    from backend.app.services.chunker import SemanticChunker
    from backend.app.services.layout_mapper import DocumentStructureMap
    from backend.app.services.loop_controller import FeedbackLoopController
    from backend.app.services.canvas_builder import CanvasReconstructor
    from backend.app.services.pdf_merger import merge_pdf_layers
    from backend.app.services.file_janitor import FileJanitor
    from backend.app.db.session import get_async_session

    try:
        logger.info(f"Asynchronous pipeline execution started for run_id={run_id}")

        # 1. Parsing status
        await ws_manager.broadcast_global_message({
            "category": "progress",
            "progress_state": "parsing",
            "token_updates": {"google": 0, "groq": 0, "deepseek": 0}
        })

        extractor = PdfLayoutExtractor(file_path)
        with extractor:
            raw_blocks = extractor.extract_all_blocks()
            dimensions = {i: (page.rect.width, page.rect.height) for i, page in enumerate(extractor.doc)}
            page_count = extractor.page_count

        blocks = [b.to_dict() if hasattr(b, "to_dict") else b for b in raw_blocks]

        # Extract plain text for context extraction
        all_texts = [b["text"].strip() for b in blocks if b["block_type"] == 0]
        full_text = "\n\n".join(all_texts)

        # Call GlobalContextExtractor to create Master Summary
        from backend.app.services.global_context_extractor import GlobalContextExtractor
        context_extractor = GlobalContextExtractor()
        await context_extractor.extract_and_save_summary(full_text, run_id)

        # 2. Analyzing status
        await ws_manager.broadcast_global_message({
            "category": "progress",
            "progress_state": "analyzing",
            "token_updates": {"google": 0, "groq": 0, "deepseek": 0}
        })

        # Apply Token Shields
        shielded_cit, citation_map = shield_citations(full_text)
        shielded_both, math_map = shield_math(shielded_cit)

        paragraphs = shielded_both.split("\n\n")
        if len(paragraphs) != len(blocks):
            # Fallback to block-by-block shielding if split counts mismatch
            paragraphs = [shield_math(shield_citations(b["text"])[0])[0] for b in blocks]

        shielded_blocks = []
        for idx, b in enumerate(blocks):
            sb = dict(b)
            sb["text"] = paragraphs[idx] if idx < len(paragraphs) else b["text"]
            shielded_blocks.append(sb)

        # Chunking
        chunker = SemanticChunker(target_words=250, max_words=400)
        chunks = chunker.chunk_document(shielded_blocks)

        mapper = DocumentStructureMap(blocks)
        mapper.register_chunks(chunks)

        # 3. Rewriting status
        await ws_manager.broadcast_global_message({
            "category": "progress",
            "progress_state": "rewriting",
            "token_updates": {"google": 0, "groq": 0, "deepseek": 0}
        })

        feedback_loop_controller = FeedbackLoopController()
        rewritten_chunk_map = {}

        for chunk in chunks:
            # Seed chunk record in database first to prevent foreign key errors
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

            # Execute humanization loop (falls back cleanly across waterfall)
            res = await feedback_loop_controller.humanize_chunk(
                raw_text=chunk["text"],
                clean_text=chunk["text"],
                run_id=run_id,
                sequence_no=chunk["chunk_id"]
            )
            rewritten_chunk_map[chunk["chunk_id"]] = res["processed"]

        # 4. Reconstruction status
        await ws_manager.broadcast_global_message({
            "category": "progress",
            "progress_state": "reconstruction",
            "token_updates": {"google": 0, "groq": 0, "deepseek": 0}
        })

        mapped_blocks = mapper.map_rewritten_chunks(rewritten_chunk_map)

        # Translate tokens back
        translation = {}
        translation.update(citation_map)
        translation.update(math_map)

        storage_dir = file_path.parent
        canvas_pdf = storage_dir / f"{run_id}_canvas.pdf"
        final_pdf = storage_dir / f"{run_id}_final.pdf"

        reconstructor = CanvasReconstructor()
        reconstructor.draw_canvas_layer(mapped_blocks, str(canvas_pdf), dimensions, translation)

        # 5. Assembly status
        await ws_manager.broadcast_global_message({
            "category": "progress",
            "progress_state": "assembly",
            "token_updates": {"google": 0, "groq": 0, "deepseek": 0}
        })

        merge_pdf_layers(str(file_path), str(canvas_pdf), str(final_pdf), blocks)

        # 6. Database and websocket completed status
        async with get_async_session() as db:
            await db.execute(
                "UPDATE paper_runs SET status='completed' WHERE run_id = :run_id",
                {"run_id": run_id}
            )
            await db.commit()

        # Cleanup
        janitor = FileJanitor()
        janitor.clean_temp_assets([canvas_pdf], file_path, final_pdf)

        logger.info(f"Pipeline execution successfully completed for run_id={run_id}")
        await ws_manager.broadcast_global_message({
            "category": "progress",
            "progress_state": "completed",
            "token_updates": {"google": 0, "groq": 0, "deepseek": 0}
        })
    except Exception as e:
        logger.error(f"E2E Background pipeline execution failed for run_id={run_id}: {e}", exc_info=True)
        # Mark run as failed in database
        try:
            async with get_async_session() as db:
                await db.execute(
                    "UPDATE paper_runs SET status='failed' WHERE run_id = :run_id",
                    {"run_id": run_id}
                )
                await db.commit()
        except Exception as db_err:
            logger.error(f"Failed to set status to failed: {db_err}")

        await ws_manager.broadcast_global_message({
            "category": "progress",
            "progress_state": "failed",
            "token_updates": {"google": 0, "groq": 0, "deepseek": 0}
        })
    finally:
        active_background_tasks.pop(run_id, None)


@router.post("/api/upload")
async def upload_pdf(file: UploadFile = File(...), background_tasks: BackgroundTasks = None):
    """
    Receives multi-part file uploads, validates file type, content size,
    PDF signatures, saves binary file, and logs record to SQLite database.
    """
    # Basic extension validation
    filename = file.filename or ""
    if not filename.lower().endswith(".pdf"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid file extension. Only PDF documents are allowed."
        )

    # Read content up to size limit + 1 to detect overflow safely in memory
    try:
        contents = await file.read(MAX_FILE_SIZE + 1)
    except Exception as e:
        logger.error(f"Error reading file stream: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Failed to read file upload stream."
        )

    if len(contents) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File exceeds maximum size limit of {MAX_FILE_SIZE // (1024 * 1024)}MB."
        )

    # Enforce magic signature check for PDFs (%PDF-)
    if not contents.startswith(b"%PDF"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid PDF file signature."
        )

    run_id = str(uuid.uuid4())
    storage_dir = settings.storage_dir
    storage_dir.mkdir(parents=True, exist_ok=True)
    target_path = storage_dir / f"{run_id}.pdf"

    # Save to disk asynchronously
    async with aiofiles.open(target_path, "wb") as out_file:
        await out_file.write(contents)

    # Parse page count using PyMuPDF (fitz)
    try:
        doc = fitz.open(str(target_path))
        page_count = doc.page_count
        doc.close()
    except Exception as e:
        logger.error(f"PyMuPDF failed to parse page count for uploaded file: {e}")
        # Clean up corrupted file
        if target_path.exists():
            target_path.unlink()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file is corrupted or could not be parsed as a PDF."
        )

    # Persist tracking record to SQLite database
    async with get_async_session() as db:
        await db.execute(
            """
            INSERT INTO paper_runs (run_id, filename, total_chunks, start_time, status, master_summary)
            VALUES (:run_id, :filename, :total_chunks, :start_time, 'running', NULL)
            """,
            {
                "run_id": run_id,
                "filename": filename,
                "total_chunks": page_count,
                "start_time": datetime.utcnow().isoformat(),
            }
        )

    task = asyncio.create_task(run_pipeline_in_background(run_id, target_path))
    active_background_tasks[run_id] = task

    return {
        "status": "success",
        "run_id": run_id,
        "filename": filename,
        "page_count": page_count
    }


@router.get("/api/download/{run_id}")
async def download_processed_output(run_id: str):
    from fastapi.responses import FileResponse
    storage_dir = settings.storage_dir
    final_pdf = storage_dir / f"{run_id}_final.pdf"
    final_txt = storage_dir / f"{run_id}_humanized.txt"

    if not final_pdf.exists() and not final_txt.exists():
        raise HTTPException(
            status_code=404,
            detail="Processed document not found. Make sure the humanizer pipeline completed successfully."
        )

    # Resolve original filename from SQLite DB
    display_name = "document"
    try:
        async with get_async_session() as db:
            async with db.execute(
                "SELECT filename FROM paper_runs WHERE run_id = :run_id",
                {"run_id": run_id}
            ) as cur:
                row = await cur.fetchone()
                if row and row["filename"]:
                    display_name = row["filename"]
    except Exception as db_err:
        logger.error(f"Failed to query filename for run_id={run_id}: {db_err}")

    # Build clean output name: strip extension, append _humanized
    stem = Path(display_name).stem if display_name else "document"
    safe_stem = stem.replace(" ", "_")[:80]

    is_pdf_mode = display_name.lower().endswith(".pdf")

    if is_pdf_mode and final_pdf.exists():
        return FileResponse(
            path=str(final_pdf),
            media_type="application/pdf",
            filename=f"{safe_stem}_humanized.pdf"
        )
    else:
        return FileResponse(
            path=str(final_txt),
            media_type="text/plain; charset=utf-8",
            filename=f"{safe_stem}_humanized.txt"
        )


# ---------------------------------------------------------------------------
# Text Humanization Background Pipeline
# ---------------------------------------------------------------------------

async def run_text_pipeline_in_background(run_id: str, input_text: str, display_name: str):
    """Runs the full humanization loop on raw pasted text (no PDF source required)."""
    from backend.app.core.websocket_manager import ws_manager
    from backend.app.services.citation_shield import shield_citations
    from backend.app.services.math_shield import shield_math
    from backend.app.services.chunker import SemanticChunker
    from backend.app.services.loop_controller import FeedbackLoopController
    from backend.app.services.global_context_extractor import GlobalContextExtractor
    from backend.app.services.token_restorer import restore_shielded_tokens, UnmaskingError
    from backend.app.db.session import get_async_session

    try:
        logger.info(f"Text pipeline started for run_id={run_id}, name='{display_name}'")

        await ws_manager.broadcast_global_message({
            "category": "progress",
            "progress_state": "parsing",
            "token_updates": {"google": 0, "groq": 0, "deepseek": 0}
        })

        # Extract global context / master summary
        context_extractor = GlobalContextExtractor()
        await context_extractor.extract_and_save_summary(input_text, run_id)

        await ws_manager.broadcast_global_message({
            "category": "progress",
            "progress_state": "analyzing",
            "token_updates": {"google": 0, "groq": 0, "deepseek": 0}
        })

        # Shield citations and math formulas
        shielded_cit, citation_map = shield_citations(input_text)
        shielded_both, math_map = shield_math(shielded_cit)

        # Build block list compatible with SemanticChunker
        blocks = [{"text": para.strip(), "block_type": 0, "page": 0, "bbox": [0, 0, 595, 842]}
                  for para in shielded_both.split("\n\n") if para.strip()]
        if not blocks:
            blocks = [{"text": shielded_both, "block_type": 0, "page": 0, "bbox": [0, 0, 595, 842]}]

        # Chunk the text
        chunker = SemanticChunker(target_words=250, max_words=400)
        chunks = chunker.chunk_document(blocks)

        # Update total_chunks count in DB now we know it
        async with get_async_session() as db:
            await db.execute(
                "UPDATE paper_runs SET total_chunks = :tc WHERE run_id = :run_id",
                {"tc": len(chunks), "run_id": run_id}
            )
            await db.commit()

        await ws_manager.broadcast_global_message({
            "category": "progress",
            "progress_state": "rewriting",
            "token_updates": {"google": 0, "groq": 0, "deepseek": 0}
        })

        feedback_loop = FeedbackLoopController()
        humanized_parts = []

        for chunk in chunks:
            # Seed chunk record in DB
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

            res = await feedback_loop.humanize_chunk(
                raw_text=chunk["text"],
                clean_text=chunk["text"],
                run_id=run_id,
                sequence_no=chunk["chunk_id"]
            )
            humanized_parts.append(res["processed"])

        # Restore shielded placeholders
        translation = {}
        translation.update(citation_map)
        translation.update(math_map)
        full_humanized = "\n\n".join(humanized_parts)
        try:
            full_humanized = restore_shielded_tokens(full_humanized, translation)
        except UnmaskingError:
            # Soft fallback: replace what we can, leave residuals
            for ph, orig in translation.items():
                full_humanized = full_humanized.replace(ph, orig)

        # Persist humanized text to storage
        storage_dir = settings.storage_dir
        txt_path = storage_dir / f"{run_id}_humanized.txt"
        async with aiofiles.open(txt_path, "w", encoding="utf-8") as f:
            await f.write(full_humanized)

        # Mark run as completed in DB
        async with get_async_session() as db:
            await db.execute(
                "UPDATE paper_runs SET status='completed' WHERE run_id = :run_id",
                {"run_id": run_id}
            )
            await db.commit()

        logger.info(f"Text pipeline completed for run_id={run_id}")
        await ws_manager.broadcast_global_message({
            "category": "text_completed",
            "progress_state": "completed",
            "run_id": run_id,
            "token_updates": {"google": 0, "groq": 0, "deepseek": 0}
        })

    except Exception as e:
        logger.error(f"Text pipeline failed for run_id={run_id}: {e}", exc_info=True)
        try:
            async with get_async_session() as db:
                await db.execute(
                    "UPDATE paper_runs SET status='failed' WHERE run_id = :run_id",
                    {"run_id": run_id}
                )
                await db.commit()
        except Exception:
            pass
        await ws_manager.broadcast_global_message({
            "category": "progress",
            "progress_state": "failed",
            "token_updates": {"google": 0, "groq": 0, "deepseek": 0}
        })
    finally:
        active_background_tasks.pop(run_id, None)


# ---------------------------------------------------------------------------
# Text Humanization Request Schema
# ---------------------------------------------------------------------------

class TextHumanizeRequest(BaseModel):
    text: str
    name: str = ""


@router.post("/api/humanize-text")
async def humanize_text_endpoint(request: TextHumanizeRequest, background_tasks: BackgroundTasks = None):
    """
    Accept pasted plain text, auto-name it, run it through the full humanization
    pipeline in the background, and return a run_id for WebSocket status tracking.
    """
    text = request.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="Text cannot be empty.")
    if len(text) > 60000:
        raise HTTPException(status_code=400, detail="Text too long. Maximum 60,000 characters allowed.")

    import re
    # Auto-generate a clean name from first meaningful words if none provided
    name = request.name.strip()
    if not name:
        words = [re.sub(r'[^a-zA-Z0-9]', '', w) for w in text.split()[:7]]
        words = [w for w in words if w]
        name = "_".join(words[:6]) if words else "pasted_text"
        name = name[:60]
    else:
        # Sanitize custom name
        name = re.sub(r'[^a-zA-Z0-9_\-\s]', '', name).strip()
        name = re.sub(r'\s+', '_', name)[:60]

    run_id = str(uuid.uuid4())

    # Persist initial run record
    async with get_async_session() as db:
        await db.execute(
            """
            INSERT INTO paper_runs (run_id, filename, total_chunks, start_time, status, master_summary)
            VALUES (:run_id, :filename, 0, :start_time, 'running', NULL)
            """,
            {
                "run_id": run_id,
                "filename": name,
                "start_time": datetime.utcnow().isoformat(),
            }
        )
        await db.commit()

    task = asyncio.create_task(run_text_pipeline_in_background(run_id, text, name))
    active_background_tasks[run_id] = task

    return {"status": "success", "run_id": run_id, "name": name}


@router.get("/api/result/{run_id}")
async def get_text_result(run_id: str):
    """
    Returns the humanized text content for a completed text-mode run.
    Used by the frontend to display the result inline after processing.
    """
    storage_dir = settings.storage_dir
    txt_path = storage_dir / f"{run_id}_humanized.txt"
    if not txt_path.exists():
        raise HTTPException(
            status_code=404,
            detail="Text result not found. The run may still be processing or failed."
        )
    async with aiofiles.open(txt_path, "r", encoding="utf-8") as f:
        content = await f.read()
    return {"status": "success", "run_id": run_id, "content": content}


@router.delete("/api/runs")
async def delete_all_runs():
    """
    Delete all run records from the database and clear all files from storage.
    """
    # Cancel all currently active background processes
    for rid, task in list(active_background_tasks.items()):
        try:
            task.cancel()
            logger.info(f"Cancelled active run {rid} during purge.")
        except Exception as cancel_err:
            logger.warning(f"Error cancelling task {rid}: {cancel_err}")
    active_background_tasks.clear()

    storage_dir = settings.storage_dir
    try:
        async with get_async_session() as db:
            # Get all run ids
            async with db.execute("SELECT run_id FROM paper_runs") as cur:
                rows = await cur.fetchall()
                run_ids = [row["run_id"] for row in rows]

            # Delete files for each run
            for run_id in run_ids:
                for suffix in [".pdf", "_final.pdf", "_canvas.pdf", "_humanized.txt"]:
                    file_path = storage_dir / f"{run_id}{suffix}"
                    if file_path.exists():
                        try:
                            file_path.unlink()
                        except Exception as e:
                            logger.warning(f"Could not delete file {file_path}: {e}")

            # Truncate tables
            await db.execute("DELETE FROM text_chunks")
            await db.execute("DELETE FROM paper_runs")
            await db.commit()

        logger.info("All history runs cleared successfully.")
        return {"status": "success", "message": "All history cleared."}
    except Exception as e:
        logger.error(f"Failed to delete all runs: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to clear history: {str(e)}")


@router.delete("/api/runs/{run_id}")
async def delete_run(run_id: str):
    """
    Delete a run record from the database and remove all associated storage files.
    """
    # Hard-cancel active background process if it is currently processing
    if run_id in active_background_tasks:
        try:
            active_background_tasks[run_id].cancel()
            logger.info(f"Hard-cancelled active background process for run {run_id}")
        except Exception as cancel_err:
            logger.warning(f"Error cancelling task {run_id}: {cancel_err}")
        active_background_tasks.pop(run_id, None)

    storage_dir = settings.storage_dir
    # Remove all possible associated files
    for suffix in [".pdf", "_final.pdf", "_canvas.pdf", "_humanized.txt"]:
        file_path = storage_dir / f"{run_id}{suffix}"
        if file_path.exists():
            try:
                file_path.unlink()
                logger.info(f"Deleted storage file: {file_path.name}")
            except Exception as e:
                logger.warning(f"Could not delete file {file_path}: {e}")

    # Remove DB records
    async with get_async_session() as db:
        await db.execute("DELETE FROM text_chunks WHERE run_id = :run_id", {"run_id": run_id})
        await db.execute("DELETE FROM paper_runs WHERE run_id = :run_id", {"run_id": run_id})
        await db.commit()

    logger.info(f"Run {run_id} deleted from database.")
    return {"status": "deleted", "run_id": run_id}


# ---------------------------------------------------------------------------
# Stage 19 Verification Guardrail Test
# ---------------------------------------------------------------------------

def run_tests() -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import io

    print("=== Stage 19: PDF Upload Router Verification ===")
    print()

    # Create local FastAPI app and test upload route
    test_app = FastAPI()
    test_app.include_router(router)
    client = TestClient(test_app)

    # 1. Reject non-PDF file extension
    print("  --- Test 1: Reject invalid extension ---")
    files = {"file": ("test.txt", b"plain text content", "text/plain")}
    response = client.post("/api/upload", files=files)
    assert response.status_code == 400
    assert "extension" in response.json()["detail"]
    print("  [PASS] Reject non-PDF extension verified.")
    print()

    # 2. Reject magic bytes signature
    print("  --- Test 2: Reject invalid magic bytes signature ---")
    files = {"file": ("test.pdf", b"Not a PDF content stream", "application/pdf")}
    response = client.post("/api/upload", files=files)
    assert response.status_code == 400
    assert "signature" in response.json()["detail"]
    print("  [PASS] Reject invalid signature verified.")
    print()

    # 3. Reject oversized files
    print("  --- Test 3: Reject oversized files ---")
    oversized_data = b"%PDF-1.4\n" + b"X" * (MAX_FILE_SIZE + 10)
    files = {"file": ("oversized.pdf", oversized_data, "application/pdf")}
    response = client.post("/api/upload", files=files)
    assert response.status_code == 400
    assert "exceeds" in response.json()["detail"]
    print("  [PASS] Reject oversized files verified.")
    print()

    # 4. Successful upload and validation
    print("  --- Test 4: Successful PDF upload, page parse and DB entry ---")
    pdf_path = Path("test_textbox.pdf")
    if pdf_path.exists():
        with open(pdf_path, "rb") as f:
            pdf_bytes = f.read()
    else:
        pdf_bytes = (
            b"%PDF-1.4\n"
            b"1 0 obj <</Type /Catalog /Pages 2 0 R>> endobj\n"
            b"2 0 obj <</Type /Pages /Kids [3 0 R] /Count 1>> endobj\n"
            b"3 0 obj <</Type /Page /Parent 2 0 R /MediaBox [0 0 595 842]>> endobj\n"
            b"xref\n"
            b"0 4\n"
            b"0000000000 65535 f\n"
            b"0000000009 00000 n\n"
            b"0000000056 00000 n\n"
            b"0000000111 00000 n\n"
            b"trailer <</Size 4 /Root 1 0 R>>\n"
            b"startxref\n"
            b"190\n"
            b"%%EOF"
        )

    files = {"file": ("valid.pdf", pdf_bytes, "application/pdf")}
    response = client.post("/api/upload", files=files)
    assert response.status_code == 200, f"Expected 200, got {response.status_code} ({response.text})"
    data = response.json()
    assert data["status"] == "success"
    assert data["filename"] == "valid.pdf"
    assert data["page_count"] == 1
    
    run_id = data["run_id"]
    print(f"  [PASS] Valid upload response verified: {data}")

    # Verify database record
    import asyncio
    async def verify_db_entry():
        async with get_async_session() as db:
            async with db.execute(
                "SELECT filename, total_chunks, status FROM paper_runs WHERE run_id = :run_id",
                {"run_id": run_id}
            ) as cur:
                row = await cur.fetchone()
                return row
                
    row = asyncio.run(verify_db_entry())
    assert row is not None
    assert row["filename"] == "valid.pdf"
    assert row["total_chunks"] == 1
    assert row["status"] == "running"
    print("  [PASS] Database record matches and has status='running'.")

    # Clean up test output file and DB record
    uploaded_file_path = settings.storage_dir / f"{run_id}.pdf"
    if uploaded_file_path.exists():
        uploaded_file_path.unlink()
        
    async def cleanup_db():
        async with get_async_session() as db:
            await db.execute("DELETE FROM paper_runs WHERE run_id = :run_id", {"run_id": run_id})
            
    asyncio.run(cleanup_db())
    print("  [PASS] Test clean up completed successfully.")
    print()
    print("Stage 19 verification: ALL CHECKS PASSED.")


if __name__ == "__main__":
    run_tests()
