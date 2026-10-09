from copy import deepcopy
from types import SimpleNamespace

import pytest

from app.extensions import db
from app.models import AuditEvent, Case, Message
from app.summary_display import summary_display
from .conftest import create_case
from .test_case_display import login


def record(text, summary=None, provider='gemini'):
    return SimpleNamespace(
        chief_complaint=text, pregnancy_status='not_applicable', rule_urgency='pending',
        ai_summary=summary or {}, messages=[SimpleNamespace(role='patient', content=text)],
        audit_events=[SimpleNamespace(action='interview_turn', detail={'provider': provider})],
    )


def test_reported_fields_recovered_verbatim_without_changing_ai_summary():
    text = ('ปวดข้อเท้าขวาหลังบิดเมื่อวาน ปวด 3 จาก 10 เดินลงน้ำหนักได้. '
            'ดีขึ้นหลังพักและประคบเย็น. ไม่เคยผ่าตัด. ไม่มีประวัติครอบครัวเกี่ยวข้อง.')
    case = record(text, {'onset_and_course': 'ยังไม่ได้ข้อมูล', 'family_history': [],
                         'symptom_location_and_character': 'ยังไม่ได้ข้อมูล'})
    original = deepcopy(case.ai_summary)
    rows = {r['field']: r for r in summary_display(case)['rows']}
    for field in ('symptom_location_and_character', 'aggravating_and_relieving_factors',
                  'past_procedures_or_hospitalizations', 'family_history'):
        assert rows[field]['quotes']
        assert all(q in text for q in rows[field]['quotes'])
        assert rows[field]['source'] == 'patient'
        assert rows[field]['value'] is None
    assert rows['family_history']['quotes'] == ['ไม่มีประวัติครอบครัวเกี่ยวข้อง.']
    assert case.ai_summary == original


def test_valid_evidence_displays_ai_value_and_original_citation():
    case = record('เริ่มปวดเมื่อวาน', {'onset_and_course': 'เริ่มเมื่อวาน',
                  'evidence': [{'field': 'onset_and_course', 'quotes': ['เมื่อวาน']}]})
    row = summary_display(case)['rows'][0]
    assert row['value'] == 'เริ่มเมื่อวาน'
    assert row['quotes'] == ['เมื่อวาน']
    assert row['source'] == 'ai'


@pytest.mark.parametrize('quotes', [['ไม่เคยผ่าตัด'], ['เมื่อวาน', 'ข้อความแต่งขึ้น']])
def test_assistant_or_partially_fabricated_citations_do_not_assert_facts(quotes):
    case = record('ปวดเมื่อวาน', {'onset_and_course': 'ค่าที่ไม่ยืนยัน',
                  'evidence': [{'field': 'onset_and_course', 'quotes': quotes}]})
    case.messages.append(SimpleNamespace(role='assistant', content='ไม่เคยผ่าตัด'))
    view = summary_display(case)
    assert view['rows'][0]['value'] is None
    surgery = next(r for r in view['rows'] if r['field'] == 'past_procedures_or_hospitalizations')
    assert not surgery['quotes']


def test_corrections_and_negations_are_preserved_without_merging_findings():
    case = record('ไม่แพ้ยา', {'allergies': []})
    case.messages.append(SimpleNamespace(role='patient', content='แก้ไข: เคยแพ้ยา penicillin'))
    row = next(r for r in summary_display(case)['rows'] if r['field'] == 'allergies')
    assert row['quotes'] == ['ไม่แพ้ยา', 'แก้ไข: เคยแพ้ยา penicillin']
    assert row['value'] is None


@pytest.mark.parametrize('provider,has_summary,expected', [
    ('gemini', True, 'ai'), ('openai', True, 'ai'),
    ('safe_fallback', True, 'fallback'), ('gemini', False, 'not_generated'),
])
def test_summary_provenance_depends_on_actual_result(provider, has_summary, expected):
    case = record('ปวดหัว', {'onset_and_course': 'วันนี้'} if has_summary else {}, provider)
    assert summary_display(case)['mode'] == expected


def test_old_summary_without_audit_is_not_claimed_as_ai():
    case = record('ปวดหัว', {'onset_and_course': 'วันนี้'})
    case.audit_events = []
    assert summary_display(case)['mode'] == 'legacy'


def test_safety_only_case_has_no_ai_summary_label(client):
    payload = create_case(client, 'ข้อมูลสมมติ: หายใจไม่ออก').json
    login(client)
    html = client.get('/staff/cases/' + payload['id']).get_data(as_text=True)
    assert 'ยังไม่ได้สร้างสรุป AI' in html
    assert 'กฎความปลอดภัยหยุดการซักประวัติ' in html
    assert 'AI SUMMARY' not in html
    assert 'สรุปนี้สร้างโดย AI' not in html
    assert 'ยังไม่ได้ประเมินโดย AI' in html
    assert 'ไม่เกี่ยวข้อง' not in html  # pregnancy form says not_pregnant
    assert 'ไม่ได้ตั้งครรภ์' in html


def test_fallback_case_is_identified_as_patient_information(client):
    payload = create_case(client, 'ปวดหัวเล็กน้อย').json
    login(client)
    html = client.get('/staff/cases/' + payload['id']).get_data(as_text=True)
    assert 'ข้อมูลจากบทสนทนา · โหมดสำรอง' in html
    assert 'AI SUMMARY' not in html
    assert 'สรุปนี้สร้างโดย AI' not in html


def test_existing_record_shows_reported_data_without_recalling_ai(app, client):
    payload = create_case(client, 'ปวดข้อเท้าขวา ไม่เคยผ่าตัด ไม่มีประวัติครอบครัวเกี่ยวข้อง').json
    with app.app_context():
        case = db.session.get(Case, payload['id'])
        case.ai_summary = {'symptom_location_and_character': 'ยังไม่ได้ข้อมูล', 'family_history': []}
        db.session.add(AuditEvent(case=case, action='interview_turn', actor='ai',
                                 detail={'provider': 'gemini', 'patient_message_id': case.messages[-2].id}))
        db.session.add(Message(case=case, role='patient', content='ครอบครัว <script>alert(1)</script>'))
        db.session.commit()
    login(client)
    html = client.get('/staff/cases/' + payload['id']).get_data(as_text=True)
    assert 'สรุป AI สำหรับบุคลากร' in html
    assert 'ข้อความผู้ใช้ · รอเจ้าหน้าที่ตรวจ' in html
    assert 'ปวดข้อเท้าขวา ไม่เคยผ่าตัด ไม่มีประวัติครอบครัวเกี่ยวข้อง' in html
    assert 'ครอบครัว &lt;script&gt;alert(1)&lt;/script&gt;' in html
    assert 'สรุปนี้ไม่ครอบคลุมข้อความผู้ใช้ล่าสุด' in html
    assert '<script>alert(1)</script>' not in html
    assert 'ยังไม่ได้ข้อมูล' not in html
    with app.app_context():
        case = db.session.get(Case, payload['id'])
        assert case.ai_summary['symptom_location_and_character'] == 'ยังไม่ได้ข้อมูล'
        assert sum(e.action == 'interview_turn' for e in case.audit_events) == 2
