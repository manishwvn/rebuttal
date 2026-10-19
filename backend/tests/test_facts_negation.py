"""Negation-aware refund and damage keywords (queue R31): "i don't want a refund" is not a refund request."""

import pytest

from rebuttal.agent.facts import _mentions
from rebuttal.policies import DAMAGE_WORDS, REFUND_WORDS


@pytest.mark.parametrize("text", [
    "i don't want a refund, just send a replacement",
    "i do not want my money back",
    "no refund needed",
    "send a replacement rather than a refund",
    "i want it fixed without a refund",
    "i never wanted a refund",
])
def test_negated_refund_words_do_not_match(text):
    assert not _mentions(text, REFUND_WORDS, whole_word=False)


@pytest.mark.parametrize("text", ["please refund me", "i want my money back", "refunds are fine", "i was refunded twice",
                                  "i want to be reimbursed", "reimbursement please", "is it refundable"])
def test_real_refund_words_match(text):
    assert _mentions(text, REFUND_WORDS, whole_word=False)


@pytest.mark.parametrize("text", ["the box is not damaged", "no broken parts", "it isn't cracked", "no scratches at all"])
def test_negated_damage_words_do_not_match(text):
    assert not _mentions(text, DAMAGE_WORDS)


@pytest.mark.parametrize("text", ["it arrived damaged", "the lid is cracked", "two scratches on it", "it was leaking"])
def test_real_damage_words_match(text):
    assert _mentions(text, DAMAGE_WORDS)


@pytest.mark.parametrize("text", ["a tornado hit the town", "the student was confident", "indentation"])
def test_damage_words_need_a_whole_word(text):
    assert not _mentions(text, DAMAGE_WORDS)


def test_one_real_hit_beats_a_negated_hit():
    assert _mentions("i don't want a refund. actually, please refund me", REFUND_WORDS, whole_word=False)
    assert _mentions("not damaged outside but the lid is cracked", DAMAGE_WORDS)


def test_negation_in_an_earlier_sentence_does_not_carry_over():
    assert _mentions("it is not late. refund me", REFUND_WORDS, whole_word=False)
