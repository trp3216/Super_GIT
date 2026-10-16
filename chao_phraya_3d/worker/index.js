// Chao Phraya 3D site: serves the static page (public/) and an archive of uploaded
// release-plan PDFs stored in R2 under plans/<id>.pdf, with a JPEG thumbnail plans/<id>.jpg
// and, when the page could read the numbers, the plan data plans/<id>.json.
//
//   GET    /api/plans          list archived plans, newest plan date first
//   POST   /api/plans          upload (multipart: pdf, thumb, date, data) — needs Authorization: Bearer <UPLOAD_PASSWORD>
//   DELETE /api/plans/:id      delete one plan — same password
//   GET    /files/plans/<id>.(pdf|jpg|json)
import PlanParser from "../public/plan-parser.js";

const MAX_PDF = 25 * 1024 * 1024;
const MAX_THUMB = 2 * 1024 * 1024;
const MAX_DATA = 256 * 1024;
const ID_RE = /^\d{4}-\d{2}-\d{2}-[a-z0-9]{4,20}$/;
const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;

export default {
  async fetch(req, env) {
    const url = new URL(req.url);
    const path = url.pathname;
    try {
      if (path === "/api/plans") {
        if (req.method === "GET") return await listPlans(env);
        if (req.method === "POST") return await uploadPlan(req, env);
        return json({ error: "method not allowed" }, 405);
      }
      const del = path.match(/^\/api\/plans\/([^/]+)$/);
      if (del) {
        if (req.method !== "DELETE") return json({ error: "method not allowed" }, 405);
        return await deletePlan(req, env, del[1]);
      }
      const file = path.match(/^\/files\/(plans\/[^/]+\.(pdf|jpg|json))$/);
      if (file && (req.method === "GET" || req.method === "HEAD")) return await serveFile(req, env, file[1], file[2]);
      if (path.startsWith("/api/") || path.startsWith("/files/")) return json({ error: "not found" }, 404);
    } catch (err) {
      console.error(err);
      return json({ error: "เกิดข้อผิดพลาดที่เซิร์ฟเวอร์" }, 500);
    }
    return env.ASSETS.fetch(req);
  },
};

function json(body, status = 200, extra = {}) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json; charset=utf-8", "cache-control": "no-store", ...extra },
  });
}

async function listPlans(env) {
  const byId = new Map();
  let cursor;
  do {
    const page = await env.BUCKET.list({ prefix: "plans/", cursor, limit: 1000 });
    for (const obj of page.objects) {
      const m = obj.key.match(/^plans\/(.+)\.(pdf|jpg|json)$/);
      if (!m || !ID_RE.test(m[1])) continue;
      const p = byId.get(m[1]) || { id: m[1], date: m[1].slice(0, 10) };
      if (m[2] === "pdf") {
        p.pdf = `/files/${obj.key}`;
        p.size = obj.size;
        p.uploaded = obj.uploaded.toISOString();
      } else if (m[2] === "jpg") {
        p.thumb = `/files/${obj.key}`;
      } else {
        p.data = `/files/${obj.key}`;
      }
      byId.set(m[1], p);
    }
    cursor = page.truncated ? page.cursor : undefined;
  } while (cursor);
  const plans = [...byId.values()].filter((p) => p.pdf);
  plans.sort((a, b) => (a.date === b.date ? (b.uploaded || "").localeCompare(a.uploaded || "") : b.date.localeCompare(a.date)));
  return json({ plans, canUpload: Boolean(env.UPLOAD_PASSWORD) });
}

async function authorized(req, env) {
  if (!env.UPLOAD_PASSWORD) return false;
  let got = (req.headers.get("authorization") || "").replace(/^Bearer\s+/i, "");
  try {
    got = decodeURIComponent(got); // the page URI-encodes so non-ASCII passwords fit in a header
  } catch {
    return false;
  }
  const enc = new TextEncoder();
  const [a, b] = await Promise.all([
    crypto.subtle.digest("SHA-256", enc.encode(got)),
    crypto.subtle.digest("SHA-256", enc.encode(env.UPLOAD_PASSWORD)),
  ]);
  return crypto.subtle.timingSafeEqual(a, b);
}

function authError(env) {
  return env.UPLOAD_PASSWORD
    ? json({ error: "รหัสผ่านไม่ถูกต้อง" }, 401)
    : json({ error: "ยังไม่ได้ตั้งรหัสผ่านสำหรับอัปโหลด (UPLOAD_PASSWORD)" }, 503);
}

