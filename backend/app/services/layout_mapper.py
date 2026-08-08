"""
backend/app/services/layout_mapper.py
======================================
Document Structural Layout Mapper for the Humanizer AI Engine.

Purpose:
  Maps processed/rewritten text chunks back to their original page layouts and
  spatial bounding coordinates in the PDF document. Ensures 100% integrity between
  what is rewritten and where it is re-inserted in the PDF layout.

Key Features:
  - Tracks chunk sequence hashes.
  - Maps rewritten chunk text back to original blocks (handling multi-block chunks
    proportionally or by paragraph splits).
  - Validates that the number of input chunks perfectly matches the number of
    generated output mappings.
  - Raises LayoutValidationError on count mismatch or mapping failures.
"""

from __future__ import annotations

import hashlib
from typing import Any, TypedDict


class LayoutValidationError(Exception):
    """Raised when there is a mismatch or validation failure in the layout mapper."""
    pass


class MappedBlock(TypedDict):
    page_no: int
    block_no: int
    x0: float
    y0: float
    x1: float
    y1: float
    original_text: str
    rewritten_text: str
    chunk_id: int
    original_index: int


class DocumentStructureMap:
    """
    Manages layout mapping and validation of rewritten text blocks.
    """

    def __init__(self, original_blocks: list[dict[str, Any]] | list[Any]):
        self.original_blocks: list[dict[str, Any]] = []
        for idx, block in enumerate(original_blocks):
            if hasattr(block, "to_dict"):
                b_dict = block.to_dict()
            elif hasattr(block, "__dict__"):
                b_dict = vars(block)
            elif isinstance(block, dict):
                b_dict = block
            else:
                b_dict = {"text": str(block), "block_no": idx, "page_no": 0}

            # Normalize coordinates and standard keys
            normalized = {
                "page_no": b_dict.get("page_no", 0),
                "block_no": b_dict.get("block_no", idx),
                "x0": float(b_dict.get("x0", 0.0)),
                "y0": float(b_dict.get("y0", 0.0)),
                "x1": float(b_dict.get("x1", 0.0)),
                "y1": float(b_dict.get("y1", 0.0)),
                "text": b_dict.get("text", "").strip(),
                "original_index": idx
            }
            self.original_blocks.append(normalized)

        self.registered_chunks: dict[int, dict[str, Any]] = {}

    def _compute_hash(self, text: str) -> str:
        """Helper to compute a stable SHA-256 hash of text."""
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def register_chunks(self, chunks: list[dict[str, Any]]) -> None:
        """
        Register the semantic chunks in the structure map and validate their block indices.

        Args:
          chunks: List of chunk dictionaries from SemanticChunker.
        """
        self.registered_chunks = {}
        for chunk in chunks:
            chunk_id = chunk["chunk_id"]
            para_indices = chunk["paragraph_indices"]
            chunk_text = chunk["text"]

            # Validate indices
            for p_idx in para_indices:
                # Find block by original list index first, fallback to block_no
                found = any(b["original_index"] == p_idx for b in self.original_blocks)
                if not found:
                    found = any(b["block_no"] == p_idx for b in self.original_blocks)
                if not found:
                    raise LayoutValidationError(
                        f"Chunk {chunk_id} references paragraph index {p_idx} "
                        f"which does not exist in the original PDF blocks."
                    )

            self.registered_chunks[chunk_id] = {
                "chunk_id": chunk_id,
                "paragraph_indices": para_indices,
                "text": chunk_text,
                "text_hash": self._compute_hash(chunk_text)
            }

    def map_rewritten_chunks(self, rewritten_chunks: dict[int, str]) -> list[MappedBlock]:
        """
        Maps rewritten chunk texts back to their original PDF blocks.

        Args:
          rewritten_chunks: A dictionary mapping chunk_id to rewritten text.

        Returns:
          A list of mapped blocks with original coordinates and new rewritten text.
        """
        # Guardrail: Count verification check
        expected_ids = set(self.registered_chunks.keys())
        received_ids = set(rewritten_chunks.keys())

        if expected_ids != received_ids:
            missing = expected_ids - received_ids
            extra = received_ids - expected_ids
            msg = "Layout mapping count mismatch. "
            if missing:
                msg += f"Missing chunk IDs: {sorted(list(missing))}. "
            if extra:
                msg += f"Unexpected extra chunk IDs: {sorted(list(extra))}. "
            raise LayoutValidationError(msg)

        mapped_blocks: list[MappedBlock] = []

        for chunk_id, chunk_info in self.registered_chunks.items():
            rewritten_text = rewritten_chunks[chunk_id].strip()
            para_indices = chunk_info["paragraph_indices"]

            # Get original blocks corresponding to this chunk
            chunk_blocks = []
            for p_idx in para_indices:
                blocks_found = [b for b in self.original_blocks if b["original_index"] == p_idx]
                if not blocks_found:
                    blocks_found = [b for b in self.original_blocks if b["block_no"] == p_idx]
                for b in blocks_found:
                    if b not in chunk_blocks:
                        chunk_blocks.append(b)

            # Distribute rewritten text across the chunk blocks
            num_blocks = len(chunk_blocks)
            if num_blocks == 0:
                raise LayoutValidationError(f"No original blocks found for chunk {chunk_id}")

            distributed_texts: list[str] = []

            if num_blocks == 1:
                distributed_texts = [rewritten_text]
            else:
                # Attempt split by double newline first
                parts = [p.strip() for p in rewritten_text.split("\n\n") if p.strip()]
                if len(parts) == num_blocks:
                    distributed_texts = parts
                else:
                    # Attempt split by single newline
                    parts = [p.strip() for p in rewritten_text.split("\n") if p.strip()]
                    if len(parts) == num_blocks:
                        distributed_texts = parts
                    else:
                        # Fallback: proportional word-count distribution
                        orig_words = [max(1, len(b["text"].split())) for b in chunk_blocks]
                        total_orig_words = sum(orig_words)
                        
                        rewritten_words = rewritten_text.split()
                        total_rew_words = len(rewritten_words)

                        start_idx = 0
                        for i in range(num_blocks - 1):
                            ratio = orig_words[i] / total_orig_words
                            words_to_take = max(1, int(total_rew_words * ratio))
                            end_idx = min(total_rew_words, start_idx + words_to_take)
                            
                            distributed_texts.append(" ".join(rewritten_words[start_idx:end_idx]))
                            start_idx = end_idx
                        
                        # Add remaining words to the last block
                        distributed_texts.append(" ".join(rewritten_words[start_idx:]))

            # Assemble mapped blocks
            for i, block in enumerate(chunk_blocks):
                mapped_blocks.append({
                    "page_no": block["page_no"],
                    "block_no": block["block_no"],
                    "x0": block["x0"],
                    "y0": block["y0"],
                    "x1": block["x1"],
                    "y1": block["y1"],
                    "original_text": block["text"],
                    "rewritten_text": distributed_texts[i],
                    "chunk_id": chunk_id,
                    "original_index": block["original_index"]
                })

        return mapped_blocks


