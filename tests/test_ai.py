from types import SimpleNamespace
from datetime import datetime, timezone

import openai

from app.ai import _fallback, generate_interview_turn
from app.extensions import db
from app.models import Case, Message
from app.prompts import PROMPT_VERSION, SYSTEM_PROMPT
from app.schemas import ClinicalSummary, InterviewTurn


def test_ai_prompt_analyzes_every_turn_without_prescribing_treatment():
    assert PROMPT_VERSION == "thai-intake-v3.0"
    assert "วิเคราะห์คำตอบล่าสุดของผู้ใช้ทุกข้อความ" in SYSTEM_PROMPT
    assert "suggested_care_pathway" in SYSTEM_PROMPT
    assert "ห้ามสั่งยา" in SYSTEM_PROMPT
    assert "กำหนดวิธีรักษา" in SYSTEM_PROMPT


def test_openai_structured_output_path(app, monkeypatch):
    parsed = InterviewTurn(
        assistant_message="อาการเริ่มเมื่อไรครับ",
        status="collecting",
        urgency_suggestion="routine",
        summary=ClinicalSummary(
            chief_complaint="ปวดท้อง",
            onset_and_course="ยังไม่ได้ข้อมูล",
            severity_and_impact="ยังไม่ได้ข้อมูล",
            associated_symptoms=[],
            relevant_history=[],
            current_medications=[],
            allergies=[],
            pregnancy_context="not_pregnant",
            patient_concerns="ยังไม่ได้ข้อมูล",
            missing_critical_information=["เวลาเริ่มอาการ"],
        ),
        red_flags_reported=[],
        remaining_questions=["เวลาเริ่มอาการ"],
    )

    class FakeResponses:
        def parse(self, **kwargs):
            assert kwargs["store"] is False
            assert kwargs["text_format"] is InterviewTurn
            assert kwargs["model"] == "gpt-test"
            return SimpleNamespace(output_parsed=parsed, _request_id="req_test")

    class FakeOpenAI:
        def __init__(self, **kwargs):
            assert kwargs["api_key"] == "sk-test"
            self.responses = FakeResponses()

    monkeypatch.setattr(openai, "OpenAI", FakeOpenAI)
    app.config.update(AI_PROVIDER="openai", OPENAI_API_KEY="sk-test", OPENAI_MODEL="gpt-test")

    with app.app_context():
        case = Case(
            reference="MPK-TESTAI",
            token_hash="x" * 64,
            age_group="18-39",
            sex_at_birth="female",
            pregnancy_status="not_pregnant",
            chief_complaint="ปวดท้อง",
            consent_version="test",
            consent_at=datetime.now(timezone.utc),
        )
        db.session.add(case)
        db.session.add(Message(case=case, role="patient", content="ปวดท้อง"))
        db.session.flush()
        result = generate_interview_turn(case)
        assert result.provider == "openai"
        assert result.request_id == "req_test"
        assert result.turn.assistant_message == "อาการเริ่มเมื่อไรครับ"


def test_gemini_structured_output_path(app, monkeypatch):
    parsed = InterviewTurn(
        assistant_message="มีไข้ร่วมด้วยหรือไม่ครับ",
        status="collecting",
        urgency_suggestion="routine",
        summary=ClinicalSummary(
            chief_complaint="ปวดท้อง",
            onset_and_course="เริ่มวันนี้",
            severity_and_impact="ยังไม่ได้ข้อมูล",
            associated_symptoms=[],
            relevant_history=[],
            current_medications=[],
            allergies=[],
            pregnancy_context="not_pregnant",
            patient_concerns="ยังไม่ได้ข้อมูล",
            missing_critical_information=["อาการร่วม"],
        ),
        red_flags_reported=[],
        remaining_questions=["อาการร่วม"],
    )

    class FakeCompletions:
        def parse(self, **kwargs):
            assert kwargs["model"] == "gemini-test"
            assert kwargs["response_format"] is InterviewTurn
            assert len(kwargs["messages"]) == 2
            message = SimpleNamespace(parsed=parsed)
            return SimpleNamespace(
                choices=[SimpleNamespace(message=message)], _request_id="gemini_req_test"
            )

    class FakeOpenAI:
        def __init__(self, **kwargs):
            assert kwargs["timeout"] == 90.0
            assert kwargs["max_retries"] == 0
            assert kwargs["api_key"] == "gemini-key-test"
            assert kwargs["base_url"] == "https://generativelanguage.googleapis.com/v1beta/openai/"
            self.beta = SimpleNamespace(
                chat=SimpleNamespace(completions=FakeCompletions())
            )

    monkeypatch.setattr(openai, "OpenAI", FakeOpenAI)
    app.config.update(
        AI_PROVIDER="gemini",
        GEMINI_API_KEY="gemini-key-test",
        GEMINI_MODEL="gemini-test",
        GEMINI_BASE_URL="https://generativelanguage.googleapis.com/v1beta/openai/",
    )

    with app.app_context():
        case = Case(
            reference="MPK-TESTGEMINI",
            token_hash="x" * 64,
            age_group="18-39",
            sex_at_birth="female",
            pregnancy_status="not_pregnant",
            chief_complaint="ปวดท้อง",
            consent_version="test",
            consent_at=datetime.now(timezone.utc),
        )
        db.session.add(case)
        db.session.add(Message(case=case, role="patient", content="ปวดท้อง"))
        db.session.flush()
        result = generate_interview_turn(case)
        assert result.provider == "gemini"
        assert result.request_id == "gemini_req_test"
        assert result.turn.assistant_message == "มีไข้ร่วมด้วยหรือไม่ครับ"


def test_gemini_without_key_uses_safe_fallback(app):
    app.config.update(AI_PROVIDER="gemini", GEMINI_API_KEY="")
    with app.app_context():
        case = Case(
            reference="MPK-TESTNO-GEMINI",
            token_hash="x" * 64,
            age_group="18-39",
            sex_at_birth="female",
            pregnancy_status="not_pregnant",
            chief_complaint="ปวดท้อง",
            consent_version="test",
            consent_at=datetime.now(timezone.utc),
        )
        db.session.add(case)
        db.session.add(Message(case=case, role="patient", content="ปวดท้อง"))
        db.session.flush()
        result = generate_interview_turn(case)
        assert result.provider == "safe_fallback"
        assert result.error_code == "provider_disabled"


def test_fallback_explains_rate_limit_without_exposing_provider_details(app):
    with app.app_context():
        case = Case(
            reference="MPK-TESTRATE",
            token_hash="x" * 64,
            age_group="18-39",
            sex_at_birth="female",
            pregnancy_status="not_pregnant",
            chief_complaint="ปวดท้อง",
            consent_version="test",
            consent_at=datetime.now(timezone.utc),
        )
        db.session.add(case)
        db.session.add(Message(case=case, role="patient", content="ปวดท้อง"))
        db.session.flush()
        result = _fallback(case, "RateLimitError")
        assert "ถึงขีดจำกัด" in result.turn.assistant_message
        assert "API key นี้" in result.turn.assistant_message
