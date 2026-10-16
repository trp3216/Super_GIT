# แผนระบายเจ้าพระยา 3 มิติ

หน้าเว็บ 3 มิติแบบโต้ตอบ อธิบายแผนการระบายน้ำเขื่อนเจ้าพระยา 16–25 ต.ค. 2569 (ไฟล์เดียว `index.html` + Three.js r128 ใน `vendor/`)

## เผยแพร่บน Cloudflare R2 (GitHub Actions)

Workflow `.github/workflows/deploy-r2.yml` จะอัปโหลดขึ้น bucket `chao-phraya-3d` และเปิด r2.dev ให้อัตโนมัติ
ทุกครั้งที่ push ไฟล์ในโฟลเดอร์นี้ไปยัง `main` หรือ `claude/sweet-goodall-crjy27` หรือกดรันเองที่แท็บ Actions

ตั้งค่าครั้งแรก:

1. Cloudflare dashboard → My Profile → API Tokens → Create Token → Custom token
   ให้สิทธิ์ **Account → Workers R2 Storage → Edit** (เลือกบัญชีของคุณ)
2. คัดลอก **Account ID** (หน้า R2 หรือ Workers & Pages ด้านขวา)
3. GitHub → repo → Settings → Secrets and variables → Actions → New repository secret
   - `CLOUDFLARE_API_TOKEN` = token จากข้อ 1
   - `CLOUDFLARE_ACCOUNT_ID` = Account ID จากข้อ 2
4. Actions → **Deploy Chao Phraya 3D to R2** → Run workflow
   ลิงก์เว็บจะแสดงใน Summary ของงาน ในรูป `https://pub-….r2.dev/index.html`

> r2.dev ไม่เปิด `index.html` ให้อัตโนมัติ ต้องใส่ `/index.html` ท้ายลิงก์
> r2.dev มีการจำกัดอัตราการเข้าถึง เหมาะกับการทดสอบหรือแชร์ภายใน ถ้าจะใช้งานจริงควรผูก custom domain ที่ R2 → bucket → Settings → Custom Domains

## รันเองจากเครื่อง

```bash
export CLOUDFLARE_API_TOKEN=...   CLOUDFLARE_ACCOUNT_ID=...
bash chao_phraya_3d/deploy.sh     # ตั้ง BUCKET=ชื่ออื่น ได้ถ้าต้องการ
```

ต้องมี Node.js 22 ขึ้นไป (สคริปต์เรียก `npx wrangler` เวอร์ชันที่ pin ไว้)
