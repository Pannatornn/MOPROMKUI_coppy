from types import SimpleNamespace
from datetime import datetime, timezone

import openai
import json
import httpx
import pytest
import app.ai as ai_module

from app.ai import _fallback, generate_interview_turn
from app.extensions import db
from app.models import Case, Message
from app.prompts import PROMPT_VERSION, SYSTEM_PROMPT
from app.schemas import ClinicalSummary, InterviewTurn


def test_ai_prompt_analyzes_every_turn_without_prescribing_treatment():
    assert PROMPT_VERSION == "thai-intake-v3.1"
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

    native_client = httpx.Client

    def handler(request):
        assert str(request.url) == "https://generativelanguage.googleapis.com/v1beta/models/gemini-test:generateContent"
        assert request.headers["x-goog-api-key"] == "gemini-key-test"
        payload = json.loads(request.content)
        assert payload["systemInstruction"]["parts"][0]["text"] == SYSTEM_PROMPT
        assert payload["generationConfig"]["responseJsonSchema"] == InterviewTurn.model_json_schema()
        assert "transcript" in payload["contents"][0]["parts"][0]["text"]
        assert 0 < request.extensions["timeout"]["read"] <= 90
        return httpx.Response(200, json={
            "responseId": "gemini_req_test",
            "candidates": [{"finishReason": "STOP", "content": {"parts": [
                {"text": parsed.model_dump_json()}
            ]}}],
        })

    monkeypatch.setattr(ai_module.httpx, "Client", lambda: native_client(transport=httpx.MockTransport(handler)))
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


@pytest.mark.parametrize(
    "status,second_fails,elapsed,expected_calls,expected_provider",
    [(500, False, 2, 2, "gemini"),
     (503, False, 2, 2, "gemini"),
     (503, True, 2, 2, "safe_fallback"),
     (429, False, 2, 1, "safe_fallback"),
     (401, False, 2, 1, "safe_fallback"),
     (500, False, 90, 1, "safe_fallback")],
)
def test_gemini_retry_is_bounded_and_only_for_server_errors(
    app, monkeypatch, status, second_fails, elapsed, expected_calls, expected_provider
):
    calls = []
    parsed = InterviewTurn(
        assistant_message="คำถามทดสอบ", status="collecting", urgency_suggestion="routine",
        summary=ClinicalSummary(chief_complaint="ทดสอบ", onset_and_course="วันนี้",
                                severity_and_impact="เล็กน้อย"),
        red_flags_reported=[], remaining_questions=["คำถามทดสอบ"],
    )
    native_client = httpx.Client

    def handler(request):
        calls.append(request)
        if len(calls) == 1 or second_fails:
            return httpx.Response(status, json={"error": {"message": "secret-patient-text"}})
        return httpx.Response(200, json={"candidates": [{
            "finishReason": "STOP", "content": {"parts": [{"text": parsed.model_dump_json()}]}
        }]})

    times = iter([0, 0, elapsed, elapsed + 1])
    monkeypatch.setattr(ai_module, "time", SimpleNamespace(monotonic=lambda: next(times), sleep=lambda seconds: None))
    monkeypatch.setattr(ai_module.httpx, "Client", lambda: native_client(transport=httpx.MockTransport(handler)))
    app.config.update(AI_PROVIDER="gemini", GEMINI_API_KEY="synthetic-key")
    with app.app_context():
        case = Case(reference="MPK-RETRY", chief_complaint="ทดสอบ", pregnancy_status="not_applicable")
        case.messages = [Message(role="patient", content="ข้อมูลสมมติ"),
                         Message(role="assistant", content="คำถามแรก"),
                         Message(role="patient", content="คำตอบถัดไป")]
        result = generate_interview_turn(case)
        assert len(calls) == expected_calls
        assert result.provider == expected_provider
        assert len(case.messages) == 3
        if status == 503 and not second_fails:
            assert result.model == "gemini-3.1-flash-lite"
        if expected_calls == 2:
            first = json.loads(calls[0].content)
            second = json.loads(calls[1].content)
            assert first["contents"] == second["contents"]
            if status == 503:
                assert "/gemini-3.1-flash-lite:generateContent" in str(calls[1].url)
                assert "responseJsonSchema" in second["generationConfig"]
            else:
                assert "responseJsonSchema" not in second["generationConfig"]
                assert "schema" in second["systemInstruction"]["parts"][-1]["text"]
            assert second["generationConfig"]["responseMimeType"] == "application/json"
            assert calls[1].extensions["timeout"]["read"] == 87.0
        if status == 503 and second_fails:
            assert "บริการ AI ขัดข้องชั่วคราว" in result.turn.assistant_message
            assert "ข้อความถัดไป" in result.turn.assistant_message


@pytest.mark.parametrize("response_data", [
    {"candidates": []},
    {"candidates": [{"finishReason": "SAFETY"}]},
    {"candidates": [{"finishReason": "MAX_TOKENS"}]},
    {"candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": "{}"}]}}]},
    {"candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": "not-json"}]}}]},
])
def test_gemini_invalid_or_blocked_output_uses_fallback(app, monkeypatch, response_data):
    native_client = httpx.Client
    monkeypatch.setattr(ai_module.httpx, "Client", lambda: native_client(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=response_data))))
    app.config.update(AI_PROVIDER="gemini", GEMINI_API_KEY="synthetic-key")
    with app.app_context():
        case = Case(reference="MPK-INVALID", chief_complaint="ทดสอบ", pregnancy_status="not_applicable")
        case.messages = [Message(role="patient", content="ข้อมูลสมมติ")]
        result = generate_interview_turn(case)
        assert result.provider == "safe_fallback"
        assert result.error_code in {"empty_or_refused", "invalid_response"}


def test_gemini_timeout_tries_fallback_with_remaining_budget(app, monkeypatch):
    native_client = httpx.Client
    calls = []
    parsed = InterviewTurn(
        assistant_message="คำถามทดสอบ", status="collecting", urgency_suggestion="routine",
        summary=ClinicalSummary(chief_complaint="ทดสอบ", onset_and_course="วันนี้", severity_and_impact="เล็กน้อย"),
        red_flags_reported=[], remaining_questions=[],
    )

    def handler(request):
        calls.append(request)
        if len(calls) == 1:
            raise httpx.ReadTimeout("synthetic timeout", request=request)
        return httpx.Response(200, json={"candidates": [{"finishReason": "STOP",
            "content": {"parts": [{"text": parsed.model_dump_json()}]}}]})

    times = iter([0, 0, 45, 45, 46, 46])
    monkeypatch.setattr(ai_module, "time", SimpleNamespace(monotonic=lambda: next(times)))
    monkeypatch.setattr(ai_module.httpx, "Client", lambda: native_client(transport=httpx.MockTransport(handler)))
    app.config.update(AI_PROVIDER="gemini", GEMINI_API_KEY="synthetic-key")
    with app.app_context():
        case = Case(reference="MPK-TIMEOUT", chief_complaint="ทดสอบ", pregnancy_status="not_applicable")
        case.messages = [Message(role="patient", content="ข้อมูลสมมติ")]
        result = generate_interview_turn(case)
        assert result.provider == "gemini"
        assert result.model == "gemini-3.1-flash-lite"
        assert len(calls) == 2
        assert [request.extensions["timeout"]["read"] for request in calls] == [45.0, 45.0]
        next_result = generate_interview_turn(case)
        assert next_result.provider == "gemini"
        assert next_result.model == "gemini-3.1-flash-lite"
        assert len(calls) == 3
        assert "/gemini-3.1-flash-lite:generateContent" in str(calls[2].url)
