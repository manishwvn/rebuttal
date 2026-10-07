"""The LangGraph workflow: pause at the approval gate, resume with approve / edit / reject, survive a restart."""

import json
import subprocess
import sys
import threading
from pathlib import Path

import httpx
import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command, RetryPolicy
from pydantic import ValidationError

from rebuttal.agent.facts import CaseFile
from rebuttal.agent.graph import DisputeAgent, _transient
from rebuttal.agent.reasoner import RuleReasoner
from rebuttal.approval import ApprovalDecision, ApprovalError, ApprovalQueue, idempotency_key
from rebuttal.audit import AuditLog
from rebuttal.paypal.client import PayPalError, PayPalClient, WriteNotPermitted, permit_writes
from rebuttal.persistence import make_checkpointer
from rebuttal.runtime import Runtime

BACKEND = Path(__file__).resolve().parents[1]
CASES = ["agent_wrong_size", "inr_no_tracking", "inr_delivered_claim"]  # PP-D-2000 offer, 2001 claim, 2002 evidence


@pytest.fixture
def rt():
    return Runtime(seed_cases=CASES, force_rules=True)


def steps(rt, dispute_id):
    return [r["step"] for r in rt.audit.for_dispute(dispute_id)]


def new_agent(rt, checkpointer, **kw):
    """A second 'process': a fresh graph and checkpointer connection over the same PayPal mock and store."""
    return DisputeAgent(client=rt.client, store=rt.store, reasoner=RuleReasoner(), audit=AuditLog(),
                        clock=rt.clock, checkpointer=checkpointer, **kw)


# ----------------------------------------------------------------- the gate
def test_graph_has_the_expected_shape_and_execute_is_only_reachable_through_approval(rt):
    graph = rt.agent.graph.get_graph()
    assert set(graph.nodes) - {"__start__", "__end__"} == {
        "gather_facts", "decide", "guard", "plan_actions", "approval", "execute", "record"}
    into_execute = {e.source for e in graph.edges if e.target == "execute"}
    assert into_execute == {"approval"}
    assert {e.target for e in graph.edges if e.source == "approval"} == {"execute", "record"}


def test_analyze_pauses_at_the_approval_gate_without_touching_paypal(rt):
    p = rt.analyze("PP-D-2000")
    snap = rt.agent.snapshot("PP-D-2000")
    assert snap.next == ("approval",) and any(t.interrupts for t in snap.tasks)
    assert p.status == "PENDING" and p.id.startswith("prop_") and p.id.endswith("_PP-D-2000")
    assert rt.mock.write_calls() == []
    assert steps(rt, "PP-D-2000") == ["gather", "decide", "guard", "propose"]
    json.dumps(snap.values)  # the whole state is plain JSON, so any process can read the checkpoint
    assert CaseFile.from_dict(snap.values["case"]).dispute_id == "PP-D-2000"


def test_analyze_again_returns_the_waiting_proposal_instead_of_a_second_one(rt):
    first = rt.analyze("PP-D-2000")
    calls = len(rt.audit.records)
    assert rt.analyze("PP-D-2000").id == first.id  # a webhook delivered twice does not re-run the agent
    assert len(rt.audit.records) == calls
    fresh = rt.analyze("PP-D-2000", force=True)
    assert fresh.id != first.id
    with pytest.raises(ApprovalError, match="not the current proposal"):
        rt.approvals.approve(first.id)  # approving a proposal the human no longer sees is refused
    with pytest.raises(ApprovalError, match="not the current proposal"):
        rt.approvals.approve("PP-D-2000")  # a bare dispute id would approve whatever is current, unseen
    assert rt.mock.write_calls() == []
    assert rt.approvals.approve(fresh.id).status == "EXECUTED"


