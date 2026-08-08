"""
backend/app/services/pdf_extractor.py
======================================
PyMuPDF-based PDF layout extraction service for the Humanizer AI Engine.

Provides the `PdfLayoutExtractor` class which:
  - Opens a target PDF document via fitz (PyMuPDF).
  - Iterates all pages, extracting text blocks via `.get_text("blocks")`.
  - Captures spatial bounding coordinates (X0, Y0, X1, Y1) per block.
  - Records block index, line number, page number, and font attributes.
  - Returns structured JSON-serializable block dictionaries.
  - Applies guardrail recovery for null/malformed coordinate blocks.

Output schema per block:
  {
    "page_no":     int,       # 0-indexed page number
    "block_no":    int,       # block index within the page
    "x0":          float,     # left edge bounding coordinate
    "y0":          float,     # top edge bounding coordinate
    "x1":          float,     # right edge bounding coordinate
    "y1":          float,     # bottom edge bounding coordinate
    "width":       float,     # derived: x1 - x0
    "height":      float,     # derived: y1 - y0
    "text":        str,       # extracted raw text content
    "word_count":  int,       # rough word count for chunker planning
    "block_type":  int,       # 0 = text, 1 = image (PyMuPDF convention)
    "lines":       list[dict] # per-line span data with font info
  }
"""

import json
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class SpanInfo:
    """Font-level span data within a text line."""
    font:        str   = "unknown"
    font_size:   float = 12.0
    font_flags:  int   = 0       # bitmask: bold=16, italic=2, etc.
    color:       int   = 0       # RGB packed integer
    text:        str   = ""

    @property
    def is_bold(self) -> bool:
        return bool(self.font_flags & 16)

    @property
    def is_italic(self) -> bool:
        return bool(self.font_flags & 2)


@dataclass
class LineInfo:
    """One text line within a block, with its own bounding box."""
    line_no:  int          = 0
    x0:       float        = 0.0
    y0:       float        = 0.0
    x1:       float        = 0.0
    y1:       float        = 0.0
    text:     str          = ""
    spans:    list[SpanInfo] = field(default_factory=list)


@dataclass
class BlockInfo:
    """One spatial text block on a PDF page."""
    page_no:    int            = 0
    block_no:   int            = 0
    x0:         float          = 0.0
    y0:         float          = 0.0
    x1:         float          = 0.0
    y1:         float          = 0.0
    width:      float          = 0.0
    height:     float          = 0.0
    text:       str            = ""
    word_count: int            = 0
    block_type: int            = 0      # 0=text, 1=image
    lines:      list[LineInfo] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Default coordinate constants (guardrail fallback)
# ---------------------------------------------------------------------------
_DEFAULT_BBOX = (0.0, 0.0, 595.0, 842.0)   # A4 page dimensions
_MIN_COORD_VALUE = -9999.0
_MAX_COORD_VALUE = 99999.0


def _sanitize_coord(value: object, fallback: float) -> float:
    """
    Ensure a coordinate value is a valid float within plausible bounds.
    Falls back to `fallback` if the value is None, non-numeric, or out of range.
    """
    try:
        v = float(value)
        if _MIN_COORD_VALUE <= v <= _MAX_COORD_VALUE:
            return v
    except (TypeError, ValueError):
        pass
    return fallback


# ---------------------------------------------------------------------------
# PdfLayoutExtractor
# ---------------------------------------------------------------------------

