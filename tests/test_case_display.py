import re
import pytest
from datetime import datetime, timezone
from app.case_display import dashboard_counts, current_review
from app.extensions import db
from app.models import Case, Message
from app.referrals import recommend_department
from .conftest import create_case
from .test_appointments import calendar


def login(client):
    client.get('/staff/login')
    with client.session_transaction() as session:
        csrf = session['_csrf_token']
    assert client.post('/staff/login', data={'csrf_token': csrf, 'username': 'nurse',
                      'password': 'correct-horse-battery'}).status_code == 302
    with client.session_transaction() as session:
        return session['_csrf_token']


def test_all_database_counts_not_just_latest_100(app, client):
    with app.app_context():
        for n in range(105):
            db.session.add(Case(reference=f'MPK-{n:08X}', token_hash='test', age_group='18-39',
                sex_at_birth='female', chief_complaint='ข้อมูลสมมติ', consent_version='test',
                consent_at=datetime.now(timezone.utc), status='collecting',
                rule_urgency='urgent' if n == 0 else 'pending'))
        db.session.flush()
        cases = db.session.scalars(db.select(Case).order_by(Case.reference)).all()
        cases[1].status = 'escalated'
        cases[2].status = 'ready'
        cases[3].status = 'closed'
        cases[3].rule_urgency = 'emergency'
        cases[4].clinician_urgency = 'urgent'
        cases[5].ai_urgency_suggestion = 'emergency'
        db.session.commit()
        counts = dashboard_counts()
        assert counts == {'collecting': 102, 'ready': 1, 'escalated': 1,
                          'closed': 1, 'total': 105, 'urgent': 4}
    login(client)
    page = client.get('/staff').get_data(as_text=True)
    assert re.search(r'data-count="total">105<', page)
    assert re.search(r'data-count="urgent">4<', page)
    assert page.count('class="case-code"') == 100
    assert 'อัปเดตข้อมูลแบบเรียลไทม์' not in page


def test_staff_decision_reaches_patient_and_controls_booking(app, client, calendar):
    case = create_case(client, 'ปวดท้องมากจนทนไม่ไหว').json
    staff = app.test_client()
    csrf = login(staff)
    form = {'csrf_token': csrf, 'urgency': 'soon', 'status': 'ready',
            'disposition': 'appointment', 'department': 'medicine',
            'guidance': 'ข้อมูลสมมติ: ประเมินแล้ว อนุมัตินัดในแผนกอายุรกรรม'}
    assert staff.post(f"/staff/cases/{case['id']}/review", data=form).status_code == 302
    result = client.get(f"/api/cases/{case['id']}", headers={'X-Case-Token': case['token']}).json
    assert result['staff_review']['guidance'] == form['guidance']
    assert result['urgency'] == 'urgent'  # preserve original screening evidence
    assert result['clinician_urgency'] == 'soon'
    assert result['appointment_referral']['department'] == 'medicine'
    assert result['appointment_referral']['source'] == 'staff'
    page = client.get('/appointments').get_data(as_text=True)
    assert 'นพ.นนทกร' in page and 'พญ.มินตรา' not in page
    # Closed interview cannot silently accept new answers or invalidate the review.
    response = client.post(f"/api/cases/{case['id']}/messages",
        headers={'X-Case-Token': case['token']}, json={'content': 'ข้อมูลเพิ่มเติม'})
    assert response.status_code == 409
    with app.app_context():
        record = db.session.get(Case, case['id'])
        db.session.add(Message(case=record, role='patient', content='ข้อมูลใหม่'))
        db.session.commit()
        assert current_review(record) is None
        assert recommend_department(record)['state'] == 'review'


def test_emergency_cannot_be_approved_for_routine_booking(app, client):
    case = create_case(client, 'หายใจไม่ออก').json
    staff = app.test_client()
    csrf = login(staff)
    form = {'csrf_token': csrf, 'urgency': 'routine', 'status': 'ready',
            'disposition': 'appointment', 'department': 'general', 'guidance': 'ข้อความทดสอบ'}
    assert staff.post(f"/staff/cases/{case['id']}/review", data=form).status_code == 400
    form.update(urgency='emergency', disposition='care', guidance='ข้อมูลสมมติ: ให้เข้ารับการดูแลทันที')
    assert staff.post(f"/staff/cases/{case['id']}/review", data=form).status_code == 302
    payload = client.get(f"/api/cases/{case['id']}", headers={'X-Case-Token': case['token']}).json
    assert payload['staff_review']['guidance'] == form['guidance']
    assert payload['appointment_referral']['state'] == 'emergency'
    assert 'name="slot_id"' not in client.get('/appointments').get_data(as_text=True)


def test_review_auth_validation_and_closed_referral(app, client):
    case = create_case(client, 'สิวบนหน้า').json
    url = f"/staff/cases/{case['id']}/review"
    assert client.post(url, data={}).status_code == 401
    csrf = login(client)
    form = {'csrf_token': csrf, 'urgency': 'routine', 'status': 'ready',
            'disposition': 'appointment', 'department': 'invalid', 'guidance': 'ข้อมูลสมมติ'}
    assert client.post(url, data=form).status_code == 400
    form.update(department='skin', guidance='')
    assert client.post(url, data=form).status_code == 400
    form.update(disposition='review_only', status='closed')
    assert client.post(url, data=form).status_code == 302
    with app.app_context():
        assert recommend_department(db.session.get(Case, case['id']))['state'] == 'closed'


@pytest.mark.parametrize('complaint,urgency,department,expected', [
    ('ข้อมูลสมมติ: ปวดท้องเล็กน้อย', 'urgent', 'gynecology', 'ไม่ตรงกับการอนุมัติคิวนัดปกติ'),
    ('ข้อมูลสมมติ: ปวดท้องเล็กน้อย', 'routine', '', 'กรุณาเลือกแผนกสำหรับการนัด'),
    ('ข้อมูลสมมติ: หายใจไม่ออก', 'routine', 'general', 'กฎคัดกรองพบสัญญาณที่อาจฉุกเฉิน'),
])
def test_review_validation_keeps_form_and_explains_actual_reason(app, client, complaint,
                                                               urgency, department, expected):
    case = create_case(client, complaint).json
    csrf = login(client)
    form = {'csrf_token': csrf, 'urgency': urgency, 'department': department,
            'disposition': 'appointment', 'guidance': 'ข้อความทดสอบ <script>alert(1)</script>'}
    response = client.post(f"/staff/cases/{case['id']}/review", data=form)
    assert response.status_code == 400
    html = response.get_data(as_text=True)
    assert expected in html
    assert 'ยังไม่ได้บันทึกผล' in html and 'name="guidance"' in html
    assert 'Emergency screening cannot' not in html
    assert f'value="{urgency}" selected' in html
    assert 'value="appointment" selected' in html
    if department:
        assert f'value="{department}" selected' in html
    assert '&lt;script&gt;alert(1)&lt;/script&gt;' in html
    with app.app_context():
        record = db.session.get(Case, case['id'])
        assert record.clinician_urgency is None
        assert current_review(record) is None
