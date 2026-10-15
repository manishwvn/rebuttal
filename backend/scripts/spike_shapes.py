"""Confirm the Disputes shapes the mock only guesses at, on the REAL PayPal sandbox (queue task S3).

    cd backend && REBUTTAL_MOCK=0 uv run python -u -m scripts.spike_shapes survey
    cd backend && REBUTTAL_MOCK=0 uv run python -u -m scripts.spike_shapes escalate <dispute id>
    cd backend && REBUTTAL_MOCK=0 uv run python -u -m scripts.spike_shapes send-message <dispute id>
    cd backend && REBUTTAL_MOCK=0 uv run python -u -m scripts.spike_shapes buyer-reply <dispute id>
    cd backend && REBUTTAL_MOCK=0 uv run python -u -m scripts.spike_shapes proof-of-return <dispute id>
    cd backend && REBUTTAL_MOCK=0 uv run python -u -m scripts.spike_shapes appeal <dispute id>

Needs PAYPAL_CLIENT_ID / PAYPAL_CLIENT_SECRET (sandbox) in backend/.env. buyer-reply also needs the second sandbox
business account: PAYPAL_BUYER_CLIENT_ID / PAYPAL_BUYER_CLIENT_SECRET. `survey` only reads. Every other command changes
the named sandbox dispute for good, and only when the dispute's own links offer that action (escalate and
proof-of-return check first and send nothing otherwise). Each write uses a fresh PayPal-Request-Id, and its request and
result go to the audit log (REBUTTAL_AUDIT_PATH, and the audit table when DATABASE_URL is set). A write command saves its
redacted record to backend/tests/fixtures/sandbox_<name>_<dispute id>.json. It refuses, before sending anything, when
that file exists: a write record is never overwritten. `survey` replaces its sandbox_dispute_<category>.json snapshots.
Refuses to run on the mock. Findings: docs/sandbox-findings.md.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

from rebuttal.audit import AuditLog
from rebuttal.config import load_settings
from rebuttal.paypal.client import PayPalClient, PayPalError, permit_writes

FIXTURES = Path(__file__).resolve().parents[1] / "tests" / "fixtures"
PLACEHOLDER_EMAIL = "redacted@example.com"
PLACEHOLDER = "REDACTED"
EMAIL_RE = re.compile(r"\S+@\S+")
EMAIL_KEYS = frozenset({"email", "email_address"})
REDACTED_KEYS = frozenset({"payer_id", "merchant_id", "account_id", "phone_number", "national_number",
                           "given_name", "surname", "full_name"})
PARTY_KEYS = frozenset({"buyer", "seller", "payer", "payee"})
SURVEY_CAP = 40
TRACKING_NUMBER = "9400111899223344556677"
PDF = b"%PDF-1.4\n%placeholder\n"
NOTE = "Research sandbox run: seller escalates this inquiry to a PayPal claim."
MESSAGE = "Research sandbox run: seller reply to the buyer's inquiry."
BUYER_MESSAGE = "Research sandbox run: buyer reply to the seller's message."
RETURN_NOTE = "Research sandbox run: proof of return with USPS tracking."
ESCALATE_REASON = "OTHER"


def redact(obj: Any, parent: str | None = None) -> Any:
    """A copy of `obj` with personal values replaced. The input is not changed."""
    if isinstance(obj, dict):
        out: dict[str, Any] = {}
        for key, value in obj.items():
            if key in EMAIL_KEYS:
                out[key] = PLACEHOLDER_EMAIL
            elif key == "address" or key.endswith("_address"):  # e.g. extensions...return_shipping_address
                out[key] = {"redacted": True}
            elif key in REDACTED_KEYS or (key == "name" and parent in PARTY_KEYS):
                out[key] = PLACEHOLDER
            else:
                out[key] = redact(value, key)
        return out
    if isinstance(obj, list):
        return [redact(item, parent) for item in obj]
    if isinstance(obj, str) and EMAIL_RE.search(obj):
        return PLACEHOLDER_EMAIL
    return obj


def summarize(dispute: dict) -> dict:
    """The fields the findings need. Only identifiers, enums and presence flags: no personal values are copied."""
    return {
        "dispute_id": dispute.get("dispute_id"),
        "stage": dispute.get("dispute_life_cycle_stage"),
        "status": dispute.get("status"),
        "reason": dispute.get("reason"),
        "link_rels": sorted({link["rel"] for link in dispute.get("links") or [] if link.get("rel")}),
        "has_allowed_response_options": "allowed_response_options" in dispute,
        "has_seller_response_due_date": "seller_response_due_date" in dispute,
        "message_posted_by": sorted({m.get("posted_by", "MISSING") for m in dispute.get("messages") or []}),
        "evidence_types": sorted({e.get("evidence_type", "MISSING") for e in dispute.get("evidences") or []}),
    }


def _warn_hrefs(obj: Any) -> None:
    if isinstance(obj, dict):
        href = obj.get("href")
        if isinstance(href, str) and "@" in href:
            print("WARNING: a link href contains '@' and is redacted in the fixture")
        for value in obj.values():
            _warn_hrefs(value)
    elif isinstance(obj, list):
        for item in obj:
            _warn_hrefs(item)


def save_fixture(name: str, obj: Any) -> Path:
    """Write `obj`, redacted, to backend/tests/fixtures/sandbox_<name>.json."""
    _warn_hrefs(obj)
    FIXTURES.mkdir(parents=True, exist_ok=True)
    path = FIXTURES / f"sandbox_{name}.json"
    path.write_text(json.dumps(redact(obj), indent=2, sort_keys=True) + "\n")
    print(f"saved {path.name}")
    return path


def _fresh(name: str) -> bool:
    """False, with a message, when the record already exists. Checked before any write, so nothing is sent."""
    path = FIXTURES / f"sandbox_{name}.json"
    if path.exists():
        print(f"refusing: {path.name} already exists; move it aside first. Nothing was sent to PayPal.")
        return False
    return True


def attempt(audit: AuditLog, dispute_id: str, op: str, call: Callable[[str], Any]) -> dict:
    """Run one PayPal write inside the write permit, under a fresh PayPal-Request-Id. The request and the result are
    audited, even when the call raises. A PayPal refusal is recorded, not raised."""
    request_id = str(uuid.uuid4())
    audit.log(dispute_id, f"spike.{op}.request", {"request_id": request_id})
    outcome: dict[str, Any] = {"request_id": request_id}
    try:
        with permit_writes():
            outcome.update(ok=True, response=call(request_id))
    except PayPalError as exc:
        outcome.update(ok=False, http_status=exc.status, error=exc.body)
    finally:
        audit.log(dispute_id, f"spike.{op}.result", outcome)
    return outcome


def _rels(dispute: dict) -> set[str]:
    return {link.get("rel") for link in dispute.get("links") or []}


def _inquiry(dispute: dict, status: str) -> bool:
    return dispute.get("dispute_life_cycle_stage") == "INQUIRY" and dispute.get("status") == status


PREDICATES: dict[str, Callable[[dict], bool]] = {
    "escalate_link": lambda d: "escalate" in _rels(d),
    "appeal_link": lambda d: "appeal" in _rels(d),
    "chargeback": lambda d: d.get("dispute_life_cycle_stage") == "CHARGEBACK",
    "inquiry_waiting_seller": lambda d: _inquiry(d, "WAITING_FOR_SELLER_RESPONSE"),
    "inquiry_under_review": lambda d: _inquiry(d, "UNDER_REVIEW"),
}


def _line(s: dict) -> str:
    return (f"{s['dispute_id']}  {s['stage']} / {s['status']}  {s['reason']}  rels={s['link_rels']}  "
            f"allowed_response_options={s['has_allowed_response_options']}  "
            f"seller_response_due_date={s['has_seller_response_due_date']}  "
            f"posted_by={s['message_posted_by']}  evidence={s['evidence_types']}")


def survey(pp: PayPalClient) -> int:
    """Read only. Prints one line per dispute, then saves the first dispute of each category."""
    items = pp.list_disputes(page_size=SURVEY_CAP)[:SURVEY_CAP]
    disputes = [pp.get_dispute(item["dispute_id"]) for item in items]
    for dispute in disputes:
        print(_line(summarize(dispute)))
    print(f"\n{len(disputes)} disputes read")

    chargebacks = [d for d in disputes if d.get("dispute_life_cycle_stage") == "CHARGEBACK"]
    absent = sum("allowed_response_options" not in d for d in chargebacks)
    print(f"CHARGEBACK: allowed_response_options absent on {absent} of {len(chargebacks)} disputes")
    inquiries = [d for d in disputes if d.get("dispute_life_cycle_stage") == "INQUIRY"]
    due = sum("seller_response_due_date" in d for d in inquiries)
    print(f"INQUIRY: seller_response_due_date present on {due} of {len(inquiries)} disputes")

    for name, matches in PREDICATES.items():
        first = next((d for d in disputes if matches(d)), None)
        if first is None:
            print(f"category {name}: none in this sandbox")
        else:
            save_fixture(f"dispute_{name}", first)
    return 0


def _offers(dispute: dict, rel: str) -> bool:
    """True when PayPal's own links for this dispute offer `rel`. A write is sent only when they do."""
    if rel in _rels(dispute):
        return True
    print(f"{dispute.get('dispute_id')} at {dispute.get('dispute_life_cycle_stage')} / {dispute.get('status')} "
          f"offers no {rel} link: nothing sent")
    return False


