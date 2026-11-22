from datetime import date

import pytest

from app.modules.ocr_mrz.mrz import (LINE_LEN, build_td3, char_value, check_digit, correct_by_field_type,
                                     normalise_mrz_text, parse_td3)

ICAO_L1 = "P<UTOERIKSSON<<ANNA<MARIA<<<<<<<<<<<<<<<<<<<"
ICAO_L2 = "L898902C36UTO7408122F1204159ZE184226B<<<<<10"


def test_icao_specimen_check_digits():
    assert check_digit("L898902C3") == "6"
    assert check_digit("740812") == "2"
    assert check_digit("120415") == "9"
    assert check_digit("ZE184226B<<<<<") == "1"


def test_char_values():
    assert char_value("<") == 0 and char_value("7") == 7 and char_value("A") == 10 and char_value("Z") == 35
    with pytest.raises(ValueError):
        char_value("a")


def test_icao_specimen_parses_and_all_digits_valid():
    """The published ICAO TD3 specimen line 2 carries valid digits (verified, not assumed)."""
    r = parse_td3(ICAO_L1, ICAO_L2, today=date(2026, 6, 1))
    assert r.format_ok, r.format_errors
    assert [c.name for c in r.checks] == ["passport_number", "date_of_birth", "date_of_expiry", "personal_number", "composite"]
    assert r.all_checks_valid, [(c.name, c.expected, c.computed) for c in r.checks if not c.valid]
    assert (r.surname, r.given_names, r.passport_number, r.issuer, r.nationality, r.sex) == \
        ("ERIKSSON", "ANNA MARIA", "L898902C3", "UTO", "UTO", "F")
    assert r.birth_date == date(1974, 8, 12) and r.expiry_date == date(2012, 4, 15)
    assert r.personal_number == "ZE184226B"


def test_build_td3_round_trip():
    l1, l2 = build_td3("Valdris", "Anna Maria", "ut1234567", "UTO", date(1985, 3, 9), "F", date(2033, 1, 14))
    assert len(l1) == len(l2) == LINE_LEN
    r = parse_td3(l1, l2, today=date(2026, 6, 1))
    assert r.format_ok and r.all_checks_valid
    assert r.surname == "VALDRIS" and r.given_names == "ANNA MARIA" and r.passport_number == "UT1234567"
    assert r.birth_date == date(1985, 3, 9) and r.expiry_date == date(2033, 1, 14)
    assert r.sex == "F" and r.document_code == "P" and r.issuer == "UTO"


def test_build_td3_with_personal_number():
    l1, l2 = build_td3("A", "B", "X1", "UTO", date(1990, 1, 1), "M", date(2030, 1, 1), personal="ab123")
    r = parse_td3(l1, l2)
    assert r.all_checks_valid and r.personal_number == "AB123"


def test_build_td3_long_names_truncated_to_44():
    l1, _ = build_td3("K" * 30, "G" * 30, "X1", "UTO", date(1990, 1, 1), "M", date(2030, 1, 1))
    assert len(l1) == LINE_LEN


@pytest.mark.parametrize("l1,l2,needle", [
    (ICAO_L1[:-1], ICAO_L2, "Line 1 has 43"),
    (ICAO_L1, ICAO_L2 + "<", "Line 2 has 45"),
    (ICAO_L1, "", "Line 2 has 0"),
])
def test_parse_wrong_length(l1, l2, needle):
    r = parse_td3(l1, l2)
    assert not r.format_ok
    assert any(needle in e for e in r.format_errors)
    assert r.checks == []  # cannot slice reliably


def test_parse_bad_charset():
    bad = ICAO_L2[:5] + "*" + ICAO_L2[6:]
    r = parse_td3(ICAO_L1, bad)
    assert not r.format_ok and any("outside A-Z" in e for e in r.format_errors)


def test_parse_wrong_document_code():
    r = parse_td3("V" + ICAO_L1[1:], ICAO_L2)
    assert not r.format_ok
    assert any("document code 'P'" in e for e in r.format_errors)