# ---------------------------------------------------------------------------
# Stage 11 Verification Guardrail
# ---------------------------------------------------------------------------

def run_tests() -> None:
    import sys
    print("=== Stage 11: Layout Mapper Verification Guardrail ===")
    print()

    # Create dummy original blocks
    dummy_blocks = [
        {"page_no": 0, "block_no": 100, "x0": 50.0, "y0": 100.0, "x1": 500.0, "y1": 150.0, "text": "This is block one text."},
        {"page_no": 0, "block_no": 101, "x0": 50.0, "y0": 160.0, "x1": 500.0, "y1": 210.0, "text": "This is block two text."},
        {"page_no": 1, "block_no": 200, "x0": 50.0, "y0": 100.0, "x1": 500.0, "y1": 150.0, "text": "This is block three text."}
    ]

    mapper = DocumentStructureMap(dummy_blocks)

    # 1. Register valid chunks
    chunks = [
        {"chunk_id": 0, "paragraph_indices": [100, 101], "text": "This is block one text. This is block two text."},
        {"chunk_id": 1, "paragraph_indices": [200], "text": "This is block three text."}
    ]

    print("  --- Test 1: Register valid chunks ---")
    mapper.register_chunks(chunks)
    print("  [PASS] Registration completed successfully without errors.")
    print()

    # 2. Register invalid chunk (index mismatch check)
    print("  --- Test 2: Index mismatch check ---")
    bad_chunks = [
        {"chunk_id": 0, "paragraph_indices": [999], "text": "Invalid index."}
    ]
    try:
        mapper.register_chunks(bad_chunks)
        print("  [FAIL] Failed to raise LayoutValidationError for invalid paragraph index.")
        sys.exit(1)
    except LayoutValidationError as e:
        print(f"  [PASS] LayoutValidationError raised correctly: {e}")
    print()

    # Re-register valid chunks for mapping tests
    mapper.register_chunks(chunks)

    # 3. Successful mapping with paragraph splits
    print("  --- Test 3: Mapping with paragraph splits ---")
    rewritten = {
        0: "This is rewritten block one.\n\nThis is rewritten block two.",
        1: "This is rewritten block three."
    }

    mapped = mapper.map_rewritten_chunks(rewritten)
    for b in mapped:
        print(f"    Page {b['page_no']} Block {b['block_no']} ({b['x0']},{b['y0']}): {b['rewritten_text']!r}")

    assert len(mapped) == 3, f"Expected 3 mapped blocks, got {len(mapped)}"
    assert mapped[0]["rewritten_text"] == "This is rewritten block one."
    assert mapped[1]["rewritten_text"] == "This is rewritten block two."
    assert mapped[2]["rewritten_text"] == "This is rewritten block three."
    print("  [PASS] Paragraph-splitting and mapping matches original blocks.")
    print()

    # 4. Successful mapping with proportional fallback
    print("  --- Test 4: Mapping with proportional fallback ---")
    rewritten_fallback = {
        0: "This is rewritten block one with extra words and block two mixed in without separators.",
        1: "Rewritten block three."
    }
    mapped_fb = mapper.map_rewritten_chunks(rewritten_fallback)
    assert len(mapped_fb) == 3
    print("    Block 0 original: 'This is block one text.'")
    print(f"    Block 0 mapped  : {mapped_fb[0]['rewritten_text']!r}")
    print("    Block 1 original: 'This is block two text.'")
    print(f"    Block 1 mapped  : {mapped_fb[1]['rewritten_text']!r}")
    assert len(mapped_fb[0]["rewritten_text"]) > 0
    assert len(mapped_fb[1]["rewritten_text"]) > 0
    print("  [PASS] Proportional distribution fallback works.")
    print()

    # 5. Guardrail check: count mismatch error
    print("  --- Test 5: Guardrail count mismatch check ---")
    bad_rewritten = {
        0: "Missing chunk 1 rewritten text."
    }
    try:
        mapper.map_rewritten_chunks(bad_rewritten)
        print("  [FAIL] Failed to raise LayoutValidationError for count mismatch.")
        sys.exit(1)
    except LayoutValidationError as e:
        print(f"  [PASS] LayoutValidationError raised correctly: {e}")
    print()

    print("Stage 11 guardrail: ALL TESTS PASSED.")


if __name__ == "__main__":
    run_tests()