def escalate(pp: PayPalClient, audit: AuditLog, dispute_id: str) -> int:
    before = pp.get_dispute(dispute_id)
    if before.get("dispute_life_cycle_stage") != "INQUIRY":
        print(f"{dispute_id} is at stage {before.get('dispute_life_cycle_stage')}, not INQUIRY: escalate does not apply")
        return 1
    if not _offers(before, "escalate"):
        return 1
    names = (f"escalate_response_{dispute_id}", f"dispute_after_escalate_{dispute_id}")
    if not all(_fresh(name) for name in names):
        return 1
    record: dict[str, Any] = {"before": summarize(before), "first_attempt": attempt(
        audit, dispute_id, "escalate", lambda rid: pp.escalate(dispute_id, NOTE, request_id=rid))}
    first = record["first_attempt"]
    if not first["ok"] and "buyer_escalation_reason" in json.dumps(first["error"]):
        # The first refusal names the field, so retry once with it: the record shows the field is required.
        record["retry_with_buyer_escalation_reason"] = attempt(audit, dispute_id, "escalate_retry", lambda rid: pp._request(
            "POST", f"/v1/customer/disputes/{dispute_id}/escalate",
            json={"note": NOTE, "buyer_escalation_reason": ESCALATE_REASON}, request_id=rid))
    after = pp.get_dispute(dispute_id)
    record["after"] = summarize(after)
    print(json.dumps(redact(record), indent=2, default=str))
    save_fixture(names[0], record)
    save_fixture(names[1], after)
    return 0


