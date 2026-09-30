# อัปเดตเป็น UI v3 + Admin/Staff

แพ็กเกจนี้ไม่รวม `.env` และไม่แตะ Docker volumes จึงรักษา API key, รหัสฐานข้อมูล และเคสเดิมไว้

## 1. อัปโหลดจาก Windows PowerShell

```powershell
cd $HOME\Downloads
scp .\mo-prom-kui-gemini.zip root@team6.105app.site:/opt/
```

## 2. อัปเดตบนเซิร์ฟเวอร์

```bash
cd /opt/mo-prom-kui
cp .env /root/mo-prom-kui.env.backup-v3
chmod 600 /root/mo-prom-kui.env.backup-v3
unzip -o /opt/mo-prom-kui-gemini.zip -d /opt/mo-prom-kui
docker compose build app
docker compose up -d --force-recreate app
docker compose ps
```

ระหว่าง startup ระบบจะสร้างตาราง `staff_users` และนำ `STAFF_USERNAME` / `STAFF_PASSWORD_HASH` เดิมมาสร้างบัญชี Admin โดยอัตโนมัติ ข้อมูลเคสเดิมไม่ถูกลบ

## 3. ตรวจระบบ

```bash
curl -fsS https://team6.105app.site/healthz
echo
docker compose logs --tail=80 app
```

เมื่อได้ `{"status":"ok"}` ให้เปิดหน้าเว็บและกด `Ctrl + F5`

## 4. ทดสอบ

1. เปิด `/intake` กรอกเคสสมมติและตรวจว่าปุ่ม “เริ่มเคสใหม่” ใช้งานได้
2. เข้า `/staff/login` ด้วยบัญชีเดิม
3. บัญชีเดิมจะมีสิทธิ์ Admin และเห็นเมนู “จัดการผู้ใช้”
4. สร้างบัญชี Staff ใหม่ด้วยรหัสผ่านอย่างน้อย 12 ตัว
5. ตรวจว่า Staff เปิดและยืนยันเคสได้ แต่เข้าหน้าจัดการผู้ใช้หรือลบเคสไม่ได้

ห้ามใช้ข้อมูลผู้ป่วยจริงกับ Gemini Free Tier และห้ามส่ง `.env`, API key หรือ password hash ในแชต
