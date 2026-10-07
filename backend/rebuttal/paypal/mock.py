"""In-memory stand-in for the PayPal sandbox, served through httpx.MockTransport.

The real PayPalClient talks to it unchanged, so everything built against the
mock runs against the sandbox once keys are added. Behaviour mirrors the
sandbox docs (developer.paypal.com/disputes/test-go-live); anything not yet
confirmed live is marked VERIFY.
"""

from __future__ import annotations

import email.parser
import email.policy
import json
import re
from datetime import datetime, timezone

import httpx

_DISPUTE_PATH = re.compile(r"^/v1/customer/disputes/([^/]+)(?:/([a-z-]+))?$")
_ORDER_PATH = re.compile(r"^/v2/checkout/orders/([^/]+)$")
_CAPTURE_PATH = re.compile(r"^/v2/payments/captures/([^/]+)$")
# Seller actions the real sandbox rejected with ACTION_NOT_ALLOWED_IN_CURRENT_DISPUTE_STATE
# on an INQUIRY dispute in UNDER_REVIEW.
_SELLER_ACTIONS = {"send-message", "make-offer", "provide-evidence", "accept-claim", "escalate"}

SUMMARY_FIELDS = (
    "dispute_id", "create_time", "update_time", "reason", "status",
    "dispute_amount", "dispute_life_cycle_stage", "dispute_channel",
)


