import pytest
from app.appointments import AppointmentRequest, Appointment, AppointmentSlot, _local
from app.extensions import db
from app.models import Case
from .conftest import create_case
from .test_case_display import login
from .test_appointments import calendar


def request_form(client, case_id):
    client.get('/appointments')
    client.get('/staff/login')
    with client.session_transaction() as session:
        return {'csrf_token': session['_csrf_token'], 'case_id': case_id}


@pytest.mark.parametrize('complaint', ['ข้อมูลสมมติ: ผื่นเล็กน้อย', 'ข้อมูลสมมติ: ปวดท้องมากจนทนไม่ไหว', 'ข้อมูลสมมติ: หายใจไม่ออก'])
def test_every_severity_can_request_without_duplicate(app, client, complaint):
    data = create_case(client, complaint).json
    page = client.get('/appointments').get_data(as_text=True)
    assert 'ส่งคำขอนัด →' in page
    form = request_form(client, data['id'])
    for _ in range(2):
        assert client.post('/appointments/request', data=form).status_code == 303
    with app.app_context():
        assert db.session.scalar(db.select(db.func.count()).select_from(AppointmentRequest)) == 1
    payload = client.get('/api/cases/'+data['id'], headers={'X-Case-Token':data['token']}).json
    assert payload['appointment_request']['status'] == 'pending'
    assert payload['appointment_request']['reference'].startswith('REQ-')


def test_request_is_confirmed_and_visible_to_patient(app, client, calendar):
    data = create_case(client, 'ข้อมูลสมมติ: หายใจไม่ออก').json
    assert client.post('/appointments/request', data=request_form(client, data['id'])).status_code == 303
    staff = app.test_client()
    csrf = login(staff)
    with app.app_context():
        slot = db.session.get(AppointmentSlot, calendar[0])
        day = _local(slot.starts_at).date().isoformat()
        doctor = slot.doctor_id
    form = {'csrf_token':csrf,'action':'assign_request','case_id':data['id'],
            'doctor':doctor,'day':day,'slot_id':calendar[0]}
    assert staff.post('/staff/appointments', data=form).status_code == 303
    with app.app_context():
        assert db.session.get(AppointmentRequest, data['id']).status == 'pending'
        assert db.session.get(AppointmentSlot, calendar[0]).state == 'free'
    form['followup'] = 'yes'
    for _ in range(2):
        assert staff.post('/staff/appointments', data=form).status_code == 303
    result = client.get('/api/cases/'+data['id'], headers={'X-Case-Token':data['token']}).json
    assert result['appointment_request']['status'] == 'confirmed'
    assert result['appointment_request']['appointment_reference'].startswith('APT-')
    assert result['appointment_referral']['state'] == 'emergency'
    assert 'ยืนยันนัดแล้ว' in client.get('/appointments').get_data(as_text=True)
    with app.app_context():
        assert db.session.scalar(db.select(db.func.count()).select_from(Appointment)) == 1
        item = db.session.scalar(db.select(Appointment))
        assert item.referral.case_id == data['id']
    # Signing into staff clears anonymous booking ownership, but the patient's
    # authenticated case token must still allow cancellation of this request.
    login(client)
    client.get('/api/cases/'+data['id'], headers={'X-Case-Token':data['token']})
    assert client.post('/appointments/'+str(item.id)+'/cancel', data={'csrf_token':request_form(client,data['id'])['csrf_token']}).status_code == 303
    result = client.get('/api/cases/'+data['id'], headers={'X-Case-Token':data['token']}).json
    assert result['appointment_request']['appointment_status'] == 'cancelled'
    assert client.post('/appointments/request', data=request_form(client,data['id'])).status_code == 303
    with app.app_context():
        assert db.session.get(AppointmentRequest,data['id']).status == 'pending'
        assert db.session.get(AppointmentRequest,data['id']).appointment_id is None


def test_request_ownership_and_staff_permission(app, client):
    data = create_case(client, 'ข้อมูลสมมติ: ผื่น').json
    stranger = app.test_client()
    form = request_form(stranger, data['id'])
    assert stranger.post('/appointments/request', data=form).status_code == 409
    assert client.post('/appointments/request', data={'case_id':data['id']}).status_code == 400
    assert client.post('/staff/appointments', data={'action':'assign_request'}).status_code == 401
    assert client.post('/appointments/request', data=request_form(client,data['id'])).status_code == 303
    with app.app_context():
        db.session.delete(db.session.get(Case, data['id']))
        db.session.commit()
        assert db.session.get(AppointmentRequest, data['id']) is None
