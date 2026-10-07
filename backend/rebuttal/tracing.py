"""Langfuse tracing, the eval dataset and experiments. Everything here is off unless both Langfuse keys are set.

Read from os.environ on every call: LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY, LANGFUSE_BASE_URL (LANGFUSE_HOST is the
fallback) and REBUTTAL_TRACING=0 (or false/off) to switch it off. langfuse is imported inside the functions that need
it, so importing this module costs nothing and never touches the network.
"""

from __future__ import annotations

import copy
import inspect
import logging
import os
import re
from typing import TYPE_CHECKING, Any, Awaitable, Callable, Iterable

if TYPE_CHECKING:
    from langfuse import Evaluation, Langfuse
    from langfuse.experiment import ExperimentResult

DATASET_NAME = "rebuttal-disputes"

logger = logging.getLogger(__name__)

_OFF = ("0", "false", "off")
_LABEL_KEYS = ("expected", "why", "hard")  # labels stay out of the dataset item input, the model never sees them
_warned: set[str] = set()


def langfuse_configured() -> bool:
    """True when both Langfuse keys are set and REBUTTAL_TRACING is not 0/false/off."""
    if os.getenv("REBUTTAL_TRACING", "").strip().lower() in _OFF:
        return False
    return all(os.getenv(key, "").strip() for key in ("LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY"))


def _base_url() -> str | None:
    """LANGFUSE_BASE_URL, else the deprecated LANGFUSE_HOST; None leaves the choice to the SDK (EU cloud)."""
    for key in ("LANGFUSE_BASE_URL", "LANGFUSE_HOST"):
        value = os.getenv(key, "").strip().rstrip("/")  # the SDK appends paths to it without normalising
        if value:
            return value
    return None


_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")


def mask_emails(*, data: Any, **kwargs: Any) -> Any:
    """Langfuse `mask` hook: replace email addresses in anything sent as a trace's input or output. Best effort:
    buyer names and addresses in the case snapshot are not masked, so keep tracing to sandbox and test data."""
    if isinstance(data, str):
        return _EMAIL.sub("[email]", data)
    if isinstance(data, dict):
        return {key: mask_emails(data=value) for key, value in data.items()}
    if isinstance(data, (list, tuple)):
        return [mask_emails(data=value) for value in data]
    return data


def _client() -> Langfuse:
    """The shared Langfuse client. The SDK keeps one set of resources per public key, so this is cheap to repeat.

    Langfuse 4.17 already reads LANGFUSE_BASE_URL, then the deprecated LANGFUSE_HOST (langfuse/_client/client.py).
    The URL is resolved here as well, so both keep working if the SDK drops HOST, and a trailing slash is removed."""
    from langfuse import Langfuse

    return Langfuse(
        public_key=os.environ["LANGFUSE_PUBLIC_KEY"].strip(),
        secret_key=os.environ["LANGFUSE_SECRET_KEY"].strip(),
        base_url=_base_url(),
        mask=mask_emails,
    )


def _require_client() -> Langfuse:
    if not langfuse_configured():
        raise RuntimeError("Langfuse is not configured: set LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY "
                           "(and do not set REBUTTAL_TRACING=0)")
    return _client()


def _warn_once(key: str, message: str, *args: Any) -> None:
    if key not in _warned:
        _warned.add(key)
        logger.warning(message, *args)


def trace_config(*, dispute_id: str, model: str, provider: str, tags: Iterable[str] = ()) -> dict:
    """A RunnableConfig fragment (callbacks, metadata) to merge into `graph.invoke(config=...)`; {} when tracing is off.

    The handler reads two reserved keys from the root run's metadata: `langfuse_session_id` becomes the session (one
    session per dispute, so every run of a dispute lands together) and `langfuse_tags` the trace tags. The other
    metadata keys are copied onto each observation as searchable trace metadata. A new handler is made on every call,
    so it joins whatever Langfuse span is active at that moment, for example an experiment item (see run_experiment).
    If the handler cannot be built (for example the `langchain` package is missing) it logs once and returns {}:
    tracing must never stop an analysis."""
    if not langfuse_configured():
        return {}
    dispute_id = str(dispute_id)
    try:
        _client()  # builds the SDK client from our settings first, so the handler below reuses it
        from langfuse.langchain import CallbackHandler

        handler = CallbackHandler(public_key=os.environ["LANGFUSE_PUBLIC_KEY"].strip())
    except Exception as exc:
        _warn_once("handler", "Langfuse tracing is off, the callback handler could not be created: %s: %s",
                   type(exc).__name__, exc)
        return {}
    extra = [tags] if isinstance(tags, str) else list(tags or ())
    return {
        "callbacks": [handler],
        "metadata": {
            "langfuse_session_id": dispute_id,
            "langfuse_tags": list(dict.fromkeys(
                [f"dispute:{dispute_id}", f"model:{model}", f"provider:{provider}", *extra])),
            "dispute_id": dispute_id,
            "model": model,
            "provider": provider,
        },
    }


