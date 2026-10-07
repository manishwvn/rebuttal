"""Step 4-5 of the agent: decide the resolution and draft the response.

Two interchangeable reasoners:
- ClaudeReasoner: reads the buyer's words, the facts, the policies and any AI
  assistant purchase record, then decides and drafts. Used when
  ANTHROPIC_API_KEY is set.
- RuleReasoner: a keyword-and-rules baseline that runs offline. It exists so
  the pipeline and evals run without a key, and as the yardstick the model
  must beat on the "hard" cases where meaning matters more than keywords.

Whatever the reasoner says, `guard` checks it against the hard facts before
anything reaches the merchant.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import asdict, dataclass, field

from .. import policies
from .facts import CaseFile

RESOLUTIONS: dict[str, str] = {
    "SHARE_TRACKING": "Message the buyer with carrier, tracking number and status (package delivered to the right address, or moving normally).",
    "SUBMIT_EVIDENCE": "Submit evidence to PayPal: proof of delivery, the listing, the transaction record, or the buyer's assistant's purchase instructions.",
    "OFFER_REPLACEMENT": "Offer to send a replacement or the correct item, no refund.",
    "OFFER_PARTIAL_REFUND": "Offer a partial refund and the buyer keeps the item.",
    "OFFER_RETURN_FOR_REFUND": "Offer a full refund once the item is returned.",
    "ACCEPT_CLAIM": "Accept the claim and refund the buyer in full.",
    "SUBMIT_REFUND_PROOF": "Submit proof that a refund was already issued.",
}

# What PayPal must list under allowed_response_options before we may propose each resolution.
PAYPAL_REQUIRES: dict[str, tuple[str, str]] = {
    "OFFER_REPLACEMENT": ("make_offer", "REPLACEMENT_WITHOUT_REFUND"),
    "OFFER_PARTIAL_REFUND": ("make_offer", "REFUND"),
    "OFFER_RETURN_FOR_REFUND": ("make_offer", "REFUND_WITH_RETURN"),
    "ACCEPT_CLAIM": ("accept_claim", "REFUND"),
}
# If PayPal won't take a resolution, the closest ones to try instead, in order.
PAYPAL_ALTERNATIVES = ("OFFER_RETURN_FOR_REFUND", "ACCEPT_CLAIM")


def paypal_allows(resolution: str, case: CaseFile) -> bool:
    """False only when PayPal told us (allowed_response_options) it won't accept this resolution."""
    options = case.allowed_response_options
    need = PAYPAL_REQUIRES.get(resolution)
    if options is None or need is None:
        return True
    action, kind = need
    key = "offer_types" if action == "make_offer" else "accept_claim_types"
    return kind in options.get(action, {}).get(key, [])


DAMAGE_WORDS = policies.DAMAGE_WORDS
TEMPERATURE = 0.0  # evals and the demo should repeat; the models still vary a little at 0


@dataclass
class Decision:
    resolution: str
    confidence: float
    reasoning: list[str]
    buyer_wants: str
    message_to_buyer: str
    evidence_summary: str
    partial_refund_pct: int | None = None
    source: str = "rules"
    guard_notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


