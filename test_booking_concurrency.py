from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from tests.conftest import app, client, create_case
from tests.test_appointments import calendar, book_form
from app.extensions import db
from app.models import Case
from app.appointments import Appointment, AppointmentSlot

def concurrent_posts(clients,forms):
    barrier=Barrier(2)
    def run(index):
        barrier.wait(timeout=10)
        return clients[index].post("/appointments/book",data=forms[index]).status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        return list(pool.map(run,range(2)))

def test_two_patients_compete_for_one_slot(app,calendar):
    clients=[app.test_client(),app.test_client()]
    cases=[create_case(c,"ข้อมูลสมมติ: ปวดศีรษะเล็กน้อย").json for c in clients]
    with app.app_context():
        for case in cases: db.session.get(Case,case["id"]).status="ready"
        db.session.commit()
    forms=[book_form(c,calendar[0]) for c in clients]
    assert concurrent_posts(clients,forms)==[303,303]
    with app.app_context():
        assert db.session.query(Appointment).filter_by(status="booked").count()==1
        assert db.session.get(AppointmentSlot,calendar[0]).state=="booked"

def test_one_case_competes_for_two_different_slots(app,calendar):
    clients=[app.test_client(),app.test_client()]
    case=create_case(clients[0],"ข้อมูลสมมติ: ปวดศีรษะเล็กน้อย").json
    with app.app_context():
        db.session.get(Case,case["id"]).status="ready"
        other=db.session.scalar(db.select(AppointmentSlot).where(AppointmentSlot.doctor_id==calendar[1],AppointmentSlot.id!=calendar[0],AppointmentSlot.state=="free").order_by(AppointmentSlot.starts_at)).id
        db.session.commit()
    clients[1].get("/api/cases/"+case["id"],headers={"X-Case-Token":case["token"]})
    clients[1].get(case['booking_url'])
    forms=[book_form(clients[0],calendar[0]),book_form(clients[1],other)]
    assert concurrent_posts(clients,forms)==[303,303]
    with app.app_context():
        assert db.session.query(Appointment).filter_by(status="booked").count()==1
        assert sum(db.session.get(AppointmentSlot,i).state=="booked" for i in [calendar[0],other])==1
