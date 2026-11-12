"""Tarkistaa, että Azure AI Foundryn chat- ja embedding-deploymentit vastaavat.

Aja:  uv run python scripts/check_azure.py
"""

from __future__ import annotations

import time

from openai import AzureOpenAI

from klinikka.config import Settings


def main() -> None:
    s = Settings.from_env()
    client = AzureOpenAI(
        azure_endpoint=s.azure_endpoint,
        api_key=s.azure_api_key,
        api_version=s.azure_api_version,
    )

    print(f"Chat-deployment: {s.chat_deployment}")
    start = time.perf_counter()
    resp = client.chat.completions.create(
        model=s.chat_deployment,
        messages=[
            {"role": "system", "content": "Vastaa lyhyesti suomeksi."},
            {"role": "user", "content": "Sano 'Yhteys toimii!' ja yksi hauska fakta revontulista."},
        ],
        max_tokens=80,
    )
    latency = time.perf_counter() - start
    usage = resp.usage
    print("  Vastaus:", resp.choices[0].message.content)
    print(f"  Viive: {latency:.2f} s")
    if usage:
        cost = s.cost_usd(usage.prompt_tokens, usage.completion_tokens)
        print(
            f"  Tokenit: {usage.prompt_tokens} sisään / {usage.completion_tokens} ulos"
            f"  ->  {cost * 100:.4f} senttiä (USD)"
        )

    print(f"\nEmbedding-deployment: {s.embedding_deployment}")
    emb = client.embeddings.create(model=s.embedding_deployment, input=["Testilause"])
    print(f"  Vektorin pituus: {len(emb.data[0].embedding)}")

    print("\nKaikki kunnossa – Azure-yhteys toimii.")


if __name__ == "__main__":
    main()