# --------------------------------------------------------------------- rules
class RuleReasoner:
    name = "rules"

    def decide(self, case: CaseFile) -> Decision:
        resolution, confidence, why = self._pick(case)
        return Decision(
            resolution=resolution,
            confidence=confidence,
            reasoning=why,
            buyer_wants="(not interpreted by the offline baseline)",
            message_to_buyer=draft_message(resolution, case),
            evidence_summary=draft_evidence_summary(resolution, case),
            source=self.name,
        )

    def _pick(self, case: CaseFile) -> tuple[str, float, list[str]]:
        f, msg = case.facts, case.last_buyer_message.lower()
        reason = case.reason

        if reason == "MERCHANDISE_OR_SERVICE_NOT_RECEIVED":
            if not f.get("has_tracking"):
                return "ACCEPT_CLAIM", 0.85, ["No tracking on file, so delivery can't be proven."]
            if f.get("shipment_status") == "DELIVERED":
                if not f.get("delivered_address_matches"):
                    return "OFFER_REPLACEMENT", 0.75, ["Delivered, but not to the address on the order."]
                if case.stage == "CHARGEBACK":
                    return "SUBMIT_EVIDENCE", 0.85, ["Claim stage; delivered to the order address."]
                return "SHARE_TRACKING", 0.8, ["Delivered to the order address."]
            if f.get("days_since_last_scan", 0) >= policies.LOST_PACKAGE_DAYS:
                return "OFFER_REPLACEMENT", 0.65, ["No carrier movement for 10+ days; treat as lost."]
            return "SHARE_TRACKING", 0.75, ["Package is moving and inside normal delivery time."]

        if reason == "MERCHANDISE_OR_SERVICE_NOT_AS_DESCRIBED":
            if f.get("is_agent_purchase") and not f.get("agent_followed_instruction", True):
                return "OFFER_REPLACEMENT", 0.8, ["The buyer's assistant ordered a different variant than instructed."]
            if any(w in msg for w in DAMAGE_WORDS):
                if case.amount < policies.SMALL_ITEM_REFUND_THRESHOLD:
                    return "ACCEPT_CLAIM", 0.8, ["Damaged and under $20: refund without return."]
                return "OFFER_REPLACEMENT", 0.75, ["Damaged in transit; replace it."]
            if f.get("within_return_window", False):
                return "OFFER_RETURN_FOR_REFUND", 0.7, ["Inside the return window; normal return applies."]
            return "SUBMIT_EVIDENCE", 0.7, ["Outside the return window and no defect described."]

        if reason == "UNAUTHORISED":
            if f.get("is_agent_purchase") and f.get("within_agent_spending_limit") and f.get("agent_followed_instruction"):
                return "SUBMIT_EVIDENCE", 0.8, ["Placed by the buyer's own assistant within its instructions."]
            if f.get("delivered_address_matches"):
                return "SUBMIT_EVIDENCE", 0.7, ["Delivered to the address on the transaction."]
            return "ACCEPT_CLAIM", 0.6, ["Nothing ties the purchase to the account holder."]

        if reason == "CREDIT_NOT_PROCESSED":
            if f.get("refund_issued"):
                return "SUBMIT_REFUND_PROOF", 0.9, ["A refund was already issued."]
            return "ACCEPT_CLAIM", 0.75, ["No refund on file."]

        if reason == "DUPLICATE_TRANSACTION":
            if not f.get("transaction_search_available", True):
                return "SUBMIT_EVIDENCE", 0.4, ["Could not check for a duplicate charge (Transaction Search "
                                                "unavailable); needs merchant review."]
            if f.get("duplicate_charge_found"):
                return "ACCEPT_CLAIM", 0.9, ["Two matching charges found."]
            return "SUBMIT_EVIDENCE", 0.75, ["Only one matching charge exists."]

        return "SUBMIT_EVIDENCE", 0.4, [f"Unhandled reason {reason}; needs merchant review."]


