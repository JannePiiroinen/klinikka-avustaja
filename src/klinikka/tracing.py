"""MLflow-tracing.

Jokainen kysely tallentuu MLflow'hun puuna:

    klinikka-avustaja (AGENT)        kysymys (henkilötiedot poistettu), vastaus, kustannus...
    ├── henkilotietojen_poisto (GUARDRAIL)   vain löydösten määrät, ei sisältöä
    └── PydanticAI-agentin ajo               autolog: mallikutsut, työkalut, tokenit

Tracing on oletuksena pois päältä (esim. testeissä). Se kytketään päälle
kutsumalla setup_tracing(). Selaa tuloksia:

    uv run mlflow ui --backend-store-uri sqlite:///mlflow.db
"""

from __future__ import annotations

import contextlib
import os
from collections.abc import Iterator
from typing import Any

from klinikka.config import PROJECT_ROOT

TRACKING_URI = f"sqlite:///{PROJECT_ROOT / 'mlflow.db'}"
EXPERIMENT = "klinikka-avustaja"

_enabled = False


def setup_tracing(experiment: str = EXPERIMENT) -> None:
    global _enabled
    os.environ.setdefault("MLFLOW_DISABLE_AGENT_HINT", "1")
    import mlflow

    mlflow.set_tracking_uri(TRACKING_URI)
    mlflow.set_experiment(experiment)
    mlflow.pydantic_ai.autolog(silent=True)
    _enabled = True


def is_enabled() -> bool:
    return _enabled


class _NoopSpan:
    def set_inputs(self, *_: Any) -> None: ...
    def set_outputs(self, *_: Any) -> None: ...
    def set_attributes(self, *_: Any) -> None: ...


@contextlib.contextmanager
def span(name: str, span_type: str) -> Iterator[Any]:
    """MLflow-span, kun tracing on päällä; muuten no-op."""
    if not _enabled:
        yield _NoopSpan()
        return
    import mlflow

    with mlflow.start_span(name=name, span_type=span_type) as s:
        yield s


def last_trace_id() -> str | None:
    if not _enabled:
        return None
    import mlflow

    mlflow.flush_trace_async_logging()
    return mlflow.get_last_active_trace_id()