def test_parse_never_raises_on_garbage():
    for l1, l2 in [("", ""), ("\x00" * 44, "E" * 44), ("P" * 44, "9" * 44), ("P" * 44, "é" * 44)]:
        parse_td3(l1, l2)


def test_bad_check_digit_detected():
    bad = ICAO_L2[:9] + "7" + ICAO_L2[10:]
    r = parse_td3(ICAO_L1, bad)
    assert r.format_ok
    by = {c.name: c for c in r.checks}
    assert not by["passport_number"].valid and by["passport_number"].computed == "6" and by["passport_number"].expected == "7"
    assert not by["composite"].valid  # composite covers the same data
    assert by["date_of_birth"].valid


def test_empty_personal_number_digit_may_be_filler():
    l1, l2 = build_td3("A", "B", "X1", "UTO", date(1990, 1, 1), "M", date(2030, 1, 1))
    assert l2[42] == "<"
    assert parse_td3(l1, l2).all_checks_valid


def test_normalise_mrz_text():
    assert normalise_mrz_text("p«utO  abc‹›\t") == "P<UTO" + "ABC<<"


# ------------------------------------------------------------- correct_by_field_type
def test_lookalike_correction_letters_to_digits_and_back():
    # '0' where letters belong (nationality) and 'O' where a digit belongs (date of birth)
    l2 = list(ICAO_L2)
    l2[10:13] = list("UT0")
    l2[13:19] = list("74O812")
    c1, c2, changes = correct_by_field_type(ICAO_L1, "".join(l2))
    assert c2 == ICAO_L2
    assert {(c["position"], c["from"], c["to"]) for c in changes} == {(12, "0", "O"), (15, "O", "0")}
    assert all(c["line"] == 2 for c in changes)
    assert parse_td3(c1, c2).all_checks_valid


def test_line1_digits_in_names_become_letters():
    l1 = ICAO_L1[:5] + "ER1KSS0N" + ICAO_L1[13:]
    c1, _, changes = correct_by_field_type(l1, ICAO_L2)
    assert c1 == ICAO_L1
    assert len(changes) == 2


def test_filler_repair_short_line1():
    short = ICAO_L1[:32]  # OCR dropped part of the trailing '<' run
    assert short.endswith("<") and len(short) < LINE_LEN
    c1, _, changes = correct_by_field_type(short, ICAO_L2)
    assert c1 == ICAO_L1
    assert any(c["expected"] == "filler run repaired" for c in changes)


def test_filler_repair_long_line1():
    c1, _, changes = correct_by_field_type(ICAO_L1 + "<<<", ICAO_L2)
    assert c1 == ICAO_L1 and changes[0]["expected"] == "filler run repaired"


def test_filler_repair_line2_run():
    # personal-number filler run is one character short; check digits are untouched
    broken = ICAO_L2[:37] + ICAO_L2[38:]
    assert len(broken) == LINE_LEN - 1
    _, c2, changes = correct_by_field_type(ICAO_L1, broken)
    assert c2 == ICAO_L2
    assert any("filler" in c["expected"] for c in changes)


def test_bad_check_digit_is_never_auto_corrected():
    bad = ICAO_L2[:9] + "7" + ICAO_L2[10:]  # wrong digit in a numeric slot: must be left alone
    c1, c2, changes = correct_by_field_type(ICAO_L1, bad)
    assert c2 == bad and changes == []
    assert not parse_td3(c1, c2).all_checks_valid


def test_wrong_data_digit_is_not_laundered_by_correction():
    bad = ICAO_L2[:13] + "749812" + ICAO_L2[19:]  # month altered 08 -> 98: digits only, nothing to correct
    _, c2, changes = correct_by_field_type(ICAO_L1, bad)
    assert c2 == bad and changes == []
    by = {c.name: c for c in parse_td3(ICAO_L1, c2).checks}
    assert not by["date_of_birth"].valid
