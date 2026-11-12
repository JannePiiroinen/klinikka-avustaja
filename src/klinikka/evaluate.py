"""Aja evaluointi.

    uv run python -m klinikka.evaluate                  # kaikki tapaukset + LLM-tuomari
    uv run python -m klinikka.evaluate --limit 5        # nopea kokeilu
    uv run python -m klinikka.evaluate --kategoria terveys
    uv run python -m klinikka.evaluate --gate           # exit 1, jos laatu alittaa rajat
    uv run python -m klinikka.evaluate --toista 3       # vakausmittaus: sama setti 3 kertaa

Tulokset: reports/latest.md (raportti), reports/latest.json (raakadata) sekä MLflow-run
kokeessa "klinikka-avustaja-eval" (metriikat, raportti ja jokaisen kyselyn trace).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import date, datetime

from klinikka import tracing
from klinikka.agent import INSTRUCTIONS, answer, build_agent, build_azure_model
from klinikka.config import PROJECT_ROOT, Settings
from klinikka.evaluation import (
    CaseResult,
    build_judge,
    check_rules,
    gate,
    judge,
    load_cases,
    render_report,
    summarize,
)
from klinikka.retrieval import AzureEmbedder, Retriever

# Kiinteä "tänään", jotta "huomenna" ja "ensi maanantaina" ovat toistettavia (to 12.11.2026).
EVAL_TODAY = date(2026, 11, 12)
REPORTS_DIR = PROJECT_ROOT / "reports"


def _run_cases(cases, agent, judge_agent, retriever, settings) -> list[CaseResult]:
    results: list[CaseResult] = []
    for i, case in enumerate(cases, 1):
        print(f"[{i:>2}/{len(cases)}] {case.id} {case.kysymys[:60]}", flush=True)
        try:
            r = answer(agent, retriever, case.kysymys, today=EVAL_TODAY, settings=settings)
            checks = check_rules(case, r)
            perusteettomat: list[str] = []
            if judge_agent is not None:
                verdict = judge(judge_agent, r)
                checks["perustuu_lahteisiin"] = verdict.perustuu_lahteisiin
                perusteettomat = verdict.perusteettomat_vaitteet
            else:
                checks["perustuu_lahteisiin"] = None
            results.append(
                CaseResult(
                    case=case,
                    checks=checks,
                    vastaus=r.output.vastaus,
                    tyyppi=r.output.tyyppi,
                    lahteet=r.output.lahteet,
                    perusteettomat=perusteettomat,
                    latency_s=r.latency_s,
                    cost_usd=r.cost_usd or 0.0,
                    validation_retries=r.validation_retries,
                    trace_id=r.trace_id,
                    fallback=r.fallback,
                )
            )
        except Exception as exc:  # yksittäinen kaatuminen ei saa kaataa koko ajoa
            results.append(CaseResult(case=case, checks={}, virhe=f"{type(exc).__name__}: {exc}"))
        last = results[-1]
        status = "OK " if last.ok else "FAIL"
        note = " (varavastaus)" if last.fallback else ""
        print(f"       {status} {last.tyyppi}{note} {last.virhe or ''}")
    return results


def _stability(runs: list[list[CaseResult]]) -> dict:
    """Vertaa toistettuja ajoja: kuinka vakaa tulos on ja mitkä tapaukset heiluvat."""
    scores = [summarize(r)["kaikki_ok"] for r in runs]
    fail_counts: dict[str, tuple[int, str]] = {}
    for run in runs:
        for r in run:
            if not r.ok:
                count, question = fail_counts.get(r.case.id, (0, r.case.kysymys))
                fail_counts[r.case.id] = (count + 1, question)
    metrics = {
        "kaikki_ok_min": min(scores),
        "kaikki_ok_ka": sum(scores) / len(scores),
        "heiluvat_tapaukset": float(sum(1 for c, _ in fail_counts.values() if c < len(runs))),
    }
    if len(runs) == 1:
        return {"metrics": metrics, "markdown": ""}
    lines = [
        "",
        f"## Vakaus ({len(runs)} ajoa)",
        "",
        "Ajojen tulokset (kaikki tarkistukset ok): "
        + ", ".join(f"{s * 100:.0f} %" for s in scores)
        + f" · keskiarvo {metrics['kaikki_ok_ka'] * 100:.0f} % · heikoin "
        f"{metrics['kaikki_ok_min'] * 100:.0f} %",
        "",
    ]
    if fail_counts:
        lines += ["| Tapaus | Epäonnistui | Kysymys |", "|---|---|---|"]
        for cid, (count, question) in sorted(fail_counts.items(), key=lambda x: -x[1][0]):
            lines.append(f"| {cid} | {count}/{len(runs)} | {question} |")
    else:
        lines.append("Kaikki tapaukset onnistuivat jokaisessa ajossa.")
    return {"metrics": metrics, "markdown": "\n".join(lines) + "\n"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, help="aja vain N ensimmäistä tapausta")
    parser.add_argument("--kategoria", help="aja vain tämän kategorian tapaukset")
    parser.add_argument("--no-judge", action="store_true", help="ohita LLM-tuomari")
    parser.add_argument("--gate", action="store_true", help="exit 1, jos raja-arvot alittuvat")
    parser.add_argument(
        "--toista", type=int, default=1, help="aja setti N kertaa ja mittaa tulosten vakaus"
    )
    args = parser.parse_args()

    cases = load_cases()
    if args.kategoria:
        cases = [c for c in cases if c.kategoria == args.kategoria]
    if args.limit:
        cases = cases[: args.limit]

    settings = Settings.from_env()
    tracing.setup_tracing(experiment="klinikka-avustaja-eval")
    import mlflow

    model = build_azure_model()
    agent = build_agent(model)
    judge_agent = (
        None if args.no_judge else build_judge(build_azure_model(settings.judge_deployment))
    )
    retriever = Retriever(AzureEmbedder(settings))
    prompt_hash = hashlib.sha256(INSTRUCTIONS.encode()).hexdigest()[:10]

    runs: list[list[CaseResult]] = []
    with mlflow.start_run(run_name=f"eval-{datetime.now():%Y%m%d-%H%M}"):
        mlflow.log_params(
            {
                "chat_model": settings.chat_deployment,
                "judge_model": settings.judge_deployment,
                "retrieval_k": 6,
                "embedding_model": settings.embedding_deployment,
                "prompt_sha": prompt_hash,
                "tapauksia": len(cases),
                "llm_tuomari": not args.no_judge,
                "toistoja": args.toista,
            }
        )
        for run_idx in range(args.toista):
            if args.toista > 1:
                print(f"\n=== Ajo {run_idx + 1}/{args.toista} ===")
            runs.append(_run_cases(cases, agent, judge_agent, retriever, settings))

        results = runs[-1]
        summary = summarize(results)
        stability = _stability(runs)
        summary.update(stability["metrics"])
        meta = {
            "model": f"{settings.chat_deployment} (tuomari: {settings.judge_deployment})",
            "today": EVAL_TODAY.isoformat(),
            "run_at": f"{datetime.now():%Y-%m-%d %H:%M}",
        }
        report = render_report(results, summary, meta) + stability["markdown"]

        REPORTS_DIR.mkdir(exist_ok=True)
        (REPORTS_DIR / "latest.md").write_text(report, encoding="utf-8")
        (REPORTS_DIR / "latest.json").write_text(
            json.dumps(
                {"meta": meta, "summary": summary, "results": [r.to_dict() for r in results]},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        mlflow.log_metrics({k: v for k, v in summary.items() if v == v})
        mlflow.log_artifact(str(REPORTS_DIR / "latest.md"))
        mlflow.log_artifact(str(REPORTS_DIR / "latest.json"))

    print("\n" + report.split("## Tapauskohtaiset")[0])
    if args.toista > 1:
        print(stability["markdown"])
    # Portti arvioidaan heikoimman ajon perusteella: laadun pitää pitää joka kerta.
    failures = gate(min((summarize(r) for r in runs), key=lambda x: x["kaikki_ok"]))
    if failures:
        print("Laatuportti EI läpäisty:\n  " + "\n  ".join(failures))
        return 1 if args.gate else 0
    print("Laatuportti läpäisty.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
