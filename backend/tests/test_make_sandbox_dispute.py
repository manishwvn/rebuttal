"""make_sandbox_dispute: buyer-auth + create-dispute HTTP, with a fake transport (no network, no model)."""

import json

import httpx
import pytest

from rebuttal.paypal.client import PayPalClient, WriteNotPermitted
from scripts.make_sandbox_dispute import create_buyer_dispute, dispute_id_from

BASE = "https://api-m.sandbox.paypal.com"


def fake(seen):
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path == "/v1/oauth2/token":
            return httpx.Response(200, json={"access_token": "tok", "expires_in": 3600})
        return httpx.Response(201, json={"links": [{"rel": "self", "href": f"{BASE}/v1/customer/disputes/PP-D-123"}]})
    return httpx.MockTransport(handler)


def test_creates_dispute_as_buyer_and_returns_id():
    seen: list[httpx.Request] = []
    did = create_buyer_dispute(BASE, "buyer-id", "buyer-secret", "CAP1", "48.00", note="wrong size",
                               transport=fake(seen))
    assert did == "PP-D-123"
    token, create = seen
    assert token.headers["authorization"].startswith("Basic ")  # buyer's own credentials
    assert create.method == "POST" and create.url.path == "/v1/customer/disputes"
    assert create.headers["authorization"] == "Bearer tok" and create.headers["paypal-request-id"]
    body = json.loads(create.content)
    assert body["disputed_transactions"] == [{"seller_transaction_id": "CAP1"}]
    assert body["reason"] == "MERCHANDISE_OR_SERVICE_NOT_AS_DESCRIBED"
    assert body["dispute_amount"] == {"currency_code": "USD", "value": "48.00"}
    assert body["messages"][0]["content"] == "wrong size"


def test_missing_buyer_credentials_fail_before_any_request():
    seen: list[httpx.Request] = []
    with pytest.raises(ValueError):
        create_buyer_dispute(BASE, "", "", "CAP1", "48.00", transport=fake(seen))
    assert seen == []


def test_dispute_id_parsing():
    assert dispute_id_from({"dispute_id": "PP-D-9"}) == "PP-D-9"
    with pytest.raises(ValueError):
        dispute_id_from({})


def test_create_dispute_is_refused_outside_permit_writes():
    seen: list[httpx.Request] = []
    pp = PayPalClient(BASE, "i", "s", transport=fake(seen))
    with pytest.raises(WriteNotPermitted):
        pp.create_dispute("CAP1", "OTHER", {"currency_code": "USD", "value": "1.00"})
    assert all(r.url.path == "/v1/oauth2/token" for r in seen) or seen == []