def test_approve_executes_once_with_a_deterministic_idempotency_key(rt):
    p = rt.analyze("PP-D-2000")
    done = rt.approvals.approve(p.id)
    assert done.status == "EXECUTED" and done.result[0]["ok"]
    assert rt.mock.disputes["PP-D-2000"]["offer"]["offer_type"] == "REFUND_WITH_RETURN"
    path = "/v1/customer/disputes/PP-D-2000/make-offer"
    assert rt.mock.request_ids == [(path, idempotency_key(p.id, 0, "make_offer"))]
    assert steps(rt, "PP-D-2000")[-3:] == ["approve", "execute", "record"]
    with pytest.raises(ApprovalError, match="EXECUTED, not PENDING"):
        rt.approvals.approve(p.id)
    assert len(rt.mock.write_calls()) == 1


def test_edit_replaces_the_buyer_text_and_is_audited_as_edited(rt):
    p = rt.analyze("PP-D-2000")
    done = rt.approvals.approve(p.id, edited_message="Edited by the merchant")
    assert done.decision.message_to_buyer == "Edited by the merchant"
    assert done.actions[0].params["note"] == "Edited by the merchant"
    assert rt.mock.disputes["PP-D-2000"]["messages"][-1]["content"] == "Edited by the merchant"
    assert [r for r in rt.audit.for_dispute("PP-D-2000") if r["step"] == "approve"][0]["detail"]["edited"] is True


def test_edit_is_refused_when_the_proposal_has_no_buyer_message(rt):
    p = rt.analyze("PP-D-2002")  # submits evidence: nothing buyer-facing to edit
    assert p.actions[0].kind == "provide_evidence"
    with pytest.raises(ApprovalError, match="no buyer-facing message"):
        rt.approvals.approve(p.id, edited_message="Please send this to the buyer")
    assert rt.mock.write_calls() == [] and rt.approvals.latest_for("PP-D-2002").status == "PENDING"
    assert rt.approvals.approve(p.id).status == "EXECUTED"  # a plain approve still works


def test_reject_sends_nothing_and_records_the_reason(rt):
    p = rt.analyze("PP-D-2000")
    done = rt.approvals.reject(p.id, "I will handle this one by phone")
    assert done.status == "REJECTED" and done.result == []
    assert rt.mock.write_calls() == []
    reject = [r for r in rt.audit.for_dispute("PP-D-2000") if r["step"] == "reject"][0]
    assert reject["detail"]["reason"] == "I will handle this one by phone"
    assert "execute" not in steps(rt, "PP-D-2000")
    with pytest.raises(ApprovalError):
        rt.approvals.approve(p.id)  # a rejected proposal cannot be approved afterwards


def test_a_malformed_decision_is_refused_and_the_proposal_stays_pending(rt):
    p = rt.analyze("PP-D-2000")
    config = {"configurable": {"thread_id": "PP-D-2000"}}
    for bad in ({"decision": "edit"}, {"decision": "maybe"}, {"decision": "approve", "edited_message": "x"}):
        with pytest.raises(ValidationError):
            rt.agent.graph.invoke(Command(resume=bad), config)
    assert rt.mock.write_calls() == [] and rt.approvals.latest_for("PP-D-2000").status == "PENDING"
    assert rt.approvals.approve(p.id).status == "EXECUTED"


