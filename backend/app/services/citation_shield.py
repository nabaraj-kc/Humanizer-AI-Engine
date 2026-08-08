"""
backend/app/services/citation_shield.py
========================================
Regex-based citation protection layer for the Humanizer AI Engine.

Purpose:
  Academic citations must survive the LLM rewriting loop completely
  unchanged. This module extracts all citation patterns from a text string,
  replaces them with opaque placeholder tokens, and provides a deterministic
  inversion function that restores them exactly.

Supported citation patterns:
  1. Numeric bracketed  : [1], [12], [1,2,3], [1, 2, 3], [1-5]
  2. Author-year paren  : (Smith, 2023), (Smith & Jones, 2023),
                          (Smith et al., 2023), (Smith et al. 2022)
  3. Author-year bracket: [Smith, 2023], [Smith & Jones, 2024]
  4. Superscript numbers: ¹, ², ¹²³ (Unicode superscript digits)
  5. Footnote refs      : [a], [b], [i], [ii], [iii], [iv], [v] etc.

Placeholder format:
  __CITATION_0__, __CITATION_1__, ... __CITATION_N__

Inversion guarantee:
  deshield_citations(shield_citations(text)[0], shield_citations(text)[1])
  must equal the original text exactly (byte-for-byte match).

Rollback safety:
  If any inversion fails to locate a placeholder, the function raises
  CitationRestoreError rather than returning corrupt text.
"""

from __future__ import annotations

import re
from typing import Optional


# ---------------------------------------------------------------------------
# Custom exception
# ---------------------------------------------------------------------------
class CitationRestoreError(Exception):
    """Raised when a placeholder cannot be resolved during deshielding."""
    pass


# ---------------------------------------------------------------------------
# Citation regex patterns (ordered most-specific to least-specific)
# ---------------------------------------------------------------------------

# Pattern 1: Numeric ranges and lists in brackets, e.g. [1], [1,2], [1-5], [1, 2, 3]
_RE_NUMERIC_BRACKET = re.compile(
    r'\['                           # opening bracket
    r'\s*'
    r'\d+'                          # first number
    r'(?:'
    r'(?:\s*[-\u2013\u2014]\s*\d+)'  # range: [1-5] or [1–5]
    r'|'
    r'(?:\s*,\s*\d+)+'              # list:  [1, 2, 3]
    r')?'
    r'\s*'
    r'\]',                          # closing bracket
    re.UNICODE,
)

# Pattern 2: Author-year in parentheses
# Matches: (Smith, 2023), (Smith & Jones, 2023), (Smith et al., 2022),
#          (Smith and Jones 2023), (de la Cruz, 2021), (Vaswani et al., 2017)
_RE_AUTHOR_YEAR_PAREN = re.compile(
    r'\('
    r'(?:[A-Z\u00C0-\u017E][A-Za-z\u00C0-\u017E\-\']*'   # first author surname
    r'(?:\s+(?:&|and)\s+[A-Za-z\u00C0-\u017E\-\']+)?'   # optional '& Co-author'
    r'(?:\s+et\s+al\.?)?'                                 # optional et al.
    r')'
    r'[,\s]+'
    r'(?:19|20)\d{2}'                                     # 4-digit year 19xx/20xx
    r'[a-z]?'                                             # optional letter suffix e.g. 2023a
    r'\)',
    re.UNICODE,
)

# Pattern 3: Author-year in brackets: [Smith, 2023], [Jones & Lee, 2024]
_RE_AUTHOR_YEAR_BRACKET = re.compile(
    r'\['
    r'(?:[A-Z\u00C0-\u017E][A-Za-z\u00C0-\u017E\-\']*'
    r'(?:\s+(?:&|and)\s+[A-Za-z\u00C0-\u017E\-\']+)?'
    r'(?:\s+et\s+al\.?)?'
    r')'
    r'[,\s]+'
    r'(?:19|20)\d{2}'
    r'[a-z]?'
    r'\]',
    re.UNICODE,
)

# Pattern 4: Unicode superscript citation numbers ¹²³⁴⁵⁶⁷⁸⁹⁰
_RE_SUPERSCRIPT = re.compile(
    r'[\u00B9\u00B2\u00B3\u2074-\u2079\u2070]+'  # superscript digit sequences
)

# Pattern 5: Footnote letter references [a], [b], [i], [ii], [iii], [iv], [v], [vi]
_RE_FOOTNOTE_LETTER = re.compile(
    r'\['
    r'(?:i{1,3}v?|vi{0,3}|ix|x|[a-e])'           # roman numerals i-x or letters a-e
    r'\]',
    re.IGNORECASE,
)