def send_message(pp: PayPalClient, audit: AuditLog, dispute_id: str) -> int:
    name = f"dispute_after_seller_message_{dispute_id}"
    if not _fresh(name):
        return 1
    result = attempt(audit, dispute_id, "send_message", lambda rid: pp.send_message(dispute_id, MESSAGE, request_id=rid))
    after = pp.get_dispute(dispute_id)
    print(json.dumps(redact({"send_message": result, "after": summarize(after)}), indent=2, default=str))
    save_fixture(name, after)
    return 0


def buyer_reply(pp: PayPalClient, base_url: str, audit: AuditLog, dispute_id: str) -> int:
    buyer_id = os.getenv("PAYPAL_BUYER_CLIENT_ID", "")
    buyer_secret = os.getenv("PAYPAL_BUYER_CLIENT_SECRET", "")
    if not (buyer_id and buyer_secret):
        print("Set PAYPAL_BUYER_CLIENT_ID and PAYPAL_BUYER_CLIENT_SECRET (second sandbox business account) in backend/.env")
        return 2
    name = f"dispute_after_buyer_reply_{dispute_id}"
    if not _fresh(name):
        return 1
    buyer = PayPalClient(base_url, buyer_id, buyer_secret)
    try:
        result = attempt(audit, dispute_id, "buyer_reply",
                         lambda rid: buyer.send_message(dispute_id, BUYER_MESSAGE, request_id=rid))
    finally:
        buyer.close()
    after = pp.get_dispute(dispute_id)
    print(json.dumps(redact({"buyer_send_message": result, "after": summarize(after)}), indent=2, default=str))
    save_fixture(name, after)
    return 0