def flush() -> None:
    """Send pending Langfuse events now. Short-lived scripts call this before they exit; no-op when tracing is off."""
    if not langfuse_configured():
        return
    try:
        _client().flush()
    except Exception as exc:
        logger.warning("Langfuse flush failed: %s: %s", type(exc).__name__, exc)


def upload_dataset(cases: list[dict], name: str = DATASET_NAME) -> str:
    """Create the dataset if needed and upsert one item per case. Returns the dataset name.

    Safe to repeat: the server upserts datasets by name and items by id, and the item id is the case id. Two server
    rules follow from that: item ids are unique per project across datasets (the same case ids cannot go into a second
    dataset), and every upsert writes a new item version even when nothing changed."""
    cases = list(cases)
    ids = [case["id"] for case in cases]
    if len(set(ids)) != len(ids):
        raise ValueError(f"duplicate case ids: {sorted({i for i in ids if ids.count(i) > 1})}")
    client = _require_client()
    client.create_dataset(name=name, description="Labeled PayPal disputes (backend/evals/cases.json) with the "
                                                 "expected resolution for each")
    for case in cases:
        client.create_dataset_item(
            dataset_name=name,
            id=case["id"],
            input={key: value for key, value in case.items() if key not in _LABEL_KEYS},
            expected_output={"resolution": case["expected"]},
            metadata={"id": case["id"], "title": case.get("title"), "hard": bool(case.get("hard", False)),
                      "why": case.get("why")},
        )
    return name


def _resolution(value: Any) -> Any:
    """The resolution in a task output or an expected output: {"resolution": ...}, a bare label, or an object."""
    if isinstance(value, dict):
        return value.get("resolution")
    if isinstance(value, str):
        return value
    return getattr(value, "resolution", None)


def correct(*, input: Any = None, output: Any = None, expected_output: Any = None, metadata: Any = None,
            **kwargs: Any) -> Evaluation:
    """Item evaluator "correct": 1.0 when the task's resolution is the labeled one, else 0.0."""
    from langfuse import Evaluation

    got, want = _resolution(output), _resolution(expected_output)
    if got is not None and got == want:
        return Evaluation(name="correct", value=1.0, comment=f"matches the label ({got})")
    if got is None and isinstance(output, dict) and output.get("error"):
        return Evaluation(name="correct", value=0.0, comment=f"task failed: {output['error']}")
    return Evaluation(name="correct", value=0.0, comment=f"expected {want}, got {got}")


def accuracy(*, item_results: list, **kwargs: Any) -> Evaluation:
    """Run evaluator "accuracy": the mean of the "correct" scores."""
    from langfuse import Evaluation

    scores = [e.value for result in item_results for e in result.evaluations if e.name == "correct"]
    if not scores:
        return Evaluation(name="accuracy", value=0.0, comment="no scored items")
    return Evaluation(name="accuracy", value=sum(scores) / len(scores),
                      comment=f"{round(sum(scores))}/{len(scores)} correct")


def _item_task(task: Callable[[dict], dict | Awaitable[dict]]) -> Callable[..., Awaitable[Any]]:
    """Adapt `task(case) -> dict` (sync or async) to the SDK's `task(*, item, **kwargs)`.

    The case is a copy, so a task that edits it does not change the input the trace records. A task that raises is
    reported as a wrong answer carrying the error, not dropped: the SDK leaves failed items out of the run results,
    which would let a crash raise the accuracy."""

    async def run(*, item: Any, **kwargs: Any) -> Any:
        case = copy.deepcopy(item.input if hasattr(item, "input") else item["input"])
        try:
            output = task(case)
            if inspect.isawaitable(output):
                output = await output
        except Exception as exc:
            logger.warning("eval task failed on %s: %s: %s", case.get("id") if isinstance(case, dict) else "?",
                           type(exc).__name__, exc, exc_info=True)
            return {"resolution": None, "error": f"{type(exc).__name__}: {exc}"}
        return output

    return run


def run_experiment(*, name: str, task: Callable[[dict], dict | Awaitable[dict]], dataset_name: str = DATASET_NAME,
                   description: str | None = None, metadata: dict | None = None,
                   max_concurrency: int = 1) -> ExperimentResult:
    """Run `task(case) -> dict` once per dataset item as the Langfuse experiment `name`; returns the SDK's result.

    `case` is the item's input. The returned dict needs a "resolution" and may carry more (confidence, source, ...).
    Each item gets the score "correct" and the run gets "accuracy" (see the two evaluators above).

    Nesting: the SDK opens a trace per item (`experiment-item-run` > `experiment-item-task`) and calls `task` while
    that span is the current OpenTelemetry span. A handler made by `trace_config()` inside `task` therefore parents
    its root run under `experiment-item-task`, so each graph run sits inside its item's trace and carries the
    experiment ids. Create the handler inside `task`, never outside it.

    A sync task runs on the event loop thread, one item at a time. `max_concurrency` only matters for an async task;
    the SDK's own default of 50 would flood a rate-limited model API."""
    dataset = _require_client().get_dataset(dataset_name)
    return dataset.run_experiment(
        name=name,
        description=description,
        task=_item_task(task),
        evaluators=[correct],
        run_evaluators=[accuracy],
        max_concurrency=max_concurrency,
        metadata=metadata,
    )
