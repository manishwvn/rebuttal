"""Settings. Rebuttal refuses to run against anything but the PayPal sandbox."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

SANDBOX_BASE_URL = "https://api-m.sandbox.paypal.com"
DEFAULT_MODEL = "claude-sonnet-5-5"
DEFAULT_GROQ_MODEL = "qwen/qwen3.8-27b"
DEFAULT_NVIDIA_MODEL = "z-ai/glm-5.3"
DEFAULT_MUSE_MODEL = "muse-spark-1.3-contributor"


def _load_dotenv(path: Path) -> None:
    """Minimal .env loader (no extra dependency). Existing env vars win."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


@dataclass(frozen=True)
class Settings:
    paypal_env: str
    client_id: str
    client_secret: str = field(repr=False)
    mock: bool
    anthropic_api_key: str | None = field(repr=False)
    model: str  # Claude model
    nvidia_api_key: str | None = field(repr=False)
    nvidia_model: str
    groq_api_key: str | None = field(repr=False)
    groq_model: str
    muse_api_key: str | None = field(repr=False)
    muse_model: str
    audit_path: Path
    database_url: str | None = field(default=None, repr=False)  # a postgres:// DATABASE_URL: checkpoints and the audit log live there
    checkpoint_target: str | None = field(default=None, repr=False)  # None = in memory; see persistence.py
    provider: str | None = None  # REBUTTAL_PROVIDER=groq|nvidia|anthropic pins the model provider
    reasoner: str = "auto"  # "rules" (REBUTTAL_REASONER=rules) never calls a model, whatever keys are set

    @property
    def base_url(self) -> str:
        return SANDBOX_BASE_URL


def load_settings(env_file: Path | None = None) -> Settings:
    _load_dotenv(env_file or Path(__file__).resolve().parents[1] / ".env")

    model = os.getenv("REBUTTAL_MODEL", DEFAULT_MODEL)
    paypal_env = os.getenv("PAYPAL_ENV", "sandbox")
    if paypal_env != "sandbox":
        raise RuntimeError(
            "Rebuttal only runs against the PayPal sandbox. Set PAYPAL_ENV=sandbox."
        )

    client_id = os.getenv("PAYPAL_CLIENT_ID", "")
    client_secret = os.getenv("PAYPAL_CLIENT_SECRET", "")
    # Mock mode unless explicitly turned off AND real sandbox keys exist.
    mock = os.getenv("REBUTTAL_MOCK", "1") == "1" or not (client_id and client_secret)

    database_url = os.getenv("DATABASE_URL", "")
    checkpoint_target = os.getenv("REBUTTAL_CHECKPOINT_URL") or (
        database_url if database_url.startswith(("postgres://", "postgresql://")) else None)
    if not checkpoint_target and not mock:
        checkpoint_target = "checkpoints.sqlite"  # real sandbox: keep paused proposals across restarts

    return Settings(
        paypal_env=paypal_env,
        client_id=client_id,
        client_secret=client_secret,
        mock=mock,
        anthropic_api_key=os.getenv("ANTHROPIC_API_KEY") or None,
        # REBUTTAL_MODEL names the model for whichever provider is active; a claude-* name is Claude's.
        model=model if model.startswith("claude") else DEFAULT_MODEL,
        nvidia_api_key=os.getenv("NVIDIA_API_KEY") or None,
        nvidia_model=os.getenv("NVIDIA_MODEL") or (DEFAULT_NVIDIA_MODEL if model.startswith("claude") else model),
        groq_api_key=os.getenv("GROQ_API_KEY") or None,
        groq_model=os.getenv("GROQ_MODEL", DEFAULT_GROQ_MODEL),
        muse_api_key=os.getenv("MUSE_API_KEY") or None,
        muse_model=os.getenv("MUSE_MODEL", DEFAULT_MUSE_MODEL),
        audit_path=Path(os.getenv("REBUTTAL_AUDIT_PATH", "audit.jsonl")),
        database_url=database_url if database_url.startswith(("postgres://", "postgresql://")) else None,
        checkpoint_target=checkpoint_target,
        provider=(os.getenv("REBUTTAL_PROVIDER") or "").strip().lower() or None,
        reasoner=os.getenv("REBUTTAL_REASONER", "auto").strip().lower(),
    )
