"""The analytics: the aggregation rules (pure functions) and the read-only /api/analytics routes."""

from datetime import UTC, datetime, timedelta

import httpx
import pytest
from fastapi.testclient import TestClient

from rebuttal import analytics
from rebuttal import app as app_module
from rebuttal.paypal.client import PayPalError
from rebuttal.runtime import Runtime

NOW = datetime(2026, 10, 6, 15, 0, tzinfo=UTC)  # the mock's clock (scenarios.DEMO_NOW)
SEEDED = ["agent_wrong_size", "inr_no_tracking", "snad_damaged_low_value"]  # become PP-D-2000, 2001, 2002
ROUTES = ["/api/analytics", "/api/analytics/rows", "/api/analytics/summary", "/api/analytics/deadlines"]
ROW_KEYS = {"dispute_id", "reason", "paypal_status", "created", "due", "product", "amount", "status", "outcome",
            "refunded", "kept", "open", "model_resolution", "final_resolution", "agrees", "count"}
DEADLINE_KEYS = {"dispute_id", "reason", "amount", "status", "paypal_status", "due", "hours_left"}


def paypal_time(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def make_dispute(dispute_id: str = "PP-D-1", amount: str = "48.00", status: str = "WAITING_FOR_SELLER_RESPONSE",
                 reason: str = "MERCHANDISE_OR_SERVICE_NOT_AS_DESCRIBED",
                 due: str | None = "2026-10-15T12:00:00.000Z") -> dict:
    """A dispute as the list endpoint returns it, with only the fields the analytics read."""
    found = {"dispute_id": dispute_id, "create_time": "2026-10-05T12:00:00.000Z", "reason": reason, "status": status,
             "dispute_amount": {"currency_code": "USD", "value": amount}}
    if due is not None:
        found["seller_response_due_date"] = due
    return found


def make_proposal(status: str = "PENDING", resolution: str = "OFFER_RETURN_FOR_REFUND",
                  item: str | None = "Linen shirt (Navy / Size L)", actions: list[dict] | None = None) -> dict:
    """`Proposal.to_dict()`, cut down to the keys the analytics read."""
    default_actions = [{"kind": "make_offer", "params": {"offer_type": "REFUND_WITH_RETURN"}}]
    return {
        "status": status,
        "decision": {"resolution": resolution},
        "actions": actions if actions is not None else default_actions,
        "case_summary": {"facts": {"item": item} if item else {}},
    }


def partial_refund(value: str) -> list[dict]:
    amount = {"currency_code": "USD", "value": value}
    return [{"kind": "make_offer", "params": {"offer_type": "REFUND", "amount": amount}}]


def make_audit(step: str, **detail) -> dict:
    return {"step": step, "detail": detail}


def rows_for(*pairs: tuple[dict, dict | None]) -> list[dict]:
    """Rows for (dispute, proposal or None) pairs."""
    proposals = {d["dispute_id"]: p for d, p in pairs if p is not None}
    return analytics.build_rows([d for d, _ in pairs], proposals, {})


def row_of(found: dict, proposal: dict | None = None, records: list[dict] | None = None) -> dict:
    proposals = {found["dispute_id"]: proposal} if proposal is not None else {}
    return analytics.build_rows([found], proposals, {found["dispute_id"]: records or []})[0]


# ------------------------------------------------------------------ outcome and money rules
def test_a_dispute_without_a_proposal_is_not_analyzed():
    row = row_of(make_dispute())
    assert (row["status"], row["outcome"], row["product"]) == ("NOT_ANALYZED", "not_analyzed", "Unknown")
    assert (row["model_resolution"], row["final_resolution"], row["agrees"]) == (None, None, None)
    assert (row["refunded"], row["kept"], row["open"]) == (0.0, 0.0, 48.0)


def test_the_row_has_exactly_the_documented_keys():
    row = row_of(make_dispute(due=None), make_proposal())
    assert set(row) == ROW_KEYS
    assert row["due"] is None and row["count"] == 1 and row["amount"] == 48.0


@pytest.mark.parametrize("status,outcome", [
    ("PENDING", "awaiting_merchant"), ("APPROVED", "awaiting_merchant"), ("INTERRUPTED", "awaiting_merchant"),
    ("REJECTED", "rejected"), ("FAILED", "failed")])
def test_open_and_closed_proposals_map_to_their_outcome(status, outcome):
    row = row_of(make_dispute(amount="48.00"), make_proposal(status=status))
    assert (row["status"], row["outcome"]) == (status, outcome)
    assert (row["refunded"], row["kept"], row["open"]) == (0.0, 0.0, 48.0)  # only an EXECUTED proposal moves money


@pytest.mark.parametrize("resolution,outcome", [
    ("ACCEPT_CLAIM", "refunded"), ("OFFER_RETURN_FOR_REFUND", "refunded"),
    ("SHARE_TRACKING", "kept"), ("OFFER_REPLACEMENT", "kept"), ("SUBMIT_EVIDENCE", "kept"),
    ("SUBMIT_REFUND_PROOF", "kept")])
def test_an_executed_proposal_is_labelled_by_its_final_resolution(resolution, outcome):
    row = row_of(make_dispute(amount="48.00"), make_proposal(status="EXECUTED", resolution=resolution))
    assert row["outcome"] == outcome
    expected = (48.0, 0.0, 0.0) if outcome == "refunded" else (0.0, 48.0, 0.0)
    assert (row["refunded"], row["kept"], row["open"]) == expected


def test_a_partial_refund_moves_the_offered_amount_and_keeps_the_rest():
    offer = make_proposal(status="EXECUTED", resolution="OFFER_PARTIAL_REFUND", actions=partial_refund("7.20"))
    row = row_of(make_dispute(amount="48.00"), offer)
    assert row["outcome"] == "partially_refunded"
    assert (row["refunded"], row["kept"], row["open"]) == (7.2, 40.8, 0.0)


def test_a_partial_refund_is_capped_at_the_disputed_amount():
    offer = make_proposal(status="EXECUTED", resolution="OFFER_PARTIAL_REFUND", actions=partial_refund("7.20"))
    row = row_of(make_dispute(amount="5.00"), offer)
    assert (row["refunded"], row["kept"], row["open"]) == (5.0, 0.0, 0.0)


def test_a_partial_refund_is_found_wherever_the_offer_sits_in_the_actions():
    actions = [{"kind": "send_message", "params": {"message": "Hello"}}, *partial_refund("7.20")]
    row = row_of(make_dispute(amount="48.00"),
                 make_proposal(status="EXECUTED", resolution="OFFER_PARTIAL_REFUND", actions=actions))
    assert (row["outcome"], row["refunded"], row["kept"]) == ("partially_refunded", 7.2, 40.8)


@pytest.mark.parametrize("actions", [
    [],
    [{"kind": "send_message", "params": {"message": "Hello"}}],
    [{"kind": "make_offer", "params": {"offer_type": "REFUND"}}],
    [{"kind": "make_offer"}],
], ids=["no actions", "no offer", "offer without an amount", "offer without params"])
def test_a_partial_refund_without_a_readable_amount_counts_nothing_instead_of_failing(actions):
    offer = make_proposal(status="EXECUTED", resolution="OFFER_PARTIAL_REFUND", actions=actions)
    row = row_of(make_dispute(amount="48.00"), offer)
    assert (row["refunded"], row["kept"], row["open"]) == (0.0, 48.0, 0.0)


def test_every_row_adds_up_to_its_amount_in_cents():
    rows = rows_for(
        (make_dispute("PP-D-1", amount="48.00"), None),
        (make_dispute("PP-D-2", amount="0.10"), make_proposal("PENDING")),
        (make_dispute("PP-D-3", amount="0.30"),
         make_proposal("EXECUTED", "OFFER_PARTIAL_REFUND", actions=partial_refund("0.10"))),
        (make_dispute("PP-D-4", amount="19.99"), make_proposal("EXECUTED", "ACCEPT_CLAIM")),
        (make_dispute("PP-D-5", amount="7.77"), make_proposal("EXECUTED", "SUBMIT_EVIDENCE")),
        (make_dispute("PP-D-6", amount="12.34"), make_proposal("FAILED")),
    )
    assert len(rows) == 6
    for row in rows:
        assert round(row["refunded"] + row["kept"] + row["open"], 2) == row["amount"], row["dispute_id"]
        assert all(round(row[k], 2) == row[k] for k in ("amount", "refunded", "kept", "open")), row["dispute_id"]


# ------------------------------------------------------------------ product and reasoner agreement
@pytest.mark.parametrize("item,product", [
    ("Linen shirt (Navy / Size L)", "Linen shirt"),
    ("Mug (ceramic) (Blue)", "Mug (ceramic)"),
    ("Linen shirt (Size (L))", "Linen shirt"),
    ("Ceramic mug ()", "Ceramic mug"),
    ("Gift card", "Gift card"),
])
def test_the_product_is_the_item_name_without_its_variant(item, product):
    assert row_of(make_dispute(), make_proposal(item=item))["product"] == product


def test_a_proposal_without_an_item_has_an_unknown_product():
    assert row_of(make_dispute(), make_proposal(item=None))["product"] == "Unknown"


def test_agreement_compares_the_last_decide_record_with_the_final_resolution():
    records = [make_audit("decide", resolution="SHARE_TRACKING"), make_audit("guard", notes=["changed"]),
               make_audit("decide", resolution="OFFER_REPLACEMENT")]
    changed = row_of(make_dispute(), make_proposal("PENDING", "OFFER_RETURN_FOR_REFUND"), records)
    assert (changed["model_resolution"], changed["final_resolution"], changed["agrees"]) == (
        "OFFER_REPLACEMENT", "OFFER_RETURN_FOR_REFUND", 0)
    same = row_of(make_dispute(), make_proposal("PENDING", "OFFER_REPLACEMENT"), records)
    assert same["agrees"] == 1
    no_decide = row_of(make_dispute(), make_proposal("PENDING", "ACCEPT_CLAIM"), [make_audit("guard", notes=[])])
    assert (no_decide["model_resolution"], no_decide["agrees"]) == (None, None)


# ------------------------------------------------------------------ summary
def test_summary_of_no_disputes_is_all_zeros_and_no_rate():
    assert analytics.summarize([], NOW) == {
        "generated_at": "2026-10-06T15:00:00+00:00",
        "totals": {"disputes": 0, "analyzed": 0, "executed": 0},
        "by_status": {}, "by_reason": [], "by_product": [],
        "money": {"currency": "USD", "disputed": 0.0, "refunded": 0.0, "kept": 0.0, "open": 0.0},
        "agreement": {"compared": 0, "agreed": 0, "rate": None, "guard_changes": 0},
    }


def test_totals_statuses_and_money_of_a_mixed_book():
    rows = rows_for(
        (make_dispute("PP-D-1", amount="48.00"), make_proposal("EXECUTED", "OFFER_RETURN_FOR_REFUND")),
        (make_dispute("PP-D-2", amount="22.00"), make_proposal("PENDING", "ACCEPT_CLAIM")),
        (make_dispute("PP-D-3", amount="12.00"), None),
    )
    summary = analytics.summarize(rows, NOW)
    assert summary["totals"] == {"disputes": 3, "analyzed": 2, "executed": 1}
    assert summary["by_status"] == {"EXECUTED": 1, "NOT_ANALYZED": 1, "PENDING": 1}
    assert summary["money"] == {"currency": "USD", "disputed": 82.0, "refunded": 48.0, "kept": 0.0, "open": 34.0}


def test_breakdowns_sort_by_count_then_name_and_sum_the_amounts():
    rows = rows_for(
        (make_dispute("PP-D-1", amount="10.00", reason="B"), make_proposal(item="Mug (Blue)")),
        (make_dispute("PP-D-2", amount="5.00", reason="A"), make_proposal(item="Shirt (M)")),
        (make_dispute("PP-D-3", amount="1.10", reason="B"), make_proposal(item="Mug (Blue)")),
        (make_dispute("PP-D-4", amount="2.20", reason="C"), None),
    )
    summary = analytics.summarize(rows, NOW)
    assert summary["by_reason"] == [
        {"reason": "B", "count": 2, "amount": 11.1},
        {"reason": "A", "count": 1, "amount": 5.0},
        {"reason": "C", "count": 1, "amount": 2.2}]
    assert summary["by_product"] == [
        {"product": "Mug", "count": 2, "amount": 11.1},
        {"product": "Shirt", "count": 1, "amount": 5.0},
        {"product": "Unknown", "count": 1, "amount": 2.2}]


def test_money_sums_are_exact_to_the_cent():
    rows = rows_for((make_dispute("PP-D-1", amount="0.10"), None), (make_dispute("PP-D-2", amount="0.20"), None))
    assert analytics.summarize(rows, NOW)["money"] == {
        "currency": "USD", "disputed": 0.3, "refunded": 0.0, "kept": 0.0, "open": 0.3}


def test_agreement_rate_counts_the_guard_changes_and_skips_missing_pairs():
    disputes = [make_dispute(f"PP-D-{i}") for i in range(1, 5)]
    proposals = {
        "PP-D-1": make_proposal("PENDING", "SHARE_TRACKING"),
        "PP-D-2": make_proposal("PENDING", "ACCEPT_CLAIM"),
        "PP-D-3": make_proposal("PENDING", "OFFER_RETURN_FOR_REFUND"),
    }
    audits = {
        "PP-D-1": [make_audit("decide", resolution="SHARE_TRACKING")],
        "PP-D-2": [make_audit("decide", resolution="ACCEPT_CLAIM")],
        "PP-D-3": [make_audit("decide", resolution="OFFER_REPLACEMENT")],  # the guard turned it into a return refund
    }
    rows = analytics.build_rows(disputes, proposals, audits)
    agreement = analytics.summarize(rows, NOW)["agreement"]
    assert agreement == {"compared": 3, "agreed": 2, "rate": 0.6667, "guard_changes": 1}


# ------------------------------------------------------------------ deadlines
def test_deadlines_keep_only_disputes_waiting_for_the_seller_with_a_due_date():
    rows = analytics.build_rows([
        make_dispute("PP-D-1", due=paypal_time(NOW + timedelta(hours=10))),
        make_dispute("PP-D-2", status="WAITING_FOR_BUYER_RESPONSE", due=paypal_time(NOW + timedelta(hours=10))),
        make_dispute("PP-D-3", status="UNDER_REVIEW", due=None),
        make_dispute("PP-D-4", due=None),
    ], {}, {})
    assert [d["dispute_id"] for d in analytics.deadlines(rows, NOW)] == ["PP-D-1"]


def test_deadlines_list_overdue_first_then_by_hours_left_and_ties_by_id():
    rows = analytics.build_rows([
        make_dispute("PP-D-9", due=paypal_time(NOW + timedelta(hours=5))),
        make_dispute("PP-D-7", due=paypal_time(NOW + timedelta(hours=40))),
        make_dispute("PP-D-2", due=paypal_time(NOW + timedelta(hours=5))),
        make_dispute("PP-D-5", due=paypal_time(NOW - timedelta(hours=3))),
    ], {}, {})
    deadlines = analytics.deadlines(rows, NOW)
    assert [d["dispute_id"] for d in deadlines] == ["PP-D-5", "PP-D-2", "PP-D-9", "PP-D-7"]
    assert [d["hours_left"] for d in deadlines] == [-3.0, 5.0, 5.0, 40.0]


def test_a_deadline_entry_carries_the_dispute_and_its_clock():
    rows = analytics.build_rows([make_dispute("PP-D-1", amount="48.00", due=paypal_time(NOW + timedelta(minutes=95)))],
                                {}, {})
    assert analytics.deadlines(rows, NOW) == [{
        "dispute_id": "PP-D-1", "reason": "MERCHANDISE_OR_SERVICE_NOT_AS_DESCRIBED", "amount": 48.0,
        "status": "NOT_ANALYZED", "paypal_status": "WAITING_FOR_SELLER_RESPONSE",
        "due": "2026-10-06T16:35:00.000Z", "hours_left": 1.6}]


def test_hours_left_rounds_to_a_tenth_and_accepts_both_utc_spellings():
    rows = analytics.build_rows([
        make_dispute("PP-D-1", due=paypal_time(NOW + timedelta(minutes=95))),  # ends in Z
        make_dispute("PP-D-2", due=(NOW + timedelta(minutes=30)).isoformat()),  # ends in +00:00
    ], {}, {})
    assert {d["dispute_id"]: d["hours_left"] for d in analytics.deadlines(rows, NOW)} == {"PP-D-1": 1.6, "PP-D-2": 0.5}


def test_a_due_date_that_cannot_be_parsed_leaves_only_that_dispute_out():
    rows = analytics.build_rows([
        make_dispute("PP-D-1", due="soon"),
        make_dispute("PP-D-2", due=paypal_time(NOW + timedelta(hours=5))),
    ], {}, {})
    assert [d["dispute_id"] for d in analytics.deadlines(rows, NOW)] == ["PP-D-2"]


# ------------------------------------------------------------------ the API
@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(app_module, "rt", Runtime(seed_cases=SEEDED, force_rules=True))
    return TestClient(app_module.app)


def test_before_any_analysis_every_seeded_dispute_is_not_analyzed(client):
    rows = client.get("/api/analytics/rows").json()
    assert [r["dispute_id"] for r in rows] == ["PP-D-2000", "PP-D-2001", "PP-D-2002"]
    assert {r["outcome"] for r in rows} == {"not_analyzed"}
    summary = client.get("/api/analytics/summary").json()
    assert summary["totals"] == {"disputes": 3, "analyzed": 0, "executed": 0}
    assert summary["money"]["open"] == summary["money"]["disputed"] == 82.0
    assert summary["agreement"]["rate"] is None


def test_the_figures_follow_an_analysis_and_an_approval(client):
    hero = client.post("/api/disputes/PP-D-2000/analyze").json()
    client.post("/api/disputes/PP-D-2001/analyze")
    assert client.post(f"/api/proposals/{hero['id']}/approve", json={}).json()["status"] == "EXECUTED"

    rows = {r["dispute_id"]: r for r in client.get("/api/analytics/rows").json()}
    refund = rows["PP-D-2000"]
    assert (refund["status"], refund["final_resolution"], refund["outcome"]) == (
        "EXECUTED", "OFFER_RETURN_FOR_REFUND", "refunded")
    assert (refund["refunded"], refund["kept"], refund["open"]) == (48.0, 0.0, 0.0)
    assert (refund["model_resolution"], refund["agrees"]) == ("OFFER_REPLACEMENT", 0)  # the guard changed it
    assert rows["PP-D-2001"]["outcome"] == "awaiting_merchant" and rows["PP-D-2001"]["open"] == 22.0
    assert rows["PP-D-2002"]["outcome"] == "not_analyzed"

    summary = client.get("/api/analytics/summary").json()
    assert summary["totals"] == {"disputes": 3, "analyzed": 2, "executed": 1}
    assert summary["by_status"] == {"EXECUTED": 1, "NOT_ANALYZED": 1, "PENDING": 1}
    money = summary["money"]
    assert money["disputed"] == 82.0 and money["refunded"] == 48.0 and money["open"] == 34.0
    assert round(money["refunded"] + money["kept"] + money["open"], 2) == money["disputed"]
    assert summary["agreement"] == {"compared": 2, "agreed": 1, "rate": 0.5, "guard_changes": 1}

    deadlines = client.get("/api/analytics/deadlines").json()
    by_id = {d["dispute_id"]: d for d in deadlines}
    # The mock's list leaves out the due date, so these come from reading each dispute.
    assert set(by_id) == {"PP-D-2001", "PP-D-2002"}  # 2000 is with the buyer now; the others still wait on the seller
    assert all(by_id[i]["due"] == rows[i]["due"] and set(by_id[i]) == DEADLINE_KEYS for i in by_id)
    hours = [d["hours_left"] for d in deadlines]
    assert hours == sorted(hours)


def test_one_report_holds_the_rows_the_summary_and_the_deadlines_from_a_single_sweep(client):
    client.post("/api/disputes/PP-D-2001/analyze")
    calls_before = len(app_module.rt.mock.calls)
    report = client.get("/api/analytics").json()
    sweep = [c for c in app_module.rt.mock.calls[calls_before:] if c[1].endswith("/disputes")]
    assert len(sweep) == 1  # the three parts share one list_disputes call
    assert set(report) == {"rows", "summary", "deadlines"}
    assert report["rows"] == client.get("/api/analytics/rows").json()
    assert report["summary"] == client.get("/api/analytics/summary").json()
    assert report["deadlines"] == client.get("/api/analytics/deadlines").json()


def test_the_analytics_routes_need_the_api_token_when_one_is_set(client, monkeypatch):
    monkeypatch.setattr(app_module, "API_TOKEN", "s3cret")
    for path in ROUTES:
        assert client.get(path).status_code == 401
        assert client.get(path, headers={"Authorization": "Bearer wrong"}).status_code == 401
        assert client.get(path, headers={"Authorization": "Bearer s3cret"}).status_code == 200


def test_reading_the_analytics_never_writes_to_paypal(client):
    hero = client.post("/api/disputes/PP-D-2000/analyze").json()
    client.post(f"/api/proposals/{hero['id']}/approve", json={})  # the write happens before the baseline
    writes_before = len(app_module.rt.mock.write_calls())
    assert writes_before >= 1  # the approval reached the mock, so the baseline means something
    calls_before = len(app_module.rt.mock.calls)
    for path in ROUTES:
        assert client.get(path).status_code == 200
    assert len(app_module.rt.mock.write_calls()) == writes_before
    new_calls = app_module.rt.mock.calls[calls_before:]
    assert all(method == "GET" or path == "/v1/oauth2/token" for method, path in new_calls)


# ------------------------------------------------------------------ PayPal failures and the due-date cache
@pytest.mark.parametrize("error", [PayPalError(429, {"name": "RATE_LIMIT_REACHED"}, "dbg-1"),
                                   httpx.ConnectTimeout("timed out")])
def test_a_failed_dispute_list_is_a_readable_502_on_every_analytics_route(client, monkeypatch, error):
    def fail(self, **params):
        raise error
    monkeypatch.setattr(type(app_module.rt.client.read_only()), "list_disputes", fail)
    for path in ROUTES:
        response = client.get(path)
        assert response.status_code == 502, path
        assert "PayPal" in response.json()["detail"]


def test_one_failed_due_date_read_leaves_that_dispute_without_a_deadline(client, monkeypatch):
    real = type(app_module.rt.client.read_only()).get_dispute

    def flaky(self, dispute_id):
        if dispute_id == "PP-D-2001":
            raise PayPalError(503, {"name": "SERVICE_UNAVAILABLE"}, "dbg-2")
        return real(self, dispute_id)
    monkeypatch.setattr(type(app_module.rt.client.read_only()), "get_dispute", flaky)
    response = client.get("/api/analytics")
    assert response.status_code == 200
    assert {d["dispute_id"] for d in response.json()["deadlines"]} == {"PP-D-2000", "PP-D-2002"}
    assert len(response.json()["rows"]) == 3  # the failing dispute still has its row


def test_due_dates_are_reused_until_they_expire_and_a_failed_read_is_not_cached(client, monkeypatch):
    def reads() -> int:
        return len([c for c in app_module.rt.mock.calls if c[0] == "GET" and not c[1].endswith("/disputes")])
    client.get("/api/analytics")
    after_first = reads()
    assert after_first == len(SEEDED)  # one read per waiting dispute
    client.get("/api/analytics")
    assert reads() == after_first  # the second sweep came from the cache
    monkeypatch.setattr(app_module, "DUE_DATE_TTL", 0.0)
    app_module.rt.due_dates.clear()
    client.get("/api/analytics")
    client.get("/api/analytics")
    assert reads() == after_first + 2 * len(SEEDED)  # a TTL of zero reads every time
