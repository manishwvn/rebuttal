"""Langfuse helpers: the on/off switch, the trace config, the dataset upload and the experiment wiring.

Nothing here reaches the network: Langfuse settings are scrubbed and replaced with fake values, socket connects are
refused, and the tests that need the real SDK run it against an in-memory span exporter.
"""

import asyncio
import json
import os
import socket
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from langgraph.graph import END, START, StateGraph
from typing_extensions import TypedDict

from rebuttal import tracing

CASES = json.loads((Path(__file__).resolve().parents[1] / "evals" / "cases.json").read_text())
LABEL_KEYS = ("expected", "why", "hard")


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    """No Langfuse settings from the shell or backend/.env, and no way to open a socket."""
    for key in list(os.environ):
        if key.startswith("LANGFUSE_") or key == "REBUTTAL_TRACING":
            monkeypatch.delenv(key)

    def refuse(self, *args, **kwargs):
        raise AssertionError(f"tracing tests must not use the network: {args}")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket.socket, "connect_ex", refuse)


@pytest.fixture
def fake_keys(monkeypatch):
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-test")
    monkeypatch.setenv("LANGFUSE_BASE_URL", "http://127.0.0.1:9")  # nothing listens there


class FakeDataset:
    def __init__(self):
        self.kwargs = None

    def run_experiment(self, **kwargs):
        self.kwargs = kwargs
        return "result"


class FakeLangfuse:
    """Records dataset and flush calls. Items are keyed by id, as the server upserts them."""

    def __init__(self):
        self.calls, self.items, self.flushed, self.requested = [], {}, 0, []
        self.dataset = FakeDataset()

    def create_dataset(self, **kwargs):
        self.calls.append("create_dataset")

    def create_dataset_item(self, **kwargs):
        self.calls.append("create_dataset_item")
        self.items[kwargs["id"]] = kwargs

    def get_dataset(self, name):
        self.requested.append(name)
        return self.dataset

    def flush(self):
        self.flushed += 1


@pytest.fixture
def fake(monkeypatch, fake_keys):
    client = FakeLangfuse()
    monkeypatch.setattr(tracing, "_client", lambda: client)
    return client


def raising(exc):
    def fail(*args, **kwargs):
        raise exc

    return fail


# --------------------------------------------------------------------------- the switch

BOTH = {"LANGFUSE_PUBLIC_KEY": "pk-test", "LANGFUSE_SECRET_KEY": "sk-test"}


@pytest.mark.parametrize("env, expected", [
    ({}, False),
    ({"LANGFUSE_PUBLIC_KEY": "pk-test"}, False),
    ({"LANGFUSE_SECRET_KEY": "sk-test"}, False),
    ({**BOTH, "LANGFUSE_PUBLIC_KEY": ""}, False),
    ({**BOTH, "LANGFUSE_SECRET_KEY": "   "}, False),
    (BOTH, True),
    ({**BOTH, "REBUTTAL_TRACING": "1"}, True),
    ({**BOTH, "REBUTTAL_TRACING": ""}, True),
    ({**BOTH, "REBUTTAL_TRACING": "0"}, False),
    ({**BOTH, "REBUTTAL_TRACING": "false"}, False),
    ({**BOTH, "REBUTTAL_TRACING": "off"}, False),
    ({**BOTH, "REBUTTAL_TRACING": " OFF "}, False),
])
def test_langfuse_configured(monkeypatch, env, expected):
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    assert tracing.langfuse_configured() is expected


def test_switch_follows_the_environment_at_call_time(monkeypatch):
    assert tracing.langfuse_configured() is False
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-test")
    assert tracing.langfuse_configured() is True
    monkeypatch.setenv("REBUTTAL_TRACING", "0")
    assert tracing.langfuse_configured() is False


@pytest.mark.parametrize("env", [
    {}, {"LANGFUSE_PUBLIC_KEY": "pk-test"}, {"LANGFUSE_SECRET_KEY": "sk-test"}, {**BOTH, "REBUTTAL_TRACING": "0"}])