# ------------------------------------------------------------------- drafting
def draft_message(resolution: str, case: CaseFile) -> str:
    f = case.facts
    first = case.order.buyer_name.split()[0] if case.order else "there"
    item = f.get("item", "your order")
    tracking = f"{f.get('carrier', '')} {f.get('tracking_number', '')}".strip()
    if resolution == "SHARE_TRACKING":
        if f.get("shipment_status") == "DELIVERED":
            return (f"Hi {first}, thanks for reaching out. {tracking} shows your {item} was delivered on "
                    f"{f.get('delivered_on')} to the address on your order. Could you check with neighbors or "
                    "your building's mail area? If it's still missing, reply here and we'll sort it out.")
        return (f"Hi {first}, your {item} is on its way. Tracking {tracking} shows it moving normally. "
                "Delivery usually takes 3 to 7 business days. We'll keep an eye on it too.")
    if resolution == "OFFER_REPLACEMENT":
        if f.get("is_agent_purchase") and not f.get("agent_followed_instruction", True):
            return (f"Hi {first}, sorry about the mix-up. Your shopping assistant placed the order for "
                    f"{item}, but your note asked for something different. We'll exchange it for free: "
                    "send it back with the prepaid label and we'll ship the right one as soon as it's scanned.")
        return (f"Hi {first}, we're sorry about your {item}. We'll send a replacement right away at no cost.")
    if resolution == "OFFER_PARTIAL_REFUND":
        return f"Hi {first}, we'd like to make this right with a partial refund, and you keep the {item}."
    if resolution == "OFFER_RETURN_FOR_REFUND":
        if f.get("is_agent_purchase") and not f.get("agent_followed_instruction", True):
            return (f"Hi {first}, sorry about the mix-up. Your shopping assistant placed the order for {item}, "
                    "but your note asked for something different. Send it back and we'll ship the right one "
                    "as soon as the return is scanned.")
        return (f"Hi {first}, no problem. Send the {item} back within our 30-day return window and we'll "
                "refund you in full as soon as it arrives.")
    if resolution == "ACCEPT_CLAIM":
        return f"Hi {first}, we're sorry. We've refunded you in full for the {item}."
    if resolution == "SUBMIT_REFUND_PROOF":
        return f"Hi {first}, your refund was issued (ID {', '.join(f.get('refund_ids', []))}). It can take a few days to show up."
    return f"Hi {first}, thanks for your patience. We've shared the details of your order with PayPal."


def draft_evidence_summary(resolution: str, case: CaseFile) -> str:
    f = case.facts
    lines = [f"Order {case.order.invoice_id if case.order else 'unknown'}: {f.get('item', '')}, ${case.amount:.2f}."]
    if f.get("has_tracking"):
        lines.append(f"Shipped via {f['carrier']} {f['tracking_number']}; status {f['shipment_status']}"
                     + (f", delivered {f['delivered_on']}." if f.get("delivered_on") else "."))
        if "delivered_address_matches" in f:
            lines.append("Delivered to the address on the order." if f["delivered_address_matches"]
                         else "Delivery address differs from the order address.")
    if f.get("is_agent_purchase"):
        lines.append(f"Placed by {f['agent_name']}. User instruction: \"{f['agent_instruction']}\". "
                     + ("Order matched the instruction." if f.get("agent_followed_instruction")
                        else "Order did not match the instruction."))
    if f.get("refund_issued"):
        lines.append(f"Refund issued: {', '.join(f['refund_ids'])}.")
    if case.reason == "DUPLICATE_TRANSACTION" and "matching_charges_same_day" in f:
        lines.append(f"Matching charges for this buyer on the purchase day: {f.get('matching_charges_same_day', 0)}.")
    return " ".join(lines)


# --------------------------------------------------------------------- Claude
SYSTEM_PROMPT = """You resolve PayPal disputes for a small online shop called Juniper & Oak.
Goal: the cheapest fair resolution. Keep the sale when the merchant isn't at fault, refund fast when the buyer is right, and never fight a case the evidence can't win.
Read the buyer's own words carefully: they often pick the wrong dispute reason, and what they ask for matters.
Facts in the case file were computed by code from PayPal and the shop's records; treat them as true.
If the purchase was made by the buyer's AI shopping assistant, compare its instruction with what it ordered.
Four facts decide specific cases: if assistant_misordered is true, the buyer's own AI assistant ordered something other than its instruction; do not fight it with evidence, offer the friendly fix; if cannot_prove_delivery is true on a not-received dispute, there is no tracking to submit, so refund the buyer; if likely_lost is true, treat the package as lost, so a buyer who wants money back gets a refund, not tracking details; if refund_without_return_eligible is true, refund in full without asking for a return.
Reply with ONLY a JSON object, no prose."""

