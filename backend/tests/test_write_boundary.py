"""PayPal writes happen in one place. These checks fail if a change opens another path."""

import ast
import json
import uuid
from email.parser import BytesParser
from pathlib import Path

import pytest

from rebuttal.approval import ApprovalError, make_execute_node, route_after_approval
from rebuttal.audit import AuditLog
from rebuttal.paypal.client import PayPalClient, WriteNotPermitted, permit_writes
from rebuttal.runtime import Runtime

PACKAGE = Path(__file__).resolve().parents[1] / "rebuttal"
BACKEND = PACKAGE.parent
# Every PayPalClient method that changes something at PayPal, and the private ways to reach one.
WRITE_METHODS = {"send_message", "make_offer", "provide_evidence", "accept_claim", "escalate", "appeal",
                 "require_evidence", "adjudicate", "create_order", "capture_order", "add_order_tracking", "create_dispute"}
PRIVATE = {"_request", "_http", "_init"}
ALLOWED = {"approval.py"}  # the gate; paypal/client.py defines the methods, paypal/mock.py is the fake server
# Manual tools that talk to the PayPal sandbox on purpose. They are not part of the agent and run only when a person starts them.
MANUAL_SCRIPTS = {"spike_sandbox.py", "spike_retry.py", "spike_fresh.py", "make_test_order.py", "make_sandbox_dispute.py", "demo.py"}


LOOKUPS = {"getattr", "attrgetter", "methodcaller", "__getattribute__"}


def references_in(path: Path) -> list[tuple[int, str]]:
    """Every mention of a PayPal write method, a private client handle, or the write permit: calls, aliases,
    partials and dispatch tables all show up as an attribute or a name, and getattr("name") as a string argument.
    (Names built at runtime cannot be seen here; the client's write permit refuses those when they run.)
    Strings elsewhere are fine: the planner uses "make_offer" as an action label, not a PayPal call."""
    found = []
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Attribute) and (node.attr in WRITE_METHODS or node.attr in PRIVATE):
            found.append((node.lineno, node.attr))
        elif isinstance(node, ast.Name) and node.id in WRITE_METHODS | {"permit_writes"}:
            found.append((node.lineno, node.id))
        elif isinstance(node, ast.alias) and node.name == "permit_writes":
            found.append((node.lineno, "import permit_writes"))
        elif isinstance(node, ast.Call):
            fn = node.func.id if isinstance(node.func, ast.Name) else getattr(node.func, "attr", "")
            if fn in LOOKUPS:
                for arg in node.args:
                    if isinstance(arg, ast.Constant) and arg.value in WRITE_METHODS | PRIVATE:
                        found.append((node.lineno, f"{fn}({arg.value!r})"))
    return found


def python_files(root: Path):
    return [p for p in root.rglob("*.py") if ".venv" not in p.parts and "__pycache__" not in p.parts]


def test_only_the_approval_module_can_reach_a_paypal_write():
    offenders = {}
    for path in python_files(PACKAGE):
        if path.name in ALLOWED or path.parent.name == "paypal":
            continue
        if refs := references_in(path):
            offenders[str(path.relative_to(PACKAGE))] = refs
    assert offenders == {}, f"PayPal writes (or the permit) outside rebuttal/approval.py: {offenders}"
    assert references_in(PACKAGE / "approval.py"), "the scan found nothing in approval.py: the test is broken"


def test_scripts_and_evals_do_not_write_to_paypal_except_the_named_manual_tools():
    offenders = {}
    for folder in ("scripts", "evals"):
        for path in python_files(BACKEND / folder):
            if path.name in MANUAL_SCRIPTS:
                continue
            if refs := references_in(path):
                offenders[f"{folder}/{path.name}"] = refs
    assert offenders == {}, f"scripts or evals reaching a PayPal write: {offenders}"


def test_the_manual_sandbox_tools_use_the_write_permit_explicitly():
    for name in ("spike_sandbox.py", "spike_retry.py", "spike_fresh.py", "make_test_order.py",
                 "make_sandbox_dispute.py"):
        assert "with permit_writes()" in (BACKEND / "scripts" / name).read_text(), name


def test_the_demo_only_ever_runs_on_the_mock():
    source = (BACKEND / "scripts" / "demo.py").read_text()
    assert "replace(load_settings(), mock=True, database_url=None" in source and "assert rt.mock is not None" in source


