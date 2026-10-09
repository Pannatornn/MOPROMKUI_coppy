"""Present sourced facts separately from unclassified patient statements.

Keyword matches are navigation aids, never clinical assertions. They cannot
change the stored AI summary, triage, interview completion or booking decision.
"""
import re


SUMMARY_FIELDS = (
    ('onset_and_course', 'เริ่มและดำเนินอาการ', r'เริ่ม|เมื่อวาน|เมื่อคืน|ตั้งแต่|ดีขึ้น|แย่ลง|started|since|yesterday'),
    ('symptom_location_and_character', 'ตำแหน่ง/ลักษณะ', r'ข้อเท้า|ศีรษะ|หัว|ท้อง|หน้าอก|แขน|ขา|หลัง|ด้าน|บริเวณ|ร้าว|ankle|head|chest|abdomen|pain'),
    ('severity_and_impact', 'ความรุนแรง/ผลกระทบ', r'\d\s*/\s*10|จาก\s*10|รุนแรง|ลงน้ำหนัก|เดิน|ทำงาน|severe|walk|work'),
    ('aggravating_and_relieving_factors', 'ปัจจัยกระตุ้น/บรรเทา', r'ประคบ|บรรเทา|ดีขึ้น|แย่ลง|หลังพัก|กระตุ้น|worse|better|rest|compress'),
    ('associated_symptoms', 'อาการร่วม', r'ไข้|บวม|ชา|รอยช้ำ|อาเจียน|คลื่นไส้|อาการอื่น|fever|swelling|numb|vomit'),
    ('relevant_history', 'โรคและประวัติสำคัญ', r'โรคประจำตัว|เคยเป็น|ประวัติ|medical history|chronic'),
    ('past_procedures_or_hospitalizations', 'ผ่าตัด/นอนโรงพยาบาล', r'ผ่าตัด|นอนโรงพยาบาล|surgery|operation|hospitali[sz]'),
    ('current_medications', 'ยาและอาหารเสริม', r'กินยา|ใช้ยา|ยาประจำ|อาหารเสริม|medication|medicine|supplement'),
    ('allergies', 'การแพ้', r'แพ้ยา|แพ้อาหาร|allerg'),
    ('family_history', 'ประวัติครอบครัว', r'ครอบครัว|family'),
    ('social_and_exposure_history', 'สังคม/การสัมผัส', r'บุหรี่|แอลกอฮอล์|สุรา|อาชีพ|สัมผัส|smok|alcohol|exposure'),
    ('travel_and_sick_contacts', 'เดินทาง/ผู้สัมผัสป่วย', r'เดินทาง|ใกล้ชิด|ผู้สัมผัส|travel|sick contact'),
    ('vital_signs_if_known', 'ค่าสัญญาณชีพ', r'ความดัน|ชีพจร|อุณหภูมิ|ออกซิเจน|blood pressure|temperature|pulse|spo2'),
    ('patient_concerns', 'ความกังวลของผู้รับบริการ', r'กังวล|กลัว|concern|worried'),
)

UNKNOWN_VALUES = {'', 'ยังไม่ได้ข้อมูล', 'ยังไม่ได้ข้อมูลเพียงพอ', 'ไม่ทราบ', 'ดูรายละเอียดจากบทสนทนา'}
PREGNANCY_LABELS = {'pregnant': 'ตั้งครรภ์', 'possibly_pregnant': 'อาจตั้งครรภ์',
                    'not_pregnant': 'ไม่ได้ตั้งครรภ์', 'not_applicable': 'ไม่เกี่ยวข้อง', 'unknown': 'ไม่ทราบ'}


def _patient_excerpts(texts, pattern):
    # Keep full sentences, including negation and corrections, verbatim. Do not
    # turn a keyword match into a positive/negative finding or drop older answers.
    excerpts = []
    for text in texts:
        for sentence in re.split(r'[\n;]+|(?<=[.!?。])\s+', text):
            sentence = sentence.strip()
            if sentence and re.search(pattern, sentence, re.IGNORECASE) and sentence not in excerpts:
                excerpts.append(sentence)
    return excerpts


def summary_display(case):
    summary = case.ai_summary or {}
    event = next((e for e in reversed(case.audit_events) if e.action == 'interview_turn'), None)
    provider = (event.detail or {}).get('provider') if event else None
    if summary and provider in {'gemini', 'openai'}:
        mode, title = 'ai', 'สรุป AI สำหรับบุคลากร'
        note = 'สรุปนี้สร้างโดย AI และอาจผิดพลาด ต้องตรวจเทียบกับบทสนทนาต้นฉบับทุกครั้ง'
    elif summary and provider == 'safe_fallback':
        mode, title = 'fallback', 'ข้อมูลจากบทสนทนา · โหมดสำรอง'
        note = 'ยังไม่มีสรุปจาก AI ที่ใช้งานได้ แสดงข้อมูลตั้งต้นและข้อความผู้ใช้ให้เจ้าหน้าที่ตรวจ'
    elif summary:
        mode, title = 'legacy', 'ข้อมูลเคสเดิม · ไม่ทราบที่มาของสรุป'
        note = 'ไม่พบประวัติที่ยืนยันผู้สร้างสรุปเดิม แสดงข้อมูลตั้งต้นและข้อความผู้ใช้ให้เจ้าหน้าที่ตรวจ'
    else:
        mode, title = 'not_generated', 'ยังไม่ได้สร้างสรุป AI'
        note = ('กฎความปลอดภัยหยุดการซักประวัติก่อนสร้างสรุป AI ให้ตรวจข้อมูลตั้งต้นและบทสนทนา'
                if case.rule_urgency in {'urgent', 'emergency'} else
                'ยังไม่มีสรุป AI แสดงข้อมูลตั้งต้นและข้อความผู้ใช้ให้เจ้าหน้าที่ตรวจ')

    texts = [m.content for m in case.messages if m.role == 'patient']
    if case.chief_complaint and case.chief_complaint not in texts:
        texts.insert(0, case.chief_complaint)
    evidence = {}
    if mode == 'ai':
        for item in summary.get('evidence', []):
            quotes = item.get('quotes', [])
            # Match the same all-quotes rule as ground_summary; assistant text
            # and partially fabricated citations cannot support an asserted fact.
            if quotes and all(isinstance(q, str) and q.strip() and any(q in t for t in texts) for q in quotes):
                evidence.setdefault(item.get('field'), []).extend(quotes)

    rows = []
    for field, label, pattern in SUMMARY_FIELDS:
        value = summary.get(field)
        if isinstance(value, list):
            value = ', '.join(value)
        value = value if isinstance(value, str) else ''
        verified = bool(evidence.get(field) and value.strip() not in UNKNOWN_VALUES)
        rows.append({'field': field, 'label': label,
                     'value': value if verified else None,
                     'quotes': list(dict.fromkeys(evidence.get(field, []))) if verified else
                               _patient_excerpts(texts, pattern),
                     'source': 'ai' if verified else 'patient'})
    return {'mode': mode, 'title': title, 'note': note, 'rows': rows,
            'pregnancy': PREGNANCY_LABELS.get(case.pregnancy_status, 'ไม่ทราบ'),
            'missing': summary.get('missing_critical_information', []) if mode == 'ai' else None}
