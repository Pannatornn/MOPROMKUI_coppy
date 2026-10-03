# ทดลองหมอพร้อมคุยออนไลน์บน Render

ใช้ `render.yaml` ที่ root ของ repository เพื่อสร้าง Docker Web Service และ PostgreSQL ใน Singapore พร้อมกัน โดย Render ให้ URL แบบ `https://ชื่อเว็บ.onrender.com` จึงยังไม่ต้องซื้อโดเมน

ชุดนี้เริ่มด้วย `AI_PROVIDER=stub`: ใช้แบบคำถามสำรองที่มีอยู่ในแอป ยังไม่ได้เรียก AI จริง และไม่ต้องใส่ API key เหมาะสำหรับทดสอบด้วยข้อมูลสมมติ ตามขอบเขตการใช้งานใน README

## 1. เตรียมโค้ดใน GitHub

นำไฟล์ชุดนี้ขึ้น GitHub และตรวจว่า branch ที่จะใช้มี `render.yaml` และการเปลี่ยนแปลงชุดนี้ครบ จากนั้นไป [Render Dashboard](https://dashboard.render.com/) สมัคร/เข้าสู่ระบบและเชื่อมบัญชี GitHub ที่เข้าถึง `Pannatornn/MOPROMKUI_coppy` ได้

หากใช้ ZIP ให้แตกไฟล์และนำไฟล์ภายในโฟลเดอร์ `MOPROMKUI_coppy` ไปไว้ที่ root ของ repository โดยเฉพาะ `render.yaml`, `app/config.py`, `entrypoint.sh` และ `.gitattributes` ไม่วางซ้อนโฟลเดอร์เพิ่มอีกชั้น

## 2. สร้าง Blueprint

1. ใน Render เลือก **New → Blueprint** แล้วเลือก repository นี้
2. เลือก branch ที่มีไฟล์ชุดนี้ และ Blueprint Path เป็น `render.yaml`
3. กรอก `STAFF_USERNAME` เช่น `demo-admin`
4. กรอก `STAFF_PASSWORD` เป็นรหัสผ่านสำหรับหน้าเจ้าหน้าที่อย่างน้อย 14 ตัวอักษร ระบบจะ hash ก่อนบันทึกลงฐานข้อมูล
5. ตรวจหน้าสรุปว่าเว็บและฐานข้อมูลเป็นแผน **Free** แล้วกด Deploy Blueprint

`SECRET_KEY` สร้างอัตโนมัติ และ `DATABASE_URL` เชื่อมจากฐานข้อมูลใน Blueprint ไม่ต้องกรอกเอง หาก workspace มีฐานข้อมูลฟรีอยู่แล้ว อาจสร้างอีกไม่ได้ ให้ตรวจข้อจำกัดใน Dashboard ก่อนเลือกแผนอื่น

ปล่อย Docker Command และ Root Directory เป็นค่าเริ่มต้น แอปจะสร้างตารางและบัญชีผู้ดูแลก่อนเปิด Gunicorn หากสร้างไม่ได้ ระบบจะหยุดพร้อม error ใน Logs ไม่เปิดเว็บที่ยังเตรียมฐานข้อมูลไม่สำเร็จ

ไม่ต้องอัปโหลด `.env` และไม่ต้องรัน Docker Compose หรือ Caddy บน Render

## 4. ตรวจหลังสถานะเป็น Live

ใช้ URL ที่ Render แสดงจริง แล้วเปิด:

| เส้นทาง | ผลที่ควรได้ |
| --- | --- |
| `/healthz` | `{"status":"ok"}` และ HTTP 200 ซึ่งตรวจการเชื่อมฐานข้อมูลด้วย |
| `/intake` | แบบซักประวัติ สร้างเคสด้วยข้อมูลสมมติได้ |
| `/staff/login` | เข้าด้วย username และรหัสผ่านต้นฉบับ ไม่ใช่ hash |

ลองสร้างเคส เข้าหน้าเจ้าหน้าที่ดูเคส จากนั้นใช้ Manual Deploy ของ Render แล้วตรวจว่าเคสและบัญชียังอยู่ เพื่อยืนยันว่าใช้ฐานข้อมูลภายนอกตัวเว็บจริง

โหมด `stub` จะแสดงข้อความว่า AI ไม่พร้อมและใช้แบบคำถามสำรอง เป็นพฤติกรรมที่ตั้งใจสำหรับการทดสอบรอบแรก

## 5. เปิด AI ภายหลัง

เมื่อเว็บและการล็อกอินทำงานแล้ว แก้ค่า `AI_PROVIDER` ใน `render.yaml` เป็น provider ที่เลือก เพื่อไม่ให้ Blueprint sync ครั้งถัดไปเปลี่ยนกลับเป็น `stub` แล้วเพิ่มค่าลับในหน้า **Environment** ของ Web Service:

| Provider | ค่าใน Blueprint | ค่าใน Render Environment |
| --- | --- | --- |
| Gemini | `AI_PROVIDER=gemini` | `GEMINI_API_KEY`, `GEMINI_MODEL` |
| OpenAI | `AI_PROVIDER=openai` | `OPENAI_API_KEY`, `OPENAI_MODEL` |

เลือกชื่อโมเดลที่บัญชีของคุณเข้าถึงได้จากผู้ให้บริการ ไม่ควรถือว่าชื่อโมเดลเริ่มต้นในโค้ดใช้ได้กับทุกบัญชี เก็บ API key ใน Render เท่านั้น แล้ว deploy ใหม่ หากเรียก AI ไม่สำเร็จ แอปจะใช้แบบคำถามสำรอง

หลังเปิด AI แล้ว ผู้ดูแลสามารถเข้าเมนู **ตั้งค่า AI** ในเว็บ เพื่อใส่ API key ใหม่ได้ทันทีเมื่อ key เดิมติดลิมิต โดยไม่ต้อง deploy ใหม่ Key ที่เพิ่มจากหน้านี้จะเข้ารหัสก่อนเก็บใน PostgreSQL และจะไม่แสดงกลับบนหน้าเว็บ ค่านี้มีผลเหนือกว่า key เดิมใน Render; หากกด **กลับไปใช้ค่า Render** ระบบจะลบค่า override และใช้ Environment เดิมอีกครั้ง

## ข้อจำกัดของชุดทดลอง

- เว็บ Free พักหลังไม่มีการใช้งาน 15 นาที การเปิดครั้งแรกหลังพักจึงอาจช้า
- PostgreSQL Free หมดอายุหลังสร้าง 30 วัน ต้องวางแผนอัปเกรดหรือย้ายข้อมูลก่อนหมดอายุ และไม่มี backup อัตโนมัติสำหรับแผนนี้
- ฐานข้อมูลปิดการเชื่อมต่อจากอินเทอร์เน็ตด้วย `ipAllowList: []` เว็บใช้การเชื่อมต่อภายใน Render หากจะ export ด้วย `pg_dump` จากเครื่องตนเอง ให้เพิ่ม IP ของตนเองชั่วคราวในรายการอนุญาตและปิดกลับหลังเสร็จ
- ใช้ Gunicorn 1 process และ rate limiter ในหน่วยความจำ ตัวนับจะรีเซ็ตเมื่อรีสตาร์ต ถ้าจะเพิ่ม process หรือหลาย instance ต้องเปลี่ยนไปใช้ Redis และติดตั้ง dependency ของ Redis ก่อน
- `DATA_RETENTION_DAYS=30` เป็นเกณฑ์ให้คำสั่ง `flask --app app:create_app purge-expired` ไม่ใช่ตัวตั้งเวลาลบอัตโนมัติ Blueprint นี้ไม่ได้สร้างงานตามเวลา
- `init-db` สร้างตารางใหม่ แต่ไม่ย้ายข้อมูลจากเครื่องเดิมและไม่แก้ schema ของตารางเดิม ต้องจัดการ migration แยกเมื่อมีการเปลี่ยน schema
- `STAFF_PASSWORD` จะซิงก์เป็นรหัสของบัญชี `STAFF_USERNAME` ทุกครั้งที่ deploy
- API key ที่บันทึกจากหน้า **ตั้งค่า AI** ถูกเข้ารหัสโดยอาศัย `SECRET_KEY`; อย่าเปลี่ยน `SECRET_KEY` หลังมี key สำรองอยู่ มิฉะนั้น key เหล่านั้นจะอ่านกลับไม่ได้ ให้กด **กลับไปใช้ค่า Render** ก่อนแล้วตั้งใหม่หลังเปลี่ยน secret

## เมื่อ deploy ไม่ผ่าน

- `No module named psycopg2` หรือ `Can't load plugin ... postgres`: ตรวจว่า deploy branch ที่แก้ `app/config.py` แล้ว
- `STAFF_PASSWORD must be at least 14 characters...`: กำหนด `STAFF_PASSWORD` อย่างน้อย 14 ตัวอักษรใน Environment ของ Web Service แล้ว deploy ใหม่
- `SECRET_KEY must be ...`: ตรวจว่า Blueprint สร้าง `SECRET_KEY` แล้ว
- `exec ... no such file` หรือ error ที่มี `\r`: ตรวจ `entrypoint.sh` ให้ใช้ LF; `.gitattributes` ในชุดนี้กำหนดไว้แล้ว
- health check ล้มเหลว: ดู Logs ของเว็บและสถานะฐานข้อมูล ตรวจว่าไม่ได้แทน `DATABASE_URL` ด้วย SQLite หรือ URL ของ Docker ชื่อ `db`
- ล็อกอินไม่ได้: เปิดผ่าน HTTPS และใช้รหัสผ่านต้นฉบับใน `STAFF_PASSWORD` ของ Web Service แล้ว deploy อีกครั้ง

เอกสารอ้างอิง: [Blueprint](https://render.com/docs/blueprint-spec), [Docker](https://render.com/docs/docker), [ข้อจำกัด Free](https://render.com/docs/free)