OUTPUT_SPEC = {
    "buyer_wants": "one sentence: what the buyer actually wants",
    "resolution": f"one of {list(RESOLUTIONS)}",
    "partial_refund_pct": "integer 5-50, only for OFFER_PARTIAL_REFUND, else null",
    "confidence": "0.0-1.0",
    "reasoning": "3-5 short bullet strings citing facts or policies",
    "message_to_buyer": "friendly, under 90 words, signed 'Juniper & Oak'",
    "evidence_summary": "2-4 factual sentences for PayPal, only if submitting evidence, else empty string",
}


def build_payload(case: CaseFile) -> dict:
    return {
        "dispute": {"reason": case.reason, "stage": case.stage, "amount": case.amount,
                    "hours_until_response_due": case.hours_left},
        "buyer_messages": case.buyer_messages,
        "facts": case.facts,
        "store_policies": [f"{t}: {b}" for t, b in case.policies],
        "allowed_resolutions": {k: v for k, v in RESOLUTIONS.items() if paypal_allows(k, case)},
        "respond_with": OUTPUT_SPEC,
    }


def to_decision(data: dict, source: str) -> Decision:
    return Decision(
        resolution=str(data["resolution"]).strip(),
        confidence=float(data.get("confidence", 0.5)),
        reasoning=list(data.get("reasoning", []))[:5],
        buyer_wants=str(data.get("buyer_wants", "")),
        message_to_buyer=str(data.get("message_to_buyer", "")),
        evidence_summary=str(data.get("evidence_summary", "")),
        partial_refund_pct=data.get("partial_refund_pct"),
        source=source,
    )


def extract_decision_json(text: str) -> dict:
    """The final JSON object with a "resolution" key. Reasoning models may think first, in <think> tags or
    as plain text containing braces, so drop think blocks and take the last matching object."""
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S | re.I)
    text = text.split("</think>")[-1]  # an unopened think block: keep only what follows it
    decoder, found, i = json.JSONDecoder(), None, text.find("{")
    while i != -1:
        try:
            obj, end = decoder.raw_decode(text, i)
        except ValueError:
            i = text.find("{", i + 1)
            continue
        if isinstance(obj, dict) and "resolution" in obj:
            found = obj
        i = text.find("{", end)
    if found is None:
        raise ValueError("no JSON decision in model output")
    return found


class ClaudeReasoner:
    name = "claude"

    def __init__(self, api_key: str, model: str, fallback: RuleReasoner | None = None):
        import anthropic  # imported lazily so offline mode needs no key

        self._client = anthropic.Anthropic(api_key=api_key)
        self._model = model
        self._fallback = fallback or RuleReasoner()

    def decide(self, case: CaseFile) -> Decision:
        payload = build_payload(case)
        try:
            resp = self._client.messages.create(
                model=self._model,
                max_tokens=1200,
                temperature=TEMPERATURE,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": json.dumps(payload, indent=2, default=str)}],
            )
            text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
            data = json.loads(re.search(r"\{.*\}", text, re.S).group(0))
            return to_decision(data, self.name)
        except Exception as exc:  # network, parsing, schema
            d = self._fallback.decide(case)
            d.guard_notes.append(f"Model call failed ({type(exc).__name__}); used rules baseline.")
            return d


class TokenBudget:
    """Keeps calls inside a provider's per-minute limits (sliding 60s window): requests, total tokens, and
    reserved output tokens (providers count a request's max_tokens against the output limit up front)."""

    def __init__(self, tpm: int, rpm: int, otpm: int | None = None, clock=time.monotonic, sleep=time.sleep):
        self.tpm, self.rpm, self.otpm, self._clock, self._sleep = tpm, rpm, otpm, clock, sleep
        self._events: list[tuple[float, int, int]] = []  # (time, tokens, reserved output)

    def wait(self, estimate: int, output: int = 0) -> None:
        while True:
            now = self._clock()
            self._events = [e for e in self._events if now - e[0] < 60]
            used, reserved = sum(e[1] for e in self._events), sum(e[2] for e in self._events)
            fits = (len(self._events) < self.rpm and used + estimate <= self.tpm
                    and (self.otpm is None or reserved + output <= self.otpm))
            if fits or not self._events:
                return
            self._sleep(max(0.5, 60 - (now - self._events[0][0])))

    def record(self, tokens: int, output: int = 0) -> None:
        self._events.append((self._clock(), tokens, output))


