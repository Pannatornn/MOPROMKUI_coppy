# Deploy หมอพร้อมคุยบน `team6.105app.site`

คู่มือนี้สมมติว่า server เป็น Ubuntu 24.04/22.04, DNS ของโดเมนชี้มายัง public IP แล้ว และคุณมีสิทธิ์ `root` ทาง SSH หากระบบปฏิบัติการไม่ใช่ Ubuntu ให้หยุดและใช้คู่มือ Docker Engine ของระบบนั้นแทน

## 0. ทำทันที: เปลี่ยน credential ที่เปิดเผยแล้ว

รหัสผ่าน `root` ที่เคยส่งในแชตถือว่าเปิดเผยแล้ว อย่าใส่รหัสนั้นในไฟล์หรือคำสั่งด้านล่าง

บน server:

```bash
passwd root
```

จากเครื่องของคุณ สร้าง SSH key หากยังไม่มี:

```bash
ssh-keygen -t ed25519 -a 100
ssh-copy-id root@team6.105app.site
```

เปิด terminal ใหม่และยืนยันว่าเข้าได้ด้วย key ก่อนปิด password login จากนั้นแก้ `/etc/ssh/sshd_config.d/99-hardening.conf` ให้มี:

```text
PermitRootLogin prohibit-password
PasswordAuthentication no
```

ตรวจและ reload โดยไม่ตัด session ปัจจุบัน:

```bash
sshd -t
systemctl reload ssh
```

## 1. ตรวจ server และ DNS

```bash
cat /etc/os-release
uname -m
getent hosts team6.105app.site
curl -4 ifconfig.me
```

IP จากสองคำสั่งท้ายต้องตรงกัน หากไม่ตรงให้แก้ A record ก่อน เพราะ Caddy ขอ TLS certificate ไม่สำเร็จหาก DNS ไม่ชี้เข้า server

แนะนำอย่างน้อย 2 vCPU, RAM 2 GB, disk ว่าง 10 GB สำหรับ pilot ขนาดเล็ก

## 2. อัปเดตระบบและติดตั้ง Docker Engine

```bash
apt-get update
apt-get upgrade -y
apt-get install -y ca-certificates curl unzip ufw
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc
cat > /etc/apt/sources.list.d/docker.sources <<EOF
Types: deb
URIs: https://download.docker.com/linux/ubuntu
Suites: $(. /etc/os-release && echo "${UBUNTU_CODENAME:-$VERSION_CODENAME}")
Components: stable
Architectures: $(dpkg --print-architecture)
Signed-By: /etc/apt/keyrings/docker.asc
EOF
apt-get update
apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
docker run --rm hello-world
docker compose version
```

## 3. Firewall

เช็กพอร์ต SSH จริงก่อนเปิด UFW:

```bash
sshd -T | grep '^port '
```

ถ้าเป็นพอร์ต 22:

```bash
ufw allow 22/tcp
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable
ufw status verbose
```

หาก SSH ใช้พอร์ตอื่น ให้ allow พอร์ตนั้นก่อน `ufw enable` มิฉะนั้นจะล็อกตัวเองออกจาก server

## 4. นำไฟล์ขึ้น server

ดาวน์โหลด `mo-prom-kui.zip` จาก ChatGPT ไว้ในเครื่องคุณ แล้วรันจากเครื่องคุณ:

```bash
scp mo-prom-kui.zip root@team6.105app.site:/opt/
```

บน server:

```bash
cd /opt
unzip mo-prom-kui.zip
cd /opt/mo-prom-kui
cp .env.example .env
chmod 600 .env
```

## 5. สร้าง secrets และแก้ `.env`

สร้างค่าใหม่:

```bash
openssl rand -hex 32
openssl rand -hex 24
```

- ค่าที่ 1 ใส่ใน `SECRET_KEY`
- ค่าที่ 2 ใส่ทั้ง `POSTGRES_PASSWORD` และแทนส่วนรหัสผ่านใน `DATABASE_URL`
- เพราะค่าที่สร้างเป็นเลขฐาน 16 จึงไม่ต้อง URL-encode

สร้าง staff password hash หลัง build image:

```bash
docker compose build app
docker compose run --rm --no-deps --entrypoint python app scripts/make_password_hash.py
```

คัดลอกบรรทัด hash ที่ขึ้นต้นด้วย `scrypt:` ไปใส่ `STAFF_PASSWORD_HASH` **ภายใน single quotes** เพราะ hash มีเครื่องหมาย `$` เช่น `STAFF_PASSWORD_HASH='scrypt:...$...$...'` และตั้ง `STAFF_USERNAME` เป็นชื่อที่เดายากกว่าค่าเริ่มต้น

สร้าง OpenAI project แยกสำหรับ pilot, ตั้ง spend limit และสร้าง API key แล้วใส่ใน `OPENAI_API_KEY` ห้ามวาง key ใน frontend หรือ Git ค่าโมเดลแนะนำเริ่มต้นคือ:

```text
OPENAI_MODEL=gpt-5.6-terra
AI_PROVIDER=openai
```

ตรวจค่าที่เหลือ:

```text
DOMAIN=team6.105app.site
CLINIC_NAME=ชื่อคลินิกหรือ Demo Clinic
PRIVACY_CONTACT=อีเมลผู้รับผิดชอบจริง
DATA_RETENTION_DAYS=30
```

ตรวจว่าไม่มี placeholder โดยไม่พิมพ์ secrets ออกจอ:

