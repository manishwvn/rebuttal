"""Guard is single-shot: a refusal on the second pass is kept at low confidence, never a loop (queue R25, piece p1)."""

import copy
import itertools

import pytest

from evals import run as ev
from rebuttal.agent.facts import gather
from rebuttal.agent.reasoner import RESOLUTIONS, Decision, RuleReasoner, draft_message, guard
from rebuttal.runtime import Runtime
from rebuttal.scenarios import DEMO_NOW, load_cases, seed_case

STATUSES = ["WAITING_FOR_SELLER_RESPONSE", "WAITING_FOR_BUYER_RESPONSE", "UNDER_REVIEW", "RESOLVED"]


def _gather(case_id):
    rt = Runtime(seed_cases=[case_id], force_rules=True)
    return gather("PP-D-2000", rt.client, rt.store, DEMO_NOW)


def _seeded(spec):
    """A gathered case from one eval spec, seeded the way the eval runner seeds it (mock sandbox, no write)."""
    rt = Runtime(settings=ev.eval_settings(), seed_cases=[], force_rules=True, tracing=False, provider=None, strict=True)
    seed_case(spec, 0, rt.mock, rt.store)
    return gather("PP-D-2000", rt.client, rt.store, DEMO_NOW)


def _case_for(case_id):
    """cnp_refunded is in the main set; ho2_dup_already_refunded is in the second held-out set."""
    if case_id.startswith("ho2_"):
        spec = next(c for c in load_cases(ev.SETS["holdout2"]) if c["id"] == case_id)
        return _seeded(spec)
    return _gather(case_id)


# ------------------------------------------------ a refund proof off the seller's turn is kept, not swapped or looped
@pytest.mark.parametrize("unlisted", [False, True], ids=["options-as-seeded", "options-none"])
@pytest.mark.parametrize("status", ["UNDER_REVIEW", "WAITING_FOR_BUYER_RESPONSE"])
@pytest.mark.parametrize("case_id", ["cnp_refunded", "ho2_dup_already_refunded"])
def test_refund_proof_off_the_sellers_turn_is_kept_capped_and_does_not_loop(case_id, status, unlisted):
    case = _case_for(case_id)
    assert case.facts["refund_issued"] is True
    case.status = status
    if unlisted:
        case.allowed_response_options = None
    d = guard(RuleReasoner().decide(case), case)
    assert d.resolution == "SUBMIT_REFUND_PROOF" and d.confidence <= 0.3
    assert any("not the seller's turn" in n for n in d.guard_notes)


def test_a_refused_second_pass_keeps_the_rules_pick_with_one_fallback_note():
    """An unknown model choice falls back to the rules once; their pick is refused again, so it stays and is capped."""
    case = _gather("cnp_refunded")
    case.status = "UNDER_REVIEW"
    case.allowed_response_options = None
    d = guard(Decision("NOT_A_REAL_RESOLUTION", 0.9, [], "", "m", "", source="claude"), case)
    assert d.resolution == "SUBMIT_REFUND_PROOF" and d.confidence <= 0.3
    assert sum("Fell back to rules" in n for n in d.guard_notes) == 1
    assert any("not the seller's turn" in n for n in d.guard_notes)


def test_a_second_pass_fallback_keeps_the_resolution_and_caps_it_at_low_confidence():
    case = _gather("inr_no_tracking")
    assert not case.facts["has_tracking"]
    assert guard(Decision("SHARE_TRACKING", 0.9, [], "", "m", "", source="claude"), case).resolution == "ACCEPT_CLAIM"
    d = guard(Decision("SHARE_TRACKING", 0.9, [], "", "m", "", source="claude"), case, _depth=1)
    assert d.resolution == "SHARE_TRACKING" and d.confidence <= 0.3
    assert any("Proposed sharing tracking, but there is no tracking. SHARE_TRACKING is not possible now; "
               "resolve in Resolution Center or wait for the buyer." in n for n in d.guard_notes)
    assert not any("Fell back to rules" in n for n in d.guard_notes)


# ------------------------------------- a second refund is refused on the second pass too, never paid again
@pytest.mark.parametrize("resolution", ["ACCEPT_CLAIM", "OFFER_RETURN_FOR_REFUND", "OFFER_PARTIAL_REFUND"])
def test_a_second_pass_refuses_a_second_refund_with_the_refund_proof(resolution):
    case = _gather("cnp_refunded")
    case.facts.update(refund_issued=True, refunded_amount=case.amount)
    assert guard(Decision(resolution, 0.9, [], "", "m", "", source="claude"), case).resolution == "SUBMIT_REFUND_PROOF"
    d = guard(Decision(resolution, 0.9, [], "", "m", "", source="claude"), case, _depth=1)
    assert d.resolution == "SUBMIT_REFUND_PROOF" and d.confidence <= 0.3
    assert d.message_to_buyer == draft_message("SUBMIT_REFUND_PROOF", case)
    assert any("refusing a second one" in n for n in d.guard_notes)


def test_a_second_pass_offer_swap_that_would_refund_again_keeps_the_refund_proof():
    """PayPal lists only REFUND_WITH_RETURN, so the offer swap is return-for-refund: on a full refund, a second refund."""
    case = _gather("cnp_refunded")
    case.facts.update(refund_issued=True, refunded_amount=case.amount)
    case.allowed_response_options = {"make_offer": {"offer_types": ["REFUND_WITH_RETURN"]}}
    d = guard(Decision("OFFER_REPLACEMENT", 0.9, [], "", "m", "", source="claude"), case, _depth=1)
    assert d.resolution == "SUBMIT_REFUND_PROOF" and d.confidence <= 0.3
    assert any("refusing a second one" in n for n in d.guard_notes)


