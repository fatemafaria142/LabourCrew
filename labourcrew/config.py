from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
PROCESSED_DIR = DATA_DIR / "processed"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=REPO_ROOT / ".env", extra="ignore")

    openai_api_key: str
    openai_chat_model: str = "gpt-4o-mini"
    openai_embed_model: str = "text-embedding-3-large"

    # "bge" (default): local BAAI/bge-m3, multilingual incl. Bangla, no API cost.
    # "openai": text-embedding-3-large, kept for A/B comparison.
    embedding_provider: str = "bge"
    bge_model_name: str = "BAAI/bge-m3"

    gemini_api_key: str
    gemini_ocr_model: str = "gemini-3-flash-preview"

    # NOT named milvus_uri/MILVUS_URI on purpose: pymilvus itself calls
    # load_dotenv() at import time and reads that exact env var as a legacy
    # connection default, then crashes trying to parse a local file path as
    # "host:port". See .env.example for the longer note.
    statutegraph_milvus_db_path: str = str(DATA_DIR / "milvus_statutegraph.db")
    statutegraph_milvus_collection: str = "statutegraph"

    statute_version: str = "BLA-2006-amended"

    # Trust Gate: "calibrated" filters claims on
    # trust_score >= trust_gate_tau (tau chosen by Conformal Risk Control,
    # see scripts/calibrate_trust_gate.py); "categorical" is the legacy
    # LLM-decided trust_status filter, kept only as an ablation baseline.
    trust_gate_mode: Literal["categorical", "calibrated"] = "calibrated"
    trust_gate_tau: float = 0.5
    trust_gate_alpha: float = 0.10

    def resolved_milvus_uri(self) -> str:
        """Resolve a relative Milvus Lite file path against REPO_ROOT.

        Milvus Lite treats any uri without a scheme (no `://`) as a local file path,
        interpreted relative to the process cwd — resolving it ourselves keeps
        behavior stable regardless of where a script is invoked from.
        """
        if "://" in self.statutegraph_milvus_db_path:
            return self.statutegraph_milvus_db_path
        p = Path(self.statutegraph_milvus_db_path)
        return str(p if p.is_absolute() else (REPO_ROOT / p))


def get_settings() -> Settings:
    return Settings()
