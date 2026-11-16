"""Yhteinen palvelukerros, jota komentorivi, REST-rajapinta (FastAPI) ja MCP-palvelin käyttävät.

Kaikki kolme kutsuvat samaa answer()-funktiota, joten guardrailit, lähdevalidaattori,
varavastaus ja tracing ovat voimassa riippumatta siitä, mistä kysymys tulee.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from pydantic_ai import Agent

from klinikka.agent import AnswerResult, Deps, Vastaus, answer, build_agent, build_azure_model
from klinikka.chunking import load_chunks
from klinikka.config import KNOWLEDGE_BASE_DIR, Settings
from klinikka.retrieval import AzureEmbedder, Retriever


@dataclass
class AssistantService:
    retriever: Retriever
    agent: Agent[Deps, Vastaus]
    settings: Settings | None = None  # None = ei kustannuslaskentaa (testit)

    @classmethod
    def from_env(cls) -> AssistantService:
        settings = Settings.from_env()
        retriever = Retriever(AzureEmbedder(settings))
        if retriever.count() == 0:
            # Ensimmäinen käynnistys (esim. uusi Docker-volyymi): indeksoidaan tietopohja.
            retriever.rebuild(load_chunks(KNOWLEDGE_BASE_DIR))
        return cls(retriever=retriever, agent=build_agent(build_azure_model()), settings=settings)

    def ask(self, question: str, today: date | None = None) -> AnswerResult:
        return answer(self.agent, self.retriever, question, today=today, settings=self.settings)
