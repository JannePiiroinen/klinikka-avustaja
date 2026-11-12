"""Keskitetyt asetukset. Kaikki ympäristökohtainen luetaan .env-tiedostosta,
joten mallin tai tarjoajan vaihtaminen ei vaadi koodimuutoksia."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


def _find_project_root() -> Path:
    """Etsii projektikansion (pyproject.toml + data/knowledge_base).

    Ei luota pelkkään __file__-polkuun, koska paketti voi olla asennettuna
    kopiona .venv-kansioon (ei-editoitava asennus), jolloin polku osoittaisi sinne.
    """
    if env_root := os.getenv("KLINIKKA_ROOT"):
        return Path(env_root).resolve()
    for start in (Path.cwd().resolve(), Path(__file__).resolve().parent):
        for candidate in (start, *start.parents):
            if (candidate / "pyproject.toml").is_file() and (
                candidate / "data" / "knowledge_base"
            ).is_dir():
                return candidate
    raise RuntimeError(
        "Projektikansiota ei löytynyt. Aja komennot projektikansiossa "
        "tai aseta ympäristömuuttuja KLINIKKA_ROOT."
    )


PROJECT_ROOT = _find_project_root()
KNOWLEDGE_BASE_DIR = PROJECT_ROOT / "data" / "knowledge_base"

load_dotenv(PROJECT_ROOT / ".env")


def _require(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Ympäristömuuttuja {name} puuttuu. Täytä se .env-tiedostoon.")
    return value


@dataclass(frozen=True)
class Settings:
    azure_endpoint: str
    azure_api_key: str
    azure_api_version: str
    chat_deployment: str
    embedding_deployment: str
    judge_deployment: str
    price_input_per_m: float
    price_output_per_m: float

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            azure_endpoint=_require("AZURE_OPENAI_ENDPOINT"),
            azure_api_key=_require("AZURE_OPENAI_API_KEY"),
            azure_api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-10-21"),
            chat_deployment=_require("CHAT_DEPLOYMENT"),
            embedding_deployment=_require("EMBEDDING_DEPLOYMENT"),
            # Tuomarina voi käyttää eri (isompaa) mallia kuin agenttina; oletus on sama malli.
            judge_deployment=os.getenv("JUDGE_DEPLOYMENT", "").strip()
            or _require("CHAT_DEPLOYMENT"),
            price_input_per_m=float(os.getenv("PRICE_INPUT_PER_M", "0.40")),
            price_output_per_m=float(os.getenv("PRICE_OUTPUT_PER_M", "1.60")),
        )

    def cost_usd(self, input_tokens: int, output_tokens: int) -> float:
        """Yhden mallikutsun hinta dollareina."""
        return (
            input_tokens * self.price_input_per_m + output_tokens * self.price_output_per_m
        ) / 1_000_000