class PdfLayoutExtractor:
    """
    Extracts spatially-indexed text blocks from a PDF document.

    Usage:
        extractor = PdfLayoutExtractor("path/to/paper.pdf")
        blocks = extractor.extract_all_blocks()
        summary = extractor.get_extraction_summary()
    """

    def __init__(self, pdf_path: str | Path):
        self.pdf_path = Path(pdf_path)
        self._doc = None
        self._blocks: list[BlockInfo] = []
        self._errors: list[str] = []

    # ── Document lifecycle ───────────────────────────────────────────────
    def open(self) -> "PdfLayoutExtractor":
        """Open the PDF document. Raises FileNotFoundError if missing."""
        import fitz
        if not self.pdf_path.exists():
            raise FileNotFoundError(f"PDF not found: {self.pdf_path}")
        self._doc = fitz.open(str(self.pdf_path))
        return self

    def close(self) -> None:
        """Close the document and release memory."""
        if self._doc:
            self._doc.close()
            self._doc = None

    def __enter__(self) -> "PdfLayoutExtractor":
        return self.open()

    def __exit__(self, *_) -> None:
        self.close()

    # ── Properties ──────────────────────────────────────────────────────
    @property
    def doc(self):
        """Expose the internal fitz Document object."""
        return self._doc

    @property
    def page_count(self) -> int:
        return len(self._doc) if self._doc else 0

    @property
    def blocks(self) -> list[BlockInfo]:
        return self._blocks

    @property
    def text_blocks(self) -> list[BlockInfo]:
        """Only text blocks (block_type == 0), excluding image placeholders."""
        return [b for b in self._blocks if b.block_type == 0 and b.text.strip()]

    # ── Core extraction ──────────────────────────────────────────────────
    def extract_all_blocks(self) -> list[BlockInfo]:
        """
        Iterate all pages and extract every block with its layout geometry.
        Applies coordinate sanitation guardrails per block.
        Returns the flat list of BlockInfo objects across all pages.
        """
        if not self._doc:
            raise RuntimeError("Document not opened. Call open() first.")

        self._blocks.clear()
        self._errors.clear()

        for page_no, page in enumerate(self._doc):
            page_width  = page.rect.width
            page_height = page.rect.height

            # get_text("blocks") returns tuples:
            # (x0, y0, x1, y1, text, block_no, block_type)
            raw_blocks = page.get_text("blocks")

            # Also get detailed dict for per-line/span font info
            detail = page.get_text("dict", flags=0)
            detail_blocks = {b["number"]: b for b in detail.get("blocks", [])}

            for raw in raw_blocks:
                try:
                    block_info = self._parse_raw_block(
                        raw, page_no, page_width, page_height, detail_blocks
                    )
                    self._blocks.append(block_info)
                except Exception as exc:
                    raw_preview = repr(raw)[:120]
                    err_msg = (
                        "Page " + str(page_no) + ", block extraction error: " + str(exc) + ". "
                        "Raw block: " + raw_preview
                    )
                    self._errors.append(err_msg)
                    # Guardrail: append a stub block with default constraints
                    stub = self._make_stub_block(page_no, len(self._blocks))
                    self._blocks.append(stub)

        return self._blocks

    def _parse_raw_block(
        self,
        raw: tuple,
        page_no: int,
        page_width: float,
        page_height: float,
        detail_blocks: dict,
    ) -> BlockInfo:
        """
        Parse a single raw block tuple into a structured BlockInfo.
        Sanitizes all coordinate values against page dimensions.
        """
        # Unpack — PyMuPDF tuple: (x0, y0, x1, y1, "text\n", block_no, block_type)
        raw_x0, raw_y0, raw_x1, raw_y1, text, block_no, block_type = raw[:7]

        # Sanitize coordinates against page bounds as fallback references
        x0 = _sanitize_coord(raw_x0, 0.0)
        y0 = _sanitize_coord(raw_y0, 0.0)
        x1 = _sanitize_coord(raw_x1, page_width)
        y1 = _sanitize_coord(raw_y1, page_height)

        # Ensure logical ordering
        if x0 > x1:
            x0, x1 = x1, x0
        if y0 > y1:
            y0, y1 = y1, y0

        width  = x1 - x0
        height = y1 - y0
        clean_text = str(text).strip()
        word_count = len(clean_text.split()) if clean_text else 0

        # Extract per-line span data from the detailed dict
        lines: list[LineInfo] = []
        detail_blk = detail_blocks.get(block_no, {})
        for line_no, line_data in enumerate(detail_blk.get("lines", [])):
            line_bbox = line_data.get("bbox", (x0, y0, x1, y1))
            spans: list[SpanInfo] = []
            line_text_parts = []
            for span in line_data.get("spans", []):
                span_text = span.get("text", "")
                line_text_parts.append(span_text)
                spans.append(SpanInfo(
                    font       = span.get("font", "unknown"),
                    font_size  = _sanitize_coord(span.get("size"), 12.0),
                    font_flags = int(span.get("flags", 0)),
                    color      = int(span.get("color", 0)),
                    text       = span_text,
                ))
            lines.append(LineInfo(
                line_no = line_no,
                x0      = _sanitize_coord(line_bbox[0], x0),
                y0      = _sanitize_coord(line_bbox[1], y0),
                x1      = _sanitize_coord(line_bbox[2], x1),
                y1      = _sanitize_coord(line_bbox[3], y1),
                text    = "".join(line_text_parts),
                spans   = spans,
            ))

        return BlockInfo(
            page_no    = page_no,
            block_no   = int(block_no),
            x0         = x0,
            y0         = y0,
            x1         = x1,
            y1         = y1,
            width      = width,
            height     = height,
            text       = clean_text,
            word_count = word_count,
            block_type = int(block_type),
            lines      = lines,
        )

    def _make_stub_block(self, page_no: int, block_no: int) -> BlockInfo:
        """Create a safe default stub block when parsing fails (guardrail recovery)."""
        return BlockInfo(
            page_no    = page_no,
            block_no   = block_no,
            x0         = _DEFAULT_BBOX[0],
            y0         = _DEFAULT_BBOX[1],
            x1         = _DEFAULT_BBOX[2],
            y1         = _DEFAULT_BBOX[3],
            width      = _DEFAULT_BBOX[2] - _DEFAULT_BBOX[0],
            height     = _DEFAULT_BBOX[3] - _DEFAULT_BBOX[1],
            text       = "",
            word_count = 0,
            block_type = 0,
        )

    # ── Output helpers ───────────────────────────────────────────────────
    def get_extraction_summary(self) -> dict:
        """Return a JSON-serializable summary of the extraction results."""
        text_blocks = self.text_blocks
        return {
            "pdf_path":          str(self.pdf_path),
            "page_count":        self.page_count,
            "total_blocks":      len(self._blocks),
            "text_block_count":  len(text_blocks),
            "image_block_count": len(self._blocks) - len(text_blocks),
            "total_words":       sum(b.word_count for b in text_blocks),
            "parse_errors":      len(self._errors),
            "error_details":     self._errors,
        }

    def to_json(self, indent: int = 2) -> str:
        """Serialize all blocks to a JSON string."""
        return json.dumps(
            [b.to_dict() for b in self._blocks],
            indent=indent,
            ensure_ascii=False,
        )


