# อัปเดตหมอพร้อมคุยให้ใช้ Gemini Free Tier

เอกสารนี้ใช้กับเซิร์ฟเวอร์ที่มีโปรเจกต์อยู่ที่ `/opt/mo-prom-kui` และมีไฟล์ `.env` เดิมแล้ว

> ใช้ข้อมูลผู้ป่วยสมมติสำหรับงานแข่งเท่านั้น ห้ามใส่ชื่อ เบอร์โทร เลขบัตร ที่อยู่ หรือข้อมูลผู้ป่วยจริงใน Free Tier

## 1. อัปโหลดไฟล์จาก Windows PowerShell

```powershell
cd $HOME\Downloads
scp .\mo-prom-kui-gemini.zip root@team6.105app.site:/opt/
```

## 2. สำรองและอัปเดตโค้ดบนเซิร์ฟเวอร์

```bash
cd /opt/mo-prom-kui
cp .env /root/mo-prom-kui.env.backup
unzip -o /opt/mo-prom-kui-gemini.zip -d /opt/mo-prom-kui
```

ไฟล์ ZIP ไม่มี `.env` จึงไม่ทับรหัสฐานข้อมูลหรือบัญชีเจ้าหน้าที่เดิม

## 3. ตั้ง Gemini key แบบไม่บันทึกใน shell history

ยกเลิกคีย์ที่เคยส่งในแชต แล้วสร้างคีย์ใหม่ก่อน จากนั้นรัน:

```bash
cd /opt/mo-prom-kui
read -rsp "วาง Gemini API key ใหม่: " MOPROM_GEMINI_KEY
echo
sed -i '/^AI_PROVIDER=/d;/^GEMINI_API_KEY=/d;/^GEMINI_MODEL=/d' .env
{
  printf 'AI_PROVIDER=gemini\n'
  printf 'GEMINI_API_KEY=%s\n' "$MOPROM_GEMINI_KEY"
  printf 'GEMINI_MODEL=gemini-3.6-flash\n'
} >> .env
unset MOPROM_GEMINI_KEY
chmod 600 .env
```

ตรวจเฉพาะชื่อการตั้งค่าโดยไม่แสดงคีย์:

```bash
grep -E '^(AI_PROVIDER|GEMINI_MODEL)=' .env
grep -q '^GEMINI_API_KEY=.' .env && echo 'OK: พบ Gemini key'
```

## 4. Build และเปิดระบบ

```bash
cd /opt/mo-prom-kui
docker compose build app
docker compose up -d
docker compose ps
```

รอประมาณ 20–60 วินาที แล้วตรวจสอบ:

```bash
curl -fsS https://team6.105app.site/healthz && echo
docker compose logs --tail=80 app
```

ห้ามส่งผล `cat .env`, `env` หรือคีย์มาในแชต หากมีปัญหาให้ส่งเฉพาะ `docker compose ps` และ log ที่ไม่มี secret

## 5. ทดสอบเดโม

1. เปิด `https://team6.105app.site`
2. เริ่มเคสด้วยข้อมูลสมมติ เช่น “ปวดท้องมา 2 ชั่วโมง ระดับ 5/10”
3. ตรวจว่า AI ถามครั้งละหนึ่งคำถาม
4. ทดสอบ red flag สมมติ เช่น “เจ็บหน้าอกและหายใจไม่ออก” ระบบต้องแสดงคำแนะนำฉุกเฉิน 1669 โดยไม่รอ AI
5. เข้าหน้า `/staff/login` แล้วตรวจสรุปเคส

หาก Gemini โควตาเต็มหรือ API ขัดข้อง ระบบจะเปลี่ยนเป็นคำถามสำรองอัตโนมัติและไม่วินิจฉัยโรค