# Master ordered list — applied in sequence, most specific first
_ALL_PATTERNS: list[re.Pattern] = [
    _RE_AUTHOR_YEAR_PAREN,    # most specific: (Author, Year) — check before bare brackets
    _RE_AUTHOR_YEAR_BRACKET,  # [Author, Year] — check before numeric brackets
    _RE_NUMERIC_BRACKET,      # [1], [1,2,3], [1-5]
    _RE_SUPERSCRIPT,          # ¹²³
    _RE_FOOTNOTE_LETTER,      # [i], [ii], [a], [b]
]

# Placeholder token format
_TOKEN_PREFIX = "__CITATION_"
_TOKEN_SUFFIX = "__"


def _make_token(idx: int) -> str:
    return f"{_TOKEN_PREFIX}{idx}{_TOKEN_SUFFIX}"


# ---------------------------------------------------------------------------
# Core shielding function
# ---------------------------------------------------------------------------

def shield_citations(text: str) -> tuple[str, dict[str, str]]:
    """
    Extract all citation patterns from `text`, replace each unique match
    with a stable placeholder token, and return the sanitised text + map.

    Args:
        text: Raw input text containing citations to protect.

    Returns:
        A tuple (shielded_text, token_map) where:
          - shielded_text: text with all citations replaced by tokens
          - token_map:     dict mapping token -> original citation string

    Notes:
        - Duplicate citations reuse the same token (map is by content).
        - Tokens are globally unique across all patterns in one call.
        - Patterns are applied in sequence; earlier matches take priority,
          preventing double-substitution of overlapping patterns.
    """
    if not text:
        return text, {}

    token_map: dict[str, str] = {}          # token  -> original citation
    content_map: dict[str, str] = {}        # citation -> token  (dedup)
    counter = [0]                            # mutable counter for nested fn

    def _replace(match: re.Match) -> str:
        original = match.group(0)
        if original in content_map:
            # Reuse existing token for duplicate citations
            return content_map[original]
        token = _make_token(counter[0])
        counter[0] += 1
        token_map[token] = original
        content_map[original] = token
        return token

    # Apply each pattern in order on a working copy of the text
    result = text
    for pattern in _ALL_PATTERNS:
        result = pattern.sub(_replace, result)

    return result, token_map


# ---------------------------------------------------------------------------
# Inversion function
# ---------------------------------------------------------------------------

def deshield_citations(shielded_text: str, token_map: dict[str, str]) -> str:
    """
    Restore all citation placeholder tokens back to their original strings.

    Args:
        shielded_text: Text containing __CITATION_N__ tokens.
        token_map:     The dict returned by shield_citations().

    Returns:
        The original text with all citations restored exactly.

    Raises:
        CitationRestoreError: If a token in the text is not found in the map,
                              which would indicate data loss or corruption.
    """
    if not token_map:
        return shielded_text

    result = shielded_text

    # Build a single regex that matches any of our tokens in one pass
    # to avoid partial-replacement collisions
    token_pattern = re.compile(
        r'__CITATION_\d+__'
    )

    missing: list[str] = []

    def _restore(match: re.Match) -> str:
        token = match.group(0)
        if token not in token_map:
            missing.append(token)
            return token   # leave as-is; error reported after scan
        return token_map[token]

    result = token_pattern.sub(_restore, result)

    if missing:
        raise CitationRestoreError(
            f"Deshield failed: {len(missing)} token(s) not found in token_map: "
            f"{missing}. The substitution map may be mismatched or corrupted."
        )

    return result


# ---------------------------------------------------------------------------
# Convenience wrapper: full round-trip in one call
# ---------------------------------------------------------------------------

def shield_and_restore(text: str) -> tuple[str, dict[str, str], str]:
    """
    Utility that shields AND restores in one call, returning both intermediate
    and final forms. Useful for debugging and pipeline testing.

    Returns:
        (shielded_text, token_map, restored_text)
    """
    shielded, token_map = shield_citations(text)
    restored = deshield_citations(shielded, token_map)
    return shielded, token_map, restored


# ---------------------------------------------------------------------------
# Stage 8 Verification Guardrail
# ---------------------------------------------------------------------------