def test_trace_config_is_empty_and_builds_no_client_when_off(monkeypatch, env):
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(tracing, "_client", raising(AssertionError("a Langfuse client was built while tracing is off")))
    assert tracing.trace_config(dispute_id="PP-D-1", model="m", provider="p") == {}
    tracing.flush()  # also a no-op


# ------------------------------------------------------------------- base URL and client

@pytest.mark.parametrize("env, expected", [
    ({}, None),
    ({"LANGFUSE_HOST": "https://host.example"}, "https://host.example"),
    ({"LANGFUSE_BASE_URL": "https://base.example"}, "https://base.example"),
    ({"LANGFUSE_BASE_URL": "https://base.example/", "LANGFUSE_HOST": "https://host.example"}, "https://base.example"),
    ({"LANGFUSE_BASE_URL": "", "LANGFUSE_HOST": "https://host.example/"}, "https://host.example"),
    ({"LANGFUSE_BASE_URL": "  ", "LANGFUSE_HOST": "https://host.example"}, "https://host.example"),
])
def test_base_url_prefers_base_url_and_falls_back_to_host(monkeypatch, env, expected):
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    assert tracing._base_url() == expected


def test_client_is_built_from_the_resolved_settings(monkeypatch):
    import langfuse

    built = []
    monkeypatch.setattr(langfuse, "Langfuse", lambda **kwargs: built.append(kwargs) or "client")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", " pk-test ")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-test")
    monkeypatch.setenv("LANGFUSE_HOST", "https://host.example")
    assert tracing._client() == "client"
    assert built == [{"public_key": "pk-test", "secret_key": "sk-test", "base_url": "https://host.example",
                      "mask": tracing.mask_emails}]


# ------------------------------------------------------------------------ the real SDK

class State(TypedDict):
    x: int


def tiny_graph():
    builder = StateGraph(State)
    builder.add_node("bump", lambda state: {"x": state["x"] + 1})
    builder.add_edge(START, "bump")
    builder.add_edge("bump", END)
    return builder.compile()


@pytest.fixture
def sdk(monkeypatch, fake_keys):
    """The real Langfuse SDK on a private tracer provider that exports to memory: no network, no globals."""
    import langchain  # noqa: F401  langfuse.langchain imports the full package, so it must be installed
    from langfuse import Langfuse
    from langfuse._client.resource_manager import LangfuseResourceManager
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    monkeypatch.setattr(LangfuseResourceManager, "_instances", {})  # one client per test
    exporter, provider = InMemorySpanExporter(), TracerProvider()
    client = Langfuse(public_key="pk-test", secret_key="sk-test", base_url="http://127.0.0.1:9",
                      tracer_provider=provider, span_exporter=exporter)
    yield SimpleNamespace(client=client, exporter=exporter)
    client.shutdown()
    provider.shutdown()


def spans_of(sdk):
    sdk.client.flush()
    return sdk.exporter.get_finished_spans()


def test_trace_config_carries_a_real_handler_and_the_keys_the_sdk_reads(sdk):
    from langfuse.langchain import CallbackHandler

    config = tracing.trace_config(dispute_id="PP-D-1", model="claude-sonnet-5-5", provider="claude", tags=["eval"])
    assert set(config) == {"callbacks", "metadata"}
    assert len(config["callbacks"]) == 1 and isinstance(config["callbacks"][0], CallbackHandler)
    assert config["metadata"] == {
        "langfuse_session_id": "PP-D-1",
        "langfuse_tags": ["dispute:PP-D-1", "model:claude-sonnet-5-5", "provider:claude", "eval"],
        "dispute_id": "PP-D-1",
        "model": "claude-sonnet-5-5",
        "provider": "claude",
    }


def traced(dispute_id, **extra):
    return tracing.trace_config(dispute_id=dispute_id, model="m", provider="p", **extra)


