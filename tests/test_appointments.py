from datetime import timedelta
import pytest
from app.appointments import Appointment, AppointmentSlot, Doctor, _local, _today
from app.extensions import db


@pytest.fixture()
def calendar(app):
    result = app.test_cli_runner().invoke(args=['seed-appointments'])
    assert result.exit_code == 0, result.output
    with app.app_context():
        slot = db.session.scalar(db.select(AppointmentSlot).where(AppointmentSlot.state == 'free').order_by(AppointmentSlot.starts_at))
        return slot.id, slot.doctor_id, _local(slot.starts_at).date().isoformat()


def token(client):
    assert client.get('/appointments').status_code == 200
    with client.session_transaction() as session:
        return session['_csrf_token']


def staff(client):
    client.post('/staff/login', data={'username': 'nurse', 'password': 'correct-horse-battery', 'csrf_token': token(client)})


def test_seed_distinct_schedules_and_preserve_states(app, calendar):
    with app.app_context():
        doctors = db.session.scalars(db.select(Doctor)).all()
        assert len(doctors) == 3
        assert len({d.schedule_label for d in doctors}) == 3
        count = db.session.query(AppointmentSlot).count()
        slot = db.session.get(AppointmentSlot, calendar[0])
        slot.state = 'blocked'
        db.session.commit()
    assert app.test_cli_runner().invoke(args=['seed-appointments']).exit_code == 0
    with app.app_context():
        assert db.session.query(AppointmentSlot).count() == count
        assert db.session.get(AppointmentSlot, calendar[0]).state == 'blocked'


def test_booking_private_and_duplicate_rejected(app, client, calendar):
    other = app.test_client()
    csrf = token(client)
    assert client.post('/appointments/book', data={'slot_id': calendar[0], 'csrf_token': csrf}).status_code == 303
    with app.app_context():
        appointment = db.session.scalar(db.select(Appointment))
        reference = appointment.reference
        appointment_id = appointment.id
    assert reference.encode() in client.get('/appointments').data
    other_csrf = token(other)
    assert reference.encode() not in other.get('/appointments').data
    assert other.post('/appointments/book', data={'slot_id': calendar[0], 'csrf_token': other_csrf}).status_code == 303
    assert other.post(f'/appointments/{appointment_id}/cancel', data={'csrf_token': other_csrf}).status_code == 404
    with app.app_context():
        assert db.session.query(Appointment).count() == 1


def test_cancel_rebook_and_repeat_cancel_safe(app, client, calendar):
    csrf = token(client)
    client.post('/appointments/book', data={'slot_id': calendar[0], 'csrf_token': csrf})
    with app.app_context():
        appointment_id = db.session.scalar(db.select(Appointment.id))
    client.post(f'/appointments/{appointment_id}/cancel', data={'csrf_token': csrf})
    other = app.test_client()
    other.post('/appointments/book', data={'slot_id': calendar[0], 'csrf_token': token(other)})
    client.post(f'/appointments/{appointment_id}/cancel', data={'csrf_token': csrf})
    with app.app_context():
        assert db.session.get(AppointmentSlot, calendar[0]).state == 'booked'
        assert db.session.query(Appointment).filter_by(status='booked').count() == 1


def test_csrf_dates_and_closed_slots(app, client, calendar):
    assert client.post('/appointments/book', data={'slot_id': calendar[0]}).status_code == 400
    for day in ['invalid', (_today() - timedelta(days=1)).isoformat(), (_today() + timedelta(days=29)).isoformat()]:
        assert client.get('/appointments', query_string={'day': day}).status_code == 400
    with app.app_context():
        db.session.get(AppointmentSlot, calendar[0]).state = 'blocked'
        db.session.commit()
    client.post('/appointments/book', data={'slot_id': calendar[0], 'csrf_token': token(client)})
    with app.app_context():
        assert db.session.query(Appointment).count() == 0


def test_staff_calendar_auth_close_and_add(app, client, calendar):
    assert client.get('/staff/appointments').status_code == 401
    staff(client)
    csrf = token(client)
    data = {'doctor': calendar[1], 'day': calendar[2], 'slot_id': calendar[0], 'csrf_token': csrf}
    assert client.get('/staff/appointments', query_string=data).status_code == 200
    assert client.post('/staff/appointments', data=dict(data, action='block')).status_code == 303
    with app.app_context():
        assert db.session.get(AppointmentSlot, calendar[0]).state == 'blocked'
    client.post('/staff/appointments', data=dict(data, action='open'))
    client.post('/appointments/book', data={'slot_id': calendar[0], 'csrf_token': csrf})
    client.post('/staff/appointments', data=dict(data, action='block'))
    with app.app_context():
        assert db.session.get(AppointmentSlot, calendar[0]).state == 'booked'
    add = dict(data, action='add', time='17:30')
    client.post('/staff/appointments', data=add)
    client.post('/staff/appointments', data=add)
    with app.app_context():
        slots = db.session.scalars(db.select(AppointmentSlot).where(AppointmentSlot.doctor_id == calendar[1])).all()
        assert sum(_local(s.starts_at).date().isoformat() == calendar[2] and _local(s.starts_at).hour == 17 for s in slots) == 1
    assert client.post('/staff/appointments', data=dict(add, time='17:15')).status_code == 400
