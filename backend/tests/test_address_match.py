from rebuttal.agent.facts import _address_match, _norm, gather
from rebuttal.runtime import Runtime
from rebuttal.scenarios import DEMO_NOW


def test_same_address_written_two_ways_matches():
    a, b = "Mill Street Apt 4B, Reno, NV 89501", "Mill St #4B, Reno NV 89501"
    assert _norm(a) == _norm(b)
    assert _address_match(a, b) is True
    assert _address_match(b, a) is True


def test_hash_unit_written_after_apt_matches_plain_unit():
    assert _address_match("310 Mill St Apt #4B, Reno, NV 89501", "310 Mill St Apt 4B, Reno, NV 89501") is True
    assert _address_match("310 Mill St Unit #4B, Reno, NV 89501", "310 Mill St Apt 4B, Reno, NV 89501") is True


def test_street_words_are_shortened():
    assert _address_match("12 Oak Avenue, Apartment 3, Reno, NV 89501", "12 Oak Ave, Apt 3, Reno, NV 89501") is True
    assert _norm("9 Pine Road, Unit 2") == "9 pine rd apt 2"


def test_identical_case_and_comma_only_differences_match():
    assert _address_match("310 Mill St, Reno, NV 89501", "310 Mill St, Reno, NV 89501") is True
    assert _address_match("310 MILL ST RENO NV 89501", "310 mill st, reno, nv 89501") is True
    assert _address_match(None, None) is True


def test_same_house_zip_and_city_but_other_street_words_is_uncertain():
    assert _address_match("310 Mill Street, Reno, NV 89501", "310 Main Street, Reno, NV 89501") is None


def test_different_house_number_zip_or_city_does_not_match():
    assert _address_match("2831 Alder Way, Spokane, WA 99203", "2813 Alder Way, Spokane, WA 99203") is False
    assert _address_match("310 Mill St, Reno, NV 89501", "310 Mill St, Reno, NV 89502") is False
    assert _address_match("310 Mill St, Reno, NV 89501", "310 Mill St, Boise, ID 89501") is False


def test_different_unit_in_same_building_does_not_match():
    assert _address_match("310 Mill St Apt 4B, Reno, NV 89501", "310 Mill St Apt 5A, Reno, NV 89501") is False


def test_zip_plus_four_is_uncertain_not_a_mismatch():
    assert _address_match("310 Mill St, Reno, NV 89501-1234", "310 Mill St, Reno, NV 89501") is None
    assert _address_match("310 Mill St, Reno, NV 89501-1234", "310 Mill St, Reno, NV 89501-9999") is None
    assert _address_match("310 Mill St, Reno, NV 89501-1234", "310 Mill St, Boise, ID 89501") is False


def test_missing_delivery_address_does_not_match():
    assert _address_match(None, "310 Mill St, Reno, NV 89501") is False


def test_address_without_zip_does_not_match():
    assert _address_match("310 Mill St, Reno, NV", "310 Mill St, Reno, NV 89501") is False


def test_seeded_delivery_to_order_address_is_a_match():
    rt = Runtime(seed_cases=["inr_delivered"], force_rules=True)
    case = gather("PP-D-2000", rt.client, rt.store, DEMO_NOW)
    assert case.facts["delivered_address_matches"] is True
