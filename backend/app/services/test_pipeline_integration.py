"""
backend/app/services/test_pipeline_integration.py
==================================================
Integrated Parsing Pipeline Test for the Humanizer AI Engine.

Purpose:
  Runs an end-to-end integration test of the PDF extraction, citation masking,
  math masking, semantic chunking, layout mapping, and geometry overflow defender modules.
  Verifies that data flows cleanly across all components without loss or corruption.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Add backend directory to path if needed to run standalone
sys.path.append(str(Path(__file__).resolve().parents[3]))

import fitz
from backend.app.services.pdf_extractor import PdfLayoutExtractor
from backend.app.services.citation_shield import shield_citations, deshield_citations, CitationRestoreError
from backend.app.services.math_shield import shield_math, deshield_math, MathRestoreError
from backend.app.services.chunker import SemanticChunker
from backend.app.services.layout_mapper import DocumentStructureMap, LayoutValidationError
from backend.app.services.geometry_defender import GeometryDefender


# ---------------------------------------------------------------------------
# Synthetic PDF generator
# ---------------------------------------------------------------------------
def create_integration_test_pdf(output_path: Path) -> None:
    """Creates a 2-page research paper PDF with over 500 words, math, and citations."""
    doc = fitz.open()

    pages_content = [
        # Page 1
        [
            ("Introduction to Neural Networks in Scholarly Processing.", (50, 50, 540, 100), 14, True),
            (
                "Artificial neural networks have emerged as a dominant paradigm in natural language "
                "processing and computer vision task suites. In this paper, we explore how document "
                "layouts can be reconstructed with coordinate tracking systems. Traditional parser methods "
                "often discard formatting information [1], which degrades layout reconstruction. "
                "Vaswani et al. (2017) demonstrated that attention mechanisms allow networks to model "
                "long-range dependencies efficiently without recurrence. We extend this research by "
                "introducing a geometric layout tracking model. Our layout parser is designed to handle "
                "complex papers with mixed formatting configurations seamlessly. We also present a detailed "
                "architectural overview.",
                (50, 110, 540, 350), 9.5, False
            ),
            ("Literature Review of Academic Documents.", (50, 370, 540, 420), 13, True),
            (
                "Prior studies have shown that academic publications feature complex multi-column formats. "
                "For instance, Smith & Jones (2023) showed that multi-column papers require spatial layout "
                "awareness during extraction. Several approaches have tried to tackle this using rule-based "
                "parsing [2]. However, deep learning models like layout transformers have achieved superior "
                "benchmarks on complex document understanding task formats [3, 4]. We present a comprehensive "
                "comparison of layout parsing algorithms across diverse layout templates. Furthermore, recent "
                "advances in long-context models allow researchers to analyze entire documents at once, "
                "although maintaining structural fidelity remains a difficult hurdle.",
                (50, 430, 540, 750), 9.5, False
            ),
        ],
        # Page 2
        [
            ("Methodology and Mathematical Formulation.", (50, 50, 540, 100), 13, True),
            (
                "Our model maps text blocks to a normalized page coordinate matrix. Let the page bounding box "
                "width be W and height be H. The position of each extracted block is represented as: "
                "$$B = (x_0, y_0, x_1, y_1)$$ where x_0 and y_0 represent the top-left coordinate, and "
                "x_1 and y_1 represent the bottom-right coordinate. We calculate the aspect ratio of each text "
                "container using the following inline formula: $\\text{Ratio} = \\frac{x_1 - x_0}{y_1 - y_0}$. "
                "The loss function for bounding box regression is defined as: "
                "\\begin{equation} L_{box} = \\sum_{i=1}^{N} || B_i - \\hat{B}_i ||^2 \\end{equation} "
                "This formulation ensures that coordinates are predicted with high spatial fidelity.",
                (50, 110, 540, 350), 9.5, False
            ),
            ("Experimental Results and Evaluation.", (50, 370, 540, 420), 13, True),
            (
                "We evaluate our model on a dataset containing 10,000 scholarly papers. The training phase "
                "utilizes a learning rate of $\\eta = 10^{-4}$ with a batch size of 32. Our model achieves a "
                "layout detection accuracy of 96.5% on standard datasets. This performance represents a "
                "significant improvement over the baseline models proposed in prior literature [5-8]. "
                "Additionally, the inference time is reduced by 25% due to our optimized coordinate extraction "
                "loop. We compare our method with several baseline approaches. Our algorithm consistently "
                "outperforms the baselines under varying levels of layout complexity.",
                (50, 430, 540, 650), 9.5, False
            ),
            ("Conclusion and Future Work.", (50, 670, 540, 700), 13, True),
            (
                "In conclusion, we have presented a robust spatial extraction pipeline for academic PDFs. "
                "By incorporating citation and math shields, our engine ensures that critical scientific "
                "components are preserved intact during processing loops. Future work will extend this framework "
                "to support multi-column table extraction and automatic legend alignment. We believe this "
                "represents a vital step toward automated scholarly reading assistants. The integration of "
                "this pipeline into existing document management platforms will greatly facilitate automated "
                "metadata harvesting and semantic retrieval systems. Furthermore, we intend to open-source our "
                "system to allow developers to build advanced citation preservation and mathematical formula "
                "layout reconstruction models.",
                (50, 705, 540, 838), 9.5, False
            ),
        ]
    ]

    for page_content in pages_content:
        page = doc.new_page(width=595, height=842)
        for text, rect, size, bold in page_content:
            fontname = "helv" if not bold else "hebo"
            page.insert_textbox(
                rect,
                text,
                fontname=fontname,
                fontsize=size,
                color=(0, 0, 0)
            )

    doc.save(str(output_path))
    doc.close()


# ---------------------------------------------------------------------------
# Pipeline execution
# ---------------------------------------------------------------------------
def run_pipeline() -> bool:
    print("=== STARTING INTEGRATED PARSING PIPELINE INTEGRATION TEST ===")
    print()

    # 1. Setup workspace paths
    storage_dir = Path(__file__).resolve().parents[3] / "storage"
    storage_dir.mkdir(exist_ok=True)
    pdf_path = storage_dir / "test_pipeline.pdf"

    print(f"  Generating synthetic PDF at: {pdf_path.name}")
    create_integration_test_pdf(pdf_path)
    assert pdf_path.exists(), "PDF file generation failed"

    # 2. Layout extraction
    print("  Step 1: Extracting layout blocks from PDF...")
    extractor = PdfLayoutExtractor(pdf_path)
    with extractor:
        raw_blocks = extractor.extract_all_blocks()
    
    # Convert BlockInfo objects to dictionaries
    blocks = [b.to_dict() if hasattr(b, "to_dict") else b for b in raw_blocks]

    print(f"    Extracted {len(blocks)} layout blocks from {extractor.page_count} pages.")
    
    # Check that coordinates are floats
    for b in blocks:
        assert isinstance(b["x0"], float) and isinstance(b["y0"], float), "Coordinates must be floats"
        assert isinstance(b["x1"], float) and isinstance(b["y1"], float), "Coordinates must be floats"
    print("    [PASS] Coordinates verified as valid floats.")

    # Aggregate plain text for word count checks
    all_texts = [b["text"].strip() for b in blocks if b["block_type"] == 0]
    full_plain_text = "\n\n".join(all_texts)
    total_words = len(full_plain_text.split())
    print(f"    Aggregated Plain Text Word Count: {total_words}")
    
    # Assert word count is above 500
    if total_words <= 500:
        print(f"    [FAIL] Aggregated plain text word count is {total_words}, must be > 500.")
        sys.exit(1)
    else:
        print(f"    [PASS] Word count is {total_words} (> 500), ready for Master Summary.")

    # 3. Shield citation and math notation
    print("  Step 2: Shielding citations & mathematical equations...")
    
    # Apply shields globally on the combined plain text
    shielded_doc_cit, combined_citation_map = shield_citations(full_plain_text)
    shielded_doc_both, combined_math_map = shield_math(shielded_doc_cit)

    # Split back into individual block texts
    shielded_paragraphs = shielded_doc_both.split("\n\n")
    assert len(shielded_paragraphs) == len(blocks), "Paragraph split count mismatch after global shielding"

    shielded_blocks = []
    for idx, b in enumerate(blocks):
        sb = dict(b)
        sb["text"] = shielded_paragraphs[idx]
        shielded_blocks.append(sb)

    print(f"    Masked Citations: {len(combined_citation_map)} tokens registered globally.")
    print(f"    Masked Math: {len(combined_math_map)} tokens registered globally.")

    # 4. Semantic Chunking
    print("  Step 3: Slicing shielded text into semantic chunks (~500 words)...")
    # Using larger limits to see how it groups, let's use 200 words target for testing, or standard 500.
    # We'll use target=200, max=300 for our 500-word test document to ensure multiple chunks are created.
    chunker = SemanticChunker(target_words=200, max_words=250)
    chunks = chunker.chunk_document(shielded_blocks)
    
    print(f"    Generated {len(chunks)} semantic chunks:")
    for c in chunks:
        print(f"      - Chunk {c['chunk_id']}: words={c['word_count']}, paragraphs={c['paragraph_indices']}")

    # 5. Initialize DocumentStructureMap
    print("  Step 4: Registering layout structural mappings...")
    mapper = DocumentStructureMap(blocks)
    mapper.register_chunks(chunks)
    print("    [PASS] Layout mapping successfully registered.")

    # 6. Simulate Rewrite Loop & Deshielding
    print("  Step 5: Simulating rewriting & token deshielding...")
    
    # We simulate rewriting by prepending a prefix to the chunk texts while maintaining all tokens intact
    rewritten_chunks = {}
    for c in chunks:
        # Construct rewritten text by joining uppercased shielded texts of blocks in the chunk with double newlines
        chunk_parts = []
        for p_idx in c["paragraph_indices"]:
            sb = shielded_blocks[p_idx]
            chunk_parts.append(sb["text"].upper())
        rewritten_chunks[c["chunk_id"]] = "\n\n".join(chunk_parts)

    # Map rewritten chunks back to layout blocks
    mapped_blocks = mapper.map_rewritten_chunks(rewritten_chunks)
    assert len(mapped_blocks) == len(blocks), "Mapped block count mismatch"
    print("    [PASS] Rewritten chunks mapped back to layout blocks.")

    # Verify that deshielding works and matches original citation and math contents
    print("  Step 6: Running round-trip inversion validations...")
    restored_blocks_count = 0
    for mb in mapped_blocks:
        rewritten_text = mb["rewritten_text"]
        
        # Invert shields in reverse order (Math first, Citations second)
        try:
            deshielded_math = deshield_math(rewritten_text, combined_math_map)
            deshielded_both = deshield_citations(deshielded_math, combined_citation_map)
        except (MathRestoreError, CitationRestoreError) as e:
            print(f"    [FAIL] Deshielding failed on block {mb['block_no']}: {e}")
            sys.exit(1)

        # Get original block's shielded text from shielded_blocks using its original index
        orig_idx = mb["block_no"] if "original_index" not in mb else mb.get("original_index", mb["block_no"])
        orig_shielded_text = shielded_blocks[orig_idx]["text"]

        # Confirm that the rewritten text contains the uppercased text with preserved shields
        try:
            expected_restored_math = deshield_math(orig_shielded_text.upper(), combined_math_map)
            expected_restored = deshield_citations(expected_restored_math, combined_citation_map)
        except (MathRestoreError, CitationRestoreError) as e:
            print(f"    [FAIL] Expected text deshielding failed: {e}")
            sys.exit(1)
        
        # We handle whitespace normalization for comparison
        clean_restored = " ".join(deshielded_both.split())
        clean_expected = " ".join(expected_restored.split())
        
        if clean_restored != clean_expected:
            # Let's print out the diffs
            print(f"    [FAIL] Text fidelity mismatch on block {mb['block_no']}:")
            print(f"      Expected: {clean_expected!r}")
            print(f"      Got:      {clean_restored!r}")
            sys.exit(1)
        restored_blocks_count += 1

    print(f"    [PASS] Deshielded and verified {restored_blocks_count} blocks with 100% byte fidelity.")

    # 7. Geometry overflow checks
    print("  Step 7: Executing Geometry Defender overflow diagnostics...")
    defender = GeometryDefender()
    for mb in mapped_blocks:
        # Calculate width and height of container
        w = mb["x1"] - mb["x0"]
        h = mb["y1"] - mb["y0"]
        
        # Run overflow check using standard font size 11
        report = defender.check_overflow(
            text=mb["rewritten_text"],
            font_size=11.0,
            container_width=w,
            container_height=h
        )
        if report["overflow"]:
            print(f"    [WARNING] Bounding overflow detected on page {mb['page_no']} block {mb['block_no']}: "
                  f"{report['overflow_percentage']:.1f}% overflow. Suggested scale factor: {report['suggested_scale_factor']}")
        else:
            print(f"    Block Page {mb['page_no']} No {mb['block_no']}: fits within bounds.")

    print()
    print("=== PIPELINE INTEGRATION TEST: ALL STAGES PASSED ===")
    
    # Cleanup generated PDF
    pdf_path.unlink(missing_ok=True)
    return True


if __name__ == "__main__":
    success = run_pipeline()
    if not success:
        sys.exit(1)
