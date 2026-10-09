"""The PayPal toolkit adapter is read-only: no PayPal write is reachable through it, even from the full client."""

import ast
import json
from datetime import timedelta
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from rebuttal.agent.toolkit import READ_TOOLS, ReadOnlyToolkit, ToolNotAvailable
from rebuttal.paypal.client import PayPalClient, PayPalError, WriteNotPermitted, permit_writes
from rebuttal.runtime import Runtime
from rebuttal.scenarios import DEMO_NOW, iso

TOOLKIT = Path(__file__).resolve().parents[1] / "rebuttal" / "agent" / "toolkit.py"
# Names a write would be called by: PayPal toolkit tool names and this client's write methods.
WRITE_NAMES = {
    "accept_dispute_claim", "create_order", "pay_order", "get_order_details", "create_shipment_tracking",
    "update_shipment_tracking", "send_message", "make_offer", "provide_evidence", "accept_claim", "escalate",
    "require_evidence", "adjudicate", "capture_order", "add_order_tracking", "create_invoice", "send_invoice",
    "record_refund_for_invoice",
}
# Client methods the module may call: the four reads, and read_only(), which the constructor uses to take the
# GET-only clone. None of them sends a PayPal write.
CLIENT_CALLS = {"get_dispute", "search_transactions", "get_order_trackers", "get_capture_order_id", "read_only"}
# Writes, the write permit, and the private handles that would reach a write.
FORBIDDEN = {
    "send_message", "make_offer", "provide_evidence", "accept_claim", "escalate", "require_evidence", "adjudicate",
    "create_order", "capture_order", "add_order_tracking", "permit_writes", "_request", "_http", "_init",
}


@pytest.fixture
def rt():
    runtime = Runtime(seed_cases=["agent_wrong_size"], force_rules=True)
    yield runtime
    # However a test ends, no PayPal write may have reached the mock.
    assert runtime.mock.write_calls() == []


def test_the_toolkit_offers_exactly_the_four_read_tools(rt):
    assert ReadOnlyToolkit(rt.client).tool_names == [
        "get_dispute", "list_transactions", "get_order_trackers", "get_capture_order_id"]
    assert all(tool.description.startswith("Read only.") for tool in READ_TOOLS)


@pytest.mark.parametrize("name", sorted(WRITE_NAMES))
def test_no_write_tool_can_be_called_or_run(rt, name):
    toolkit = ReadOnlyToolkit(rt.client)
    with pytest.raises(ToolNotAvailable, match=f"{name}.*only read tools exist"):
        toolkit.call(name, {})
    with pytest.raises(ToolNotAvailable, match=f"{name}.*only read tools exist"):
        toolkit.run(name, {})


def test_the_read_tools_are_disjoint_from_the_write_names():
    assert {tool.method for tool in READ_TOOLS}.isdisjoint(WRITE_NAMES)


