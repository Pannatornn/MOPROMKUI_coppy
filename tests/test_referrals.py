from types import SimpleNamespace
import pytest
from app.referrals import recommend_department
from app.models import Case
from app.appointments import Appointment, AppointmentSlot
from app.extensions import db
from .conftest import create_case
from .test_appointments import calendar, book_form, token


def example(chief, **values):
    return SimpleNamespace(chief_complaint=chief, messages=values.get('messages', []),
        rule_urgency=values.get('rule_urgency', 'routine'), clinician_urgency=None,
        ai_urgency_suggestion=values.get('ai_urgency_suggestion', 'routine'),
        status=values.get('status', 'ready'), age_group=values.get('age_group', '18-39'),
        pregnancy_status=values.get('pregnancy_status', 'not_pregnant'))


@pytest.mark.parametrize('chief,department', [
    ('สิวบนหน้า', 'skin'), ('ปวดท้องเล็กน้อย', 'medicine'), ('ปวดเข่าเวลาขึ้นบันได', 'orthopedics'),
    ('หูอื้อ', 'ent'), ('ประจำเดือนมาไม่สม่ำเสมอ', 'gynecology'),
    ('ปวดศีรษะเล็กน้อย', 'general'), ('ผื่นและปวดท้อง', 'general'),
    ('ไม่มีผื่น ไม่มีปวดท้อง ปวดศีรษะ', 'general'),
])
def test_demo_symptom_groups(chief, department):
    assert recommend_department(example(chief))['department'] == department


def test_context_and_safety_take_priority():
    assert recommend_department(example('สิว', age_group='0-12'))['department'] == 'pediatrics'
    assert recommend_department(example('ผื่น', pregnancy_status='pregnant'))['department'] == 'general'
    assert recommend_department(example('หายใจไม่ออก', age_group='0-12'))['state'] == 'emergency'
    assert recommend_department(example('ปวดมากมากมาก'))['state'] == 'review'
    assert recommend_department(example('สิว', ai_urgency_suggestion='urgent'))['state'] == 'review'
    assert recommend_department(example('สิว', status='collecting'))['state'] == 'collecting'
    later = SimpleNamespace(role='patient', content='ปวดท้องเล็กน้อยด้วย')
    assert recommend_department(example('สิว', messages=[later]))['department'] == 'general'


def test_intake_required_and_server_rejects_wrong_department(app, client, calendar):
    page = client.get('/appointments').get_data(as_text=True)
    assert 'เริ่มซักประวัติก่อนนัด' in page
    assert 'name="slot_id"' not in page
    client.get('/staff/login')
    with client.session_transaction() as session:
        csrf = session['_csrf_token']
    assert client.post('/appointments/book', data={'csrf_token': csrf, 'slot_id': calendar[0]}).status_code == 409
    case = create_case(client, 'มีสิวบนใบหน้า').get_json()
    assert client.post('/appointments/book', data={'csrf_token': csrf, 'case_id': case['id'], 'slot_id': calendar[0]}).status_code == 409
    with app.app_context():
        db.session.get(Case, case['id']).status = 'ready'
        db.session.commit()
        skin_slot = db.session.scalar(db.select(AppointmentSlot).where(AppointmentSlot.doctor_id == 'demo-pim'))
        skin_id = skin_slot.id
    page = client.get('/appointments').get_data(as_text=True)
    assert 'พญ.พิมพ์ชนก' in page and 'นพ.ปกรณ์' in page
    assert 'พญ.มินตรา' not in page
    assert client.get('/appointments?doctor=demo-mint').status_code == 303
    assert client.post('/appointments/book', data={'csrf_token': csrf, 'case_id': case['id'], 'slot_id': calendar[0]}).status_code == 409
    assert client.post('/appointments/book', data={'csrf_token': csrf, 'case_id': case['id'], 'slot_id': skin_id}).status_code == 303
    with app.app_context():
        booked = db.session.scalar(db.select(Appointment))
        assert booked.referral.case_id == case['id']
        assert booked.referral.department == 'skin'


def test_case_switch_deleted_case_and_emergency_block_booking(app, client, calendar):
    data = book_form(client, calendar[0])
    old_id = data['case_id']
    create_case(client, 'ปวดศีรษะเล็กน้อย')
    assert client.post('/appointments/book', data=data).status_code == 409
    emergency = create_case(client, 'หายใจไม่ออก').get_json()
    page = client.get('/appointments').get_data(as_text=True)
    assert 'ห้องฉุกเฉิน' in page and 'name="slot_id"' not in page
    data['case_id'] = emergency['id']
    assert client.post('/appointments/book', data=data).status_code == 409
    with app.app_context():
        assert db.session.get(AppointmentSlot, calendar[0]).state == 'free'
        db.session.delete(db.session.get(Case, emergency['id']))
        db.session.commit()
    assert 'เริ่มซักประวัติก่อนนัด' in client.get('/appointments').get_data(as_text=True)


def test_patient_token_cannot_bind_someone_elses_case(app, client, calendar):
    token(client)
    other = app.test_client()
    other_case = create_case(other, 'ผื่นคัน').get_json()
    with client.session_transaction() as session:
        previous = session['appointment_case_id']
    assert client.get('/api/cases/' + other_case['id'], headers={'X-Case-Token': 'wrong'}).status_code == 404
    with client.session_transaction() as session:
        assert session['appointment_case_id'] == previous