# ------------------------------------- an accept or an offer is not swapped in for a claim off the seller's turn
def test_accept_claim_off_the_sellers_turn_is_not_swapped_for_an_offer_paypal_lists():
    for status in ("WAITING_FOR_BUYER_RESPONSE", "UNDER_REVIEW"):
        case = _gather("inr_no_tracking")
        case.status = status
        case.allowed_response_options = {"accept_claim": {"accept_claim_types": []},
                                         "make_offer": {"offer_types": ["REFUND_WITH_RETURN", "REFUND"]}}
        d = guard(Decision("ACCEPT_CLAIM", 0.9, [], "", "m", "", source="claude"), case)
        assert d.resolution == "ACCEPT_CLAIM" and d.confidence <= 0.3, status
        assert any("not the seller's turn" in n for n in d.guard_notes), status


def test_accept_claim_on_an_unrefunded_claim_under_review_is_capped_not_offered():
    case = _gather("cnp_refunded")
    case.facts.update(refund_issued=False, refunded_amount=0.0)
    case.status = "UNDER_REVIEW"
    case.allowed_response_options = None
    d = guard(Decision("ACCEPT_CLAIM", 0.9, [], "", "m", "", source="claude"), case)
    assert d.resolution == "ACCEPT_CLAIM" and d.confidence <= 0.3
    assert any("not the seller's turn" in n for n in d.guard_notes)


# --------------------------- facts conversions to an offer are seller's-turn only; evidence and claims stay off-turn
@pytest.mark.parametrize("status", ["WAITING_FOR_BUYER_RESPONSE", "UNDER_REVIEW", "RESOLVED"])
@pytest.mark.parametrize(("case_id", "resolution"), [
    ("agent_wrong_size", "SUBMIT_EVIDENCE"),
    ("inr_misdelivered", "SUBMIT_EVIDENCE"),
    ("snad_damaged_high_value", "ACCEPT_CLAIM"),
])
def test_facts_conversion_to_an_offer_is_not_made_off_the_sellers_turn(case_id, resolution, status):
    case = _gather(case_id)
    case.status = status
    d = guard(Decision(resolution, 0.9, [], "", "m", "", source="claude"), case)
    assert d.resolution == resolution and d.confidence <= 0.3
    assert any("not the seller's turn" in n for n in d.guard_notes)


def test_facts_conversion_to_an_offer_still_happens_on_the_sellers_turn():
    case = _gather("agent_wrong_size")
    assert case.status == "WAITING_FOR_SELLER_RESPONSE"
    case.allowed_response_options = {"accept_claim": {"accept_claim_types": []},
                                     "make_offer": {"offer_types": ["REPLACEMENT_WITHOUT_REFUND"]}}
    d = guard(Decision("SUBMIT_EVIDENCE", 0.9, [], "", "m", "", source="claude"), case)
    assert d.resolution == "OFFER_REPLACEMENT" and d.confidence == 0.9


# ---------------------------------------------------------------- the graph: approve, then analyze again
def test_approved_refund_proof_then_analyze_again_does_not_crash():
    """After the proof is sent the mock moves the dispute to UNDER_REVIEW; analysing it again used to recurse forever."""
    rt = Runtime(seed_cases=["cnp_refunded"], force_rules=True)
    did = rt.client.list_disputes()[0]["dispute_id"]
    first = rt.analyze(did)
    assert first.decision.resolution == "SUBMIT_REFUND_PROOF"
    assert rt.approvals.approve(first.id).status == "EXECUTED"
    assert rt.mock.disputes[did]["status"] == "UNDER_REVIEW"
    rt.analyze(did)
    latest = rt.approvals.latest_for(did)
    assert latest is not None and latest.decision.confidence <= 0.3
    assert latest.decision.resolution == "SUBMIT_REFUND_PROOF"


# -------------------------------------------------------- evidence off the seller's turn stays evidence
def test_evidence_on_a_duplicate_claim_off_the_sellers_turn_is_not_swapped_for_an_offer():
    case = _gather("duplicate_false")
    case.status = "UNDER_REVIEW"
    case.allowed_response_options = None
    case.facts.update(refund_issued=False, refunded_amount=0.0, transaction_search_available=True,
                      duplicate_charge_found=False)
    d = guard(Decision("SUBMIT_EVIDENCE", 0.9, [], "", "m", "", source="claude"), case)
    assert d.resolution == "SUBMIT_EVIDENCE" and d.confidence <= 0.3
    assert any("not the seller's turn" in n for n in d.guard_notes)


# ------------------------------------------------------------- sweep: every case, status, option list and choice
@pytest.mark.parametrize("set_name", list(ev.SETS))
def test_every_model_choice_returns_without_recursion_in_any_case_status_and_option_list(set_name):
    for spec in load_cases(ev.SETS[set_name]):
        base = _seeded(spec)
        option_lists = [("as seeded", base.allowed_response_options), ("none", None)]
        for status, (label, options), resolution in itertools.product(STATUSES, option_lists, RESOLUTIONS):
            case = copy.deepcopy(base)
            case.status, case.allowed_response_options = status, options
            where = f"{set_name}/{spec['id']}: status {status}, options {label}, model said {resolution}"
            try:
                d = guard(Decision(resolution, 0.9, [], "", "m", "", source="claude"), case)
            except RecursionError:
                pytest.fail(f"guard recursed forever at {where}")
            assert d.resolution in RESOLUTIONS and 0 <= d.confidence <= 1, where
