"""
backend/app/services/file_janitor.py
====================================
File Janitor & Lock Release Utility.
Purges intermediate canvas files and scratch assets safely post-assembly.
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
import gc
import os
from pathlib import Path

# Resolve project root path
sys.path.append(str(Path(__file__).resolve().parents[3]))

logger = logging.getLogger("humanizer_file_janitor")


class JanitorSafetyError(Exception):
    """Raised when a safety check prevents deletion of protected primary files."""
    pass


class FileJanitor:
    """
    Manages intermediate asset deletions.
    Ensures safe releases of file handles prior to deletion to prevent OS lock crashes.
    """

    def __init__(self):
        pass

    def release_file_handles(self) -> None:
        """
        Force runs garbage collection to release unclosed PyMuPDF document handles
        or ReportLab file objects that might be locking folders/files on Windows.
        """
        gc.collect()

    def clean_temp_assets(
        self,
        temp_paths: list[str | Path],
        original_pdf: str | Path,
        final_pdf: str | Path
    ) -> list[str]:
        """
        Cleans up a list of temporary build files/folders.
        Enforces a compulsory guardrail: never delete original_pdf or final_pdf.
        
        Returns a list of successfully deleted file path strings.
        """
        # Resolve target guardrail files to absolute forms for comparison
        orig_abs = Path(original_pdf).resolve()
        final_abs = Path(final_pdf).resolve()

        deleted_files: list[str] = []

        self.release_file_handles()

        for path in temp_paths:
            p = Path(path).resolve()
            
            # Enforce path protection check
            if p == orig_abs:
                logger.error(f"Janitor safety violation: attempt to delete original file: {p}")
                raise JanitorSafetyError(f"Safety violation: cannot delete original input file: {p}")
            if p == final_abs:
                logger.error(f"Janitor safety violation: attempt to delete final output export: {p}")
                raise JanitorSafetyError(f"Safety violation: cannot delete final output export file: {p}")

            # General sanity check: do not delete directories that are root/project root/system
            # Or parent dirs of the original file
            if p in orig_abs.parents or p in final_abs.parents:
                logger.error(f"Janitor safety violation: attempt to delete system workspace container: {p}")
                raise JanitorSafetyError(f"Safety violation: cannot delete workspace parent directory: {p}")

            if not p.exists():
                continue

            try:
                if p.is_file():
                    # Attempt deletion
                    # Retry once after another collect if permission error occurs (Windows lock)
                    try:
                        p.unlink()
                    except PermissionError:
                        logger.warning(f"File locked: {p}. Retrying GC collection...")
                        self.release_file_handles()
                        p.unlink()
                    deleted_files.append(str(p))
                    logger.info(f"Janitor removed temporary file: {p}")
                elif p.is_dir():
                    # Check if empty or clean sub-files
                    # We only allow unlinking files inside temp folders, not recursive rmtree for general safety
                    for sub_file in list(p.iterdir()):
                        sub_abs = sub_file.resolve()
                        if sub_abs != orig_abs and sub_abs != final_abs:
                            sub_abs.unlink(missing_ok=True)
                    p.rmdir()
                    deleted_files.append(str(p))
                    logger.info(f"Janitor removed temporary folder: {p}")
            except Exception as e:
                logger.error(f"Janitor failed to delete temporary path {p}: {e}")

        return deleted_files


# ---------------------------------------------------------------------------
# Stage 41 Verification Guardrail Tests
# ---------------------------------------------------------------------------
def run_tests() -> None:
    print("=== Stage 41: File Janitor Verification ===")
    print()

    janitor = FileJanitor()

    # Create dummy files
    orig = Path("test_orig.pdf")
    final = Path("test_final.pdf")
    temp1 = Path("test_temp1.pdf")
    temp2 = Path("test_temp2.pdf")

    for p in [orig, final, temp1, temp2]:
        p.write_text("dummy pdf contents")

    # 1. Successful cleanup
    print("  --- Test 1: Clean temporary files ---")
    deleted = janitor.clean_temp_assets([temp1, temp2], orig, final)
    assert len(deleted) == 2
    assert not temp1.exists()
    assert not temp2.exists()
    print("  [PASS] Deleted temporary assets successfully.")
    print()

    # 2. Safety check original file protection
    print("  --- Test 2: Protect original uploaded file guardrail ---")
    try:
        janitor.clean_temp_assets([orig], orig, final)
        assert False, "Expected JanitorSafetyError"
    except JanitorSafetyError as e:
        print(f"  [PASS] Correctly rejected original file deletion: {e}")
    assert orig.exists()
    print()

    # 3. Safety check final export file protection
    print("  --- Test 3: Protect final export file guardrail ---")
    try:
        janitor.clean_temp_assets([final], orig, final)
        assert False, "Expected JanitorSafetyError"
    except JanitorSafetyError as e:
        print(f"  [PASS] Correctly rejected final export file deletion: {e}")
    assert final.exists()
    print()

    # Clean up test files
    orig.unlink(missing_ok=True)
    final.unlink(missing_ok=True)
    print("Stage 41 verification: ALL CHECKS PASSED.")


if __name__ == "__main__":
    run_tests()
