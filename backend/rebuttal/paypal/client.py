"""Typed wrapper over the PayPal REST endpoints Rebuttal uses.

Every call that changes a dispute (message, offer, evidence, accept) is only
ever invoked by the approval executor, never directly by the agent.

Endpoint shapes follow developer.paypal.com (Disputes API v1, Orders v2).
Items marked VERIFY should be confirmed against the live sandbox in the
week-1 spike (scripts/spike_sandbox.py).
"""

from __future__ import annotations

import json
import time
import uuid
from typing import Any

import httpx


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
        self._client_id = client_id
        self._client_secret = client_secret
        self._http = httpx.Client(base_url=base_url, transport=transport, timeout=timeout)
        self._token: str | None = None
        self._token_expiry = 0.0

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

    def _request(self, method: str, path: str, *, headers: dict | None = None, **kw) -> Any:
        hdrs = {"Authorization": f"Bearer {self._access_token()}"}
        if method in {"POST", "PATCH"}:
            hdrs["PayPal-Request-Id"] = str(uuid.uuid4())  # idempotency
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

    def send_message(self, dispute_id: str, message: str) -> dict:
        return self._request(
            "POST", f"/v1/customer/disputes/{dispute_id}/send-message", json={"message": message}
        )

    def make_offer(
        self,
        dispute_id: str,
        *,
        note: str,
        offer_type: str,
        amount: dict | None = None,
        return_address: dict | None = None,
    ) -> dict:
        """offer_type: REFUND | REFUND_WITH_RETURN | REFUND_WITH_REPLACEMENT | REPLACEMENT_WITHOUT_REFUND"""
        body: dict[str, Any] = {"note": note, "offer_type": offer_type}
        if amount:
            body["offer_amount"] = amount
        if return_address:
            body["return_shipping_address"] = return_address
        return self._request("POST", f"/v1/customer/disputes/{dispute_id}/make-offer", json=body)

    def provide_evidence(
        self, dispute_id: str, evidences: list[dict], files: list[tuple[str, bytes, str]] = ()
    ) -> dict:
        """Multipart: an `input` JSON part plus optional document files."""
        parts: list[tuple[str, tuple]] = [
            ("input", (None, json.dumps({"evidences": evidences}), "application/json"))
        ]
        for i, (name, content, mime) in enumerate(files):
            parts.append((f"file{i + 1}", (name, content, mime)))
        return self._request(
            "POST", f"/v1/customer/disputes/{dispute_id}/provide-evidence", files=parts
        )

    def accept_claim(self, dispute_id: str, *, note: str, refund_amount: dict | None = None) -> dict:
        body: dict[str, Any] = {"note": note, "accept_claim_type": "REFUND"}
        if refund_amount:
            body["refund_amount"] = refund_amount
        return self._request("POST", f"/v1/customer/disputes/{dispute_id}/accept-claim", json=body)

    def escalate(self, dispute_id: str, note: str) -> dict:
        return self._request(
            "POST", f"/v1/customer/disputes/{dispute_id}/escalate", json={"note": note}
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

    def close(self) -> None:
        self._http.close()
