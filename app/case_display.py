"""Shared display semantics; screening signals remain separate from staff decisions."""
from .models import Case
from .extensions import db
from sqlalchemy import func, or_

STATUS_LABELS = {'collecting': 'กำลังซักประวัติ', 'ready': 'ข้อมูลพร้อมตรวจ',
                 'escalated': 'รอประเมินโดยเจ้าหน้าที่', 'closed': 'ปิดเคส'}
URGENCY_LABELS = {'pending': 'ยังไม่ระบุ', 'routine': 'ทั่วไป', 'soon': 'ควรตรวจเร็ว',
                  'urgent': 'เร่งด่วน', 'emergency': 'ฉุกเฉิน'}


def current_review(case):
    event = next((e for e in reversed(getattr(case, 'audit_events', []))
                  if e.action == 'clinical_review_updated'), None)
    if not event:
        return None
    detail = event.detail or {}
    # Old reviews remain visible but cannot authorize appointments. New patient
    # information invalidates the decision until staff explicitly reviews it again.
    patient_ids = [m.id for m in case.messages if m.role == 'patient']
    if detail.get('patient_message_ids') != patient_ids:
        return None
    return {**detail, 'reviewed_at': event.created_at.isoformat()}


def dashboard_counts():
    counts = {s: 0 for s in STATUS_LABELS}
    counts.update(dict(db.session.execute(db.select(Case.status, func.count())
                                         .group_by(Case.status)).all()))
    counts['total'] = sum(counts.values())
    counts['urgent'] = db.session.scalar(db.select(func.count()).select_from(Case).where(
        Case.status != 'closed', or_(Case.status == 'escalated',
            Case.rule_urgency.in_(['urgent', 'emergency']),
            Case.ai_urgency_suggestion.in_(['urgent', 'emergency']),
            Case.clinician_urgency.in_(['urgent', 'emergency'])))) or 0
    return counts