def test_trace_config_builds_the_sdk_client_on_first_use(monkeypatch, fake_keys):
    from langfuse._client.resource_manager import LangfuseResourceManager

    monkeypatch.setenv("LANGFUSE_TRACING_ENABLED", "false")  # a real client, but no OpenTelemetry provider or exporter
    monkeypatch.setattr(LangfuseResourceManager, "_instances", {})
    config = traced("PP-D-1")
    try:
        assert len(config["callbacks"]) == 1
        assert list(LangfuseResourceManager._instances) == ["pk-test"]
    finally:
        for instance in LangfuseResourceManager._instances.values():
            instance.shutdown()


def test_trace_config_makes_a_new_handler_each_time_and_dedupes_tags(sdk):
    first, second = traced("d", tags="dispute:d"), traced("d", tags=None)
    assert first["callbacks"][0] is not second["callbacks"][0]
    assert first["metadata"]["langfuse_tags"] == second["metadata"]["langfuse_tags"] == [
        "dispute:d", "model:m", "provider:p"]


def test_graph_runs_are_tagged_and_grouped_into_the_dispute_session(sdk):
    graph = tiny_graph()
    for dispute in ("PP-D-7", "PP-D-7", "PP-D-8"):
        assert graph.invoke({"x": 1}, config=traced(dispute)) == {"x": 2}

    spans = spans_of(sdk)
    assert {s.name for s in spans} == {"LangGraph", "bump"}
    for span in spans:
        dispute = span.attributes["langfuse.trace.metadata.dispute_id"]
        assert span.attributes["session.id"] == dispute
        assert set(span.attributes["langfuse.trace.tags"]) == {f"dispute:{dispute}", "model:m", "provider:p"}
        assert span.attributes["langfuse.trace.metadata.model"] == "m"
        assert span.attributes["langfuse.trace.metadata.provider"] == "p"
    sessions = {s.context.trace_id: s.attributes["session.id"] for s in spans}
    assert sorted(sessions.values()) == ["PP-D-7", "PP-D-7", "PP-D-8"]  # three traces, two sessions


def test_a_resumed_run_lands_in_the_same_session(sdk):
    """The approval gate: the first run pauses at interrupt(), the resume is a new invoke with a new handler."""
    from langgraph.checkpoint.memory import InMemorySaver
    from langgraph.types import Command, interrupt

    builder = StateGraph(State)
    builder.add_node("ask", lambda state: {"x": state["x"] + int(interrupt("approve?"))})
    builder.add_edge(START, "ask")
    builder.add_edge("ask", END)
    graph = builder.compile(checkpointer=InMemorySaver())

    def config():
        return {"configurable": {"thread_id": "PP-D-9"}, **traced("PP-D-9")}

    graph.invoke({"x": 1}, config())
    assert graph.invoke(Command(resume=2), config()) == {"x": 3}

    spans = spans_of(sdk)
    assert [s.name for s in spans if s.parent is None] == ["LangGraph", "LangGraph"]  # both runs were recorded
    assert {s.attributes["session.id"] for s in spans} == {"PP-D-9"}


@pytest.mark.parametrize("failure", ["handler import", "client"])
def test_trace_config_survives_a_broken_sdk_and_says_so_once(monkeypatch, fake, caplog, failure):
    if failure == "handler import":
        monkeypatch.setitem(sys.modules, "langfuse.langchain", None)  # makes `import langfuse.langchain` fail
    else:
        monkeypatch.setattr(tracing, "_client", raising(ValueError("bad LANGFUSE setting")))
    monkeypatch.setattr(tracing, "_warned", set())
    with caplog.at_level("WARNING", logger="rebuttal.tracing"):
        assert traced("d") == {}
        assert traced("d") == {}
    assert len(caplog.records) == 1  # logged once, not on every dispute
    assert "Langfuse tracing is off" in caplog.text


# --------------------------------------------------------------------------------- flush

def test_flush_flushes_the_client(fake):
    tracing.flush()
    assert fake.flushed == 1