async function startsWith(file, bytes) {
  const head = new Uint8Array(await file.slice(0, bytes.length).arrayBuffer());
  return bytes.every((v, i) => head[i] === v);
}

async function uploadPlan(req, env) {
  if (!(await authorized(req, env))) return authError(env);
  const len = Number(req.headers.get("content-length") || 0);
  if (len > MAX_PDF + MAX_THUMB + MAX_DATA + 64 * 1024) return json({ error: "ไฟล์ใหญ่เกิน 25 MB" }, 413);

  const form = await req.formData();
  const pdf = form.get("pdf");
  const thumb = form.get("thumb");
  const date = String(form.get("date") || "");
  if (!DATE_RE.test(date) || Number.isNaN(Date.parse(date))) return json({ error: "วันที่ของแผนไม่ถูกต้อง" }, 400);
  if (!(pdf instanceof File) || pdf.size === 0) return json({ error: "กรุณาเลือกไฟล์ PDF" }, 400);
  if (pdf.size > MAX_PDF) return json({ error: "ไฟล์ PDF ใหญ่เกิน 25 MB" }, 413);
  if (!(await startsWith(pdf, [0x25, 0x50, 0x44, 0x46, 0x2d]))) return json({ error: "ไฟล์นี้ไม่ใช่ PDF" }, 400);
  const hasThumb = thumb instanceof File && thumb.size > 0;
  if (hasThumb && (thumb.size > MAX_THUMB || !(await startsWith(thumb, [0xff, 0xd8, 0xff])))) {
    return json({ error: "ภาพย่อไม่ถูกต้อง" }, 400);
  }

  let data = null;
  const rawData = form.get("data");
  if (typeof rawData === "string" && rawData) {
    if (rawData.length > MAX_DATA) return json({ error: "ข้อมูลแผนใหญ่เกินไป" }, 413);
    try {
      data = JSON.parse(rawData);
      PlanParser.validate(data);
    } catch (err) {
      return json({ error: "ข้อมูลตัวเลขของแผนไม่ถูกต้อง: " + (err.message || "รูปแบบผิด") }, 400);
    }
  }

  const id = `${date}-${Date.now().toString(36)}`;
  await env.BUCKET.put(`plans/${id}.pdf`, pdf.stream(), { httpMetadata: { contentType: "application/pdf" } });
  if (hasThumb) await env.BUCKET.put(`plans/${id}.jpg`, thumb.stream(), { httpMetadata: { contentType: "image/jpeg" } });
  if (data) await env.BUCKET.put(`plans/${id}.json`, JSON.stringify(data), { httpMetadata: { contentType: "application/json; charset=utf-8" } });
  return json({
    plan: {
      id, date, pdf: `/files/plans/${id}.pdf`,
      thumb: hasThumb ? `/files/plans/${id}.jpg` : undefined,
      data: data ? `/files/plans/${id}.json` : undefined,
    },
  }, 201);
}

async function deletePlan(req, env, id) {
  if (!ID_RE.test(id)) return json({ error: "not found" }, 404);
  if (!(await authorized(req, env))) return authError(env);
  await env.BUCKET.delete([`plans/${id}.pdf`, `plans/${id}.jpg`, `plans/${id}.json`]);
  return json({ deleted: id });
}

async function serveFile(req, env, key, ext) {
  const obj = await env.BUCKET.get(key, { onlyIf: req.headers, range: req.headers });
  if (!obj) return new Response("Not found", { status: 404 });
  const headers = new Headers();
  obj.writeHttpMetadata(headers);
  headers.set("etag", obj.httpEtag);
  headers.set("cache-control", "public, max-age=86400");
  headers.set("x-content-type-options", "nosniff");
  if (ext === "pdf") headers.set("content-disposition", `inline; filename="chao-phraya-plan-${key.slice(6, 16)}.pdf"`);
  if (!("body" in obj) || !obj.body) return new Response(null, { status: 304, headers });
  if (obj.range && req.headers.has("range")) {
    const { offset = 0, length = obj.size - offset } = obj.range;
    headers.set("content-range", `bytes ${offset}-${offset + length - 1}/${obj.size}`);
    return new Response(req.method === "HEAD" ? null : obj.body, { status: 206, headers });
  }
  return new Response(req.method === "HEAD" ? null : obj.body, { headers });
}
