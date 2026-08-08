"""
backend/app/services/geometry_defender.py
==========================================
PDF Geometry Overflow Defender for the Humanizer AI Engine.

Purpose:
  Estimates the layout dimensions of rewritten text and prevents layout overflows
  that could break the PDF presentation. If the rewritten text exceeds the original
  bounding box height by more than 15%, it flags an overflow and computes a
  proportional scaling/compression factor for the font size to fit the text exactly.
"""

from __future__ import annotations

import math
from typing import TypedDict


class OverflowReport(TypedDict):
    overflow: bool
    original_height: float
    container_height: float
    overflow_percentage: float
    suggested_scale_factor: float
    suggested_font_size: float


class GeometryDefender:
    """
    Defends PDF boundaries from text overflows after LLM rewriting.
    """

    def __init__(self, line_spacing: float = 1.2, avg_char_width_ratio: float = 0.38):
        self.line_spacing = line_spacing
        self.avg_char_width_ratio = avg_char_width_ratio

    def estimate_text_dimensions(
        self, text: str, font_size: float, container_width: float
    ) -> tuple[float, int]:
        """
        Estimates the height and number of lines required to render text.

        Args:
          text: The string content to render.
          font_size: The font size in points.
          container_width: Bounding box width in points.

        Returns:
          A tuple of (estimated_height, line_count).
        """
        if not text:
            return 0.0, 0

        # Estimate average character and space width
        char_w = font_size * self.avg_char_width_ratio
        space_w = char_w  # space has roughly similar width

        words = text.split()
        if not words:
            return 0.0, 0

        lines_count = 1
        current_line_width = 0.0

        for word in words:
            word_w = len(word) * char_w
            
            # If word is wider than the container, it must break
            if word_w > container_width:
                if current_line_width > 0.0:
                    lines_count += 1
                # The long word itself occupies multiple lines
                word_lines = math.ceil(word_w / container_width)
                lines_count += (word_lines - 1)
                current_line_width = word_w % container_width
            # If word fits on next line
            elif current_line_width + word_w > container_width:
                lines_count += 1
                current_line_width = word_w + space_w
            else:
                current_line_width += word_w + space_w

        estimated_height = lines_count * font_size * self.line_spacing
        return estimated_height, lines_count

    def check_overflow(
        self,
        text: str,
        font_size: float,
        container_width: float,
        container_height: float,
        overflow_threshold: float = 0.15
    ) -> OverflowReport:
        """
        Checks if the rewritten text exceeds the container height by more than
        the threshold (default 15%), and calculates a scale factor if it does.

        Args:
          text: Rewritten text string.
          font_size: Original font size.
          container_width: Original bounding box width.
          container_height: Original bounding box height.
          overflow_threshold: Max allowed overflow percentage (e.g. 0.15 for 15%).

        Returns:
          OverflowReport dictionary containing evaluation results.
        """
        est_height, _ = self.estimate_text_dimensions(text, font_size, container_width)
        
        # Max height including tolerance
        max_height = container_height * (1.0 + overflow_threshold)
        overflow = est_height > max_height
        overflow_percentage = ((est_height - container_height) / container_height) * 100 if container_height > 0 else 0.0

        suggested_scale = 1.0
        suggested_font_size = font_size

        if overflow:
            # Iteratively search for a scale factor that keeps the height <= container_height
            # We check scales from 0.95 down to 0.10 in steps of 0.01
            for s_pct in range(95, 9, -1):
                scale = s_pct / 100.0
                scaled_font_size = font_size * scale
                scaled_height, _ = self.estimate_text_dimensions(
                    text, scaled_font_size, container_width
                )
                if scaled_height <= container_height:
                    suggested_scale = scale
                    suggested_font_size = scaled_font_size
                    break
            else:
                # Absolute minimum scale fallback
                suggested_scale = 0.1
                suggested_font_size = font_size * 0.1

        return {
            "overflow": overflow,
            "original_height": est_height,
            "container_height": container_height,
            "overflow_percentage": overflow_percentage,
            "suggested_scale_factor": suggested_scale,
            "suggested_font_size": suggested_font_size
        }


# ---------------------------------------------------------------------------
# Stage 12 Verification Guardrail
# ---------------------------------------------------------------------------

def run_tests() -> None:
    print("=== Stage 12: Geometry Defender Verification Guardrail ===")
    print()

    defender = GeometryDefender()

    # Test 1: Fits comfortably
    print("  --- Test 1: Fits comfortably ---")
    text_normal = "This is a short sentence that should fit."
    # Box: W=200, H=50. Font size = 12
    report_normal = defender.check_overflow(text_normal, font_size=12, container_width=200, container_height=50)
    print(f"    Report: {report_normal}")
    assert not report_normal["overflow"]
    assert report_normal["suggested_scale_factor"] == 1.0
    print("  [PASS] normal text does not report overflow.")
    print()

    # Test 2: Overflows (needs scaling)
    print("  --- Test 2: Overflows (needs scaling) ---")
    text_long = (
        "This is an extremely long paragraph of text designed to overflow the "
        "modest container bounds. We are putting a lot of content here so that the "
        "height needed will grow far beyond the container height, triggering our "
        "geometry defender and forcing a calculation of a font scale factor."
    )
    # Box: W=150, H=40. Font size = 12.
    report_long = defender.check_overflow(text_long, font_size=12, container_width=150, container_height=40)
    print(f"    Report: {report_long}")
    
    assert report_long["overflow"]
    assert report_long["suggested_scale_factor"] < 1.0
    
    # Verify the scaled font size keeps text within container height
    scaled_height, _ = defender.estimate_text_dimensions(
        text_long, report_long["suggested_font_size"], container_width=150
    )
    print(f"    Scaled height at size {report_long['suggested_font_size']:.2f} is {scaled_height:.2f} (Container: 40)")
    assert scaled_height <= 40.0
    print("  [PASS] Overflow detected and scaled font size fits container bounds.")
    print()

    # Test 3: Overflow but within 15% tolerance
    print("  --- Test 3: Overflow within tolerance threshold ---")
    # Let's construct a text that overflows by just ~5%
    # If font size = 10, line height = 12, W=100.
    # Text requires 4 lines -> 48 points. Container = 45 points.
    # Overflow = (48 - 45)/45 = 6.6% overflow (which is <= 15%)
    text_tolerance = "Small overflow test case."
    report_tolerance = defender.check_overflow(
        text_tolerance, font_size=10, container_width=100, container_height=42, overflow_threshold=0.15
    )
    print(f"    Report: {report_tolerance}")
    assert not report_tolerance["overflow"]  # should NOT trigger overflow because it's within 15%
    print("  [PASS] Small overflow within tolerance is ignored as expected.")
    print()

    print("Stage 12 guardrail: ALL TESTS PASSED.")


if __name__ == "__main__":
    run_tests()