# ---------------------------------------------------------------------------
# Synthetic PDF generator for testing (no real PDF needed)
# ---------------------------------------------------------------------------
def _create_test_pdf(output_path: Path) -> None:
    """Create a minimal multi-page test PDF with known text content."""
    import fitz
    doc = fitz.open()

    pages_content = [
        [
            ("Introduction", (72, 72, 520, 100),  14, True),
            ("This paper presents a novel approach to machine learning. "
             "The methodology builds upon previous research in neural networks. "
             "We demonstrate significant improvements over baseline models.",
             (72, 110, 520, 170), 11, False),
            ("Related Work", (72, 190, 520, 215), 13, True),
            ("Previous studies [1] have shown that transformer architectures "
             "outperform recurrent models on sequential tasks. "
             "Smith et al. (2023) demonstrated this on language modeling benchmarks.",
             (72, 225, 520, 280), 11, False),
        ],
        [
            ("Methodology", (72, 72, 520, 97), 13, True),
            ("Our approach uses the formula $E = mc^2$ as inspiration. "
             "We define burstiness B = (sigma - mu) / (sigma + mu) "
             "where sigma is sentence length standard deviation.",
             (72, 107, 520, 160), 11, False),
            ("Results", (72, 180, 520, 205), 13, True),
            ("Experimental results confirm our hypothesis [2, 3]. "
             "The system achieves 94.7% accuracy on the benchmark dataset. "
             "This represents a 12% improvement over prior state-of-the-art.",
             (72, 215, 520, 270), 11, False),
        ],
    ]

    for page_content in pages_content:
        page = doc.new_page(width=595, height=842)
        for text, rect, size, bold in page_content:
            flags = 1 if bold else 0   # 1 = bold in fitz fontname context
            fontname = "helv" if not bold else "hebo"
            page.insert_text(
                (rect[0], rect[1] + size),
                text,
                fontname=fontname,
                fontsize=size,
                color=(0, 0, 0),
            )

    doc.save(str(output_path))
    doc.close()


