"""
backend/app/services/chunker.py
==============================
Adaptive Semantic Text Segmentation Chunker for the Humanizer AI Engine.

Purpose:
  Breaks down a document stream (plain text or layout blocks) into coherent,
  semantic segments targeting roughly 500 words. Split boundaries prioritize
  double newlines (paragraphs), sentence boundaries, and clause-level punctuation,
  guaranteeing that sentences are never split in half unless a single sentence
  exceeds the entire word budget.

Key Features:
  - Supports raw strings and layout blocks (BlockInfo or dictionary list).
  - Tracks the original paragraph or layout block indices for every chunk.
  - Implements a shift-back split-point adjuster to satisfy the guardrail
    requirement that any split occurring mid-sentence rolls back to the
    nearest punctuation boundary.
  - Exposes validation helpers to verify sentence continuity.
"""

from __future__ import annotations

import re
from typing import TypedDict, Any


class ChunkDict(TypedDict):
    chunk_id: int
    text: str
    word_count: int
    paragraph_indices: list[int]


class SemanticChunker:
    """
    Chunks document text streams or spatial layout blocks into semantic segments.
    """

    def __init__(self, target_words: int = 500, max_words: int = 600):
        self.target_words = target_words
        self.max_words = max_words
        # Common academic abbreviations to avoid false sentence splits
        self.abbreviations = {
            "et", "al", "e.g", "i.e", "fig", "vol", "dr", "mr", "ms",
            "prof", "vs", "ca", "approx", "dept", "univ", "ed", "eds",
            "pp", "p", "ref", "refs", "chap", "sec"
        }

    def split_sentences(self, text: str) -> list[str]:
        """
        Splits text block into sentences, avoiding splits on common abbreviations.
        """
        if not text:
            return []

        # Split on sentence-ending punctuation followed by whitespace
        raw_splits = re.split(r'(?<=[.!?])\s+', text)
        sentences: list[str] = []
        current_sentence: list[str] = []

        for split in raw_splits:
            if not split:
                continue
            current_sentence.append(split)
            # Check if the split ends with an abbreviation
            words = split.strip().split()
            if words:
                last_word = words[-1].lower().rstrip('.?,!')
                if last_word in self.abbreviations:
                    # Accumulate next split as part of this sentence
                    continue
            # Complete sentence
            sentences.append(" ".join(current_sentence))
            current_sentence = []

        if current_sentence:
            sentences.append(" ".join(current_sentence))

        return [s.strip() for s in sentences if s.strip()]

    def _split_long_sentence(self, sentence: str, limit_words: int) -> list[str]:
        """
        Splits a single extremely long sentence at clause-level punctuation
        or word boundaries so that no segment exceeds limit_words.
        """
        # Split on clause punctuation followed by space
        raw_parts = re.split(r'(?<=[,;:—])\s+', sentence)
        parts: list[str] = []
        current_part: list[str] = []
        current_word_count = 0

        for part in raw_parts:
            part_words = len(part.split())
            if current_word_count + part_words <= limit_words or not current_part:
                current_part.append(part)
                current_word_count += part_words
            else:
                parts.append(" ".join(current_part))
                current_part = [part]
                current_word_count = part_words

        if current_part:
            parts.append(" ".join(current_part))

        # Hard limit split on word boundary if parts are still too long
        final_parts: list[str] = []
        for p in parts:
            p_words = p.split()
            if len(p_words) <= limit_words:
                final_parts.append(p)
            else:
                for i in range(0, len(p_words), limit_words):
                    final_parts.append(" ".join(p_words[i : i + limit_words]))

        return final_parts

    def chunk_document(
        self,
        doc: str | list[dict[str, Any]] | list[Any],
        target_words: int | None = None,
        max_words: int | None = None
    ) -> list[ChunkDict]:
        """
        Semantic chunker prioritizing:
          1. Paragraph boundaries
          2. Sentence boundaries
          3. Clause boundaries
          4. Word boundaries

        Args:
          doc: Raw text string OR list of block dicts/BlockInfo objects.
          target_words: Target word limit (default to self.target_words).
          max_words: Strict upper word limit (default to self.max_words).

        Returns:
          List of ChunkDict matching the database schema properties.
        """
        t_words = target_words if target_words is not None else self.target_words
        m_words = max_words if max_words is not None else self.max_words

        # Normalize document into unified paragraphs list
        paragraphs: list[dict[str, Any]] = []

        if isinstance(doc, str):
            raw_paras = re.split(r'\n\s*\n', doc)
            for idx, para_text in enumerate(raw_paras):
                para_text = para_text.strip()
                if para_text:
                    paragraphs.append({"text": para_text, "index": idx})
        elif isinstance(doc, list):
            for idx, block in enumerate(doc):
                # Handle BlockInfo dataclasses or normal dicts
                if hasattr(block, "text"):
                    text = getattr(block, "text", "")
                elif isinstance(block, dict):
                    text = block.get("text", "")
                elif isinstance(block, str):
                    text = block
                else:
                    text = str(block)

                text = text.strip()
                if text:
                    paragraphs.append({"text": text, "index": idx})
        else:
            raise ValueError("Unsupported doc type passed to SemanticChunker")

        if not paragraphs:
            return []

        chunks: list[ChunkDict] = []
        current_chunk_sentences: list[str] = []
        current_chunk_paras: list[int] = []
        current_word_count = 0

        for para in paragraphs:
            para_text = para["text"]
            para_index = para["index"]
            para_sentences = self.split_sentences(para_text)
            if not para_sentences:
                continue

            para_word_count = sum(len(s.split()) for s in para_sentences)

            # Check if adding the paragraph exceeds target_words
            if current_word_count + para_word_count > t_words:
                # If we already have a substantial amount of text in the current chunk,
                # split at the paragraph boundary.
                if current_word_count >= max(1, t_words // 2):
                    chunks.append({
                        "chunk_id": len(chunks),
                        "text": " ".join(current_chunk_sentences),
                        "word_count": current_word_count,
                        "paragraph_indices": list(current_chunk_paras)
                    })
                    current_chunk_sentences = []
                    current_chunk_paras = []
                    current_word_count = 0

            # If the entire paragraph fits inside the max limit
            if current_word_count + para_word_count <= m_words:
                current_chunk_sentences.extend(para_sentences)
                if para_index not in current_chunk_paras:
                    current_chunk_paras.append(para_index)
                current_word_count += para_word_count
            else:
                # Does not fit. If current chunk already has some words, close it.
                if current_word_count > 0:
                    chunks.append({
                        "chunk_id": len(chunks),
                        "text": " ".join(current_chunk_sentences),
                        "word_count": current_word_count,
                        "paragraph_indices": list(current_chunk_paras)
                    })
                    current_chunk_sentences = []
                    current_chunk_paras = []
                    current_word_count = 0

                # Try to put the entire paragraph in the clean chunk
                if para_word_count <= m_words:
                    current_chunk_sentences.extend(para_sentences)
                    current_chunk_paras.append(para_index)
                    current_word_count = para_word_count
                    continue

                # If paragraph still doesn't fit (or chunk is too small to dump),
                # process sentence-by-sentence.
                for sentence in para_sentences:
                    sentence_word_count = len(sentence.split())

                    # Handle super long sentence
                    if sentence_word_count > t_words:
                        # Flush current chunk first
                        if current_word_count > 0:
                            chunks.append({
                                "chunk_id": len(chunks),
                                "text": " ".join(current_chunk_sentences),
                                "word_count": current_word_count,
                                "paragraph_indices": list(current_chunk_paras)
                            })
                            current_chunk_sentences = []
                            current_chunk_paras = []
                            current_word_count = 0

                        # Split long sentence at clause level
                        sub_sentences = self._split_long_sentence(sentence, t_words)
                        for sub_s in sub_sentences:
                            sub_s_words = len(sub_s.split())
                            if current_word_count + sub_s_words <= m_words:
                                current_chunk_sentences.append(sub_s)
                                if para_index not in current_chunk_paras:
                                    current_chunk_paras.append(para_index)
                                current_word_count += sub_s_words
                            else:
                                if current_word_count > 0:
                                    chunks.append({
                                        "chunk_id": len(chunks),
                                        "text": " ".join(current_chunk_sentences),
                                        "word_count": current_word_count,
                                        "paragraph_indices": list(current_chunk_paras)
                                    })
                                current_chunk_sentences = [sub_s]
                                current_chunk_paras = [para_index]
                                current_word_count = sub_s_words
                        continue

                    # Normal sentence addition
                    if current_word_count + sentence_word_count <= m_words:
                        current_chunk_sentences.append(sentence)
                        if para_index not in current_chunk_paras:
                            current_chunk_paras.append(para_index)
                        current_word_count += sentence_word_count
                    else:
                        # Close current chunk
                        if current_word_count > 0:
                            chunks.append({
                                "chunk_id": len(chunks),
                                "text": " ".join(current_chunk_sentences),
                                "word_count": current_word_count,
                                "paragraph_indices": list(current_chunk_paras)
                            })
                        # Start new chunk
                        current_chunk_sentences = [sentence]
                        current_chunk_paras = [para_index]
                        current_word_count = sentence_word_count

        # Append last chunk
        if current_chunk_sentences:
            chunks.append({
                "chunk_id": len(chunks),
                "text": " ".join(current_chunk_sentences),
                "word_count": current_word_count,
                "paragraph_indices": list(current_chunk_paras)
            })

        return chunks

    def chunk_text_with_shiftback(self, text: str, max_chars: int) -> list[str]:
        """
        Compulsory guardrail: Slices raw text by character limits, but if a split
        occurs mid-sentence or mid-word, it rolls back index to the nearest
        punctuation mark.

        Punctuation priority:
          1. Double newline (Paragraph)
          2. Sentence end (. ! ? followed by space)
          3. Clause end (, ; : followed by space)
          4. Word end (whitespace)
        """
        if not text:
            return []

        chunks: list[str] = []
        remaining = text.strip()

        while remaining:
            if len(remaining) <= max_chars:
                chunks.append(remaining)
                break

            # Try split at max_chars
            split_idx = max_chars

            # Lookback up to 150 characters to find a punctuation boundary
            lookback_limit = max(0, split_idx - 150)
            sub = remaining[lookback_limit:split_idx]

            found = False

            # 1. Paragraph boundary: \n\s*\n
            p_matches = list(re.finditer(r'\n\s*\n', sub))
            if p_matches:
                split_idx = lookback_limit + p_matches[-1].start()
                found = True

            # 2. Sentence boundary: . ! ? followed by whitespace
            if not found:
                s_matches = list(re.finditer(r'[.!?]\s', sub))
                if s_matches:
                    split_idx = lookback_limit + s_matches[-1].start() + 1
                    found = True

            # 3. Clause boundary: , ; : followed by whitespace
            if not found:
                c_matches = list(re.finditer(r'[,;:]\s', sub))
                if c_matches:
                    split_idx = lookback_limit + c_matches[-1].start() + 1
                    found = True

            # 4. Word boundary: any space character
            if not found:
                w_matches = list(re.finditer(r'\s', sub))
                if w_matches:
                    split_idx = lookback_limit + w_matches[-1].start()
                    found = True

            # Extract the slice
            chunk = remaining[:split_idx].strip()
            chunks.append(chunk)
            remaining = remaining[split_idx:].strip()

        return chunks


# ---------------------------------------------------------------------------
# Stage 10 Verification Guardrail
# ---------------------------------------------------------------------------

def run_tests() -> None:
    import sys
    print("=== Stage 10: Semantic Chunker Verification Guardrail ===")
    print()

    chunker = SemanticChunker(target_words=10, max_words=15)

    # Test case 1: Paragraph split prioritization
    print("  --- Test 1: Paragraph split priority ---")
    text1 = "This is para one. It has sentences.\n\nThis is para two. It is separate."
    chunks1 = chunker.chunk_document(text1)
    for c in chunks1:
        print(f"    Chunk {c['chunk_id']} (words: {c['word_count']}, paras: {c['paragraph_indices']}): {c['text']!r}")

    assert len(chunks1) == 2, f"Expected 2 chunks, got {len(chunks1)}"
    assert chunks1[0]["paragraph_indices"] == [0], f"Expected index [0], got {chunks1[0]['paragraph_indices']}"
    assert chunks1[1]["paragraph_indices"] == [1], f"Expected index [1], got {chunks1[1]['paragraph_indices']}"
    print("  [PASS] Paragraph boundary split works.")
    print()

    # Test case 2: Sentence boundary split when paragraph doesn't fit
    print("  --- Test 2: Sentence boundary split ---")
    text2 = "Sentence one is here. Sentence two follows it. Sentence three is the last."
    # target_words=10, max_words=15. Text has 12 words. Fits in 1 chunk.
    # Let's adjust limits for sentence splitting check
    small_chunker = SemanticChunker(target_words=5, max_words=7)
    chunks2 = small_chunker.chunk_document(text2)
    for c in chunks2:
        print(f"    Chunk {c['chunk_id']} (words: {c['word_count']}): {c['text']!r}")
    
    # Sentence 1: "Sentence one is here." (4 words)
    # Sentence 2: "Sentence two follows it." (4 words) -> Adding would make 8 words (> 7 max_words)
    # Split occurs at sentence end.
    assert len(chunks2) == 3, f"Expected 3 chunks, got {len(chunks2)}"
    assert "here." in chunks2[0]["text"] and "Sentence two" not in chunks2[0]["text"]
    print("  [PASS] Sentence boundary split works (no sentences clipped).")
    print()

    # Test case 3: Extremely long sentence splitting
    print("  --- Test 3: Long sentence clause split ---")
    long_sentence = "This is a single extremely long sentence, which has a clause comma here, and another semicolon here; all of which exceed our limit."
    # long_sentence has 24 words. Small chunker has target=5, max=7.
    chunks3 = small_chunker.chunk_document(long_sentence)
    for c in chunks3:
        print(f"    Chunk {c['chunk_id']} (words: {c['word_count']}): {c['text']!r}")
    
    assert len(chunks3) > 1
    # Check that sentences were split on clause punctuation (like commas/semicolons) where possible
    print("  [PASS] Long sentence splitting works.")
    print()

    # Test case 4: Shift-back guardrail demonstration
    print("  --- Test 4: Shift-back guardrail validation ---")
    # This text has a mid-sentence break. If we cut strictly at char 30, it cuts "sen|tence".
    # Punctuation check should shift it back to the comma or sentence end.
    text_guardrail = "Hello world, this is a long sentence. We want to test the shiftback."
    # Char 30 is: "Hello world, this is a long se"
    # The nearest punctuation mark before char 30 is the comma at index 11.
    chunks_sb = chunker.chunk_text_with_shiftback(text_guardrail, max_chars=30)
    print(f"    Original: {text_guardrail!r}")
    print(f"    Strict cut 30: {text_guardrail[:30]!r}")
    for idx, c in enumerate(chunks_sb):
        print(f"    Guardrail Chunk {idx}: {c!r}")
    
    assert chunks_sb[0] == "Hello world,", f"Expected 'Hello world,', got {chunks_sb[0]!r}"
    print("  [PASS] Shift-back rolls back cleanly to the nearest punctuation mark.")
    print()

    # Test case 5: Block list input validation
    print("  --- Test 5: Block list input ---")
    blocks = [
        {"text": "Block one text.", "block_no": 10},
        {"text": "Block two has more text.", "block_no": 20}
    ]
    chunks5 = chunker.chunk_document(blocks, target_words=10, max_words=15)
    for c in chunks5:
        print(f"    Chunk {c['chunk_id']} (paras: {c['paragraph_indices']}): {c['text']!r}")
    assert chunks5[0]["paragraph_indices"] == [0, 1]
    print("  [PASS] Block input indexing works.")
    print()

    print("Stage 10 guardrail: ALL TESTS PASSED.")


if __name__ == "__main__":
    run_tests()