def test_the_write_method_list_covers_every_mutating_client_method():
    tree = ast.parse((PACKAGE / "paypal" / "client.py").read_text())
    client = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "PayPalClient")
    methods = {n.name for n in client.body if isinstance(n, ast.FunctionDef) and not n.name.startswith("_")}
    posting = set()
    for fn in (n for n in client.body if isinstance(n, ast.FunctionDef) and n.name in methods):
        for call in ast.walk(fn):  # a public method that issues a non-GET request is a write
            if isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute) and call.func.attr == "_request" \
                    and call.args and isinstance(call.args[0], ast.Constant) and call.args[0].value != "GET":
                posting.add(fn.name)
    posting -= {"verify_webhook_signature"}  # a POST that only asks PayPal whether an event is genuine
    assert posting == WRITE_METHODS, f"WRITE_METHODS is out of date: {posting ^ WRITE_METHODS}"


def test_execute_refuses_to_run_without_an_approval():
    rt = Runtime(seed_cases=["agent_wrong_size"], force_rules=True)
    p = rt.analyze("PP-D-2000")
    execute = make_execute_node(rt.client, AuditLog())
    state = rt.agent.snapshot("PP-D-2000").values
    for approval in (None, {}, {"status": "rejected"}, {"status": "pending"}):
        with pytest.raises(ApprovalError, match="no approval"):
            execute({**state, "approval": approval})
    assert rt.mock.write_calls() == [] and p.status == "PENDING"


@pytest.mark.parametrize("approval,route", [
    (None, "record"), ({"status": "rejected"}, "record"), ({"status": "approved"}, "execute"),
    ({"status": "edited"}, "execute"), ({"status": "anything else"}, "record")])
def test_only_approve_and_edit_route_to_execute(approval, route):
    assert route_after_approval({"approval": approval}) == route


def test_the_paypal_client_gives_every_post_an_idempotency_key():
    import httpx

    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/oauth2/token":
            return httpx.Response(200, json={"access_token": "t", "expires_in": 3600})
        seen.append(request.headers.get("paypal-request-id"))
        return httpx.Response(200, json={})

    client = PayPalClient("https://api-m.sandbox.paypal.com", "id", "secret", transport=httpx.MockTransport(handler))
    with permit_writes():
        client.send_message("D1", "hi")
        client.send_message("D1", "hi")
        client.send_message("D1", "hi", request_id="fixed")
    assert all(seen) and len(set(seen[:2])) == 2 and seen[2] == "fixed"


APPEAL_EVIDENCES = [{"evidence_type": "PROOF_OF_DELIVERY", "notes": "Delivered 3 Oct, signed for by the buyer"}]
DISPUTE_WRITES = [  # (call, the path it must POST to)
    pytest.param(lambda c, **kw: c.escalate("D1", "more facts", **kw),
                 "/v1/customer/disputes/D1/escalate", id="escalate"),
    pytest.param(lambda c, **kw: c.appeal("D1", APPEAL_EVIDENCES, **kw),
                 "/v1/customer/disputes/D1/appeal", id="appeal"),
]


def _recording_client():
    """A client over a mock PayPal that records every request except the OAuth token call."""
    import httpx

    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/oauth2/token":
            return httpx.Response(200, json={"access_token": "t", "expires_in": 3600})
        request.read()
        seen.append(request)
        return httpx.Response(200, json={})

    client = PayPalClient("https://api-m.sandbox.paypal.com", "id", "secret", transport=httpx.MockTransport(handler))
    return client, seen


@pytest.mark.parametrize("call,_path", DISPUTE_WRITES)
def test_escalate_and_appeal_refuse_to_run_outside_the_approval_gate(call, _path):
    client, seen = _recording_client()
    with pytest.raises(WriteNotPermitted):
        call(client)
    assert seen == []


@pytest.mark.parametrize("call,_path", DISPUTE_WRITES)
def test_the_read_only_clone_refuses_escalate_and_appeal_even_inside_the_permit(call, _path):
    client, seen = _recording_client()
    with permit_writes(), pytest.raises(WriteNotPermitted):
        call(client.read_only())
    assert seen == []


@pytest.mark.parametrize("call,path", DISPUTE_WRITES)
def test_escalate_and_appeal_send_one_post_each_with_the_caller_or_a_generated_request_id(call, path):
    client, seen = _recording_client()
    with permit_writes():
        call(client, request_id="fixed-id")
        call(client)
        call(client)
    assert [(r.method, r.url.path) for r in seen] == [("POST", path)] * 3
    assert seen[0].headers["paypal-request-id"] == "fixed-id"
    generated = [r.headers["paypal-request-id"] for r in seen[1:]]
    for value in generated:
        uuid.UUID(value)  # a generated key is a UUID
    assert generated[0] != generated[1]