def test_two_simultaneous_approvals_make_exactly_one_paypal_call(rt):
    p = rt.analyze("PP-D-2000")
    outcomes = []

    def approve():
        try:
            outcomes.append(rt.approvals.approve(p.id).status)
        except ApprovalError as exc:
            outcomes.append(f"refused: {exc}")

    threads = [threading.Thread(target=approve) for _ in range(2)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert sorted(o.split(":")[0] for o in outcomes) == ["EXECUTED", "refused"]
    assert len(rt.mock.write_calls()) == 1


def test_pending_lists_only_proposals_waiting_for_a_human(rt):
    a, b = rt.analyze("PP-D-2000"), rt.analyze("PP-D-2001")
    rt.approvals.reject(b.id)
    assert [p.id for p in rt.approvals.pending()] == [a.id]


# ------------------------------------------------------------- restart / crash
def test_a_paused_proposal_is_resumed_by_a_new_process_from_the_sqlite_checkpoint(tmp_path):
    db = tmp_path / "checkpoints.sqlite"
    rt = Runtime(seed_cases=CASES, force_rules=True, checkpointer=make_checkpointer(str(db)))
    proposal = rt.analyze("PP-D-2000")
    assert rt.mock.write_calls() == []
    del rt.agent  # nothing of the first graph is reused below

    second = new_agent(rt, make_checkpointer(str(db)))
    queue = ApprovalQueue(second)
    assert [p.id for p in queue.pending()] == [proposal.id]
    done = queue.approve(proposal.id, edited_message="Approved after a restart")
    assert done.status == "EXECUTED"
    assert rt.mock.disputes["PP-D-2000"]["messages"][-1]["content"] == "Approved after a restart"
    assert queue.pending() == []


def test_resume_after_a_real_process_restart(tmp_path):
    """Process 1 analyses and exits. Process 2 starts from nothing but the SQLite file and approves."""
    db = tmp_path / "checkpoints.sqlite"
    common = f"""
import os, sys
os.environ["REBUTTAL_TRACING"] = "0"
from rebuttal.runtime import Runtime
from rebuttal.persistence import make_checkpointer
rt = Runtime(seed_cases=["agent_wrong_size"], force_rules=True, checkpointer=make_checkpointer({str(db)!r}))
"""
    env = {"PATH": "/usr/bin:/bin", "REBUTTAL_MOCK": "1", "PAYPAL_ENV": "sandbox", "HOME": str(tmp_path)}
    first = subprocess.run([sys.executable, "-c", common + 'print(rt.analyze("PP-D-2000").id)'],
                           cwd=BACKEND, env=env, capture_output=True, text=True, timeout=120)
    assert first.returncode == 0, first.stderr[-2000:]
    proposal_id = first.stdout.strip().splitlines()[-1]
    assert proposal_id.startswith("prop_")
    second = subprocess.run(
        [sys.executable, "-c", common + f"""
done = rt.approvals.approve({proposal_id!r})
offer = rt.mock.disputes["PP-D-2000"]["offer"]
print(done.status, offer["offer_type"], len(rt.mock.write_calls()))
"""], cwd=BACKEND, env=env, capture_output=True, text=True, timeout=120)
    assert second.returncode == 0, second.stderr[-2000:]
    assert second.stdout.strip().splitlines()[-1] == "EXECUTED REFUND_WITH_RETURN 1"


def crash_after_paypal_answers(monkeypatch):
    """Simulate the process dying right after PayPal accepted the call, before `execute` could checkpoint."""
    from rebuttal import approval

    real, died = approval.execute_action, []

    def execute_then_die(*args, **kwargs):
        response = real(*args, **kwargs)
        if not died:
            died.append(True)
            raise RuntimeError("process died right after PayPal answered")
        return response

    monkeypatch.setattr(approval, "execute_action", execute_then_die)


def test_a_crash_after_the_offer_is_retried_without_a_second_offer(rt, monkeypatch):
    p = rt.analyze("PP-D-2000")
    crash_after_paypal_answers(monkeypatch)
    with pytest.raises(RuntimeError, match="process died"):
        rt.approvals.approve(p.id)
    assert len(rt.mock.disputes["PP-D-2000"]["offer"]["history"]) == 1  # PayPal did get the offer
    assert rt.approvals.latest_for("PP-D-2000").status == "APPROVED"  # approved, but not recorded as done
    done = rt.approvals.retry(p.id)
    assert done.status == "EXECUTED" and done.result[0]["reconciled"] is True
    assert len(rt.mock.disputes["PP-D-2000"]["offer"]["history"]) == 1
    assert len(rt.mock.write_calls()) == 1  # the retry read the dispute, saw the offer, and sent nothing
    assert "execute" in steps(rt, "PP-D-2000") and steps(rt, "PP-D-2000")[-1] == "record"
    with pytest.raises(ApprovalError, match="not waiting to continue"):
        rt.approvals.retry(p.id)


def test_a_crash_after_a_message_does_not_send_it_twice_even_if_paypal_ignores_the_key(monkeypatch):
    """PayPal does not document PayPal-Request-Id for Disputes, so the retry must not lean on it: here the mock's
    replay cache is switched off and the second message is still not sent."""
    rt = Runtime(seed_cases=["inr_delivered"], force_rules=True)
    monkeypatch.setattr(rt.mock, "_replays", type("NoCache", (dict,), {"__contains__": lambda *a: False})())
    p = rt.analyze("PP-D-2000")
    assert p.actions[0].kind == "send_message"
    crash_after_paypal_answers(monkeypatch)
    with pytest.raises(RuntimeError, match="process died"):
        rt.approvals.approve(p.id)
    assert rt.approvals.retry(p.id).status == "EXECUTED"
    sellers = [m for m in rt.mock.disputes["PP-D-2000"]["messages"] if m["posted_by"] == "SELLER"]
    assert len(sellers) == 1 and len(rt.mock.write_calls()) == 1


def test_a_failure_before_the_paypal_call_leaves_nothing_sent_and_cannot_be_flipped_to_a_reject(rt, monkeypatch):
    """A failure after the human answered must not let that first answer decide a later one (review blocker)."""
    p = rt.analyze("PP-D-2000")
    real_log, failing = rt.audit.log, [True]

    def flaky_log(dispute_id, step, detail):
        if step == "approve" and failing:
            failing.clear()
            raise OSError("disk full")
        return real_log(dispute_id, step, detail)

    monkeypatch.setattr(rt.audit, "log", flaky_log)
    with pytest.raises(OSError):
        rt.approvals.approve(p.id)
    assert rt.mock.write_calls() == []
    assert rt.approvals.latest_for("PP-D-2000").status == "APPROVED"
    with pytest.raises(ApprovalError, match="APPROVED, not PENDING"):
        rt.approvals.reject(p.id, "changed my mind")  # the answer was approve; it cannot silently become reject
    assert rt.mock.write_calls() == []
    assert rt.approvals.retry(p.id).status == "EXECUTED" and len(rt.mock.write_calls()) == 1


def test_analysis_never_replaces_an_approved_proposal_that_is_unfinished(rt, monkeypatch):
    p = rt.analyze("PP-D-2000")
    crash_after_paypal_answers(monkeypatch)
    with pytest.raises(RuntimeError):
        rt.approvals.approve(p.id)
    assert rt.analyze("PP-D-2000").id == p.id and rt.analyze("PP-D-2000").status == "APPROVED"  # a second webhook
    with pytest.raises(ApprovalError, match="retry it first"):
        rt.analyze("PP-D-2000", force=True)
    assert rt.approvals.retry(p.id).status == "EXECUTED"


def test_a_failed_reanalysis_does_not_leave_the_old_proposal_looking_approvable(rt, monkeypatch):
    p = rt.analyze("PP-D-2000")
    monkeypatch.setattr(PayPalClient, "get_dispute", lambda self, dispute_id: (_ for _ in ()).throw(PayPalError(404, {})))
    with pytest.raises(PayPalError):
        rt.analyze("PP-D-2000", force=True)
    assert rt.approvals.latest_for("PP-D-2000").status == "INTERRUPTED"
    with pytest.raises(ApprovalError, match="INTERRUPTED, not PENDING"):
        rt.approvals.approve(p.id)
    assert rt.mock.write_calls() == []


def test_two_processes_on_one_sqlite_file_cannot_both_approve(tmp_path):
    db = str(tmp_path / "checkpoints.sqlite")
    rt = Runtime(seed_cases=CASES, force_rules=True, checkpointer=make_checkpointer(db))
    proposal = rt.analyze("PP-D-2000")
    queues = [ApprovalQueue(new_agent(rt, make_checkpointer(db))) for _ in range(2)]  # two workers
    outcomes = []

    def approve(queue):
        try:
            outcomes.append(queue.approve(proposal.id).status)
        except ApprovalError as exc:
            outcomes.append("refused")

    threads = [threading.Thread(target=approve, args=(q,)) for q in queues]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert sorted(outcomes) == ["EXECUTED", "refused"]
    assert len(rt.mock.write_calls()) == 1 and rt.mock.replayed == []  # not hidden by the idempotency cache


def test_edits_that_fail_validation_are_approval_errors_not_server_errors(rt):
    p = rt.analyze("PP-D-2000")
    for bad in ("   ", "x" * 2001):
        with pytest.raises(ApprovalError):
            rt.approvals.approve(p.id, edited_message=bad)
    assert rt.mock.write_calls() == [] and rt.approvals.latest_for("PP-D-2000").status == "PENDING"


def test_a_later_proposal_with_the_same_text_is_not_mistaken_for_the_first_one():
    """Reconciling compares with what the dispute held at analysis time, not with clocks."""
    rt = Runtime(seed_cases=["inr_delivered"], force_rules=True)
    first = rt.analyze("PP-D-2000")
    assert rt.approvals.approve(first.id).result[0].get("reconciled") is None
    second = rt.analyze("PP-D-2000", force=True)
    assert second.id != first.id and second.actions[0].params == first.actions[0].params
    done = rt.approvals.approve(second.id)
    assert done.status == "EXECUTED" and done.result[0].get("reconciled") is None
    assert len([m for m in rt.mock.disputes["PP-D-2000"]["messages"] if m["posted_by"] == "SELLER"]) == 2


def test_a_paypal_5xx_is_not_a_final_failure_because_the_call_may_have_landed(rt, monkeypatch):
    from rebuttal import approval

    p = rt.analyze("PP-D-2000")
    real, calls = approval.execute_action, []

    def answer_503_after_acting(*args, **kwargs):
        real(*args, **kwargs)  # PayPal processed the offer, then the gateway failed
        calls.append(1)
        raise PayPalError(503, {"name": "SERVICE_UNAVAILABLE"})

    monkeypatch.setattr(approval, "execute_action", answer_503_after_acting)
    with pytest.raises(PayPalError):
        rt.approvals.approve(p.id)
    assert rt.approvals.latest_for("PP-D-2000").status == "APPROVED"  # not FAILED
    done = rt.approvals.retry(p.id)
    assert done.status == "EXECUTED" and done.result[0]["reconciled"] is True
    assert len(rt.mock.write_calls()) == 1 and len(calls) == 1
    # A 4xx is PayPal's definitive answer and is recorded as FAILED.
    rt2 = Runtime(seed_cases=["agent_wrong_size"], force_rules=True)
    p2 = rt2.analyze("PP-D-2000")
    monkeypatch.setattr(approval, "execute_action", lambda *a, **k: (_ for _ in ()).throw(PayPalError(422, {})))
    assert rt2.approvals.approve(p2.id).status == "FAILED"


def test_a_stale_proposal_is_refused_before_anything_is_sent(rt):
    p = rt.analyze("PP-D-2000")
    options = rt.mock.disputes["PP-D-2000"]["allowed_response_options"]
    options["make_offer"]["offer_types"].remove("REFUND_WITH_RETURN")  # the dispute moved on while it waited
    done = rt.approvals.approve(p.id)
    assert done.status == "FAILED" and "no longer allows" in done.result[0]["error"]
    assert done.result[0]["sent"] is False and rt.mock.write_calls() == []
    assert [r["step"] for r in rt.audit.for_dispute("PP-D-2000")][-2:] == ["execute_failed", "record"]


def test_a_run_that_stopped_before_record_is_not_replaced_by_a_new_analysis(rt, monkeypatch):
    p = rt.analyze("PP-D-2000")
    real_log, failing = rt.audit.log, [True]

    def flaky_log(dispute_id, step, detail):
        if step == "record" and failing:
            failing.clear()
            raise OSError("disk full")
        return real_log(dispute_id, step, detail)

    monkeypatch.setattr(rt.audit, "log", flaky_log)
    with pytest.raises(OSError):
        rt.approvals.approve(p.id)  # the offer went out; the audit line for it was not written yet
    assert len(rt.mock.write_calls()) == 1
    assert rt.analyze("PP-D-2000").id == p.id  # no new run that would lose the record
    with pytest.raises(ApprovalError, match="retry it first"):
        rt.analyze("PP-D-2000", force=True)
    assert rt.approvals.retry(p.id).status == "EXECUTED"
    assert "execute" in steps(rt, "PP-D-2000") and len(rt.mock.write_calls()) == 1


def test_the_full_clients_private_http_handle_cannot_write_either(rt):
    with pytest.raises(WriteNotPermitted):
        rt.client._http.post("/v1/customer/disputes/PP-D-2000/send-message", json={"message": "hi"})
    assert rt.mock.write_calls() == []
    assert rt.client.read_only().read_only() is not None and rt.client.read_only()._init is None


# -------------------------------------------------------------- reads and retries
def test_analysis_nodes_only_hold_a_client_that_cannot_write(rt):
    reader = rt.client.read_only()
    assert reader.get_dispute("PP-D-2000")["dispute_id"] == "PP-D-2000"
    calls = [lambda: reader.send_message("PP-D-2000", "hi"), lambda: reader.make_offer("PP-D-2000", note="x", offer_type="REFUND"),
             lambda: reader.accept_claim("PP-D-2000", note="x"), lambda: reader.adjudicate("PP-D-2000", "SELLER_FAVOR"),
             lambda: reader._request("POST", "/v1/customer/disputes/PP-D-2000/send-message", json={"message": "hi"}),
             lambda: reader._http.post("/v1/customer/disputes/PP-D-2000/send-message", json={"message": "hi"}),
             lambda: reader._http.request("PATCH", "/v2/checkout/orders/X")]
    for attempt in calls:
        with pytest.raises(WriteNotPermitted):
            attempt()
    with permit_writes():  # even a context that permits writes cannot make this handle write: the transport refuses
        with pytest.raises(WriteNotPermitted):
            reader.send_message("PP-D-2000", "hi")
        with pytest.raises(WriteNotPermitted):
            reader._client_leak = reader.get_dispute.__self__.send_message("PP-D-2000", "hi")
    assert rt.mock.write_calls() == []


def test_the_full_client_refuses_writes_outside_the_approval_gate(rt):
    with pytest.raises(WriteNotPermitted):
        rt.client.send_message("PP-D-2000", "hi")
    assert rt.mock.write_calls() == []
    with permit_writes():
        rt.client.send_message("PP-D-2000", "hi")
    assert len(rt.mock.write_calls()) == 1


def test_the_client_refuses_the_live_paypal_hosts():
    for url in ("https://api-m.paypal.com", "https://api.paypal.com", "https://API-M.PAYPAL.COM.", "https://api-m.paypal.com:443"):
        with pytest.raises(ValueError, match="sandbox"):
            PayPalClient(url, "id", "secret")
    PayPalClient("https://api-m.sandbox.paypal.com", "id", "secret")


def test_a_flaky_paypal_read_is_retried_but_a_404_is_not(rt, monkeypatch):
    real = PayPalClient.get_dispute
    failures = [PayPalError(503, {"name": "SERVICE_UNAVAILABLE"}), httpx.ConnectError("reset")]

    def flaky(self, dispute_id):
        if failures:
            raise failures.pop(0)
        return real(self, dispute_id)

    # on the class: analysis reads through a read-only clone of the client
    monkeypatch.setattr(PayPalClient, "get_dispute", flaky)
    agent = new_agent(rt, InMemorySaver(),
                      retry_policy=RetryPolicy(max_attempts=3, initial_interval=0.0, jitter=False, retry_on=_transient))
    assert agent.analyze("PP-D-2000").status == "PENDING" and not failures

    monkeypatch.setattr(PayPalClient, "get_dispute",
                        lambda self, dispute_id: (_ for _ in ()).throw(PayPalError(404, {"name": "NOT_FOUND"})))
    with pytest.raises(PayPalError):
        agent.analyze("PP-D-2001", force=True)


def test_approval_decision_schema():
    assert ApprovalDecision(decision="approve").approver == "merchant"
    assert ApprovalDecision(decision="edit", edited_message=" hi ").edited_message == " hi "
    for bad in ({"decision": "edit"}, {"decision": "edit", "edited_message": "  "},
                {"decision": "reject", "edited_message": "x"}, {"decision": "edit", "edited_message": "x" * 2001}):
        with pytest.raises(ValidationError):
            ApprovalDecision(**bad)
