"""Kysy agentilta komentoriviltä.

Aja:  uv run python -m klinikka.ask "Paljonko maksaa perusverenkuva?"
      uv run python -m klinikka.ask            (interaktiivinen tila)
"""

from __future__ import annotations

import sys

from klinikka.agent import answer, build_agent, build_azure_model
from klinikka.config import Settings
from klinikka.retrieval import AzureEmbedder, Retriever
from klinikka.tracing import setup_tracing


def main() -> None:
    settings = Settings.from_env()
    setup_tracing()
    retriever = Retriever(AzureEmbedder(settings))
    agent = build_agent(build_azure_model())

    questions = [" ".join(sys.argv[1:])] if len(sys.argv) > 1 else None
    while True:
        question = questions.pop() if questions else input("\nKysymys (tyhjä lopettaa): ").strip()
        if not question:
            break
        r = answer(agent, retriever, question, settings=settings)
        cost = r.cost_usd or 0.0
        print(f"\n{r.output.vastaus}")
        print(f"\n  tyyppi: {r.output.tyyppi}")
        print(f"  lähteet (malli): {', '.join(r.output.lahteet) or '-'}")
        print(f"  haetut dokumentit: {', '.join(r.retrieved_sources) or '-'}")
        if r.pii_input:
            print(f"  poistetut henkilötiedot (syöte): {r.pii_input}")
        if r.pii_output:
            print(f"  poistetut henkilötiedot (vastaus): {r.pii_output}")
        if r.fallback:
            print("  VARAVASTAUS: malli ei tuottanut hyväksyttävää vastausta")
        if r.validation_retries:
            print(f"  validaattori pakotti korjaamaan: {r.validation_retries} kertaa")
        print(
            f"  {r.latency_s:.2f} s | {r.requests} mallikutsua | "
            f"{r.input_tokens}+{r.output_tokens} tokenia | {cost * 100:.4f} senttiä"
        )
        print(f"  trace: {r.trace_id}")
        if questions is not None:
            break


if __name__ == "__main__":
    main()
