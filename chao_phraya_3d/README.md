# แผนระบายเจ้าพระยา 3 มิติ

หน้าเว็บ 3 มิติแบบโต้ตอบ อธิบายแผนการระบายน้ำเขื่อนเจ้าพระยา 16–25 ต.ค. 2569
พร้อม**คลังแผนการระบาย**: อัปโหลด PDF ของแต่ละวัน แสดงเป็นภาพย่อ และคลิกดูฉบับเต็มได้

| ส่วน | ไฟล์ |
|---|---|
| หน้าเว็บ (Three.js r128, pdf.js 3.11.174 ใน `vendor/`) | `public/index.html` |
| ตัวอ่านตัวเลขจาก PDF (ใช้ทั้งในเบราว์เซอร์และ Worker) | `public/plan-parser.js` |
| Cloudflare Worker: API คลังแผน + เสิร์ฟไฟล์ | `worker/index.js`, `wrangler.toml` |
| แผนฉบับแรก (16 ต.ค. 2569) + ตัวเลขที่อ่านแล้ว ที่ใส่ในคลังตอน deploy ครั้งแรก | `seed/` |
| สคริปต์ deploy | `deploy.sh` |
| ข้อมูลภูมิศาสตร์ของฉาก 3 มิติ (สร้างจากสคริปต์) | `public/geo.js` ← `tools/build_geo.py` |

ไฟล์ PDF ภาพย่อ และตัวเลขของแผนเก็บใน R2 bucket `chao-phraya-3d` ที่ `plans/<วันที่>-<รหัส>.pdf` / `.jpg` / `.json`

## ภาพ 3 มิติอัปเดตตาม PDF

ตอนอัปโหลด เบราว์เซอร์ใช้ pdf.js + `public/plan-parser.js` อ่านตัวเลขจาก PDF รูปแบบเดียวกับฉบับ 16 ต.ค. 2569 (4 หน้า):

| ข้อมูล | อ่านจาก |
|---|---|
| วันที่ แผนระบาย ระดับเหนือเขื่อน พระราม 8 (+เวลา) การผันน้ำรวมและราย ปตร. ข้อมูล C.2 / ป่าสัก | หน้าตาราง “ค่ากำหนดการบริหารจัดการน้ำ” |
| น้ำไหลมาถึงหน้าเขื่อน และน้ำไหลเข้าสุทธิ | หน้า “ปริมาณน้ำไหลมาถึงหน้าเขื่อน” |
| น้ำขึ้นสูงสุดที่สันดอน | หน้าแรก กราฟที่ 3 |
| ระดับ C.29B C.38 C.22A C.12 และระดับตลิ่ง | หน้า “ระดับน้ำสูงสุดรายวัน เขตน้ำขึ้นลง” |

ผลที่อ่านได้จะแสดงให้ตรวจก่อนกดอัปโหลด และตรวจซ้ำที่ Worker (`PlanParser.validate`)
เว็บแสดงแผนล่าสุดที่มีตัวเลขโดยอัตโนมัติ เลือกฉบับก่อนหน้าได้จากคลัง (ปุ่ม “แสดงในภาพ 3 มิติ”) หรือลิงก์ `#plan-<id>`
ถ้าอ่านตัวเลขไม่ได้ (เช่น รูปแบบเอกสารเปลี่ยน) ไฟล์ยังเก็บในคลังได้ แต่ภาพ 3 มิติจะไม่เปลี่ยน
แผนที่มีเฉพาะ PDF เปิดดูแล้วกด “อ่านตัวเลขจาก PDF อีกครั้ง” ได้ (เช่น หลังปรับตัวอ่าน) ถ้าอ่านได้ ใส่รหัสผ่านแล้วบันทึก แผนนั้นจะใช้กับภาพ 3 มิติได้โดยไม่ต้องอัปโหลดใหม่

ทดสอบตัวอ่านกับไฟล์ในเครื่อง (ต้องมี `pdfjs-dist@3.11.174`):

```bash
node -e "const pdfjs=require('pdfjs-dist/legacy/build/pdf.js'),P=require('./chao_phraya_3d/public/plan-parser.js'),fs=require('fs');
pdfjs.getDocument({data:new Uint8Array(fs.readFileSync('chao_phraya_3d/seed/2026-10-16.pdf'))}).promise.then(P.parse).then(r=>console.log(r))"
```

## แผนที่จริงและขอบเขตการปกครอง

