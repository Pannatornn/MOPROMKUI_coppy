# หมอพร้อมคุย

ระบบซักประวัติก่อนพบแพทย์สำหรับคลินิกไทย ใช้กฎความปลอดภัยตรวจสัญญาณฉุกเฉินก่อนส่งข้อความให้ AI จากนั้นใช้ Gemini หรือ OpenAI พร้อม Structured Outputs เพื่อถามทีละคำถามและสรุปข้อมูลให้บุคลากรตรวจ

> ขอบเขต: ระบบช่วยงาน (decision support) ไม่ใช่เครื่องวินิจฉัย ไม่ให้คำแนะนำยา และห้ามใช้งานกับผู้ป่วยจริงก่อนผ่าน clinical validation, privacy/legal review, security review และการอนุมัติของสถานพยาบาล

## Local Dev

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env
# ตั้ง APP_ENV=development, DATABASE_URL=sqlite:///morpromkui.db, AI_PROVIDER=stub
# สร้าง STAFF_PASSWORD_HASH ด้วย: python scripts/make_password_hash.py
flask --app app:create_app init-db
flask --app app:create_app run --debug
```

Open `http://127.0.0.1:5000` , admin `/staff/login`

## Tasting

```bash
pytest -q
python scripts/evaluate_triage.py
```

อ่านเกณฑ์ Emergency และความหมายของ Recall/Precision/FN/FP
[docs/TRIAGE_VALIDATION_TH.md](docs/TRIAGE_VALIDATION_TH.md)

## Deploy

ทดลองออนไลน์บน Render: อ่าน [คู่มือ Render ภาษาไทย](docs/RENDER_TH.md)
มี `render.yaml` สำหรับเว็บและ PostgreSQL โดยเริ่มในโหมด `stub` ที่ไม่ต้องใช้ API key

read [docs/DEPLOY_TH.md](docs/DEPLOY_TH.md) in order , don't upload `.env` to Git and don't put API key in JS

## Structure

- `app/routes.py` — API, หน้าใช้งาน, staff auth และ audit events
- `app/safety.py` — กฎสัญญาณอันตรายที่ทำงานก่อน AI
- `app/ai.py` — Gemini/OpenAI พร้อม Pydantic Structured Output และ safe fallback
- `app/models.py` — PostgreSQL schema
- `Caddyfile` — reverse proxy + HTTPS อัตโนมัติ
- `docker-compose.yml` — app + PostgreSQL + Caddy
- `tests/` — safety, API, authentication และ clinical review flow
- `docs/PITCH_AND_PILOT_TH.md` — กลุ่มเป้าหมาย เดโม KPI และแผนนำร่อง
- `docs/TRIAGE_VALIDATION_TH.md` — เกณฑ์ Emergency, regression corpus และวิธีวัดผล

## Ability UI 

- เริ่มเคสใหม่ได้หลายครั้ง โดยเคสเดิมยังอยู่ในแดชบอร์ด
- ซักประวัติแบบปรับตามบริบทประมาณ 8–12 คำถาม
- สรุปอาการ ประวัติยา/แพ้ยา ผ่าตัด ครอบครัว การสัมผัส การเดินทาง และค่าสัญญาณชีพ
- บัญชีเจ้าหน้าที่หลายคน พร้อมสิทธิ์ `admin` และ `staff`
- Admin สร้าง ระงับ และตั้งรหัสผ่านบัญชีจากหน้าเว็บ
- UI สีแดง–ขาวสไตล์องค์กรการแพทย์สากล รองรับมือถือและอ่านง่ายขึ้น
- ใช้ visual language ทางการแพทย์โดยไม่ใช้ตรากาชาดที่ได้รับความคุ้มครอง

## Safety Properties 

1. กฎฉุกเฉินทำงานก่อนเรียกโมเดล
2. ผู้ป่วยเห็น 1669 เมื่อพบ red flag
3. Structured Outputs บังคับรูปแบบข้อมูล
4. Output guard บล็อกคำวินิจฉัยและคำแนะนำยาแบบชัดเจน
5. เมื่อ AI ล่ม ระบบใช้แบบคำถามสำรองและไม่สร้างคำวินิจฉัย
6. AI urgency เป็นเพียง suggestion; ช่อง clinician urgency แยกต่างหาก
7. ไม่เก็บชื่อ เบอร์โทร เลขบัตร หรือที่อยู่ใน MVP และปฏิเสธรูปแบบตัวเลข/อีเมลพื้นฐาน
8. Patient API ใช้ token แบบสุ่มและเก็บเฉพาะ hash
9. หน้าเจ้าหน้าที่ใช้ hashed password, secure session, CSRF และ HTTPS
10. มีคำสั่ง purge ตาม retention และลบเคสรายบุคคล
