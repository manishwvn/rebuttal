"""`gather` reads PayPal only through the read-only toolkit: the client is never called for a read directly."""

import ast
from pathlib import Path

import pytest

from rebuttal.agent import facts
from rebuttal.agent.facts import gather
from rebuttal.agent.toolkit import READ_TOOLS, ReadOnlyToolkit
from rebuttal.paypal.client import PayPalClient
from rebuttal.paypal.mock import MockPayPal
from rebuttal.runtime import Runtime
from rebuttal.scenarios import DEMO_NOW, fixture_order, iso, live_invoice_id
from rebuttal.store import MerchantStore

FACTS = Path(facts.__file__)


class SpyToolkit(ReadOnlyToolkit):
    used: list[str] = []

    def call(self, method, params):
        self.used.append(method)
        return super().call(method, params)


@pytest.fixture
def spy(monkeypatch):
    SpyToolkit.used = []
    monkeypatch.setattr(facts, "ReadOnlyToolkit", SpyToolkit)
    return SpyToolkit


def live_shape_client():
    """A sandbox that looks like the live one: the merchant record has no PayPal order id, so gather asks the
    capture for it, then reads the order's trackers and the day's transactions."""
    mock = MockPayPal()
    client = PayPalClient("https://api-m.sandbox.paypal.com", "id", "secret", transport=mock.transport())
    invoice = live_invoice_id("agent_wrong_size", 1791368378)
    mock.add_order("8MD03238YM8593329", "7UM591057M790460L")
    mock.add_tracker("8MD03238YM8593329", "7UM591057M790460L", "9400111899223344556677", "DELIVERED")
    mock.add_dispute({
        "dispute_id": "PP-R-LIVE-1", "create_time": iso(DEMO_NOW), "update_time": iso(DEMO_NOW),
        "reason": "MERCHANDISE_OR_SERVICE_NOT_AS_DESCRIBED", "status": "WAITING_FOR_SELLER_RESPONSE",
        "dispute_life_cycle_stage": "INQUIRY", "dispute_amount": {"currency_code": "USD", "value": "48.00"},
        "disputed_transactions": [{"seller_transaction_id": "7UM591057M790460L", "invoice_number": invoice,
                                   "custom": invoice, "buyer": {"name": "Sandbox Buyer"}}],
        "messages": [{"posted_by": "BUYER", "time_posted": iso(DEMO_NOW), "content": "I asked for a medium."}],
    })
    return mock, client, MerchantStore(fixtures=fixture_order)


def _arguments(call: ast.Call) -> list[ast.expr]:
    return [*call.args, *(k.value for k in call.keywords)]


def gather_body() -> ast.FunctionDef:
    return next(n for n in ast.parse(FACTS.read_text()).body if isinstance(n, ast.FunctionDef) and n.name == "gather")


def test_gather_calls_nothing_on_the_client_but_read_only():
    """Every PayPal read goes through the toolkit: the only attribute `gather` may use on `client` is read_only
    (the toolkit constructor takes it), and it hands the client to nothing but `ReadOnlyToolkit`."""
    body = gather_body()
    attributes = {n.attr for n in ast.walk(body)
                  if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name) and n.value.id == "client"}
    assert attributes <= {"read_only"}
    handed_over = [n for n in ast.walk(body) if isinstance(n, ast.Call)
                   and any(isinstance(a, ast.Name) and a.id == "client" for a in _arguments(n))]
    assert [c.func.id for c in handed_over] == ["ReadOnlyToolkit"]


def test_gather_on_the_hero_case_uses_the_toolkit_and_the_audit_lines_name_the_tool(spy):
    rt = Runtime(seed_cases=["agent_wrong_size"], force_rules=True)
    case = gather("PP-D-2000", rt.client, rt.store, DEMO_NOW)
    assert spy.used == ["get_dispute", "get_order_trackers", "list_transactions"]
    assert case.tool_calls == [
        "get_dispute: GET /v1/customer/disputes/PP-D-2000",
        "merchant orders: lookup invoice " + case.order.invoice_id,
        "get_order_trackers: GET /v2/checkout/orders/" + case.order.order_id + " (shipping.trackers)",
        "list_transactions: GET /v1/reporting/transactions (purchase day)",
    ]
    assert case.facts["tracking_uploaded_to_paypal"] is True and case.facts["transaction_search_available"] is True
    assert rt.mock.write_calls() == []


def test_gather_on_a_live_shape_order_uses_exactly_the_four_read_tools(spy):
    mock, client, store = live_shape_client()
    case = gather("PP-R-LIVE-1", client.read_only(), store, DEMO_NOW)
    assert spy.used == ["get_dispute", "get_capture_order_id", "get_order_trackers", "list_transactions"]
    assert set(spy.used) == {tool.name for tool in READ_TOOLS}
    assert case.order.order_id == "8MD03238YM8593329"
    assert case.facts["tracking_uploaded_to_paypal"] is True
    assert any(c.startswith("get_capture_order_id: GET /v2/payments/captures/7UM591057M790460L")
               for c in case.tool_calls)
    assert mock.write_calls() == []


def test_gather_given_the_full_client_still_cannot_write(spy):
    """The graph passes a read-only client, but a caller with the full one gets the same GET-only behavior."""
    mock, client, store = live_shape_client()
    gather("PP-R-LIVE-1", client, store, DEMO_NOW)
    assert mock.write_calls() == []


@pytest.mark.parametrize("bad_capture", ["", "bad id!"])
def test_gather_skips_tracker_lookup_when_the_capture_id_is_invalid(spy, bad_capture):
    rt = Runtime(seed_cases=["agent_wrong_size"], force_rules=True)
    rt.mock.disputes["PP-D-2000"]["disputed_transactions"][0]["seller_transaction_id"] = bad_capture
    case = gather("PP-D-2000", rt.client, rt.store, DEMO_NOW)
    assert any("tracking not checked" in c for c in case.tool_calls)
    assert not any(c.startswith("get_order_trackers: GET") for c in case.tool_calls)
    assert rt.mock.write_calls() == []
