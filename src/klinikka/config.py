"""Keskitetyt asetukset. Kaikki ympäristökohtainen luetaan .env-tiedostosta,
joten mallin tai tarjoajan vaihtaminen ei vaadi koodimuutoksia."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
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
            price_input_per_m=float(os.getenv("PRICE_INPUT_PER_M", "0.40")),
            price_output_per_m=float(os.getenv("PRICE_OUTPUT_PER_M", "1.60")),
        )

    def cost_usd(self, input_tokens: int, output_tokens: int) -> float:
        """Yhden mallikutsun hinta dollareina."""
        return (
            input_tokens * self.price_input_per_m + output_tokens * self.price_output_per_m
        ) / 1_000_000