# ---------------------------------------------------------------------------
# Stage 7 Verification Guardrail
# ---------------------------------------------------------------------------
def _run_verification() -> None:
    import fitz

    print("=== Stage 7: PDF Layout Extraction Verification ===")
    print(f"  PyMuPDF version: {fitz.__version__}")
    print()

    # Create a test PDF in storage/
    storage = Path(__file__).resolve().parents[3] / "storage"
    storage.mkdir(exist_ok=True)
    test_pdf = storage / "test_extraction.pdf"

    print("  Creating synthetic test PDF...")
    _create_test_pdf(test_pdf)
    assert test_pdf.exists(), "Test PDF not created"
    print(f"  [PASS] Test PDF created: {test_pdf.name} ({test_pdf.stat().st_size} bytes)")
    print()

    # Run extraction
    extractor = PdfLayoutExtractor(test_pdf)
    with extractor:
        blocks = extractor.extract_all_blocks()

    summary = extractor.get_extraction_summary()
    print("  Extraction Summary:")
    for k, v in summary.items():
        if k != "error_details":
            print(f"    {k:<25} = {v}")
    print()

    # ── Guardrail checks ──────────────────────────────────────────────
    errors_found = []

    # Check 1: blocks were extracted
    if summary["total_blocks"] == 0:
        errors_found.append("No blocks extracted from test PDF")
    else:
        print(f"  [PASS] Extracted {summary['total_blocks']} total blocks "
              f"({summary['text_block_count']} text, "
              f"{summary['image_block_count']} image)")

    # Check 2: coordinates are floats
    coord_errors = 0
    for b in extractor.text_blocks:
        for coord_name, val in [("x0", b.x0), ("y0", b.y0), ("x1", b.x1), ("y1", b.y1)]:
            if not isinstance(val, float):
                coord_errors += 1
                errors_found.append(
                    f"Block {b.block_no} page {b.page_no}: "
                    f"{coord_name}={val!r} is not float (type={type(val).__name__})"
                )
            if val < 0 or val > 10000:
                coord_errors += 1
                errors_found.append(
                    f"Block {b.block_no} page {b.page_no}: "
                    f"{coord_name}={val} out of plausible range"
                )
    if coord_errors == 0:
        print(f"  [PASS] All block coordinates are valid floats within expected range")
    else:
        print(f"  [FAIL] {coord_errors} coordinate type/range errors detected")

    # Check 3: logical coordinate ordering (x0 < x1, y0 < y1)
    ordering_errors = 0
    for b in extractor.text_blocks:
        if b.x0 >= b.x1 or b.y0 >= b.y1:
            ordering_errors += 1
            errors_found.append(
                f"Block {b.block_no}: invalid bbox order "
                f"({b.x0},{b.y0})-({b.x1},{b.y1})"
            )
    if ordering_errors == 0:
        print(f"  [PASS] All bounding boxes have correct coordinate ordering (x0<x1, y0<y1)")

    # Check 4: text is non-empty strings
    empty_text_blocks = [b for b in extractor.text_blocks if not b.text.strip()]
    if empty_text_blocks:
        errors_found.append(f"{len(empty_text_blocks)} text blocks have empty text content")
    else:
        print(f"  [PASS] All {len(extractor.text_blocks)} text blocks contain non-empty text")

    # Check 5: word counts are positive integers
    word_count_errors = [
        b for b in extractor.text_blocks if not isinstance(b.word_count, int) or b.word_count < 0
    ]
    if word_count_errors:
        errors_found.append(f"{len(word_count_errors)} blocks have invalid word_count values")
    else:
        total_words = sum(b.word_count for b in extractor.text_blocks)
        print(f"  [PASS] Word counts valid — {total_words} total words across all text blocks")

    # Check 6: multi-page coverage
    pages_seen = set(b.page_no for b in extractor.blocks)
    if len(pages_seen) < 2:
        errors_found.append(f"Expected blocks from multiple pages, got: {pages_seen}")
    else:
        print(f"  [PASS] Blocks span {len(pages_seen)} pages: {sorted(pages_seen)}")

    # Check 7: parse error count
    if summary["parse_errors"] == 0:
        print(f"  [PASS] Zero extraction errors (guardrail recovery not needed)")
    else:
        print(f"  [NOTE] {summary['parse_errors']} blocks used guardrail stub recovery")
        print(f"         Errors: {summary['error_details']}")

    # Check 8: JSON serialization
    try:
        json_out = extractor.to_json()
        parsed = json.loads(json_out)
        assert len(parsed) == len(blocks)
        print(f"  [PASS] JSON serialization: {len(parsed)} blocks serialized cleanly")
    except Exception as e:
        errors_found.append(f"JSON serialization failed: {e}")

    # ── Final result ───────────────────────────────────────────────────
    print()
    if errors_found:
        print(f"  [FAIL] {len(errors_found)} guardrail error(s):")
        for err in errors_found:
            print(f"    - {err}")
        sys.exit(1)
    else:
        print("  Stage 7 guardrail: PASSED. PDF extraction engine is healthy.")

    # Cleanup test file
    test_pdf.unlink(missing_ok=True)


if __name__ == "__main__":
    _run_verification()