def test_flush_never_raises(monkeypatch, fake_keys, caplog):
    monkeypatch.setattr(tracing, "_client", raising(OSError("network is down")))
    tracing.flush()
    assert "flush failed" in caplog.text


# ---------------------------------------------------------------------------- the dataset

def test_upload_dataset_creates_the_dataset_once_and_upserts_every_case(fake):
    assert len(CASES) == 20
    assert tracing.upload_dataset(CASES) == "rebuttal-disputes" == tracing.DATASET_NAME
    assert fake.calls.count("create_dataset") == 1
    assert fake.calls.count("create_dataset_item") == 20
    assert set(fake.items) == {case["id"] for case in CASES}
    for case in CASES:
        assert fake.items[case["id"]] == {
            "dataset_name": "rebuttal-disputes",
            "id": case["id"],
            "input": {key: value for key, value in case.items() if key not in LABEL_KEYS},
            "expected_output": {"resolution": case["expected"]},
            "metadata": {"id": case["id"], "title": case["title"], "hard": case["hard"], "why": case["why"]},
        }


def test_upload_dataset_keeps_the_labels_out_of_the_input(fake):
    tracing.upload_dataset(CASES)
    for item in fake.items.values():
        assert not set(LABEL_KEYS) & set(item["input"])
        assert item["input"]["id"] == item["id"]


def test_upload_dataset_is_idempotent_and_takes_a_name(fake):
    tracing.upload_dataset(CASES)
    assert tracing.upload_dataset(CASES, name="other") == "other"
    assert len(fake.items) == 20  # same ids again: an upsert, not 40 items
    assert {item["dataset_name"] for item in fake.items.values()} == {"other"}


def test_upload_dataset_rejects_duplicate_case_ids(fake):
    with pytest.raises(ValueError, match="duplicate case ids"):
        tracing.upload_dataset([CASES[0], CASES[0]])
    assert fake.calls == []


def test_dataset_calls_need_langfuse_to_be_configured(monkeypatch):
    monkeypatch.setattr(tracing, "_client", lambda: pytest.fail("built a client without keys"))
    with pytest.raises(RuntimeError, match="not configured"):
        tracing.upload_dataset(CASES)
    with pytest.raises(RuntimeError, match="not configured"):
        tracing.run_experiment(name="x", task=lambda case: {})


# --------------------------------------------------------------------------- evaluators

@pytest.mark.parametrize("output, expected, value", [
    ({"resolution": "ACCEPT_CLAIM"}, {"resolution": "ACCEPT_CLAIM"}, 1.0),
    ({"resolution": "ACCEPT_CLAIM", "confidence": 0.7, "source": "rules"}, {"resolution": "ACCEPT_CLAIM"}, 1.0),
    ({"resolution": "SUBMIT_EVIDENCE"}, {"resolution": "ACCEPT_CLAIM"}, 0.0),
    ({}, {"resolution": "ACCEPT_CLAIM"}, 0.0),
    ({"resolution": None}, {"resolution": None}, 0.0),  # no decision is never right
    ({"resolution": None, "error": "boom"}, {"resolution": "ACCEPT_CLAIM"}, 0.0),
    ({"resolution": "ACCEPT_CLAIM", "error": None}, {"resolution": "ACCEPT_CLAIM"}, 1.0),
    (SimpleNamespace(resolution="ACCEPT_CLAIM"), {"resolution": "ACCEPT_CLAIM"}, 1.0),
])
def test_correct_scores_one_when_the_resolution_matches_the_label(output, expected, value):
    evaluation = tracing.correct(input={"id": "c"}, output=output, expected_output=expected, metadata=None)
    assert (evaluation.name, evaluation.value) == ("correct", value)
    assert evaluation.comment


def test_correct_explains_a_miss_and_a_crash():
    miss = tracing.correct(output={"resolution": "B"}, expected_output={"resolution": "A"})
    assert miss.comment == "expected A, got B"
    crash = tracing.correct(output={"resolution": None, "error": "KeyError: 'x'"}, expected_output={"resolution": "A"})
    assert "task failed: KeyError: 'x'" in crash.comment


