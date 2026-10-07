import pytest

from app.extensions import db
from app.models import Case, Message
from .conftest import create_case


def test_ready_case_accepts_answer_to_previous_question(client, app):
    case = create_case(client).json
    with app.app_context():
        record = db.session.get(Case, case['id'])
        record.status = 'ready'
        db.session.add(Message(case=record, role='assistant', content='มีอาการอื่นร่วมด้วยไหมครับ'))
        db.session.commit()
    headers = {'X-Case-Token': case['token']}
    assert client.get(f"/api/cases/{case['id']}", headers=headers).json['chat']['can_send']
    response = client.post(f"/api/cases/{case['id']}/messages", headers=headers,
                           json={'content': 'ไม่มีอาการอื่นร่วมด้วย'})
    assert response.status_code == 200
    assert any(m['content'] == 'ไม่มีอาการอื่นร่วมด้วย' for m in response.json['messages'])


def test_ready_ai_output_does_not_ask_unanswerable_question(client, app, monkeypatch):
    from app.ai import _fallback
    import app.routes as routes

    def ready_result(case):
        result = _fallback(case, 'provider_disabled')
        result.turn.status = 'ready'
        result.turn.assistant_message = 'มีอาการอื่นร่วมด้วยไหมครับ'
        return result

    monkeypatch.setattr(routes, 'generate_interview_turn', ready_result)
    case = create_case(client).json
    headers = {'X-Case-Token': case['token']}
    for _ in range(7):
        response = client.post(f"/api/cases/{case['id']}/messages", headers=headers,
                               json={'content': 'ไม่มีข้อมูลเพิ่มเติม'})
        assert response.status_code == 200
    assert response.json['status'] == 'ready'
    assert 'ข้อมูลเบื้องต้นพร้อม' in response.json['messages'][-1]['content']
    assert response.json['chat']['can_send']


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
