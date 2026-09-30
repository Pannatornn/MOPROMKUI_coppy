import json
from pathlib import Path

from app.safety import ai_message_is_safe, find_red_flags, find_urgent_signals


TRIAGE_CASES = Path(__file__).parent / "fixtures" / "triage_cases.json"


def test_detects_emergency_thai_phrases():
    matches = find_red_flags("เจ็บแน่นหน้าอกและหายใจไม่ออก")
    assert {item["code"] for item in matches} == {"chest_pain", "severe_breathing"}


def test_ignores_simple_negation():
    assert find_red_flags("ไม่มีเจ็บแน่นหน้าอก อาการทั่วไปดี") == []


def test_negated_first_occurrence_does_not_hide_later_affirmed_occurrence():
    matches = find_red_flags("เมื่อเช้าไม่มีเจ็บแน่นหน้าอก แต่ตอนนี้เจ็บแน่นหน้าอกมาก")
    assert "chest_pain" in {item["code"] for item in matches}


def test_emergency_regression_corpus():
    cases = json.loads(TRIAGE_CASES.read_text(encoding="utf-8"))
    for case in cases:
        matches = find_red_flags(case["text"])
        codes = {item["code"] for item in matches}
        if case["level"] == "emergency":
            assert matches, f'{case["id"]} false negative: {case["text"]}'
            assert case["expected_code"] in codes, (
                f'{case["id"]} expected {case["expected_code"]}, got {sorted(codes)}'
            )
        else:
            assert not matches, f'{case["id"]} false positive {sorted(codes)}: {case["text"]}'


def test_detects_severe_pain_as_urgent_but_not_emergency():
    matches = find_urgent_signals("ปวดท้องมากจนทนไม่ไหว ระดับความปวด 9/10")
    assert {item["code"] for item in matches} == {"severe_pain", "high_pain_score"}


def test_ignores_non_severe_pain_phrases():
    assert find_urgent_signals("ปวดท้องไม่มาก พอทนได้") == []
    assert find_urgent_signals("ไม่ได้ปวดมาก แค่ตึงเล็กน้อย") == []


def test_blocks_diagnosis_and_medication_advice():
    assert not ai_message_is_safe("คุณเป็นโรคไมเกรน")
    assert not ai_message_is_safe("รับประทานยาแล้วรอดูอาการ")
    assert ai_message_is_safe("อาการเริ่มเมื่อไรครับ")