def results_of(*values):
    from langfuse import Evaluation

    return [SimpleNamespace(evaluations=[Evaluation(name="other", value=5), Evaluation(name="correct", value=v)])
            for v in values]


def test_accuracy_is_the_mean_of_the_correct_scores():
    evaluation = tracing.accuracy(item_results=results_of(1.0, 0.0, 1.0, 1.0))
    assert (evaluation.name, evaluation.value, evaluation.comment) == ("accuracy", 0.75, "3/4 correct")
    assert tracing.accuracy(item_results=results_of(1.0, 1.0)).value == 1.0
    assert tracing.accuracy(item_results=results_of(0.0)).value == 0.0


def test_accuracy_of_an_empty_run_is_zero():
    assert tracing.accuracy(item_results=[]).value == 0.0
    assert tracing.accuracy(item_results=[SimpleNamespace(evaluations=[])]).value == 0.0


# --------------------------------------------------------------------- experiment wiring

def run_item(task, item):
    return asyncio.run(task(item=item))  # how the SDK calls it: keyword-only `item`


def test_run_experiment_hands_the_sdk_our_task_and_evaluators(fake):
    result = tracing.run_experiment(name="rules baseline", task=lambda case: {"resolution": "X"},
                                    description="d", metadata={"model": "rules"})
    kwargs = fake.dataset.kwargs
    assert result == "result" and fake.requested == ["rebuttal-disputes"]
    assert (kwargs["name"], kwargs["description"], kwargs["metadata"]) == ("rules baseline", "d", {"model": "rules"})
    assert kwargs["evaluators"] == [tracing.correct] and kwargs["run_evaluators"] == [tracing.accuracy]
    assert kwargs["max_concurrency"] == 1

    tracing.run_experiment(name="n", task=lambda case: {}, dataset_name="other", max_concurrency=4)
    assert fake.requested[-1] == "other" and fake.dataset.kwargs["max_concurrency"] == 4


def test_the_task_adapter_serves_dataset_items_and_plain_dicts_sync_or_async(fake):
    seen = []

    def sync_task(case):
        seen.append(case)
        return {"resolution": "A"}

    async def async_task(case):
        return {"resolution": case["id"]}

    tracing.run_experiment(name="n", task=sync_task)
    adapted = fake.dataset.kwargs["task"]
    assert run_item(adapted, SimpleNamespace(input={"id": "c1"})) == {"resolution": "A"}  # a DatasetItem
    assert run_item(adapted, {"input": {"id": "c2"}}) == {"resolution": "A"}  # a local dict item
    assert seen == [{"id": "c1"}, {"id": "c2"}]

    tracing.run_experiment(name="n", task=async_task)
    assert run_item(fake.dataset.kwargs["task"], SimpleNamespace(input={"id": "c3"})) == {"resolution": "c3"}


def test_the_task_gets_a_copy_of_the_case(fake):
    def task(case):
        case["item"]["name"] = "changed"
        return {"resolution": "A"}

    tracing.run_experiment(name="n", task=task)
    item = SimpleNamespace(input={"id": "c1", "item": {"name": "Linen shirt"}})
    run_item(fake.dataset.kwargs["task"], item)
    assert item.input["item"]["name"] == "Linen shirt"  # the SDK records this input on the trace afterwards


def test_a_task_that_raises_is_scored_wrong_instead_of_dropped(fake, caplog):
    def task(case):
        raise KeyError("buyer_message")

    tracing.run_experiment(name="n", task=task)
    output = run_item(fake.dataset.kwargs["task"], SimpleNamespace(input={"id": "c1"}))
    assert output == {"resolution": None, "error": "KeyError: 'buyer_message'"}
    assert tracing.correct(output=output, expected_output={"resolution": "A"}).value == 0.0
    assert "eval task failed on c1" in caplog.text


# ------------------------------------------------------- a whole experiment on the real SDK