def allowed_response_options(reason: str, stage: str) -> dict:
    """What the seller may do. A MERCHANDISE_OR_SERVICE_NOT_AS_DESCRIBED INQUIRY in the real sandbox allowed only
    REFUND / REFUND_WITH_RETURN offers (REPLACEMENT_WITHOUT_REFUND gave INVALID_OFFER_TYPE)."""
    if reason == "MERCHANDISE_OR_SERVICE_NOT_AS_DESCRIBED" and stage == "INQUIRY":
        return {"accept_claim": {"accept_claim_types": ["PARTIAL_REFUND", "REFUND_WITH_RETURN", "REFUND"]},
                "make_offer": {"offer_types": ["REFUND", "REFUND_WITH_RETURN"]}}
    # VERIFY: other reasons and stages not yet observed; assumes the documented full set.
    return {"accept_claim": {"accept_claim_types": ["PARTIAL_REFUND", "REFUND_WITH_RETURN", "REFUND"]},
            "make_offer": {"offer_types": ["REFUND", "REFUND_WITH_RETURN", "REFUND_WITH_REPLACEMENT",
                                           "REPLACEMENT_WITHOUT_REFUND"]}}


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _parse(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _json(status: int, body: dict) -> httpx.Response:
    return httpx.Response(status, json=body)


def _error(status: int, name: str, message: str) -> httpx.Response:
    return _json(status, {"name": name, "message": message, "debug_id": "mock-debug"})


class MockPayPal:
    def __init__(self) -> None:
        self.disputes: dict[str, dict] = {}
        self.transactions: dict[str, dict] = {}
        self.orders: dict[str, dict] = {}
        self.events: list[dict] = []
        self.calls: list[tuple[str, str]] = []
        self.evidence_files: dict[str, list[str]] = {}
        self._replays: dict[tuple[str, str], httpx.Response] = {}  # (path, PayPal-Request-Id) -> first response
        self.replayed: list[tuple[str, str]] = []  # requests answered from the idempotency cache
        self.request_ids: list[tuple[str, str]] = []  # (path, PayPal-Request-Id) of every POST that had one

    # ----------------------------------------------------------- seeding
    def add_dispute(self, dispute: dict) -> None:
        dispute.setdefault("allowed_response_options",
                           allowed_response_options(dispute["reason"], dispute["dispute_life_cycle_stage"]))
        self.disputes[dispute["dispute_id"]] = dispute
        self._event("CUSTOMER.DISPUTE.CREATED", dispute)

    def add_transaction(self, txn: dict) -> None:
        self.transactions[txn["transaction_info"]["transaction_id"]] = txn

    def add_order(self, order_id: str, capture_id: str) -> dict:
        return self.orders.setdefault(order_id, {
            "id": order_id, "intent": "CAPTURE", "status": "COMPLETED",
            "purchase_units": [{"reference_id": "default", "shipping": {"trackers": []},
                                "payments": {"captures": [{"id": capture_id, "status": "COMPLETED"}]}}],
        })

    def add_tracker(self, order_id: str, capture_id: str, tracking_number: str, status: str) -> None:
        """Same shape the real sandbox returns: id, status, links; no carrier or tracking_number fields."""
        order = self.add_order(order_id, capture_id)
        tracker_id = f"{capture_id}-{tracking_number}"
        order["purchase_units"][0]["shipping"]["trackers"].append({
            "id": tracker_id, "status": status, "notify_payer": False,
            "links": [{"href": f"/v2/checkout/orders/{order_id}", "rel": "up", "method": "GET"},
                      {"href": f"/v2/checkout/orders/{order_id}/trackers/{tracker_id}", "rel": "update",
                       "method": "PATCH"}],
        })

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self._handle)

    def write_calls(self) -> list[tuple[str, str]]:
        return [c for c in self.calls if c[0] == "POST" and c[1] not in ("/v1/oauth2/token", "/v1/notifications/verify-webhook-signature")]

    # ----------------------------------------------------------- routing
    def _event(self, event_type: str, dispute: dict) -> None:
        self.events.append({
            "id": f"WH-MOCK-{len(self.events) + 1:04d}",
            "event_type": event_type,
            "create_time": _now(),
            "resource": {"dispute_id": dispute["dispute_id"], "status": dispute["status"]},
        })

    def _handle(self, request: httpx.Request) -> httpx.Response:
        """Idempotency like PayPal's: a POST repeating a PayPal-Request-Id gets the first response back and is not
        executed again. VERIFY: PayPal's OpenAPI specs document PayPal-Request-Id for Orders and Payments but not for
        any Disputes endpoint; the mock replays every POST so the retry path can be tested."""
        key = (request.url.path, request.headers.get("paypal-request-id", ""))
        if request.method == "POST" and key[1]:
            self.request_ids.append(key)
        if request.method == "POST" and key[1] and key in self._replays:
            self.calls.append((request.method, request.url.path))
            self.replayed.append(key)
            first = self._replays[key]
            return httpx.Response(first.status_code, content=first.content, headers=first.headers)
        response = self._dispatch(request)
        if request.method == "POST" and key[1] and response.status_code < 400:
            response.read()
            self._replays[key] = response
        return response

    def _dispatch(self, request: httpx.Request) -> httpx.Response:
        path, method = request.url.path, request.method
        self.calls.append((method, path))

        if path == "/v1/oauth2/token":
            return _json(200, {"access_token": "MOCK-TOKEN", "token_type": "Bearer", "expires_in": 32400})
        if not request.headers.get("authorization", "").startswith("Bearer "):
            return _error(401, "AUTHENTICATION_FAILURE", "Missing bearer token")
        if path == "/v1/notifications/verify-webhook-signature" and method == "POST":
            # The real call needs PayPal's signing certificate; the mock accepts any complete request except a
            # transmission_sig of "invalid", which tests use for a forged delivery.
            body = json.loads(request.content or b"{}")
            ok = body.get("transmission_sig") not in (None, "", "invalid") and bool(body.get("webhook_id"))
            return _json(200, {"verification_status": "SUCCESS" if ok else "FAILURE"})

        if path == "/v1/customer/disputes" and method == "GET":
            items = [{k: d[k] for k in SUMMARY_FIELDS if k in d} for d in self.disputes.values()]
            return _json(200, {"items": items})

        match = _DISPUTE_PATH.match(path)
        if match:
            return self._dispute_route(method, match.group(1), match.group(2), request)

        order_match = _ORDER_PATH.match(path)
        if order_match and method == "GET":
            order = self.orders.get(order_match.group(1))
            if order is None:
                return _error(404, "RESOURCE_NOT_FOUND", f"No order {order_match.group(1)}")
            return _json(200, order)

        capture_match = _CAPTURE_PATH.match(path)
        if capture_match and method == "GET":  # same shape as the real sandbox: the order id sits in supplementary_data
            for order in self.orders.values():
                for unit in order["purchase_units"]:
                    for cap in unit["payments"]["captures"]:
                        if cap["id"] == capture_match.group(1):
                            return _json(200, {**cap, "supplementary_data": {"related_ids": {"order_id": order["id"]}}})
            return _error(404, "RESOURCE_NOT_FOUND", f"No capture {capture_match.group(1)}")

        if path == "/v1/reporting/transactions" and method == "GET":
            params = request.url.params
            txn_id = params.get("transaction_id")
            rows = list(self.transactions.values())
            if txn_id:
                rows = [r for r in rows if r["transaction_info"]["transaction_id"] == txn_id]
            if params.get("start_date") and params.get("end_date"):
                start = _parse(params["start_date"])
                end = _parse(params["end_date"])
                rows = [r for r in rows
                        if start <= _parse(r["transaction_info"]["transaction_initiation_date"]) <= end]
            return _json(200, {"transaction_details": rows})

        if path == "/v1/notifications/webhooks-events" and method == "GET":
            etype = request.url.params.get("event_type")
            events = [e for e in self.events if not etype or e["event_type"] == etype]
            return _json(200, {"events": events})

        return _error(404, "RESOURCE_NOT_FOUND", f"Mock has no route for {method} {path}")

    def _dispute_route(self, method: str, dispute_id: str, action: str | None, request: httpx.Request):
        dispute = self.disputes.get(dispute_id)
        if dispute is None:
            return _error(404, "RESOURCE_NOT_FOUND", f"No dispute {dispute_id}")
        if action is None and method == "GET":
            return _json(200, dispute)
        if method != "POST" or action is None:
            return _error(405, "METHOD_NOT_SUPPORTED", "Unsupported")
        if dispute["status"] == "RESOLVED":
            return _error(422, "UNPROCESSABLE_ENTITY", "Dispute is already resolved")
        if dispute["status"] == "UNDER_REVIEW" and action in _SELLER_ACTIONS:
            return _json(422, {"name": "UNPROCESSABLE_ENTITY", "debug_id": "mock-debug",
                               "message": "The requested action could not be performed, semantically incorrect, "
                                          "or failed business validation.",
                               "details": [{"issue": "ACTION_NOT_ALLOWED_IN_CURRENT_DISPUTE_STATE"}]})

        if action == "provide-evidence":
            body = self._parse_evidence(request)
        else:
            body = json.loads(request.content or b"{}")

        options = dispute.get("allowed_response_options", {})
        if action == "make-offer" and body.get("offer_type") not in options.get("make_offer", {}).get("offer_types", []):
            return _json(400, {"name": "INVALID_REQUEST", "debug_id": "mock-debug",
                               "message": "Request is not well-formed, syntactically incorrect, or violates schema.",
                               "details": [{"issue": "INVALID_OFFER_TYPE"}]})

        dispute["update_time"] = _now()
        if action == "send-message":
            dispute.setdefault("messages", []).append(
                {"posted_by": "SELLER", "time_posted": _now(), "content": body.get("message", "")}
            )
        elif action == "make-offer":
            amount = body.get("offer_amount")
            dispute["offer"] = {
                "buyer_requested_amount": dispute["dispute_amount"],
                "seller_offered_amount": amount,
                "offer_type": body.get("offer_type"),
                "history": [{"offer_time": _now(), "actor": "SELLER", "event_type": "PROPOSED",
                             "offer_type": body.get("offer_type"), "offer_amount": amount}],
            }
            # The real sandbox shows the offer note as a SELLER message.
            dispute.setdefault("messages", []).append(
                {"posted_by": "SELLER", "time_posted": _now(), "content": body.get("note", "")})
            dispute["status"] = "WAITING_FOR_BUYER_RESPONSE"
        elif action == "provide-evidence":
            dispute.setdefault("evidences", []).extend(body.get("evidences", []))
            dispute["status"] = "UNDER_REVIEW"
        elif action == "accept-claim":
            dispute["status"] = "RESOLVED"
            dispute["dispute_outcome"] = {"outcome_code": "RESOLVED_BUYER_FAVOUR"}
        elif action == "escalate":
            dispute["dispute_life_cycle_stage"] = "CHARGEBACK"
            dispute["status"] = "UNDER_REVIEW"
        elif action == "require-evidence":  # sandbox only
            party = body.get("action", "SELLER_EVIDENCE")
            dispute["status"] = (
                "WAITING_FOR_SELLER_RESPONSE" if party == "SELLER_EVIDENCE" else "WAITING_FOR_BUYER_RESPONSE"
            )
        elif action == "adjudicate":  # sandbox only
            outcome = body.get("adjudication_outcome", "SELLER_FAVOR")
            dispute["status"] = "RESOLVED"
            dispute["dispute_outcome"] = {
                "outcome_code": "RESOLVED_SELLER_FAVOUR" if outcome == "SELLER_FAVOR" else "RESOLVED_BUYER_FAVOUR"
            }
        elif action == "accept-offer":  # buyer side
            dispute["status"] = "RESOLVED"
            dispute["dispute_outcome"] = {"outcome_code": "OFFER_ACCEPTED"}  # VERIFY real code
        else:
            return _error(404, "RESOURCE_NOT_FOUND", f"Unknown action {action}")

        event = "CUSTOMER.DISPUTE.RESOLVED" if dispute["status"] == "RESOLVED" else "CUSTOMER.DISPUTE.UPDATED"
        self._event(event, dispute)
        return _json(200, {"links": [{"rel": "self", "href": f"/v1/customer/disputes/{dispute_id}"}]})

    def _parse_evidence(self, request: httpx.Request) -> dict:
        ctype = request.headers.get("content-type", "")
        raw = b"Content-Type: " + ctype.encode() + b"\r\n\r\n" + request.content
        msg = email.parser.BytesParser(policy=email.policy.default).parsebytes(raw)
        payload: dict = {}
        files: list[str] = []
        for part in msg.iter_parts():
            name = part.get_param("name", header="content-disposition")
            if name == "input":
                payload = json.loads(part.get_content())
            elif part.get_filename():
                files.append(part.get_filename())
        dispute_id = request.url.path.split("/")[4]
        self.evidence_files.setdefault(dispute_id, []).extend(files)
        return payload