ฉาก 3 มิติวางตามพิกัดจริง (UTM 47N, 0.8 หน่วย/กม. ทิศเหนืออยู่ซ้าย) จาก `public/geo.js`:

- เส้นลำน้ำเจ้าพระยา ป่าสัก สะแกกรัง: `แม่น้ำ คลอง/Main_River.shp` (ใช้เส้นตลิ่งฝั่งหนึ่งเป็นแนวลำน้ำ)
- ขอบเขตจังหวัด/อำเภอ ชื่อไทย: [OpenGISData-Thailand](https://github.com/chingchai/OpenGISData-Thailand) (CC BY 4.0)
- ตำแหน่งเขื่อนเจ้าพระยา สถานี C.29B C.38 C.22A สะพานพระราม 8 เป็นพิกัดโดยประมาณที่ snap เข้าลำน้ำ ; C.12 วางเหนือพระราม 8 ราว 3 กม. ตามเอกสาร
- แม่น้ำน้อย (ต้นน้ำที่ ปตร.บรมธาตุ) และแม่น้ำท่าจีน/สุพรรณ (ต้นน้ำที่ ปตร.พลเทพ) ใช้เส้นจริงจาก shapefile
- ปตร.มะขามเฒ่า-กระเสียว อยู่ที่ปากคลองมะขามเฒ่า (~30 กม. เหนือเขื่อน) ; ปตร.มะขามเฒ่า-อู่ทอง อยู่ฝั่งเดียวกันเหนือขึ้นไป ~5 กม. (ตำแหน่งแผนผัง)
  ทั้งสองแยกช่องน้ำกัน ออกจากตลิ่งแล้วไหลคู่ตามแนวคลองมะขามเฒ่าจริง (`Main_canal.shp`)
  แล้วต่อไปยังเส้นจริงของคลองมะขามเฒ่าอู่ทอง/คลองกระเสียว ; ช่วงเชื่อมที่ไม่มีในข้อมูล (~31 กม. และ ~10 กม.) วาดเป็นเส้นตรง (`canalGaps` ใน geo.js)
- อาคาร ปตร. ทุกแห่งวางห่างจากลำน้ำเจ้าพระยาพอให้อยู่บนตลิ่ง ไม่จมใต้ผิวน้ำในภาพ
- ปตร.มโนรมย์และมหาราชอยู่ฝั่งซ้าย (ตะวันออก) ; มหาราชอยู่เหนือเขื่อนเล็กน้อย คลองไหลขนานลำน้ำทางฝั่งซ้าย มโนรมย์อยู่เหนือขึ้นไป ~30 กม. คลองแยกไปทางตะวันออก
  ไม่มีแนวคลองทั้งสองใน shapefile จึงยังเป็นแผนผังเช่นเดียวกับคลองย่อย (ตรวจแล้วว่าไม่ตัดข้ามแม่น้ำเจ้าพระยา)
- คลองย่อย/อื่น ๆ (แผนผัง) รับน้ำฝั่งขวาเหนือเขื่อน ~7 กม. ไหลลงใต้ระหว่างแม่น้ำท่าจีนกับแม่น้ำน้อย ไม่ทับลำน้ำทั้งสอง
- ความกว้างลำน้ำและความสูงขยายเพื่อให้มองเห็น

สร้าง `geo.js` ใหม่ (เช่น แก้พิกัดสถานีใน `ANCHORS` ของสคริปต์):

```bash
pip install pyshp shapely pyproj
mkdir -p /tmp/gb && cd /tmp/gb
curl -LO https://raw.githubusercontent.com/chingchai/OpenGISData-Thailand/master/provinces.geojson
curl -LO https://raw.githubusercontent.com/chingchai/OpenGISData-Thailand/master/districts.geojson
cd - && python chao_phraya_3d/tools/build_geo.py --boundaries /tmp/gb
```

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
| POST | `/api/plans` | multipart: `pdf`, `thumb` (JPEG), `date` (YYYY-MM-DD), `data` (JSON ตัวเลขแผน, ไม่บังคับ) · header `Authorization: Bearer <รหัสผ่าน>` |
| DELETE | `/api/plans/<id>` | header เดียวกับ POST |
| PUT | `/api/plans/<id>/data` | body: JSON ตัวเลขแผน (ตรวจด้วย `PlanParser.validate`) เพิ่มหรือแทนตัวเลขของแผนที่มีอยู่ · header เดียวกับ POST |
| GET | `/files/plans/<id>.pdf` / `.jpg` / `.json` | ไฟล์ในคลัง |

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