def test_experiment_nests_graph_runs_under_each_item_and_scores_every_case(monkeypatch, sdk):
    from langfuse.api import DatasetItem

    stamp = "2026-10-06T00:00:00Z"
    dataset_items = [
        DatasetItem(id=case_id, status="ACTIVE", input={"id": case_id, "buyer_message": "hi"},
                    expected_output={"resolution": expected}, metadata={"id": case_id, "hard": False},
                    dataset_id="ds-1", dataset_name="rebuttal-disputes", created_at=stamp, updated_at=stamp,
                    media_references=[])
        for case_id, expected in (("case_right", "ACCEPT_CLAIM"), ("case_wrong", "ACCEPT_CLAIM"))
    ]

    class Dataset:
        def run_experiment(self, **kwargs):
            return sdk.client.run_experiment(data=dataset_items, **kwargs)

    api = SimpleNamespace(
        dataset_run_items=SimpleNamespace(create=lambda **kwargs: SimpleNamespace(dataset_run_id="run-1")),
        projects=SimpleNamespace(get=lambda: SimpleNamespace(data=[SimpleNamespace(id="project-1")])),
    )
    scores = []
    monkeypatch.setattr(sdk.client, "api", api)
    monkeypatch.setattr(sdk.client, "get_dataset", lambda name, **kwargs: Dataset())
    monkeypatch.setattr(sdk.client, "create_score", lambda **kwargs: scores.append(kwargs))
    monkeypatch.setattr(tracing, "_client", lambda: sdk.client)
    graph = tiny_graph()

    def task(case):
        graph.invoke({"x": 1}, config=tracing.trace_config(dispute_id=case["id"], model="m", provider="p"))
        return {"resolution": "ACCEPT_CLAIM" if case["id"] == "case_right" else "SUBMIT_EVIDENCE", "confidence": 0.9}

    result = tracing.run_experiment(name="e2e", task=task, metadata={"model": "m"})

    assert [r.output["resolution"] for r in result.item_results] == ["ACCEPT_CLAIM", "SUBMIT_EVIDENCE"]
    per_case = {s["trace_id"]: s for s in scores if s["name"] == "correct"}
    assert sorted((s["value"], s["comment"]) for s in per_case.values()) == [
        (0.0, "expected ACCEPT_CLAIM, got SUBMIT_EVIDENCE"), (1.0, "matches the label (ACCEPT_CLAIM)")]
    (run_score,) = [s for s in scores if s["name"] == "accuracy"]
    assert (run_score["value"], run_score["comment"], run_score["dataset_run_id"]) == (0.5, "1/2 correct", "run-1")
    assert [e.value for e in result.run_evaluations] == [0.5]

    spans = spans_of(sdk)
    for item_result in result.item_results:
        in_trace = [s for s in spans if format(s.context.trace_id, "032x") == item_result.trace_id]
        by_name = {s.name: s for s in in_trace}
        assert {"experiment-item-run", "experiment-item-task", "LangGraph", "bump", "correct"} <= set(by_name)
        # the graph run hangs under the task span: that is how it ends up inside the item's trace
        assert by_name["LangGraph"].parent.span_id == by_name["experiment-item-task"].context.span_id
        assert by_name["bump"].parent.span_id == by_name["LangGraph"].context.span_id
        assert by_name["LangGraph"].attributes["session.id"] == item_result.item.id
        assert by_name["LangGraph"].attributes["langfuse.experiment.name"].startswith("e2e")


def test_emails_are_masked_in_anything_sent_to_langfuse():
    data = {"buyer_email": "priya.k+shop@example.co.uk", "messages": ["write to priya@example.com please", 3],
            "nested": ({"payer": "a@b.io"},), "amount": 48.0, "none": None}
    masked = tracing.mask_emails(data=data)
    assert masked == {"buyer_email": "[email]", "messages": ["write to [email] please", 3],
                      "nested": [{"payer": "[email]"}], "amount": 48.0, "none": None}
    assert "priya" not in json.dumps(masked) and data["buyer_email"].startswith("priya")  # the input is untouched
