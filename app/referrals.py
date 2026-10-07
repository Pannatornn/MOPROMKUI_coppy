"""Demo clinic routing policy; not a diagnosis or validated referral protocol."""
import re
from .safety import _is_negated, find_red_flags, find_urgent_signals, normalize
from .case_display import current_review

DEPARTMENTS = {
    'general': 'เวชปฏิบัติทั่วไป', 'medicine': 'อายุรกรรม', 'skin': 'ผิวหนัง',
    'orthopedics': 'กระดูกและข้อ', 'ent': 'หู คอ จมูก',
    'gynecology': 'สูติ–นรีเวช', 'pediatrics': 'กุมารเวช',
}
PATTERNS = {
    'skin': r'ผื่น|สิว|ผิวหนัง|คันผิว|คันตามตัว',
    'medicine': r'ปวดท้อง|ท้องเสีย|ท้องผูก|คลื่นไส้|อาเจียน|เบาหวาน|ความดันโลหิต',
    'orthopedics': r'ปวดเข่า|ปวดข้อ|ปวดหลัง|ปวดไหล่|ปวดกระดูก|ข้อเท้า|ข้อมือ',
    'ent': r'ปวดหู|หูอื้อ|ได้ยิน|น้ำมูก|คัดจมูก|เจ็บคอ|เสียงแหบ',
    'gynecology': r'ประจำเดือน|ตกขาว|ช่องคลอด|ปวดอุ้งเชิงกราน',
}


def recommend_department(case):
    texts = [case.chief_complaint] + [m.content for m in case.messages if m.role == 'patient']
    if case.rule_urgency == 'emergency' or case.clinician_urgency == 'emergency' or any(find_red_flags(t) for t in texts):
        return {'state': 'emergency', 'department': None, 'label': 'ห้องฉุกเฉิน',
                'reason': 'พบสัญญาณที่อาจฉุกเฉิน ไม่ควรรอคิวนัดปกติ ให้โทร 1669 หรือไปห้องฉุกเฉินทันที'}
    if case.status == 'closed':
        return {'state': 'closed', 'department': None, 'label': 'ปิดเคสแล้ว',
                'reason': 'เคสนี้ปิดแล้ว หากต้องการนัดใหม่ให้เริ่มซักประวัติใหม่'}
    review = current_review(case)
    if review and review.get('disposition') == 'appointment' and review.get('department') in DEPARTMENTS and case.clinician_urgency in {'routine', 'soon'}:
        department = review['department']
        return {'state': 'ready', 'department': department, 'label': DEPARTMENTS[department],
                'reason': review['guidance'], 'source': 'staff'}
    if review and review.get('disposition') in {'care', 'wait'}:
        return {'state': 'review', 'department': None,
                'label': 'คำแนะนำจากเจ้าหน้าที่' if review['disposition'] == 'care' else 'รอเจ้าหน้าที่ดำเนินการ',
                'reason': review['guidance'], 'source': 'staff'}
    if (case.rule_urgency == 'urgent'
            or case.ai_urgency_suggestion in {'urgent', 'emergency'}
            or case.clinician_urgency in {'urgent', 'emergency'}
            or any(find_urgent_signals(t) for t in texts)):
        return {'state': 'review', 'department': None, 'label': 'ให้เจ้าหน้าที่ประเมินก่อนนัด',
                'reason': 'ข้อมูลนี้ควรได้รับการตรวจโดยเร็ว โปรดติดต่อสถานพยาบาลเพื่อประเมิน ไม่ควรรอคิวนัดปกติ หากเป็นเหตุฉุกเฉินให้โทร 1669'}
    if case.status == 'escalated':
        return {'state': 'review', 'department': None, 'label': 'ให้เจ้าหน้าที่ตรวจข้อมูลก่อนนัด',
                'reason': 'ระบบยังยืนยันข้อมูลสำคัญไม่ได้ จึงต้องให้เจ้าหน้าที่ตรวจและจัดขั้นตอนต่อ การส่งประเมินไม่ได้หมายความว่าพบอาการฉุกเฉิน หากมีอาการรุนแรงขึ้นให้ติดต่อสถานพยาบาลโดยตรง'}
    if case.status != 'ready':
        return {'state': 'collecting', 'department': None, 'label': 'ซักประวัติให้ครบก่อน',
                'reason': 'ระบบจะจัดแผนกและแสดงแพทย์ที่เหมาะกับอาการ หลังรวบรวมข้อมูลซักประวัติครบแล้ว'}
    # Later/history answers can be ambiguous; never infer a diagnosis from the summary.
    matches = set()
    for raw in texts:
        if re.search(r'ประวัติ|เคย|หายแล้ว|ปีก่อน', raw) and raw != case.chief_complaint:
            continue
        text = normalize(raw)
        for department, pattern in PATTERNS.items():
            if any(not _is_negated(text, match.start()) for match in re.finditer(pattern, text)):
                matches.add(department)
    if case.age_group in {'0-12', '13-17'}:
        department, reason = 'pediatrics', 'ช่วงอายุที่แจ้งอยู่ในกลุ่มเด็กและวัยรุ่น จึงเริ่มประเมินที่กุมารเวชตามนโยบายเดโม'
    elif case.pregnancy_status in {'pregnant', 'possibly_pregnant'}:
        department, reason = 'general', 'มีบริบทตั้งครรภ์หรืออาจตั้งครรภ์ ให้แพทย์ประเมินภาพรวมก่อนส่งต่อ'
    elif len(matches) == 1:
        department = next(iter(matches))
        reason = 'หมวดอาการที่แจ้งตรงกับแผนกนี้ตามกติกาของคลินิกทดลอง'
    else:
        department, reason = 'general', 'มีหลายหมวดอาการหรือข้อมูลยังไม่ชัดเจน จึงเริ่มที่เวชปฏิบัติทั่วไปเพื่อประเมินและส่งต่อ'
    return {'state': 'ready', 'department': department, 'label': DEPARTMENTS[department], 'reason': reason}
