"""Typed wrapper over the PayPal REST endpoints Rebuttal uses.

Every call that changes a dispute (message, offer, evidence, accept) is only
ever invoked by the approval executor, never directly by the agent. Two runtime
guards back that rule up:

- a write (POST/PATCH/PUT/DELETE, except the OAuth token call) raises `WriteNotPermitted` unless the calling
  context is inside `permit_writes()`, which only the approval gate's `execute` node (and manual sandbox scripts)
  enter;
- `PayPalClient.read_only()` returns a clone whose HTTP transport itself refuses anything but GET, so analysis steps
  hold a handle that cannot write even if someone reaches for its private attributes.

Endpoint shapes follow developer.paypal.com (Disputes API v1, Orders v2).
Items marked VERIFY should be confirmed against the live sandbox in the
week-1 spike (scripts/spike_sandbox.py).
"""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any
from urllib.parse import urlparse

import httpx

SANDBOX_HOSTS = {"api-m.sandbox.paypal.com", "api.sandbox.paypal.com"}
WRITE_METHODS = frozenset({"POST", "PATCH", "PUT", "DELETE"})
TOKEN_PATH = "/v1/oauth2/token"  # authentication, not a change to any dispute
VERIFY_PATH = "/v1/notifications/verify-webhook-signature"  # a POST that only answers "is this event from PayPal?"
# The only POSTs that change nothing at PayPal, so the write gates let them through (POST only).
READ_ONLY_POSTS = frozenset({TOKEN_PATH, VERIFY_PATH})

_writes_permitted: ContextVar[bool] = ContextVar("paypal_writes_permitted", default=False)


def _is_read_only(method: str, path: str) -> bool:
    return method in {"GET", "HEAD"} or (method == "POST" and path in READ_ONLY_POSTS)


class WriteNotPermitted(RuntimeError):
    """A PayPal write was attempted outside the approval gate."""


@contextmanager
def permit_writes() -> Iterator[None]:
    """Allow PayPal writes in this context. Used by the `execute` node after a human approval, and by manual
    sandbox scripts. Nothing else should enter it (tests/test_write_boundary.py checks)."""
    token = _writes_permitted.set(True)
    try:
        yield
    finally:
        _writes_permitted.reset(token)


class WriteGateTransport(httpx.BaseTransport):
    """Refuses a write unless the caller is inside `permit_writes()`, whatever code issued the request: this is the
    lowest layer, so it also stops anything that reaches for the client's private httpx handle."""

    def __init__(self, inner: httpx.BaseTransport):
        self._inner = inner

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        if not _is_read_only(request.method, request.url.path) and not _writes_permitted.get():
            raise WriteNotPermitted(f"{request.method} {request.url.path} is a PayPal write outside the approval gate")
        return self._inner.handle_request(request)

    def close(self) -> None:
        self._inner.close()


class ReadOnlyTransport(httpx.BaseTransport):
    """Passes GET and HEAD through and refuses everything else, except the OAuth token request."""

    def __init__(self, inner: httpx.BaseTransport):
        self._inner = inner

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        if not _is_read_only(request.method, request.url.path):
            raise WriteNotPermitted(f"read-only PayPal handle refused {request.method} {request.url.path}")
        return self._inner.handle_request(request)

    def close(self) -> None:
        self._inner.close()


class PayPalError(RuntimeError):
    def __init__(self, status: int, body: Any, debug_id: str | None = None):
        self.status = status
        self.body = body
        self.debug_id = debug_id
        super().__init__(f"PayPal API error {status} (debug_id={debug_id}): {body}")


