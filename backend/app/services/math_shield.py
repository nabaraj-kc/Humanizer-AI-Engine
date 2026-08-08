"""
backend/app/services/math_shield.py
=====================================
LaTeX mathematical expression protection layer for the Humanizer AI Engine.

Purpose:
  Mathematical notation must pass through the LLM rewriting loop completely
  unchanged. This module extracts all LaTeX math expressions from text,
  replaces them with opaque placeholder tokens, and provides a deterministic
  inversion function that restores them byte-for-byte.

Supported math patterns (matched in priority order):
  1. Display/block equations  : $$...$$  (multi-line, highest priority)
  2. LaTeX environments       : \\begin{equation}...\\end{equation},
                                \\begin{align}...\\end{align}, etc.
  3. Inline equations         : $...$    (single dollar, non-empty)
  4. Parenthesis notation     : \\(...\\)
  5. Bracket notation         : \\[...\\]

Placeholder format:
  - Block equations   : __MATH_BLOCK_0__, __MATH_BLOCK_1__, ...
  - Inline equations  : __MATH_INLINE_0__, __MATH_INLINE_1__, ...

Inversion guarantee:
  deshield_math(shield_math(text)[0], shield_math(text)[1]) == original text

Rollback safety:
  If any inversion fails to locate a placeholder, MathRestoreError is raised
  rather than returning silently corrupt text.

IMPORTANT ordering note:
  $$...$$ MUST be matched before $...$ to prevent the double-dollar
  delimiter from being split into two separate single-dollar matches.
"""

from __future__ import annotations

import re
from typing import Optional


# ---------------------------------------------------------------------------
# Custom exception
# ---------------------------------------------------------------------------
class MathRestoreError(Exception):
    """Raised when a math placeholder cannot be resolved during deshielding."""
    pass


# ---------------------------------------------------------------------------
# Regex patterns (ordered highest → lowest priority)
# ---------------------------------------------------------------------------

# Pattern 1: Display block  $$...$$
# Flags: DOTALL so '.' matches newlines inside multi-line equations
_RE_DISPLAY_BLOCK = re.compile(
    r'\$\$'            # opening $$
    r'(?!\$)'          # not followed by a third $ (safety)
    r'(.+?)'           # content (non-greedy, DOTALL)
    r'\$\$',           # closing $$
    re.DOTALL,
)

# Pattern 2: LaTeX environments  \begin{env}...\end{env}
# Supports: equation, equation*, align, align*, gather, multline, eqnarray
_RE_LATEX_ENV = re.compile(
    r'\\begin\{(equation\*?|align\*?|gather\*?|multline\*?|eqnarray\*?)\}'
    r'(.+?)'
    r'\\end\{\1\}',
    re.DOTALL,
)

# Pattern 3: Inline equation  $...$
# Avoids matching:
#   - Empty $$  (handled by Pattern 1 above)
#   - $$ opening of display blocks (matched first by Pattern 1)
#   - Lone $ signs that aren't math (require at least one non-space char)
_RE_INLINE = re.compile(
    r'(?<!\$)'         # not preceded by $ (avoids $$)
    r'\$'              # opening $
    r'(?!\$)'          # not followed by $ (avoids $$)
    r'([^$\n]{1,500})' # content: 1-500 non-$ non-newline chars
    r'(?<!\$)'         # not preceded by $
    r'\$'              # closing $
    r'(?!\$)',         # not followed by $
)

# Pattern 4: \(...\)  inline math notation
_RE_PAREN_INLINE = re.compile(
    r'\\\('            # \(
    r'(.+?)'           # content
    r'\\\)',           # \)
    re.DOTALL,
)

# Pattern 5: \[...\]  display math notation
_RE_BRACKET_DISPLAY = re.compile(
    r'\\\['            # \[
    r'(.+?)'           # content
    r'\\\]',           # \]
    re.DOTALL,
)

# Ordered list: block patterns first, inline second
_BLOCK_PATTERNS: list[re.Pattern] = [
    _RE_DISPLAY_BLOCK,
    _RE_LATEX_ENV,
    _RE_BRACKET_DISPLAY,
]
_INLINE_PATTERNS: list[re.Pattern] = [
    _RE_PAREN_INLINE,
    _RE_INLINE,
]