def test_the_module_reaches_the_client_only_through_read_methods():
    tree = ast.parse(TOOLKIT.read_text())
    client_calls = [
        node.attr for node in ast.walk(tree)
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "client"
    ]
    assert len(client_calls) >= 4, "the scan found too few client calls, so the test is broken"
    assert set(client_calls) <= CLIENT_CALLS
    names = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
    names |= {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    assert names.isdisjoint(FORBIDDEN)


def test_handed_the_full_client_the_toolkit_still_cannot_write(rt):
    toolkit = ReadOnlyToolkit(rt.client)
    with permit_writes():
        with pytest.raises(WriteNotPermitted):
            toolkit._client.send_message("PP-D-2000", "x")


def test_get_dispute_returns_the_seeded_dispute(rt):
    dispute = ReadOnlyToolkit(rt.client).call("get_dispute", {"dispute_id": "PP-D-2000"})
    assert dispute["dispute_id"] == "PP-D-2000"


def test_run_returns_the_json_text_of_the_call(rt):
    toolkit = ReadOnlyToolkit(rt.client)
    params = {"dispute_id": "PP-D-2000"}
    text = toolkit.run("get_dispute", params)
    assert isinstance(text, str)
    assert json.loads(text) == toolkit.call("get_dispute", params)


def test_list_transactions_finds_the_seeded_payment_in_a_thirty_day_window(rt):
    toolkit = ReadOnlyToolkit(rt.client)
    dispute = toolkit.call("get_dispute", {"dispute_id": "PP-D-2000"})
    capture_id = dispute["disputed_transactions"][0]["seller_transaction_id"]
    # PayPal's Transaction Search allows at most a 31-day range; the mock does not enforce that yet.
    result = toolkit.call("list_transactions", {
        "start_date": iso(DEMO_NOW - timedelta(days=30)),
        "end_date": iso(DEMO_NOW),
    })
    assert isinstance(result["transaction_details"], list)
    assert capture_id in [t["transaction_info"]["transaction_id"] for t in result["transaction_details"]]


def test_list_transactions_with_a_transaction_id_returns_only_that_transaction(rt):
    rt.mock.add_transaction({"transaction_info": {
        "transaction_id": "OTHERTXN000001", "transaction_initiation_date": iso(DEMO_NOW - timedelta(days=8))}})
    toolkit = ReadOnlyToolkit(rt.client)
    dispute = toolkit.call("get_dispute", {"dispute_id": "PP-D-2000"})
    capture_id = dispute["disputed_transactions"][0]["seller_transaction_id"]
    window = {"start_date": iso(DEMO_NOW - timedelta(days=30)), "end_date": iso(DEMO_NOW)}
    everything = toolkit.call("list_transactions", window)
    one = toolkit.call("list_transactions", {**window, "transaction_id": capture_id})
    listed = {t["transaction_info"]["transaction_id"] for t in everything["transaction_details"]}
    assert {"OTHERTXN000001", capture_id} <= listed
    assert [t["transaction_info"]["transaction_id"] for t in one["transaction_details"]] == [capture_id]


def test_get_order_trackers_returns_only_the_trackers_of_the_requested_capture(rt):
    rt.mock.add_tracker("3TKORDER000001A", "4TKCAPTURE00001B", "9400111899223344556677", "SHIPPED")
    rt.mock.add_tracker("3TKORDER000001A", "4TKOTHER00002C", "9400999999999999999999", "SHIPPED")
    toolkit = ReadOnlyToolkit(rt.client)
    one = toolkit.call("get_order_trackers", {"order_id": "3TKORDER000001A", "capture_id": "4TKCAPTURE00001B"})
    assert [t["tracking_number"] for t in one["trackers"]] == ["9400111899223344556677"]
    every = toolkit.call("get_order_trackers", {"order_id": "3TKORDER000001A"})
    numbers = sorted(t["tracking_number"] for t in every["trackers"])
    assert numbers == ["9400111899223344556677", "9400999999999999999999"]


def test_get_capture_order_id_returns_the_order_the_capture_belongs_to(rt):
    rt.mock.add_order("3TKORDER000001A", "4TKCAPTURE00001B")
    order = ReadOnlyToolkit(rt.client).call("get_capture_order_id", {"capture_id": "4TKCAPTURE00001B"})
    assert order == {"order_id": "3TKORDER000001A"}


VALID_WINDOW = {"start_date": "2026-10-05T00:00:00.000Z", "end_date": "2026-10-06T00:00:00.000Z"}


@pytest.mark.parametrize("method,params", [
    ("get_dispute", {"dispute_id": "../../x"}),
    ("get_dispute", {"dispute_id": ""}),
    ("get_dispute", {"dispute_id": "PP-D-1", "extra": "x"}),
    ("get_dispute", {}),
    ("get_order_trackers", {"order_id": "../x"}),
    ("get_order_trackers", {"order_id": "O1", "capture_id": "../x"}),
    ("get_order_trackers", {"order_id": "O1", "extra": "x"}),
    ("list_transactions", {"start_date": "", "end_date": "2026-10-06T00:00:00Z"}),
    ("list_transactions", {"start_date": "2026-10-05T00:00:00.000Z", "end_date": ""}),
    ("list_transactions", {**VALID_WINDOW, "transaction_id": "../x"}),
    ("list_transactions", {**VALID_WINDOW, "extra": "x"}),
    ("get_capture_order_id", {"capture_id": "../x"}),
    ("get_capture_order_id", {"capture_id": "C1", "extra": "x"}),
    ("get_capture_order_id", {}),
])
def test_bad_arguments_fail_validation_before_any_request(method, params):
    sent = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return httpx.Response(500)

    client = PayPalClient("https://api-m.sandbox.paypal.com", "id", "secret", transport=httpx.MockTransport(handler))
    with pytest.raises(ValidationError):
        ReadOnlyToolkit(client).call(method, params)
    assert sent == []


def test_paypal_errors_reach_the_caller_unchanged():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/oauth2/token":
            return httpx.Response(200, json={"access_token": "t", "expires_in": 3600})
        return httpx.Response(404, json={"name": "RESOURCE_NOT_FOUND"})

    client = PayPalClient("https://api-m.sandbox.paypal.com", "id", "secret", transport=httpx.MockTransport(handler))
    with pytest.raises(PayPalError) as error:
        ReadOnlyToolkit(client).call("get_dispute", {"dispute_id": "X1"})
    assert error.value.status == 404