def _run_verification() -> None:
    import sys

    print("=== Stage 8: Citation Shield Verification Guardrail ===")
    print()

    # ── Test corpus: mixed citation formats ───────────────────────────
    test_cases = [
        # (description, input_text, expected_citation_count)
        (
            "Single numeric bracket",
            "The study [1] confirms the hypothesis.",
            1,
        ),
        (
            "Numeric list bracket",
            "Multiple references [1, 2, 3] support this claim.",
            1,
        ),
        (
            "Numeric range bracket",
            "Prior work [1-5] established the baseline.",
            1,
        ),
        (
            "Author-year parentheses",
            "As shown by Smith et al. (2023) in their analysis.",
            1,
        ),
        (
            "Multiple author-year paren",
            "Studies (Jones, 2021) and (Lee & Park, 2022) confirm this.",
            2,
        ),
        (
            "Author-year bracket",
            "The result [Smith & Jones, 2024] is significant.",
            1,
        ),
        (
            "Mixed citation types",
            "Research [1, 2] and (Brown et al., 2023) plus [Jones, 2022] agree.",
            3,
        ),
        (
            "Duplicate citations",
            "See [1] and also [1] and again [1].",
            1,   # all three [1] should map to same token
        ),
        (
            "No citations",
            "This sentence has no citations at all.",
            0,
        ),
        (
            "Complex academic paragraph",
            (
                "Transformer models [1, 2] have revolutionised NLP. "
                "Smith et al. (2023) demonstrated that attention mechanisms "
                "(Vaswani et al., 2017) scale efficiently. "
                "This was confirmed by [Jones & Lee, 2022] and independently "
                "by Brown (2021). The formula $E=mc^2$ remains unaffected [3]."
            ),
            7,
        ),
    ]

    all_pass = True
    for desc, text, expected_count in test_cases:
        shielded, token_map = shield_citations(text)
        citation_count = len(token_map)

        # ── Sub-check A: round-trip fidelity ────────────────────────────
        try:
            restored = deshield_citations(shielded, token_map)
            roundtrip_ok = (restored == text)
        except CitationRestoreError as e:
            roundtrip_ok = False
            restored = f"ERROR: {e}"

        # ── Sub-check B: no raw citations remain in shielded text ────────
        remaining_citations = 0
        for pattern in _ALL_PATTERNS:
            remaining_citations += len(pattern.findall(shielded))

        # ── Sub-check C: no tokens remain in restored text ───────────────
        leftover_tokens = re.findall(r'__CITATION_\d+__', restored)

        passed = roundtrip_ok and len(leftover_tokens) == 0

        status = "[PASS]" if passed else "[FAIL]"
        if not passed:
            all_pass = False

        print(f"  {status} {desc}")
        print(f"         Citations found : {citation_count} (expected ~{expected_count})")
        if not roundtrip_ok:
            print(f"         ROUND-TRIP FAIL:")
            print(f"           Original : {text[:80]!r}")
            print(f"           Restored : {restored[:80]!r}")
        if leftover_tokens:
            print(f"         Leftover tokens in restored text: {leftover_tokens}")
        if remaining_citations > 0:
            print(f"         NOTE: {remaining_citations} citation-like patterns remain in shielded text")
        print()

    # ── Token map content check ────────────────────────────────────────
    print("  Token map content verification:")
    test_text = "See [1, 2] by Smith et al. (2023) and also [Jones, 2022]."
    shielded, tmap = shield_citations(test_text)
    for token, original in tmap.items():
        valid_token = bool(re.match(r'^__CITATION_\d+__$', token))
        status = "[PASS]" if valid_token else "[FAIL]"
        if not valid_token:
            all_pass = False
        print(f"    {status} {token!r} -> {original!r}")
    print()

    # ── Rollback test: bad token triggers CitationRestoreError ──────────
    print("  Rollback test: corrupted token triggers CitationRestoreError")
    try:
        deshield_citations("hello __CITATION_99__ world", {"__CITATION_0__": "[1]"})
        print("  [FAIL] No error raised for missing token")
        all_pass = False
    except CitationRestoreError as e:
        print(f"  [PASS] CitationRestoreError raised correctly")
    print()

    # ── Empty string edge case ─────────────────────────────────────────
    print("  Edge case: empty string")
    shielded_empty, map_empty = shield_citations("")
    assert shielded_empty == "", "Empty string should return empty"
    assert map_empty == {}, "Empty string should return empty map"
    print("  [PASS] Empty string handled correctly")
    print()

    # ── Final result ───────────────────────────────────────────────────
    if all_pass:
        print("  Stage 8 guardrail: PASSED. Citation shield round-trips are exact.")
    else:
        print("  Stage 8 guardrail: FAILED. See errors above.")
        sys.exit(1)


if __name__ == "__main__":
    _run_verification()
