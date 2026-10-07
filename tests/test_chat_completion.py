import pytest

from app.extensions import db
from app.models import Case, Message
from .conftest import create_case
from .test_appointments import calendar, book_form


def test_completed_case_booking_locks_one_slot_and_returns_receipt(client, app, calendar):
    from app.appointments import Appointment, AppointmentSlot, AppointmentRequest
    case = create_case(client, 'ข้อมูลสมมติ: ปวดศีรษะเล็กน้อย').json
    with app.app_context():
        db.session.get(Case, case['id']).status = 'ready'
        other_slot = db.session.scalar(db.select(AppointmentSlot).where(
            AppointmentSlot.doctor_id == calendar[1], AppointmentSlot.id != calendar[0],
            AppointmentSlot.state == 'free').order_by(AppointmentSlot.starts_at)).id
        db.session.commit()
    assert client.post('/appointments/book', data=book_form(client, calendar[0])).status_code == 303
    assert client.post('/appointments/book', data=book_form(client, other_slot)).status_code == 303
    result = client.get('/api/cases/'+case['id'], headers={'X-Case-Token':case['token']}).json
    receipt = result['appointment_request']
    assert receipt['appointment_status'] == 'booked'
    assert receipt['appointment_reference'].startswith('APT-')
    assert receipt['doctor'] and receipt['time']
    assert not result['chat']['can_send']
    page = client.get('/appointments').get_data(as_text=True)
    assert receipt['appointment_reference'] in page and 'name="slot_id"' not in page
    with app.app_context():
        assert db.session.scalar(db.select(db.func.count()).select_from(Appointment)) == 1
        assert db.session.get(AppointmentSlot, calendar[0]).state == 'booked'
        assert db.session.get(AppointmentSlot, other_slot).state == 'free'
        assert db.session.get(AppointmentRequest, case['id']).status == 'confirmed'


def test_ready_case_ends_chat_and_rejects_further_answers(client, app):
    case = create_case(client).json
    with app.app_context():
        record = db.session.get(Case, case['id'])
        record.status = 'ready'
        db.session.add(Message(case=record, role='assistant', content='มีอาการอื่นร่วมด้วยไหมครับ'))
        db.session.commit()
    headers = {'X-Case-Token': case['token']}
    assert not client.get(f"/api/cases/{case['id']}", headers=headers).json['chat']['can_send']
    response = client.post(f"/api/cases/{case['id']}/messages", headers=headers,
                           json={'content': 'ไม่มีอาการอื่นร่วมด้วย'})
    assert response.status_code == 409
    assert not any(m['content'] == 'ไม่มีอาการอื่นร่วมด้วย' for m in response.json['messages'])


def test_ready_ai_output_does_not_ask_unanswerable_question(client, app, monkeypatch):
    from app.ai import _fallback
    import app.routes as routes

    def ready_result(case):
        result = _fallback(case, 'provider_disabled')
        result.turn.status = 'ready'
        result.turn.remaining_questions = []
        result.turn.summary.missing_critical_information = []
        result.turn.assistant_message = 'มีอาการอื่นร่วมด้วยไหมครับ'
        return result

    monkeypatch.setattr(routes, 'generate_interview_turn', ready_result)
    response = create_case(client)
    assert response.json['status'] == 'ready'
    assert 'ซักประวัติเสร็จแล้ว' in response.json['messages'][-1]['content']
    assert 'มีอาการอื่นร่วมด้วยไหม' not in response.json['messages'][-1]['content']
    assert not response.json['chat']['can_send']


def test_premature_ai_ready_with_missing_info_keeps_question_open(client, monkeypatch):
    from app.ai import _fallback
    import app.routes as routes
    def incomplete(case):
        result = _fallback(case, 'provider_disabled')
        result.turn.status = 'ready'
        return result
    monkeypatch.setattr(routes, 'generate_interview_turn', incomplete)
    response = create_case(client)
    assert response.json['status'] == 'collecting'
    assert response.json['chat']['can_send']
    assert 'อาการนี้เริ่มเมื่อไร' in response.json['messages'][-1]['content']


def test_turn_limit_with_missing_critical_info_requires_staff(client, monkeypatch):
    from app.ai import _fallback
    import app.routes as routes
    def incomplete(case):
        result = _fallback(case, 'provider_disabled')
        result.turn.status = 'collecting'
        result.turn.remaining_questions = ['ยังไม่ได้ระดับความรุนแรง']
        result.turn.summary.missing_critical_information = ['ระดับความรุนแรง']
        return result
    monkeypatch.setattr(routes, 'generate_interview_turn', incomplete)
    case = create_case(client).json
    for _ in range(11):
        response = client.post(f"/api/cases/{case['id']}/messages", headers={'X-Case-Token':case['token']}, json={'content':'ยังไม่ทราบ'})
    assert response.json['status'] == 'escalated'
    assert not response.json['chat']['can_send']
    assert response.json['appointment_referral']['state'] == 'review'


def test_urgent_rule_does_not_wait_for_ai(client, monkeypatch):
    import app.routes as routes
    def should_not_call(_case):
        raise AssertionError('Urgent care must not wait for AI')
    monkeypatch.setattr(routes, 'generate_interview_turn', should_not_call)
    response = create_case(client, 'ปวดท้องมากจนทนไม่ไหว 9/10')
    assert response.json['status'] == 'escalated'
    assert not response.json['chat']['can_send']


@pytest.mark.parametrize('status,rule,clinician', [
    ('escalated', 'pending', None), ('closed', 'pending', None),
    ('collecting', 'emergency', None), ('collecting', 'pending', 'emergency'),
])
def test_blocked_chat_returns_reason_without_discarding_answer(client, app, status, rule, clinician):
    case = create_case(client).json
    with app.app_context():
        record = db.session.get(Case, case['id'])
        record.status, record.rule_urgency, record.clinician_urgency = status, rule, clinician
        original_count = len(record.messages)
        db.session.commit()
    response = client.post(f"/api/cases/{case['id']}/messages",
                           headers={'X-Case-Token': case['token']}, json={'content': 'คำตอบที่ยังไม่ได้ส่ง'})
    assert response.status_code == 409
    assert response.json['error'] == response.json['chat']['reason']
    assert not response.json['chat']['can_send']
    assert len(response.json['messages']) == original_count