class PayPalClient:
    def __init__(
        self,
        base_url: str,
        client_id: str,
        client_secret: str,
        transport: httpx.BaseTransport | None = None,
        timeout: float = 30.0,
    ):
        host = (urlparse(base_url).hostname or "").rstrip(".").lower()
        if host.endswith("paypal.com") and host not in SANDBOX_HOSTS:
            raise ValueError(f"Rebuttal only talks to the PayPal sandbox; refusing {host}")
        self._init = (base_url, client_id, client_secret, transport, timeout)
        self._client_id = client_id
        self._client_secret = client_secret
        self._http = httpx.Client(base_url=base_url, timeout=timeout,
                                  transport=WriteGateTransport(transport or httpx.HTTPTransport()))
        self._token: str | None = None
        self._token_expiry = 0.0

    def read_only(self) -> PayPalClient:
        """A clone for analysis steps: same credentials and endpoint, but its transport refuses any write."""
        if self._init is None:  # already a read-only clone
            return self
        base_url, client_id, client_secret, transport, timeout = self._init
        clone = PayPalClient(base_url, client_id, client_secret, timeout=timeout,
                             transport=ReadOnlyTransport(transport or httpx.HTTPTransport()))
        clone._init = None  # a read-only handle keeps no recipe for building a writable one
        return clone

    # ------------------------------------------------------------------ core
    def _access_token(self) -> str:
        if self._token and time.time() < self._token_expiry - 60:
            return self._token
        resp = self._http.post(
            "/v1/oauth2/token",
            auth=(self._client_id, self._client_secret),
            data={"grant_type": "client_credentials"},
        )
        self._raise_for(resp)
        payload = resp.json()
        self._token = payload["access_token"]
        self._token_expiry = time.time() + int(payload.get("expires_in", 3600))
        return self._token

    @staticmethod
    def _raise_for(resp: httpx.Response) -> None:
        if resp.status_code < 400:
            return
        try:
            body: Any = resp.json()
        except ValueError:
            body = resp.text
        debug_id = body.get("debug_id") if isinstance(body, dict) else None
        raise PayPalError(resp.status_code, body, debug_id)

    def _request(self, method: str, path: str, *, headers: dict | None = None,
                 request_id: str | None = None, **kw) -> Any:
        if method in WRITE_METHODS and not _is_read_only(method, path) and not _writes_permitted.get():
            raise WriteNotPermitted(f"{method} {path} is a PayPal write outside the approval gate")
        hdrs = {"Authorization": f"Bearer {self._access_token()}"}
        if method in {"POST", "PATCH"}:
            # Idempotency key. Approved actions pass a deterministic one (approval.idempotency_key) so a retry of
            # the same action is the same request to PayPal; anything else gets a fresh key per call.
            hdrs["PayPal-Request-Id"] = request_id or str(uuid.uuid4())
        if headers:
            hdrs.update(headers)
        resp = self._http.request(method, path, headers=hdrs, **kw)
        self._raise_for(resp)
        if resp.status_code == 204 or not resp.content:
            return {}
        return resp.json()

    # -------------------------------------------------------------- disputes
    def list_disputes(self, **params: Any) -> list[dict]:
        return self._request("GET", "/v1/customer/disputes", params=params).get("items", [])

    def get_dispute(self, dispute_id: str) -> dict:
        return self._request("GET", f"/v1/customer/disputes/{dispute_id}")

    def send_message(self, dispute_id: str, message: str, *, request_id: str | None = None) -> dict:
        return self._request(
            "POST", f"/v1/customer/disputes/{dispute_id}/send-message", json={"message": message},
            request_id=request_id,
        )

    def make_offer(
        self,
        dispute_id: str,
        *,
        note: str,
        offer_type: str,
        amount: dict | None = None,
        return_address: dict | None = None,
        request_id: str | None = None,
    ) -> dict:
        """offer_type: REFUND | REFUND_WITH_RETURN | REFUND_WITH_REPLACEMENT | REPLACEMENT_WITHOUT_REFUND"""
        body: dict[str, Any] = {"note": note, "offer_type": offer_type}
        if amount:
            body["offer_amount"] = amount
        if return_address:
            body["return_shipping_address"] = return_address
        return self._request("POST", f"/v1/customer/disputes/{dispute_id}/make-offer", json=body,
                             request_id=request_id)

    def provide_evidence(
        self, dispute_id: str, evidences: list[dict], files: list[tuple[str, bytes, str]] = (),
        *, request_id: str | None = None,
    ) -> dict:
        """Multipart: an `input` JSON part plus optional document files."""
        parts: list[tuple[str, tuple]] = [
            ("input", (None, json.dumps({"evidences": evidences}), "application/json"))
        ]
        for i, (name, content, mime) in enumerate(files):
            parts.append((f"file{i + 1}", (name, content, mime)))
        return self._request(
            "POST", f"/v1/customer/disputes/{dispute_id}/provide-evidence", files=parts, request_id=request_id
        )

    def accept_claim(self, dispute_id: str, *, note: str, refund_amount: dict | None = None,
                     request_id: str | None = None) -> dict:
        body: dict[str, Any] = {"note": note, "accept_claim_type": "REFUND"}
        if refund_amount:
            body["refund_amount"] = refund_amount
        return self._request("POST", f"/v1/customer/disputes/{dispute_id}/accept-claim", json=body,
                             request_id=request_id)

    def escalate(self, dispute_id: str, note: str, *, request_id: str | None = None) -> dict:
        return self._request(
            "POST", f"/v1/customer/disputes/{dispute_id}/escalate", json={"note": note}, request_id=request_id
        )

    # ---------------------------------------------- sandbox-only simulation
    def require_evidence(self, dispute_id: str, action: str = "SELLER_EVIDENCE") -> dict:
        return self._request(
            "POST", f"/v1/customer/disputes/{dispute_id}/require-evidence", json={"action": action}
        )

    def adjudicate(self, dispute_id: str, outcome: str) -> dict:
        """outcome: BUYER_FAVOR | SELLER_FAVOR (sandbox only)."""
        return self._request(
            "POST",
            f"/v1/customer/disputes/{dispute_id}/adjudicate",
            json={"adjudication_outcome": outcome},
        )

    # ---------------------------------------------------------------- orders
    def create_order(self, purchase_units: list[dict], return_url: str, cancel_url: str) -> dict:
        body = {
            "intent": "CAPTURE",
            "purchase_units": purchase_units,
            "payment_source": {
                "paypal": {
                    "experience_context": {"return_url": return_url, "cancel_url": cancel_url}
                }
            },
        }
        return self._request("POST", "/v2/checkout/orders", json=body)

    def get_order(self, order_id: str) -> dict:
        return self._request("GET", f"/v2/checkout/orders/{order_id}")

    def get_capture_order_id(self, capture_id: str) -> str | None:
        """The order a captured payment belongs to (supplementary_data.related_ids.order_id). Read only."""
        capture = self._request("GET", f"/v2/payments/captures/{capture_id}")
        return ((capture.get("supplementary_data") or {}).get("related_ids") or {}).get("order_id")

    def capture_order(self, order_id: str) -> dict:
        return self._request(
            "POST",
            f"/v2/checkout/orders/{order_id}/capture",
            headers={"Content-Type": "application/json"},
        )

    def add_order_tracking(self, order_id: str, capture_id: str, tracking_number: str, carrier: str) -> dict:
        return self._request(
            "POST",
            f"/v2/checkout/orders/{order_id}/track",
            json={"capture_id": capture_id, "tracking_number": tracking_number, "carrier": carrier,
                  "notify_payer": False},
        )

    # --------------------------------------------- tracking & transactions
    def get_order_trackers(self, order_id: str, capture_id: str | None = None) -> list[dict]:
        """Trackers on the order (purchase_units[].shipping.trackers).

        The sandbox returns only id ("<capture_id>-<tracking_number>"), status and links, so the
        capture and tracking number are split out of the id. Carrier is not echoed back.
        /v1/shipping/trackers returns 403 for sandbox apps.
        """
        trackers: list[dict] = []
        for unit in self.get_order(order_id).get("purchase_units", []):
            for t in (unit.get("shipping") or {}).get("trackers", []):
                tracker_capture, _, number = t.get("id", "").partition("-")
                if capture_id and tracker_capture != capture_id:
                    continue
                trackers.append({**t, "transaction_id": tracker_capture, "tracking_number": number})
        return trackers

    def search_transactions(
        self, start: str, end: str, transaction_id: str | None = None
    ) -> list[dict]:
        """Transaction Search API. Note: sandbox data can lag a few hours (VERIFY)."""
        params = {"start_date": start, "end_date": end, "fields": "all"}
        if transaction_id:
            params["transaction_id"] = transaction_id
        data = self._request("GET", "/v1/reporting/transactions", params=params)
        return data.get("transaction_details", [])

    # -------------------------------------------------------------- webhooks
    def list_webhook_events(self, event_type: str | None = None) -> list[dict]:
        params = {"event_type": event_type} if event_type else None
        return self._request("GET", "/v1/notifications/webhooks-events", params=params).get(
            "events", []
        )

    def verify_webhook_signature(self, webhook_id: str, headers: dict, event: dict) -> bool:
        """Ask PayPal whether a webhook delivery is genuine. `headers` are the request's PayPal-* headers (any case),
        `event` the parsed body. Changes nothing at PayPal (see READ_ONLY_POSTS)."""
        h = {k.lower(): v for k, v in headers.items()}
        body = {
            "auth_algo": h.get("paypal-auth-algo"), "cert_url": h.get("paypal-cert-url"),
            "transmission_id": h.get("paypal-transmission-id"), "transmission_sig": h.get("paypal-transmission-sig"),
            "transmission_time": h.get("paypal-transmission-time"), "webhook_id": webhook_id, "webhook_event": event,
        }
        if not all(body[k] for k in ("auth_algo", "cert_url", "transmission_id", "transmission_sig", "transmission_time")):
            return False
        return self._request("POST", VERIFY_PATH, json=body).get("verification_status") == "SUCCESS"

    def close(self) -> None:
        self._http.close()