def test_appeal_is_multipart_with_an_input_json_part():
    client, seen = _recording_client()
    with permit_writes():
        client.appeal("D1", APPEAL_EVIDENCES)
    (request,) = seen
    content_type = request.headers["content-type"]
    assert content_type.startswith("multipart/form-data; boundary=")
    message = BytesParser().parsebytes(f"Content-Type: {content_type}\r\n\r\n".encode() + request.content)
    assert message.is_multipart()
    parts = {part.get_param("name", header="content-disposition"): part for part in message.get_payload()}
    assert json.loads(parts["input"].get_payload(decode=True)) == {"evidences": APPEAL_EVIDENCES}


EVASIONS = {
    "alias": "f = client.make_offer\nf('D', note='x', offer_type='REFUND')",
    "getattr": "getattr(client, 'send_message')('D', 'hi')",
    "partial": "import functools\nfunctools.partial(client.accept_claim, 'D')",
    "table": "table = {'go': client.provide_evidence}",
    "private": "client._request('POST', '/x')",
    "http": "client._http.post('/x')",
    "keyword": "client._request(method='POST', path='/x')",
    "permit": "from rebuttal.paypal.client import permit_writes",
    "appeal": "client.appeal('D', [])",
}


@pytest.mark.parametrize("name,code", EVASIONS.items())
def test_the_scan_catches_the_evasions_a_reviewer_tried(name, code, tmp_path):
    path = tmp_path / "sneaky.py"
    path.write_text(code)
    assert references_in(path), f"the boundary scan misses: {name}"


def test_only_post_to_the_token_and_verify_paths_passes_the_write_gates():
    import httpx

    from rebuttal.paypal.client import ReadOnlyTransport, WriteGateTransport, WriteNotPermitted

    inner = httpx.MockTransport(lambda r: httpx.Response(200, json={}))
    for gate in (ReadOnlyTransport(inner), WriteGateTransport(inner)):
        for path in ("/v1/oauth2/token", "/v1/notifications/verify-webhook-signature"):
            assert gate.handle_request(httpx.Request("POST", f"https://api-m.sandbox.paypal.com{path}")).status_code == 200
            with pytest.raises(WriteNotPermitted):  # POST only: no PATCH/DELETE on those paths
                gate.handle_request(httpx.Request("DELETE", f"https://api-m.sandbox.paypal.com{path}"))
        with pytest.raises(WriteNotPermitted):
            gate.handle_request(httpx.Request("POST", "https://api-m.sandbox.paypal.com/v1/customer/disputes/X/send-message"))


def test_render_blueprint_holds_no_secret_values_and_keeps_groq_live():
    import yaml

    blueprint = yaml.safe_load((BACKEND.parent / "render.yaml").read_text())
    env = {e["key"]: e for e in blueprint["services"][0]["envVars"]}
    for key in ("PAYPAL_CLIENT_ID", "PAYPAL_CLIENT_SECRET", "PAYPAL_WEBHOOK_ID", "GROQ_API_KEY", "DATABASE_URL",
                "LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY"):
        assert env[key] == {"key": key, "sync": False}, f"{key} must be prompted for in the dashboard, not stored"
    assert env["REBUTTAL_API_TOKEN"].get("generateValue") is True and "value" not in env["REBUTTAL_API_TOKEN"]
    assert env["PAYPAL_ENV"]["value"] == "sandbox" and "ANTHROPIC_API_KEY" not in env
    assert blueprint["services"][0]["healthCheckPath"] == "/api/health"


def test_make_test_order_only_creates_orders_and_never_touches_a_dispute():
    source = (BACKEND / "scripts" / "make_test_order.py").read_text()
    for method in ("send_message", "make_offer", "provide_evidence", "accept_claim", "escalate", "appeal",
                   "require_evidence", "adjudicate", "get_dispute"):
        assert method not in source, method


def test_make_sandbox_dispute_never_acts_as_the_merchant_on_a_dispute():
    source = (BACKEND / "scripts" / "make_sandbox_dispute.py").read_text()
    for method in ("send_message", "make_offer", "provide_evidence", "accept_claim", "escalate", "appeal",
                   "require_evidence", "adjudicate"):
        assert method not in source, method


def test_approval_never_creates_disputes_or_orders():
    source = (PACKAGE / "approval.py").read_text()
    for method in ("create_dispute", "create_order", "capture_order"):
        assert method not in source, method
