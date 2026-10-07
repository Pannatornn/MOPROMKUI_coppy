from tests.conftest import app, client, create_case
from app.extensions import db
from app.models import Case

def test_appointment_link_keeps_case_when_other_tab_polls(client,app):
    skin=create_case(client,"ข้อมูลสมมติ: ผื่นคันเล็กน้อย").json
    emergency=create_case(client,"ข้อมูลสมมติ: หายใจไม่ออก").json
    with app.app_context():
        db.session.get(Case,skin["id"]).status="ready"
        db.session.commit()
    client.get("/api/cases/"+skin["id"],headers={"X-Case-Token":skin["token"]})
    first=client.get(skin["booking_url"]).get_data(as_text=True)
    assert skin["reference"] in first
    client.get("/api/cases/"+emergency["id"],headers={"X-Case-Token":emergency["token"]})
    second=client.get(skin["booking_url"]+"&doctor=demo-skin-2").get_data(as_text=True)
    assert skin["reference"] in second, "Booking navigation switched cases after another tab polled"


def test_unknown_answers_in_stub_mode_do_not_allow_routine_booking(client):
    case=create_case(client,"ข้อมูลสมมติ: ปวดศีรษะ ไม่ทราบรายละเอียด").json
    for _ in range(11):
        response=client.post("/api/cases/"+case["id"]+"/messages",headers={"X-Case-Token":case["token"]},json={"content":"ไม่ทราบ ยังตอบไม่ได้"})
        if response.json["status"] != "collecting":
            break
    assert response.json["status"]=="escalated", "Unknown answers became ready based on question count"
    assert response.json["appointment_referral"]["state"]=="review"


def test_english_emergency_does_not_depend_on_ai(client):
    case=create_case(client,"Fictional QA case: severe chest pain and cannot breathe").json
    assert case["urgency"]=="emergency", "English emergency was not caught before AI"
    assert not case["chat"]["can_send"]


def test_late_ai_response_does_not_log_staff_out(app,monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    import app.routes as routes
    from app.ai import _fallback
    patient=app.test_client()
    staff=app.test_client()
    patient.get("/staff/login")
    with patient.session_transaction() as session:
        csrf=session["_csrf_token"]
    cookie_name=app.config["SESSION_COOKIE_NAME"]
    staff.set_cookie(cookie_name,patient.get_cookie(cookie_name).value)
    started,release=Event(),Event()
    def slow_ai(case):
        # Release SQLite's database-wide write lock so independent staff writes
        # can proceed as on production Postgres. This test checks cookie ordering.
        db.session.commit()
        started.set()
        assert release.wait(timeout=10)
        return _fallback(case,"provider_disabled")
    monkeypatch.setattr(routes,"generate_interview_turn",slow_ai)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future=pool.submit(patient.post,"/api/cases",json={"age_group":"18-39", "sex_at_birth":"female", "pregnancy_status":"not_pregnant", "chief_complaint":"ข้อมูลสมมติ: ปวดศีรษะเล็กน้อย", "consent":True})
        assert started.wait(timeout=10)
        try:
            result=staff.post("/staff/login",data={"username":"nurse","password":"correct-horse-battery","csrf_token":csrf})
            assert result.status_code in (302,303)
            assert staff.get("/staff").status_code==200
        finally:
            release.set()
        response = future.result(timeout=10)
        assert response.status_code==201
        assert not response.headers.getlist('Set-Cookie')
    # The late API response has no cookie to overwrite the staff login.
    assert staff.get("/staff").status_code==200, "Late anonymous AI response overwrote the successful staff login"


def test_authenticated_polling_never_refreshes_staff_cookie(client):
    case = create_case(client).json
    from tests.test_case_display import login
    login(client)
    response = client.get('/api/cases/'+case['id'], headers={'X-Case-Token':case['token']})
    assert response.status_code == 200
    assert not response.headers.getlist('Set-Cookie')
    assert client.get('/staff').status_code == 200


def test_booking_context_cannot_be_tampered_with(client):
    case = create_case(client).json
    assert client.get(case['booking_url']+'tampered').status_code == 404


def test_closed_case_cannot_request_appointment(client,app):
    case = create_case(client).json
    with app.app_context():
        db.session.get(Case,case['id']).status='closed'
        db.session.commit()
    page=client.get(case['booking_url']).get_data(as_text=True)
    assert 'ส่งคำขอนัด →' not in page
    assert 'ขอนัดใหม่' not in page
    with client.session_transaction() as session:
        csrf=session['_csrf_token']
    from urllib.parse import parse_qs,urlparse
    context=parse_qs(urlparse(case['booking_url']).query)['context'][0]
    assert client.post('/appointments/request',data={'case_id':case['id'],'csrf_token':csrf,'context':context}).status_code==409


def test_safety_escalation_marks_previous_ai_summary_stale(client,app):
    case=create_case(client).json
    assert case['ai_summary_current']
    response=client.post('/api/cases/'+case['id']+'/messages',headers={'X-Case-Token':case['token']},json={'content':'หายใจไม่ออก'})
    assert not response.json['ai_summary_current']
    assert response.json['ai_mode']=='safety_rule'
    from tests.test_case_display import login
    login(client)
    page=client.get('/staff/cases/'+case['id']).get_data(as_text=True)
    assert 'สรุปนี้ไม่ครอบคลุมข้อความผู้ใช้ล่าสุด' in page


def test_urgent_rule_badge_is_not_connecting_ai(client):
    case=create_case(client,'ปวดท้องมากจนทนไม่ไหว 9/10').json
    assert case['ai_mode']=='safety_rule'


def test_facts_without_patient_evidence_are_unknown(client,app):
    from app.ai import _fallback,ground_summary
    from app.schemas import SummaryEvidence
    case=create_case(client,'ปวดหัวตั้งแต่เมื่อวาน 3/10 ทำงานได้ตามปกติ').json
    with app.app_context():
        record=db.session.get(Case,case['id'])
        turn=_fallback(record).turn
        turn.summary.onset_and_course='เริ่มเมื่อวาน'
        turn.summary.travel_and_sick_contacts=['ไม่มี']
        turn.summary.current_medications=['ไม่มี']
        turn.summary.evidence=[SummaryEvidence(field='onset_and_course',quotes=['ตั้งแต่เมื่อวาน']),
                               SummaryEvidence(field='current_medications',quotes=['อาการเริ่มเมื่อไรครับ'])]
        ground_summary(record,turn)
        assert turn.summary.onset_and_course=='เริ่มเมื่อวาน'
        assert turn.summary.travel_and_sick_contacts==[]
        assert turn.summary.current_medications==[]
        assert any('ความรุนแรง' in item for item in turn.summary.missing_critical_information)


def test_negated_english_symptoms_do_not_trigger_emergency():
    from app.safety import find_red_flags
    assert not find_red_flags('No severe chest pain. No heavy bleeding. Not unconscious.')
    assert find_red_flags('No severe chest pain, but I cannot breathe.')
