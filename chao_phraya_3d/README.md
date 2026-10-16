# แผนระบายเจ้าพระยา 3 มิติ

หน้าเว็บ 3 มิติแบบโต้ตอบ อธิบายแผนการระบายน้ำเขื่อนเจ้าพระยา 16–25 ต.ค. 2569
พร้อม**คลังแผนการระบาย**: อัปโหลด PDF ของแต่ละวัน แสดงเป็นภาพย่อ และคลิกดูฉบับเต็มได้

| ส่วน | ไฟล์ |
|---|---|
| หน้าเว็บ (Three.js r128, pdf.js 3.11.174 ใน `vendor/`) | `public/index.html` |
| Cloudflare Worker: API คลังแผน + เสิร์ฟไฟล์ | `worker/index.js`, `wrangler.toml` |
| แผนฉบับแรก (16 ต.ค. 2569) ที่ใส่ในคลังตอน deploy ครั้งแรก | `seed/` |
| สคริปต์ deploy | `deploy.sh` |

ไฟล์ PDF และภาพย่อเก็บใน R2 bucket `chao-phraya-3d` ที่ `plans/<วันที่>-<รหัส>.pdf` / `.jpg`
ภาพย่อสร้างในเบราว์เซอร์จากหน้าแรกของ PDF ตอนอัปโหลด

## Deploy (GitHub Actions)

Workflow `.github/workflows/deploy-r2.yml` รันเมื่อ push ไฟล์ในโฟลเดอร์นี้ไปที่ `main` หรือ `claude/sweet-goodall-crjy27` หรือกดรันเองที่แท็บ Actions
ลิงก์เว็บ (`https://chao-phraya-3d.<subdomain>.workers.dev`) จะแสดงใน Summary ของงาน

Repository secrets (Settings → Secrets and variables → Actions):

| Secret | ค่า |
|---|---|
| `CLOUDFLARE_API_TOKEN` | Custom token ที่มีสิทธิ์ **Account → Workers R2 Storage → Edit** และ **Account → Workers Scripts → Edit** |
| `CLOUDFLARE_ACCOUNT_ID` | Account ID ของ Cloudflare |
| `UPLOAD_PASSWORD` | รหัสผ่านสำหรับอัปโหลด/ลบแผนในคลัง (ถ้าไม่ตั้ง คลังจะเปิดดูได้อย่างเดียว) |

ถ้าบัญชี Cloudflare ยังไม่เคยใช้ Workers ให้เข้า **Workers & Pages** ใน dashboard หนึ่งครั้งเพื่อตั้ง workers.dev subdomain ก่อน

ลิงก์ r2.dev เดิมจะพาไปที่เว็บใหม่บน workers.dev ให้อัตโนมัติ

## API

| Method | Path | หมายเหตุ |
|---|---|---|
| GET | `/api/plans` | รายการแผน เรียงวันที่ใหม่ → เก่า |
| POST | `/api/plans` | multipart: `pdf`, `thumb` (JPEG), `date` (YYYY-MM-DD) · header `Authorization: Bearer <รหัสผ่าน>` |
| DELETE | `/api/plans/<id>` | header เดียวกับ POST |
| GET | `/files/plans/<id>.pdf` / `.jpg` | ไฟล์ในคลัง |

## ทดสอบในเครื่อง

```bash
cd chao_phraya_3d
npx wrangler@4.140.0 dev --local --var UPLOAD_PASSWORD:test   # เปิด http://localhost:8787
```

## Deploy เองจากเครื่อง

```bash
export CLOUDFLARE_API_TOKEN=...  CLOUDFLARE_ACCOUNT_ID=...  UPLOAD_PASSWORD=...
bash chao_phraya_3d/deploy.sh
```

ต้องมี Node.js 22 ขึ้นไป (สคริปต์เรียก `npx wrangler` เวอร์ชันที่ pin ไว้)