class OpenAICompatReasoner:
    """Same prompt, payload and fallback as ClaudeReasoner, over an OpenAI-compatible chat API."""

    name = ""
    BASE_URL = ""
    MAX_TOKENS = 4096
    EXTRA_BODY: dict | None = None

    def __init__(self, api_key: str, model: str, fallback: RuleReasoner | None = None, client=None,
                 throttle: TokenBudget | None = None):
        if client is None:
            from openai import OpenAI  # imported lazily so offline mode needs no key

            client = OpenAI(base_url=self.BASE_URL, api_key=api_key, timeout=240.0, max_retries=2)
        self._client = client
        self._model = model
        self._fallback = fallback or RuleReasoner()
        self._throttle = throttle
        self.tokens_used = 0

    def decide(self, case: CaseFile) -> Decision:
        try:
            user = json.dumps(build_payload(case), indent=2, default=str)
            if self._throttle:
                self._throttle.wait((len(SYSTEM_PROMPT) + len(user)) // 3 + self.MAX_TOKENS, self.MAX_TOKENS)
            resp = self._client.chat.completions.create(
                model=self._model,
                messages=[{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": user}],
                temperature=TEMPERATURE, top_p=1, max_tokens=self.MAX_TOKENS, stream=False,
                **({"extra_body": self.EXTRA_BODY} if self.EXTRA_BODY else {}),
            )
            used = getattr(getattr(resp, "usage", None), "total_tokens", None) or 0
            self.tokens_used += used
            if self._throttle:
                self._throttle.record(used, self.MAX_TOKENS)
            # Only message.content: reasoning_content is the model's thinking and is ignored.
            text = resp.choices[0].message.content or ""
            return to_decision(extract_decision_json(text), self.name)
        except Exception as exc:  # network, rate limit, parsing, schema
            d = self._fallback.decide(case)
            d.guard_notes.append(f"Model call failed ({type(exc).__name__}: {str(exc)[:600]}); used rules baseline.")
            return d


class NvidiaReasoner(OpenAICompatReasoner):
    name = "nvidia"
    BASE_URL = "https://integrate.api.nvidia.com/v1"


class GroqReasoner(OpenAICompatReasoner):
    """Groq free tier for qwen/qwen3.8-27b: 30 requests/min, 1K/day, 8K tokens/min, 200K/day, and (from the 429
    error) 1,000 output tokens/min."""

    name = "groq"
    BASE_URL = "https://api.groq.com/openai/v1"
    MAX_TOKENS = 500  # reserved against the 1,000 output-tokens/min limit (so 2 calls/min); answers use ~300
    EXTRA_BODY = {"reasoning_format": "hidden"}
    TPM, RPM, OTPM = 8000, 30, 1000
    _shared_budget: TokenBudget | None = None  # one budget per process: the evals build a reasoner per case

    def __init__(self, api_key: str, model: str, fallback: RuleReasoner | None = None, client=None,
                 throttle: TokenBudget | None = None):
        if throttle is None:
            if GroqReasoner._shared_budget is None:
                GroqReasoner._shared_budget = TokenBudget(self.TPM, self.RPM, self.OTPM)
            throttle = GroqReasoner._shared_budget
        super().__init__(api_key, model, fallback, client, throttle)


# ---------------------------------------------------------------------- guard
def guard(decision: Decision, case: CaseFile) -> Decision:
    """Reject or adjust decisions the facts don't support. Never trusts the model blindly."""
    f = case.facts
    notes = decision.guard_notes

    def fallback(why: str) -> Decision:
        base = RuleReasoner().decide(case)
        base.guard_notes = notes + [why, f"Fell back to rules: {base.resolution}."]
        base.source = f"{decision.source}+guard"
        return base

    if decision.resolution not in RESOLUTIONS:
        return fallback(f"Unknown resolution '{decision.resolution}'.")
    if decision.resolution == "SHARE_TRACKING" and not f.get("has_tracking"):
        return fallback("Proposed sharing tracking, but there is no tracking.")
    if decision.resolution == "SUBMIT_REFUND_PROOF" and not f.get("refund_issued"):
        return fallback("Proposed refund proof, but no refund exists.")
    if (decision.resolution == "SUBMIT_EVIDENCE" and f.get("assistant_misordered")
            and case.reason == "MERCHANDISE_OR_SERVICE_NOT_AS_DESCRIBED"):
        # Proposed as a replacement; the PayPal check below turns it into return-for-refund where needed.
        decision.resolution = "OFFER_REPLACEMENT"
        decision.message_to_buyer = draft_message("OFFER_REPLACEMENT", case)
        notes.append("The buyer's assistant ordered a different variant than instructed; offering the friendly "
                     "fix instead of fighting with evidence.")
    if (decision.resolution == "SUBMIT_EVIDENCE" and f.get("cannot_prove_delivery")
            and case.reason == "MERCHANDISE_OR_SERVICE_NOT_RECEIVED"):
        decision.resolution = "ACCEPT_CLAIM"
        decision.message_to_buyer = draft_message("ACCEPT_CLAIM", case)
        notes.append("No tracking on file, so delivery can't be proven; converted 'submit evidence' into a refund.")
    if decision.resolution == "SHARE_TRACKING" and f.get("likely_lost") and f.get("buyer_asks_for_refund"):
        decision.resolution = "ACCEPT_CLAIM"
        decision.message_to_buyer = draft_message("ACCEPT_CLAIM", case)
        notes.append("Package is likely lost (no carrier scan for 10+ days) and the buyer wants money back; "
                     "converted 'share tracking' into a refund.")
    if decision.resolution == "SHARE_TRACKING" and case.stage == "CHARGEBACK":
        decision.resolution = "SUBMIT_EVIDENCE"
        decision.evidence_summary = decision.evidence_summary or draft_evidence_summary("SUBMIT_EVIDENCE", case)
        notes.append("Claim stage: converted 'share tracking' into submitting delivery evidence.")
    if not paypal_allows(decision.resolution, case):
        wanted = decision.resolution
        instead = next((r for r in PAYPAL_ALTERNATIVES if r != wanted and paypal_allows(r, case)), None)
        if instead:
            decision.resolution = instead
            decision.message_to_buyer = draft_message(instead, case)  # the old text promised something else
            notes.append(f"PayPal does not allow {wanted} on this dispute (allowed_response_options); "
                         f"proposing {instead} instead.")
        else:
            decision.confidence = min(decision.confidence, 0.3)
            notes.append(f"PayPal does not allow {wanted} on this dispute and offers no close alternative; "
                         "the merchant must resolve it in Resolution Center.")
    if decision.resolution == "OFFER_PARTIAL_REFUND":
        pct = int(decision.partial_refund_pct or 15)
        decision.partial_refund_pct = max(5, min(50, pct))
    if decision.resolution in {"SUBMIT_EVIDENCE"} and not decision.evidence_summary:
        decision.evidence_summary = draft_evidence_summary(decision.resolution, case)
    decision.confidence = max(0.0, min(1.0, decision.confidence))
    if len(decision.message_to_buyer) > 1500:
        decision.message_to_buyer = decision.message_to_buyer[:1500]
        notes.append("Trimmed buyer message to 1500 characters.")
    decision.guard_notes = notes
    return decision