```bash
if grep -q 'CHANGE_ME' .env; then echo 'ยังมี CHANGE_ME ใน .env'; exit 1; fi
docker compose config --quiet
```

## 6. เปิดระบบ

```bash
docker compose up -d --build
docker compose ps
docker compose logs --tail=100 app caddy
curl --fail --silent --show-error https://team6.105app.site/healthz
```

ผล health check ต้องเป็น `{"status":"ok"}` จากนั้นเปิด:

- ผู้รับบริการ: `https://team6.105app.site/intake`
- เจ้าหน้าที่: `https://team6.105app.site/staff/login`

รันทดสอบปลายทาง:

```bash
chmod +x scripts/smoke_test.sh scripts/backup.sh
./scripts/smoke_test.sh https://team6.105app.site
```

Smoke test จะสร้างเคสทดสอบหนึ่งเคส ให้ลบจากหน้าเจ้าหน้าที่หลังตรวจเสร็จ

## 7. ชุดทดสอบก่อนเดโม

ทดสอบอย่างน้อย 6 สถานการณ์และบันทึกผล:

1. อาการทั่วไป → AI ถามทีละคำถาม
2. `เจ็บแน่นหน้าอกและหายใจไม่ออก` → หยุด flow และแสดง 1669
3. `ไม่มีเจ็บแน่นหน้าอก` → ไม่ควร trigger กฎหน้าอก
4. ใส่เบอร์โทร → API ปฏิเสธข้อมูลระบุตัว
5. ปิด/ลบ `OPENAI_API_KEY` ชั่วคราว → safe fallback ยังถามต่อได้
6. เจ้าหน้าที่เปิด transcript และยืนยัน urgency ได้

รัน unit tests ใน image:

```bash
docker compose run --rm --no-deps --user root --entrypoint sh app -c 'pip install -r requirements-dev.txt >/dev/null && pytest -q'
```

## 8. Backup, retention และ restore drill

รัน backup (สคริปต์อ่านชื่อฐานข้อมูลจาก environment ภายใน container จึงไม่ source `.env` เข้าสู่ shell):

```bash
./scripts/backup.sh
```

ตั้ง cron ด้วย `crontab -e`:

```cron
0 2 * * * cd /opt/mo-prom-kui && ./scripts/backup.sh >> /var/log/morpromkui-maintenance.log 2>&1
15 2 * * * cd /opt/mo-prom-kui && docker compose exec -T app flask --app app:create_app purge-expired >> /var/log/morpromkui-maintenance.log 2>&1
```

ทดสอบ restore ใน database แยกก่อนเปิดใช้จริง ห้ามถือว่ามี backup จนกว่าจะ restore สำเร็จอย่างน้อยหนึ่งครั้ง

## 9. อัปเดตและ rollback

ก่อนอัปเดต:

```bash
cd /opt/mo-prom-kui
./scripts/backup.sh
docker compose pull
docker compose up -d --build
docker compose ps
```

เก็บ zip รุ่นก่อนและ `.env` แยกจาก source หากรุ่นใหม่มีปัญหา ให้นำ source รุ่นก่อนกลับมาแล้ว `docker compose up -d --build` อย่าลบ PostgreSQL volume

รุ่นนี้สร้าง schema ครั้งแรกด้วย `db.create_all()` ซึ่งเพียงพอสำหรับ initial deploy แต่จะไม่แก้ตารางเดิมเมื่อ schema เปลี่ยน ก่อนพัฒนารุ่นถัดไปที่แก้ database schema ต้องเพิ่ม Alembic/Flask-Migrate และทดสอบ migration + rollback กับสำเนาฐานข้อมูลก่อน

## 10. เกณฑ์ผ่านก่อน pilot กับคนจริง

- แพทย์/พยาบาลเจ้าของ protocol ลงนามรับรอง red flags และคำถามทุกข้อ
- ทำ test set อย่างน้อย 100 เคส (รวม negation, คำผิด, ภาษาพูด, ผู้สูงอายุ และข้อมูลไม่ครบ)
- false negative ของ emergency test set ต้องเป็นศูนย์ตามชุดที่ clinical owner อนุมัติ
- มีเจ้าหน้าที่ monitor dashboard ตลอดช่วงเปิดรับข้อมูล
- มี privacy notice, lawful basis, DPA/vendor review, cross-border transfer review และขั้นตอนใช้สิทธิที่ตรวจโดยผู้เชี่ยวชาญไทย
- ทำ penetration/security review, restore drill, incident response และ access review
- ผู้ใช้ทุกคนเห็นข้อจำกัดและช่องทาง 1669 ชัดเจน
- ห้ามต่อ HIS/EMR หรือเรียกตัวเองว่าเครื่องมือแพทย์จนกว่าจะประเมินข้อกฎหมาย/มาตรฐานที่เกี่ยวข้อง

## Troubleshooting สั้น ๆ

```bash
docker compose ps
docker compose logs --tail=200 app
docker compose logs --tail=200 db
docker compose logs --tail=200 caddy
ss -lntp | grep -E ':80|:443'
```

- TLS ไม่ออก: ตรวจ DNS, firewall 80/443 และ Caddy log
- app unhealthy: ตรวจ `.env`, `DATABASE_URL`, database health และ production config validation
- AI ใช้ไม่ได้: ตรวจ project key, model access, spend/rate limit; ระบบจะใช้ safe fallback
- login ไม่ได้: สร้าง hash ใหม่และ `docker compose up -d --force-recreate app`
