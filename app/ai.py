from __future__ import annotations

from dataclasses import dataclass
import json
import logging
import time

import httpx
from pydantic import ValidationError

from flask import current_app

from .credentials import get_api_key
from .models import Case
from .prompts import SYSTEM_PROMPT
from .schemas import ClinicalSummary, InterviewTurn

logger = logging.getLogger(__name__)

FALLBACK_NOTICES = {
    "provider_disabled": "AI ไม่พร้อมใช้งาน เพราะยังไม่มี API key ที่ใช้งานได้ ผู้ดูแลควรตรวจหน้า ตั้งค่า AI",
    "AuthenticationError": "API key ไม่ถูกต้องหรือถูกยกเลิก ผู้ดูแลควรเปลี่ยน key ใหม่",
    "PermissionDeniedError": "บัญชี API นี้ไม่มีสิทธิ์ใช้ model ที่ตั้งไว้ ผู้ดูแลควรตรวจสิทธิ์บัญชีหรือเปลี่ยน model",
    "NotFoundError": "ไม่พบ model ที่ตั้งไว้ ผู้ดูแลควรตรวจค่า OPENAI_MODEL ใน Render",
    "RateLimitError": "API key นี้ถึงขีดจำกัดการใช้งาน ผู้ดูแลสามารถเปลี่ยน key ใหม่ในหน้า ตั้งค่า AI",
    "APITimeoutError": "AI ตอบช้ากว่ากำหนด ระบบจึงใช้คำถามสำรองชั่วคราว",
    "APIConnectionError": "เชื่อมต่อ AI ไม่สำเร็จชั่วคราว ระบบจึงใช้คำถามสำรอง",
    "InternalServerError": "บริการ AI ขัดข้องชั่วคราว ระบบจึงใช้คำถามสำรอง และจะลอง AI อีกครั้งเมื่อคุณตอบข้อความถัดไป",
    "invalid_response": "AI ส่งคำตอบไม่ครบหรือรูปแบบไม่ถูกต้อง ระบบจึงใช้คำถามสำรองชั่วคราว",
    "empty_or_refused": "AI ไม่ส่งคำตอบที่ใช้งานได้ ระบบจึงใช้คำถามสำรองชั่วคราว",
}


@dataclass
class AIResult:
    turn: InterviewTurn
    provider: str
    request_id: str | None = None
    error_code: str | None = None


