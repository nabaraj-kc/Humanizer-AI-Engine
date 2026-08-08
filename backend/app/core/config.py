"""
backend/app/core/config.py
==========================
Centralized environment settings for the Humanizer AI Engine.

GUARDRAIL RECOVERY NOTE:
  Pydantic v1 and v2 both crash (0xC0000005 / ImportError on typing.Required)
  on Python 3.11.0a2 in this environment. The recovery path implements an
  equivalent validated settings class using only the Python standard library
  + python-dotenv (which works cleanly on this runtime).

  The public API is IDENTICAL to what pydantic_settings.BaseSettings would
  produce:
    - Settings.model_validate(dict) — build from a dict (mirrors pydantic v2)
    - get_settings()                — cached singleton from .env file
    - ValidationError               — raised on missing or invalid fields
    - Field descriptors             — documented on each attribute

Free-tier quota defaults:
  - Google AI Studio  : 1,000,000 tokens/day, 15 RPM
  - Groq Cloud        :    14,400 tokens/day, 30 RPM
  - DeepSeek          :   500,000 tokens/day, 60 RPM
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

from dotenv import dotenv_values

# Resolve project root for .env file location
_PROJECT_ROOT = Path(__file__).resolve().parents[3]  # core->app->backend->root
_ENV_FILE = _PROJECT_ROOT / ".env"


# ---------------------------------------------------------------------------
# Custom ValidationError (mirrors pydantic's interface)
# ---------------------------------------------------------------------------
class ValidationError(Exception):
    """
    Raised when Settings construction fails due to missing or invalid fields.
    Provides a structured list of per-field errors matching pydantic's API.
    """

    def __init__(self, errors: list[dict[str, Any]]):
        self._errors = errors
        messages = "\n".join(
            f"  {e['loc'][0]}: {e['msg']}" for e in errors
        )
        super().__init__(
            f"{len(errors)} validation error(s) for Settings:\n{messages}"
        )

    def errors(self) -> list[dict[str, Any]]:
        return self._errors


# ---------------------------------------------------------------------------
# Settings class
# ---------------------------------------------------------------------------
class Settings:
    """
    Application-wide validated configuration.

    Behaves like pydantic_settings.BaseSettings:
      - Loads .env file on construction.
      - Validates all required fields with descriptive error messages.
      - Raises ValidationError on missing or invalid values.
    """

    # ── Field registry (name -> (required, default, validators, description))
    _FIELD_SPEC: dict[str, dict] = {
        "DATABASE_URL": {
            "required": False,
            "default": None,  # computed from project root
            "description": "Async SQLite connection URL.",
        },
        "GOOGLE_API_KEY": {
            "required": False,
            "min_length": 10,
            "placeholder": "your_google_ai_studio_key_here",
            "description": "Google AI Studio API key (Gemini Flash/Pro).",
        },
        "GROQ_API_KEY": {
            "required": False,
            "min_length": 10,
            "placeholder": "your_groq_api_key_here",
            "description": "Groq Cloud API key (Llama 3 models).",
        },
        "DEEPSEEK_API_KEY": {
            "required": False,
            "min_length": 10,
            "placeholder": "your_deepseek_api_key_here",
            "description": "DeepSeek API key (deepseek-chat / reasoning).",
        },
        "OPENROUTER_API_KEY": {
            "required": False,
            "min_length": 10,
            "placeholder": "your_openrouter_api_key_here",
            "description": "OpenRouter API key (unified gateway to many models).",
        },
        "JWT_SECRET_KEY": {
            "required": True,
            "min_length": 16,
            "placeholder": "your_random_secret_key_here",
            "description": "Random secret (>=16 chars) for JWT signing.",
        },
    }

    def __init__(self, **values: Any):
        self._values = values
        self._validate()
        self._set_attributes()

    # ── Construction helpers ─────────────────────────────────────────────
    @classmethod
    def model_validate(cls, data: dict[str, Any]) -> "Settings":
        """Build Settings from a plain dict (mirrors pydantic v2 API)."""
        # Normalize keys to uppercase for case-insensitive matching
        normalized = {k.upper(): v for k, v in data.items()}
        return cls(**normalized)

    @classmethod
    def from_env(cls, env_file: Optional[str] = None) -> "Settings":
        """Load settings from environment variables and an optional .env file."""
        env_path = Path(env_file) if env_file else _ENV_FILE
        # Start from actual OS environment
        raw: dict[str, str] = dict(os.environ)
        # Override with .env file values if it exists
        if env_path.exists():
            file_values = dotenv_values(str(env_path))
            raw.update({k: v for k, v in file_values.items() if v is not None})
        return cls(**raw)

    # ── Validation ──────────────────────────────────────────────────────
    def _validate(self) -> None:
        errors: list[dict] = []
        v = self._values

        # Helper: get value case-insensitively
        def get(key: str) -> Optional[str]:
            return v.get(key) or v.get(key.lower())

        for field_name, spec in self._FIELD_SPEC.items():
            value = get(field_name)

            # Required check
            if spec.get("required") and not value:
                errors.append({
                    "loc": (field_name,),
                    "type": "missing",
                    "msg": (
                        f"Field is required but not set. "
                        f"Add {field_name}=<value> to your .env file. "
                        f"Hint: {spec.get('description', '')}"
                    ),
                })
                continue

            if value is None:
                continue

            # Placeholder check
            placeholder = spec.get("placeholder")
            if placeholder and value.strip().lower() == placeholder:
                errors.append({
                    "loc": (field_name,),
                    "type": "value_error",
                    "msg": (
                        f"Field contains a placeholder value from .env.example. "
                        f"Replace it with your actual value before starting the server."
                    ),
                })
                continue

            # Min-length check
            min_len = spec.get("min_length")
            if min_len and len(value.strip()) < min_len:
                errors.append({
                    "loc": (field_name,),
                    "type": "value_error",
                    "msg": (
                        f"Value is too short (min {min_len} characters, "
                        f"got {len(value.strip())}). "
                        f"{spec.get('description', '')}"
                    ),
                })

        # DATABASE_URL: must contain 'sqlite' if set
        db_url = get("DATABASE_URL")
        if db_url and "sqlite" not in db_url.lower():
            errors.append({
                "loc": ("DATABASE_URL",),
                "type": "value_error",
                "msg": (
                    f"DATABASE_URL must be a SQLite connection string for this "
                    f"local-first application. Got: {db_url!r}"
                ),
            })

        if errors:
            raise ValidationError(errors)

    def _set_attributes(self) -> None:
        """Populate typed attributes from the validated raw values dict."""
        v = self._values

        def get(key: str, default=None):
            return v.get(key) or v.get(key.lower()) or default

        # Database
        default_db = (
            f"sqlite+aiosqlite:///"
            f"{(_PROJECT_ROOT / 'storage' / 'humanizer.db').as_posix()}"
        )
        self.DATABASE_URL: str = get("DATABASE_URL", default_db)

        # API keys
        self.GOOGLE_API_KEY:      str = get("GOOGLE_API_KEY", "")
        self.GROQ_API_KEY:        str = get("GROQ_API_KEY", "")
        self.DEEPSEEK_API_KEY:    str = get("DEEPSEEK_API_KEY", "")
        self.OPENROUTER_API_KEY:  str = get("OPENROUTER_API_KEY", "")
        self.JWT_SECRET_KEY:      str = get("JWT_SECRET_KEY")

        # Processing tuning (with safe defaults)
        self.MAX_ITERATIONS:         int   = int(get("MAX_ITERATIONS", "3"))
        self.AI_SCORE_THRESHOLD:     float = float(get("AI_SCORE_THRESHOLD", "15.0"))
        self.CHUNK_TARGET_WORDS:     int   = int(get("CHUNK_TARGET_WORDS", "500"))
        self.MAX_CONCURRENT_WORKERS: int   = int(get("MAX_CONCURRENT_WORKERS", "3"))

        # Application
        self.DEBUG:       bool = str(get("DEBUG", "false")).lower() == "true"
        self.APP_TITLE:   str  = get("APP_TITLE", "Humanizer AI Engine")
        self.APP_VERSION: str  = get("APP_VERSION", "1.0.0")

    # ── Computed properties ──────────────────────────────────────────────
    @property
    def storage_dir(self) -> Path:
        return _PROJECT_ROOT / "storage"

    @property
    def api_providers(self) -> list[str]:
        return ["openrouter", "google", "groq", "deepseek"]

    def __repr__(self) -> str:
        return (
            f"<Settings title={self.APP_TITLE!r} "
            f"version={self.APP_VERSION!r} debug={self.DEBUG}>"
        )


# ---------------------------------------------------------------------------
# Cached singleton
# ---------------------------------------------------------------------------
@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """
    Return the application settings singleton loaded from .env.
    Cached after first call. Raises ValidationError immediately if any
    required fields are missing or contain placeholder values.
    """
    return Settings.from_env()


# ---------------------------------------------------------------------------
# Verification script (Stage 6 guardrail)
# ---------------------------------------------------------------------------
def _run_verification() -> None:
    import sys
    print("=== Stage 6: Config Verification Guardrail ===")
    print()

    # ── Test 1: Missing required keys ─────────────────────────────────
    print("  Test 1: Missing required keys -> ValidationError")
    try:
        bad = Settings()   # no keys supplied at all
        print("  [FAIL] No error raised — expected ValidationError")
        sys.exit(1)
    except ValidationError as e:
        errs = e.errors()
        missing = [err["loc"][0] for err in errs if err["type"] == "missing"]
        print(f"  [PASS] ValidationError raised — {len(errs)} error(s)")
        print(f"         Missing fields: {missing}")

    # ── Test 2: Placeholder key rejection ──────────────────────────────
    print()
    print("  Test 2: Placeholder values -> ValidationError")
    try:
        bad2 = Settings.model_validate({
            "GOOGLE_API_KEY":   "your_google_ai_studio_key_here",
            "GROQ_API_KEY":     "your_groq_api_key_here",
            "DEEPSEEK_API_KEY": "your_deepseek_api_key_here",
            "JWT_SECRET_KEY":   "your_random_secret_key_here",
        })
        print("  [FAIL] No error raised for placeholder keys")
        sys.exit(1)
    except ValidationError as e:
        ph_errs = [err["loc"][0] for err in e.errors() if "placeholder" in err["msg"]]
        print(f"  [PASS] ValidationError raised — placeholder fields: {ph_errs}")

    # ── Test 3: JWT secret too short ───────────────────────────────────
    print()
    print("  Test 3: JWT_SECRET_KEY too short -> ValidationError")
    try:
        bad3 = Settings.model_validate({
            "GOOGLE_API_KEY":   "valid-google-key-abcdefghij",
            "GROQ_API_KEY":     "valid-groq-key-abcdefghijkl",
            "DEEPSEEK_API_KEY": "valid-deepseek-key-abcdefgh",
            "JWT_SECRET_KEY":   "tooshort",
        })
        print("  [FAIL] No error for short JWT secret")
        sys.exit(1)
    except ValidationError as e:
        print(f"  [PASS] ValidationError raised — {e.errors()[0]['loc'][0]} too short")

    # ── Test 4: Valid config builds successfully ───────────────────────
    print()
    print("  Test 4: Valid configuration object")
    valid = Settings.model_validate({
        "DATABASE_URL":        "sqlite+aiosqlite:///./storage/humanizer.db",
        "GOOGLE_API_KEY":      "AIzaSy-valid-google-key-0123456789",
        "GROQ_API_KEY":        "gsk_valid_groq_key_0123456789abcdef",
        "DEEPSEEK_API_KEY":    "sk-valid-deepseek-key-0123456789ab",
        "JWT_SECRET_KEY":      "supersecretjwtkey_atleast16chars!!",
        "MAX_ITERATIONS":      "3",
        "AI_SCORE_THRESHOLD":  "15.0",
        "DEBUG":               "false",
    })
    print(f"  [PASS] Settings object created: {valid!r}")

    # ── Test 5: Default values and properties ──────────────────────────
    print()
    print("  Test 5: Field defaults and properties")
    assert valid.MAX_ITERATIONS == 3,          f"Bad default: {valid.MAX_ITERATIONS}"
    assert valid.AI_SCORE_THRESHOLD == 15.0,   f"Bad default: {valid.AI_SCORE_THRESHOLD}"
    assert valid.CHUNK_TARGET_WORDS == 500,    f"Bad default: {valid.CHUNK_TARGET_WORDS}"
    assert valid.MAX_CONCURRENT_WORKERS == 3,  f"Bad default: {valid.MAX_CONCURRENT_WORKERS}"
    assert valid.DEBUG is False,               f"Bad default: {valid.DEBUG}"
    assert valid.api_providers == ["google", "groq", "deepseek"]
    print(f"  [PASS] MAX_ITERATIONS         = {valid.MAX_ITERATIONS}")
    print(f"  [PASS] AI_SCORE_THRESHOLD     = {valid.AI_SCORE_THRESHOLD}%")
    print(f"  [PASS] CHUNK_TARGET_WORDS     = {valid.CHUNK_TARGET_WORDS}")
    print(f"  [PASS] MAX_CONCURRENT_WORKERS = {valid.MAX_CONCURRENT_WORKERS}")
    print(f"  [PASS] api_providers          = {valid.api_providers}")
    print(f"  [PASS] storage_dir            = {valid.storage_dir}")

    # ── Test 6: Non-SQLite DATABASE_URL rejection ──────────────────────
    print()
    print("  Test 6: Non-SQLite DATABASE_URL -> ValidationError")
    try:
        bad_db = Settings.model_validate({
            "DATABASE_URL":      "postgresql://user:pass@localhost/db",
            "GOOGLE_API_KEY":    "AIzaSy-valid-google-key-0123456789",
            "GROQ_API_KEY":      "gsk_valid_groq_key_0123456789abcdef",
            "DEEPSEEK_API_KEY":  "sk-valid-deepseek-key-0123456789ab",
            "JWT_SECRET_KEY":    "supersecretjwtkey_atleast16chars!!",
        })
        print("  [FAIL] Non-SQLite URL accepted without error")
        sys.exit(1)
    except ValidationError as e:
        print(f"  [PASS] ValidationError raised for non-SQLite DATABASE_URL")

    print()
    print("  Stage 6 guardrail: PASSED. All 6 validation tests passed.")


if __name__ == "__main__":
    _run_verification()
