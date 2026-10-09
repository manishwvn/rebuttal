"""Read-only PayPal tools for the agent, in the shape of PayPal's agent toolkit.

PayPal's `paypal-agent-toolkit` describes each tool as a method, a name, a description, a pydantic argument model
and an execute function, and exposes `run(method, params)`. We do not install that package: it pins an older
langchain, its `run()` dispatches every tool including the writes, and it calls PayPal with `requests`, which skips
our transports. This module keeps the same interface for four read tools only. `ReadOnlyToolkit` wraps
`PayPalClient.read_only()`, a clone whose transport refuses anything but reads, so no PayPal write is reachable
through it.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from ..paypal.client import PayPalClient

# PayPal ids are letters, digits, "_" and "-". The pattern keeps an id from changing the URL path it is put in.
ID_PATTERN = r"^[A-Za-z0-9_-]{1,255}$"


class GetDisputeParameters(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dispute_id: str = Field(pattern=ID_PATTERN)


class ListTransactionsParameters(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start_date: str = Field(min_length=1)
    end_date: str = Field(min_length=1)
    transaction_id: str | None = Field(default=None, pattern=ID_PATTERN)


class GetOrderTrackersParameters(BaseModel):
    model_config = ConfigDict(extra="forbid")

    order_id: str = Field(pattern=ID_PATTERN)
    capture_id: str | None = Field(default=None, pattern=ID_PATTERN)


class GetCaptureOrderIdParameters(BaseModel):
    model_config = ConfigDict(extra="forbid")

    capture_id: str = Field(pattern=ID_PATTERN)


@dataclass(frozen=True)
class ReadTool:
    method: str
    name: str
    description: str
    args_schema: type[BaseModel]
    actions: dict[str, dict[str, bool]]
    execute: Callable[[PayPalClient, dict], Any]


def _get_dispute(client: PayPalClient, params: dict) -> dict:
    return client.get_dispute(params["dispute_id"])


def _list_transactions(client: PayPalClient, params: dict) -> dict:
    transactions = client.search_transactions(params["start_date"], params["end_date"], params.get("transaction_id"))
    return {"transaction_details": transactions}


def _get_order_trackers(client: PayPalClient, params: dict) -> dict:
    return {"trackers": client.get_order_trackers(params["order_id"], params.get("capture_id"))}


def _get_capture_order_id(client: PayPalClient, params: dict) -> dict:
    return {"order_id": client.get_capture_order_id(params["capture_id"])}


READ_TOOLS: tuple[ReadTool, ...] = (
    ReadTool(
        method="get_dispute",
        name="get_dispute",
        description="Read only. Get the details of one PayPal dispute by its dispute ID.",
        args_schema=GetDisputeParameters,
        actions={"disputes": {"get": True}},
        execute=_get_dispute,
    ),
    ReadTool(
        method="list_transactions",
        name="list_transactions",
        description="Read only. List PayPal transactions in a date range, optionally for one transaction ID.",
        args_schema=ListTransactionsParameters,
        actions={"transactions": {"list": True}},
        execute=_list_transactions,
    ),
    ReadTool(
        method="get_order_trackers",
        name="get_order_trackers",
        description="Read only. Get the shipment trackers on a PayPal order, optionally for one capture.",
        args_schema=GetOrderTrackersParameters,
        actions={"orders": {"get": True}},
        execute=_get_order_trackers,
    ),
    ReadTool(
        method="get_capture_order_id",
        name="get_capture_order_id",
        description="Read only. Get the ID of the order that a PayPal capture belongs to.",
        args_schema=GetCaptureOrderIdParameters,
        actions={"orders": {"get": True}},
        execute=_get_capture_order_id,
    ),
)


class ToolNotAvailable(LookupError):
    """Raised for any method that is not one of READ_TOOLS: only read tools exist here."""


class ReadOnlyToolkit:
    def __init__(self, client: PayPalClient):
        # Even a full client is reduced to its GET-only clone, so this object holds no writable handle.
        self._client = client.read_only()
        self._tools = {tool.method: tool for tool in READ_TOOLS}

    @property
    def tool_names(self) -> list[str]:
        return list(self._tools)

    def call(self, method: str, params: dict) -> Any:
        tool = self._tools.get(method)
        if tool is None:
            raise ToolNotAvailable(f"{method!r} is not available: only read tools exist")
        validated = tool.args_schema.model_validate(params)
        return tool.execute(self._client, validated.model_dump(exclude_none=True))

    def run(self, method: str, params: dict) -> str:
        """The JSON text of `call`, as PayPal's toolkit returns from `run`."""
        return json.dumps(self.call(method, params))