def _fallback(case: Case, error_code: str | None = None) -> AIResult:
    patient_messages = [message.content for message in case.messages if message.role == "patient"]
    questions = [
        "อาการนี้เริ่มเมื่อไร เกิดขึ้นทันทีหรือค่อย ๆ เป็น และตอนนี้ดีขึ้นหรือแย่ลงอย่างไรครับ",
        "อาการอยู่บริเวณใด มีลักษณะอย่างไร และมีร้าวหรือกระจายไปที่อื่นไหมครับ",
        "ถ้าให้คะแนนความรุนแรงจาก 0 ถึง 10 ตอนนี้อยู่ที่เท่าไร และกระทบการกิน นอน เดิน หรือทำงานอย่างไรครับ",
        "มีอาการอื่นร่วมด้วยหรือสัญญาณผิดปกติอะไรที่สังเกตเห็นไหมครับ",
        "มีอะไรทำให้อาการเริ่มขึ้น แย่ลง หรือดีขึ้นบ้างครับ",
        "มีโรคประจำตัว เคยผ่าตัด นอนโรงพยาบาล หรือเคยมีอาการแบบนี้มาก่อนไหมครับ",
        "ปัจจุบันใช้ยา ยาที่เพิ่งรับประทาน หรืออาหารเสริมอะไร และเคยแพ้ยาหรืออาหารอย่างไรบ้างครับ",
        "สูบบุหรี่ ดื่มแอลกอฮอล์ มีการสัมผัสสาร สัตว์ ผู้ป่วย หรือเดินทางไม่นานมานี้ที่เกี่ยวข้องไหมครับ",
        "มีประวัติสุขภาพในครอบครัว บริบทการตั้งครรภ์ หรือข้อมูลประจำเดือนที่เกี่ยวข้องกับอาการนี้ไหมครับ",
        "มีค่าวัดไข้ ชีพจร ความดัน ออกซิเจน หรือข้อมูลสำคัญอื่น และกังวลเรื่องใดมากที่สุดครับ",
    ]
    answered = max(0, len(patient_messages) - 1)
    ready = answered >= len(questions)
    if ready:
        assistant_message = (
            "ขอบคุณครับ ข้อมูลเบื้องต้นพร้อมให้บุคลากรทางการแพทย์ตรวจแล้ว "
            "โปรดรอการประเมิน และหากอาการรุนแรงขึ้นให้โทร 1669"
        )
    else:
        assistant_message = questions[answered]
        if error_code:
            notice = FALLBACK_NOTICES.get(
                error_code, "AI ไม่พร้อมใช้งาน ระบบจึงใช้คำถามสำรองชั่วคราว"
            )
            assistant_message = (
                f"ขณะนี้ {notice}: "
                f"{assistant_message}"
            )
    summary = ClinicalSummary(
        chief_complaint=case.chief_complaint,
        onset_and_course="ดูรายละเอียดจากบทสนทนา",
        symptom_location_and_character="ดูรายละเอียดจากบทสนทนา",
        severity_and_impact="ดูรายละเอียดจากบทสนทนา",
        associated_symptoms=[],
        relevant_history=[],
        current_medications=[],
        allergies=[],
        pregnancy_context=case.pregnancy_status,
        patient_concerns="ยังไม่ได้สรุปโดย AI",
        patient_goal_or_expected_care="ยังไม่ได้ข้อมูล",
        latest_response_analysis="AI ไม่พร้อมใช้งาน จึงยังไม่มีผลวิเคราะห์จากโมเดล",
        care_level_reasoning="ใช้กฎความปลอดภัยและรอให้บุคลากรตรวจ",
        suggested_care_pathway="clinician_review_required",
        missing_critical_information=[] if ready else questions[answered:],
    )
    return AIResult(
        turn=InterviewTurn(
            assistant_message=assistant_message,
            status="ready" if ready else "collecting",
            urgency_suggestion="routine",
            summary=summary,
            red_flags_reported=[],
            remaining_questions=[] if ready else questions[answered:],
        ),
        provider="safe_fallback",
        error_code=error_code,
    )


def _request_payload(case: Case) -> dict:
    transcript = [
        {"role": message.role, "content": message.content}
        for message in case.messages
        if message.role in {"patient", "assistant"}
    ]
    return {
        "case_reference": case.reference,
        "demographics": {
            "age_group": case.age_group,
            "sex_at_birth": case.sex_at_birth,
            "pregnancy_status": case.pregnancy_status,
        },
        "transcript": transcript,
        "patient_turn_count": len([item for item in transcript if item["role"] == "patient"]),
        "minimum_patient_turns": 8,
        "maximum_patient_turns": 12,
        "instruction": (
            "วิเคราะห์คำตอบล่าสุดร่วมกับ transcript ทั้งหมด อัปเดตทุกช่องใน summary "
            "ระบุเส้นทางเข้ารับบริการและเหตุผลจากข้อเท็จจริงโดยไม่วินิจฉัยหรือเสนอวิธีรักษา "
            "จากนั้นถามต่อเพียงหนึ่งคำถามที่สำคัญที่สุด ห้ามขอข้อมูลระบุตัวบุคคล "
            "และห้ามจบก่อนข้อมูลสำคัญครบ"
        ),
    }