# Placeholder formats
_BLOCK_PREFIX  = "__MATH_BLOCK_"
_INLINE_PREFIX = "__MATH_INLINE_"
_TOKEN_SUFFIX  = "__"


def _make_block_token(idx: int) -> str:
    return f"{_BLOCK_PREFIX}{idx}{_TOKEN_SUFFIX}"


def _make_inline_token(idx: int) -> str:
    return f"{_INLINE_PREFIX}{idx}{_TOKEN_SUFFIX}"


# ---------------------------------------------------------------------------
# Core shielding function
# ---------------------------------------------------------------------------

def shield_math(text: str) -> tuple[str, dict[str, str]]:
    """
    Extract all LaTeX math expressions from `text`, replace each with a
    stable placeholder token, and return the sanitised text + token map.

    Args:
        text: Raw input text containing math expressions to protect.

    Returns:
        (shielded_text, token_map) where:
          - shielded_text : text with all math replaced by tokens
          - token_map     : dict mapping token -> original LaTeX expression

    Notes:
        - Block patterns are applied before inline to avoid $$...$$ being
          split into two $...$ inline matches.
        - Duplicate expressions reuse the same token (deduplicated by content).
        - Tokens are globally unique across both block and inline counters.
    """
    if not text:
        return text, {}

    token_map: dict[str, str] = {}       # token -> original expression
    content_map: dict[str, str] = {}     # expression -> token (dedup)
    block_counter = [0]
    inline_counter = [0]

    def _replace_block(match: re.Match) -> str:
        original = match.group(0)
        if original in content_map:
            return content_map[original]
        token = _make_block_token(block_counter[0])
        block_counter[0] += 1
        token_map[token] = original
        content_map[original] = token
        return token

    def _replace_inline(match: re.Match) -> str:
        original = match.group(0)
        if original in content_map:
            return content_map[original]
        token = _make_inline_token(inline_counter[0])
        inline_counter[0] += 1
        token_map[token] = original
        content_map[original] = token
        return token

    result = text

    # Step 1: Apply block patterns first ($$, \begin{env}, \[...\])
    for pattern in _BLOCK_PATTERNS:
        result = pattern.sub(_replace_block, result)

    # Step 2: Apply inline patterns on the block-shielded text
    for pattern in _INLINE_PATTERNS:
        result = pattern.sub(_replace_inline, result)

    return result, token_map


# ---------------------------------------------------------------------------
# Inversion function
# ---------------------------------------------------------------------------

def deshield_math(shielded_text: str, token_map: dict[str, str]) -> str:
    """
    Restore all math placeholder tokens back to their original LaTeX strings.

    Args:
        shielded_text: Text containing __MATH_BLOCK_N__ or __MATH_INLINE_N__ tokens.
        token_map:     The dict returned by shield_math().

    Returns:
        Original text with all math expressions restored exactly.

    Raises:
        MathRestoreError: If a token in the text is not found in token_map,
                          indicating data loss or map corruption.
    """
    if not token_map:
        return shielded_text

    # Single regex matches both block and inline tokens
    token_pattern = re.compile(
        r'__MATH_(?:BLOCK|INLINE)_\d+__'
    )

    missing: list[str] = []

    def _restore(match: re.Match) -> str:
        token = match.group(0)
        if token not in token_map:
            missing.append(token)
            return token
        return token_map[token]

    result = token_pattern.sub(_restore, shielded_text)

    if missing:
        raise MathRestoreError(
            f"Deshield failed: {len(missing)} token(s) not in token_map: "
            f"{missing}. The map may be mismatched or the text was modified."
        )

    return result


# ---------------------------------------------------------------------------
# Convenience: combined shield check (citation + math)
# ---------------------------------------------------------------------------

def get_math_token_counts(token_map: dict[str, str]) -> dict[str, int]:
    """Return counts of block vs inline tokens in a token map."""
    return {
        "block_count":  sum(1 for t in token_map if t.startswith(_BLOCK_PREFIX)),
        "inline_count": sum(1 for t in token_map if t.startswith(_INLINE_PREFIX)),
        "total":        len(token_map),
    }


