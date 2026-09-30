from typing import Literal

from pydantic import BaseModel, Field


class ClinicalSummary(BaseModel):
    chief_complaint: str = Field(description="อาการสำคัญตามคำผู้ป่วยโดยไม่วินิจฉัย")
    onset_and_course: str = Field(description="เริ่มเมื่อไรและเปลี่ยนแปลงอย่างไร")
    symptom_location_and_character: str = Field(
        default="ยังไม่ได้ข้อมูล", description="ตำแหน่ง ลักษณะ และการร้าวของอาการเมื่อเกี่ยวข้อง"
    )
    severity_and_impact: str = Field(description="ความรุนแรงและผลต่อกิจวัตร")
    aggravating_and_relieving_factors: list[str] = Field(default_factory=list)
    associated_symptoms: list[str] = Field(default_factory=list)
    relevant_history: list[str] = Field(default_factory=list)
    past_procedures_or_hospitalizations: list[str] = Field(default_factory=list)
    current_medications: list[str] = Field(default_factory=list)
    allergies: list[str] = Field(default_factory=list)
    family_history: list[str] = Field(default_factory=list)
    social_and_exposure_history: list[str] = Field(default_factory=list)
    travel_and_sick_contacts: list[str] = Field(default_factory=list)
    vital_signs_if_known: list[str] = Field(default_factory=list)
    pregnancy_context: str = "ยังไม่ได้ข้อมูล"
    functional_status: str = "ยังไม่ได้ข้อมูล"
    patient_concerns: str = "ยังไม่ได้ข้อมูล"
    patient_goal_or_expected_care: str = Field(
        default="ยังไม่ได้ข้อมูล", description="สิ่งที่ผู้ใช้ต้องการจากการมารับบริการตามที่กล่าวไว้"
    )
    latest_response_analysis: str = Field(
        default="ยังไม่ได้ข้อมูลเพียงพอ",
        description="วิเคราะห์คำตอบล่าสุดอย่างกระชับโดยไม่วินิจฉัยหรือแสดงกระบวนการคิดภายใน",
    )
    care_level_reasoning: str = Field(
        default="ต้องให้บุคลากรตรวจข้อมูลเพิ่มเติม",
        description="เหตุผลสั้นจากข้อเท็จจริงที่สนับสนุนระดับความเร่งด่วน",
    )
    suggested_care_pathway: Literal[
        "emergency_now",
        "same_day_assessment",
        "appointment_soon",
        "routine_follow_up",
        "clinician_review_required",
    ] = "clinician_review_required"
    missing_critical_information: list[str] = Field(default_factory=list)


class InterviewTurn(BaseModel):
    assistant_message: str = Field(
        description="คำถามภาษาไทยหนึ่งคำถาม ห้ามวินิจฉัย แนะนำยา หรือรับรองว่าปลอดภัย"
    )
    status: Literal["collecting", "ready", "escalate_review"]
    urgency_suggestion: Literal["routine", "soon", "urgent"]
    summary: ClinicalSummary
    red_flags_reported: list[str]
    remaining_questions: list[str]