def _return_evidence(dispute_id: str) -> tuple[list[dict], list[tuple[str, bytes, str]]]:
    """The shape agent/pipeline.py builds for a received return (_return_entries), with a one-page PDF."""
    evidences = [{"evidence_type": "PROOF_OF_RETURN",
                  "evidence_info": {"tracking_info": [{"carrier_name": "USPS", "tracking_number": TRACKING_NUMBER}]},
                  "notes": RETURN_NOTE}]
    return evidences, [(f"proof-of-return-{dispute_id}.pdf", PDF, "application/pdf")]


def proof_of_return(pp: PayPalClient, audit: AuditLog, dispute_id: str) -> int:
    before = pp.get_dispute(dispute_id)
    if not _offers(before, "provide_evidence"):
        return 1
    name = f"proof_of_return_response_{dispute_id}"
    if not _fresh(name):
        return 1
    evidences, files = _return_evidence(dispute_id)
    result = attempt(audit, dispute_id, "proof_of_return",
                     lambda rid: pp.provide_evidence(dispute_id, evidences, files, request_id=rid))
    after = pp.get_dispute(dispute_id)
    record = {"before": summarize(before), "evidence_type": "PROOF_OF_RETURN", "result": result,
              "after": summarize(after)}
    print(json.dumps(redact(record), indent=2, default=str))
    save_fixture(name, record)
    return 0


def appeal(pp: PayPalClient, audit: AuditLog, dispute_id: str) -> int:
    before = pp.get_dispute(dispute_id)
    if not _offers(before, "appeal"):
        return 1
    name = f"appeal_response_{dispute_id}"
    if not _fresh(name):
        return 1
    evidences, files = _return_evidence(dispute_id)
    result = attempt(audit, dispute_id, "appeal", lambda rid: pp.appeal(dispute_id, evidences, files, request_id=rid))
    after = pp.get_dispute(dispute_id)
    record = {"before": summarize(before), "result": result, "after": summarize(after)}
    print(json.dumps(redact(record), indent=2, default=str))
    save_fixture(name, record)
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="command", required=True)
    sub.add_parser("survey", help="read only: list disputes and save the first of each category")
    for name, text in (("escalate", "INQUIRY only: escalate, then re-read"),
                       ("send-message", "seller message, then re-read"),
                       ("buyer-reply", "buyer message as the second account, then re-read"),
                       ("proof-of-return", "PROOF_OF_RETURN evidence, then re-read"),
                       ("appeal", "appeal, only if the dispute shows an appeal link")):
        sub.add_parser(name, help=text).add_argument("dispute_id")
    args = ap.parse_args(argv)

    s = load_settings()
    if s.mock:
        print("This needs the real PayPal sandbox: set REBUTTAL_MOCK=0 and the sandbox keys in backend/.env")
        return 2
    if not (s.client_id and s.client_secret):
        print("Add PAYPAL_CLIENT_ID and PAYPAL_CLIENT_SECRET (sandbox) to backend/.env first.")
        return 2
    pp = PayPalClient(s.base_url, s.client_id, s.client_secret)
    audit = AuditLog(s.audit_path, s.database_url)
    try:
        if args.command == "survey":
            return survey(pp)
        if args.command == "buyer-reply":
            return buyer_reply(pp, s.base_url, audit, args.dispute_id)
        handlers = {"escalate": escalate, "send-message": send_message,
                    "proof-of-return": proof_of_return, "appeal": appeal}
        return handlers[args.command](pp, audit, args.dispute_id)
    finally:
        pp.close()


if __name__ == "__main__":
    raise SystemExit(main())