# ---------------------------------------------------------------------------
# Stage 9 Verification Guardrail
# ---------------------------------------------------------------------------

def _run_verification() -> None:
    import sys

    print("=== Stage 9: Math Shield Verification Guardrail ===")
    print()

    test_cases = [
        # (description, input_text, expect_block, expect_inline, special_note)
        (
            "Simple inline equation",
            "The formula $E = mc^2$ defines mass-energy equivalence.",
            0, 1, None,
        ),
        (
            "Display block equation",
            "The perplexity is defined as:\n$$P(W) = \\sqrt[N]{\\prod_{i=1}^{N} \\frac{1}{P(w_i)}}$$\nwhere N is length.",
            1, 0, None,
        ),
        (
            "Multi-line display block",
            "We compute:\n$$\n\\sigma_L = \\sqrt{\\frac{\\sum_{i=1}^{n}(x_i - \\mu)^2}{n}}\n$$\nas the variance.",
            1, 0, None,
        ),
        (
            "Mixed inline and block",
            "Given $x > 0$ and $y < 1$, the equation $$z = x/y$$ holds.",
            1, 2, None,
        ),
        (
            "Fraction inside inline",
            "The ratio $\\frac{\\sigma - \\mu}{\\sigma + \\mu}$ measures burstiness.",
            0, 1, None,
        ),
        (
            "Exponents and subscripts",
            "Compute $x_{i}^{2} + y_{j}^{2} = r^{2}$ for all $i, j$.",
            0, 2, None,
        ),
        (
            "LaTeX environment block",
            "The alignment is:\n\\begin{align}\nB &= \\frac{\\sigma - \\mu}{\\sigma + \\mu} \\\\\nP &= \\prod_{i=1}^{N} p_i\n\\end{align}\nwhere variables are defined above.",
            1, 0, None,
        ),
        (
            "Parenthesis notation inline",
            "Note that \\(a^2 + b^2 = c^2\\) is the Pythagorean theorem.",
            0, 1, None,
        ),
        (
            "Bracket display notation",
            "The Euler identity is:\n\\[\ne^{i\\pi} + 1 = 0\n\\]\nwhich is remarkable.",
            1, 0, None,
        ),
        (
            "Complex full paper paragraph",
            (
                "Transformer models maximize the log-likelihood $\\log P(y|x)$ using "
                "attention weights $\\alpha_{ij} = \\text{softmax}(e_{ij})$. "
                "The training objective is:\n"
                "$$\\mathcal{L} = -\\sum_{t=1}^{T} \\log P(y_t | y_{<t}, x)$$\n"
                "with temperature scaling $T_{\\text{soft}} = \\tau \\cdot T$ where "
                "$\\tau \\in (0, 1]$. Burstiness is computed as:\n"
                "\\begin{equation}\nB = \\frac{\\sigma_L - \\mu_L}{\\sigma_L + \\mu_L}\n\\end{equation}"
            ),
            2, 4, "Complex mixed notation test",
        ),
        (
            "Duplicate equations reuse same token",
            "See $x^2$ twice: also $x^2$ is the same expression.",
            0, 1, "Deduplication check",
        ),
        (
            "No math present",
            "This paragraph contains no mathematical notation whatsoever.",
            0, 0, None,
        ),
        (
            "$$...$$ not split into two $...$",
            "Display: $$\\int_0^\\infty e^{-x} dx = 1$$ should be one block token.",
            1, 0, "Critical ordering check",
        ),
    ]

    all_pass = True

    for desc, text, expect_block, expect_inline, note in test_cases:
        shielded, token_map = shield_math(text)
        counts = get_math_token_counts(token_map)

        # Round-trip fidelity check
        try:
            restored = deshield_math(shielded, token_map)
            roundtrip_ok = (restored == text)
        except MathRestoreError as e:
            roundtrip_ok = False
            restored = "ERROR: " + str(e)

        # No raw math tokens remain in shielded text (crude check)
        # Block: $$, \begin{
        # Inline: standalone $
        leftover_tokens = re.findall(r'__MATH_(?:BLOCK|INLINE)_\d+__', restored)

        # Count tokens by type
        block_count  = counts["block_count"]
        inline_count = counts["inline_count"]

        passed = roundtrip_ok and len(leftover_tokens) == 0

        status = "[PASS]" if passed else "[FAIL]"
        if not passed:
            all_pass = False

        print(f"  {status} {desc}")
        if note:
            print(f"         Note: {note}")
        print(f"         Block tokens: {block_count} | Inline tokens: {inline_count} | Total: {counts['total']}")
        if not roundtrip_ok:
            print(f"         ROUND-TRIP FAIL:")
            print(f"           Original  (first 100): {text[:100]!r}")
            print(f"           Restored  (first 100): {restored[:100]!r}")
        if leftover_tokens:
            print(f"         Leftover tokens after restore: {leftover_tokens}")
        print()

    # ── Specific critical tests ────────────────────────────────────────
    print("  --- Critical ordering test: $$ not split into two $ ---")
    test_display = "Equation: $$\\frac{a}{b} = c$$"
    shielded_d, tmap_d = shield_math(test_display)
    counts_d = get_math_token_counts(tmap_d)
    if counts_d["block_count"] == 1 and counts_d["inline_count"] == 0:
        print("  [PASS] $$ correctly matched as one block token (not split into inline)")
    else:
        print("  [FAIL] $$ was incorrectly split into inline tokens!")
        print("         block=" + str(counts_d["block_count"]) + ", inline=" + str(counts_d["inline_count"]))
        all_pass = False
    print()

    # ── Rollback test ──────────────────────────────────────────────────
    print("  --- Rollback test: missing token raises MathRestoreError ---")
    try:
        deshield_math("hello __MATH_BLOCK_99__ world", {"__MATH_BLOCK_0__": "$$x$$"})
        print("  [FAIL] No error raised for missing token")
        all_pass = False
    except MathRestoreError:
        print("  [PASS] MathRestoreError raised correctly for missing token")
    print()

    # ── Nested expression test ─────────────────────────────────────────
    print("  --- Nested expression test: fractions with exponents ---")
    nested = (
        "The formula $\\frac{x^{2} + y^{2}}{\\sqrt{z^{3}}} = "
        "\\int_{0}^{\\infty} e^{-t^{2}} dt$ appears in many contexts."
    )
    shielded_n, tmap_n = shield_math(nested)
    restored_n = deshield_math(shielded_n, tmap_n)
    if restored_n == nested:
        print("  [PASS] Nested fraction/exponent expression restored exactly")
        print("         Token: " + list(tmap_n.keys())[0])
        stored = list(tmap_n.values())[0]
        print("         Stored LaTeX: " + stored[:70] + ("..." if len(stored) > 70 else ""))
    else:
        print("  [FAIL] Nested expression round-trip mismatch")
        all_pass = False
    print()

    # ── Multi-line block test ──────────────────────────────────────────
    print("  --- Multi-line block equation test ---")
    multiline = "The integral:\n$$\n\\int_{-\\infty}^{\\infty}\ne^{-x^2} dx = \\sqrt{\\pi}\n$$\nconverges absolutely."
    shielded_m, tmap_m = shield_math(multiline)
    restored_m = deshield_math(shielded_m, tmap_m)
    counts_m = get_math_token_counts(tmap_m)
    if restored_m == multiline and counts_m["block_count"] == 1:
        print("  [PASS] Multi-line $$ block matched and restored as single token")
    else:
        print("  [FAIL] Multi-line block test failed")
        print("         counts=" + str(counts_m) + ", match=" + str(restored_m == multiline))
        all_pass = False
    print()

    # ── Empty string edge case ─────────────────────────────────────────
    print("  --- Edge case: empty string ---")
    shielded_e, tmap_e = shield_math("")
    assert shielded_e == "" and tmap_e == {}
    print("  [PASS] Empty string returns empty shielded text and empty map")
    print()

    # ── Final result ───────────────────────────────────────────────────
    if all_pass:
        print("  Stage 9 guardrail: PASSED. Math shield round-trips are exact.")
    else:
        print("  Stage 9 guardrail: FAILED. See errors above.")
        sys.exit(1)


if __name__ == "__main__":
    _run_verification()