def _gemini_turn(case: Case) -> AIResult:
    # Use Google's native endpoint and validate the JSON locally. This avoids
    # translating our schema through the OpenAI compatibility layer.
    model = current_app.config["GEMINI_MODEL"].removeprefix("models/")
    endpoint = "https://generativelanguage.googleapis.com/v1beta/models/"
    payload = {
        "systemInstruction": {"parts": [{"text": SYSTEM_PROMPT}]},
        "contents": [{"role": "user", "parts": [{"text": json.dumps(
            _request_payload(case), ensure_ascii=False, separators=(",", ":")
        )}]}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "responseJsonSchema": InterviewTurn.model_json_schema(),
        },
    }
    deadline = time.monotonic() + 90.0
    with httpx.Client() as client:
        for attempt in range(2):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return _fallback(case, "APITimeoutError")
            try:
                response = client.post(
                    endpoint + model + ":generateContent",
                    headers={"x-goog-api-key": get_api_key("gemini")},
                    json=payload,
                    timeout=httpx.Timeout(remaining, connect=min(10.0, remaining)),
                )
            except httpx.TimeoutException:
                return _fallback(case, "APITimeoutError")
            except httpx.RequestError:
                return _fallback(case, "APIConnectionError")
            if response.is_success:
                break
            code = {
                401: "AuthenticationError", 403: "PermissionDeniedError",
                404: "NotFoundError", 429: "RateLimitError",
            }.get(response.status_code, "InternalServerError" if response.status_code >= 500 else "BadRequestError")
            # Log status only: error bodies can contain keys or patient text.
            logger.warning("Gemini native request failed: %s (HTTP %s)", code, response.status_code)
            if response.status_code >= 500 and attempt == 0 and deadline - time.monotonic() > 1.0:
                time.sleep(1.0)
                continue
            return _fallback(case, code)
    try:
        data = response.json()
        candidates = data.get("candidates", [])
        if not candidates or candidates[0].get("finishReason") != "STOP":
            return _fallback(case, "empty_or_refused")
        parts = candidates[0].get("content", {}).get("parts", [])
        text = "".join(part.get("text", "") for part in parts if not part.get("thought"))
        parsed = InterviewTurn.model_validate_json(text)
    except (ValueError, ValidationError, TypeError, AttributeError):
        return _fallback(case, "invalid_response")
    if not parsed.assistant_message.strip():
        return _fallback(case, "empty_or_refused")
    return AIResult(
        turn=parsed,
        provider="gemini",
        request_id=data.get("responseId"),
    )


def generate_interview_turn(case: Case) -> AIResult:
    provider = current_app.config["AI_PROVIDER"]
    if provider == "gemini":
        api_key = get_api_key("gemini")
        if not api_key or api_key.startswith("CHANGE_ME"):
            return _fallback(case, "provider_disabled")
        try:
            return _gemini_turn(case)
        except Exception as exc:  # Never log patient text, key or request payload.
            logger.warning("Gemini request failed: %s", type(exc).__name__)
            return _fallback(case, type(exc).__name__)

    api_key = get_api_key("openai")
    if provider != "openai" or not api_key or api_key.startswith("CHANGE_ME"):
        return _fallback(case, "provider_disabled")

    try:
        from openai import OpenAI

        client = OpenAI(api_key=api_key, timeout=25.0, max_retries=1)
        response = client.responses.parse(
            model=current_app.config["OPENAI_MODEL"],
            input=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": json.dumps(
                        _request_payload(case), ensure_ascii=False, separators=(",", ":")
                    ),
                },
            ],
            text_format=InterviewTurn,
            max_output_tokens=1800,
            store=False,
        )
        if response.output_parsed is None:
            return _fallback(case, "empty_or_refused")
        return AIResult(
            turn=response.output_parsed,
            provider="openai",
            request_id=getattr(response, "_request_id", None),
        )
    except Exception as exc:  # Never log patient text or the request payload.
        logger.warning("AI request failed: %s", type(exc).__name__)
        return _fallback(case, type(exc).__name__)
