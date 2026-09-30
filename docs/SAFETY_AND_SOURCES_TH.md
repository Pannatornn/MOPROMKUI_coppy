# Safety, compliance และแหล่งทางการ

เอกสารนี้เป็น engineering checklist ไม่ใช่คำปรึกษากฎหมายหรือการรับรองทางคลินิก

## หลักที่ใช้ในการออกแบบ

- **Human oversight:** AI สร้างคำถามและสรุป แต่บุคลากรเห็น transcript และยืนยัน urgency เอง
- **Emergency first:** rule engine ทำงานก่อนโมเดล และแสดง 1669 เมื่อพบข้อความที่ตรงกับกฎ
- **Data minimization:** MVP ไม่ต้องการ direct identifiers และปฏิเสธรูปแบบเลขบัตร/เบอร์โทร/อีเมลพื้นฐาน
- **Traceability:** audit event เก็บ prompt version, model, provider และ request id โดยไม่เก็บ prompt ซ้ำใน log
- **Graceful degradation:** ถ้า AI ล่ม ระบบเปลี่ยนเป็นแบบคำถามคงที่ที่ไม่วินิจฉัย
- **No silent RAG:** ห้ามเพิ่มเอกสารทางการแพทย์เข้าฐานค้นคืนจนกว่าจะมี owner, version, review date และ clinical sign-off

## แหล่งอ้างอิงที่ต้องทบทวนก่อน pilot

1. OpenAI Developer Quickstart — Responses API และ server-side API key: https://developers.openai.com/api/docs/quickstart
2. OpenAI Structured Outputs — Pydantic schema และ `responses.parse`: https://developers.openai.com/api/docs/guides/structured-outputs
3. OpenAI Production Best Practices — key management, staging, rate/spend limits, compliance: https://developers.openai.com/api/docs/guides/production-best-practices
4. WHO Ethics and governance of AI for health: https://www.who.int/publications/i/item/9789240029200
5. WHO guidance for large multi-modal models in health: https://www.who.int/news/item/18-01-2024-who-releases-ai-ethics-and-governance-guidance-for-large-multi-modal-models
6. ประกาศแพทยสภา 54/2563 เรื่องโทรเวชและคลินิกออนไลน์: https://www.tmc.or.th/download/ประกาศ%20โทรเวชกรรม%202563.PDF
7. สถาบันการแพทย์ฉุกเฉินแห่งชาติ — เจ็บป่วยฉุกเฉิน โทร 1669: https://www.niems.go.th/
8. GPPC/PDPC privacy policy ตัวอย่างหัวข้อ controller, purpose, third party, cross-border, security, retention และ data-subject rights: https://gppc.pdpc.or.th/privacy-policy/
9. Docker Engine on Ubuntu: https://docs.docker.com/engine/install/ubuntu/
10. Caddy Automatic HTTPS: https://caddyserver.com/docs/automatic-https

## สิ่งที่ยังต้องให้ผู้เชี่ยวชาญยืนยัน

- clinical protocol และ red-flag coverage รวมคำปฏิเสธ คำผิด ภาษาถิ่น และอาการในเด็ก/ผู้สูงอายุ/การตั้งครรภ์
- สถานะผลิตภัณฑ์ตามกฎหมายสถานพยาบาล เครื่องมือแพทย์ โทรเวช และวิชาชีพที่เกี่ยวข้อง
- lawful basis สำหรับข้อมูลสุขภาพ, consent wording, processor agreement, cross-border transfer และ retention
- การตั้งค่าและสัญญาของผู้ให้บริการ AI ที่เหมาะกับข้อมูลจริงขององค์กร
- incident response, breach notification, access control, backup/restore และ audit retention

