#!/usr/bin/env bash
# Deploy the Chao Phraya 3D site as a Cloudflare Worker (static page + plan archive API)
# with uploaded plan PDFs stored in an R2 bucket.
#
# Required env: CLOUDFLARE_API_TOKEN (Account > Workers R2 Storage: Edit and Account > Workers Scripts: Edit),
#               CLOUDFLARE_ACCOUNT_ID
# Optional env: UPLOAD_PASSWORD (sets the archive upload password), WRANGLER_VERSION
set -euo pipefail

BUCKET="chao-phraya-3d" # must match bucket_name in wrangler.toml
WRANGLER_VERSION="${WRANGLER_VERSION:-4.140.0}"
SITE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TMP="${RUNNER_TEMP:-${TMPDIR:-/tmp}}"
cd "${SITE_DIR}"

: "${CLOUDFLARE_API_TOKEN:?set CLOUDFLARE_API_TOKEN}"
: "${CLOUDFLARE_ACCOUNT_ID:?set CLOUDFLARE_ACCOUNT_ID}"

NODE_MAJOR="$(node -p 'process.versions.node.split(".")[0]' 2>/dev/null || echo 0)"
if (( NODE_MAJOR < 22 )); then
  echo "wrangler ${WRANGLER_VERSION} needs Node.js 22 or newer (found: $(node --version 2>/dev/null || echo none))" >&2
  exit 1
fi

export NO_COLOR=1 FORCE_COLOR=0
wr() { npx --yes "wrangler@${WRANGLER_VERSION}" "$@"; }

if wr r2 bucket info "${BUCKET}" >/dev/null 2>&1; then
  echo "Bucket ${BUCKET} exists"
else
  echo "Creating bucket ${BUCKET}"
  wr r2 bucket create "${BUCKET}"
fi

# Put the 16 Oct 2569 plan into the archive once. The marker lives outside plans/,
# so deleting that plan from the web page does not bring it back on the next deploy.
SEED_ID="2026-10-16-seed0001"
if wr r2 object get "${BUCKET}/meta/seeded-${SEED_ID}" --remote --pipe >/dev/null 2>&1; then
  echo "Archive already seeded"
else
  echo "Seeding the archive with the 16 Oct plan"
  wr r2 object put "${BUCKET}/plans/${SEED_ID}.pdf" --file seed/2026-10-16.pdf --ct application/pdf --remote
  wr r2 object put "${BUCKET}/plans/${SEED_ID}.jpg" --file seed/2026-10-16.jpg --ct image/jpeg --remote
  printf 'seeded\n' > "${TMP}/seeded.txt"
  wr r2 object put "${BUCKET}/meta/seeded-${SEED_ID}" --file "${TMP}/seeded.txt" --ct text/plain --remote
fi

wr deploy 2>&1 | tee "${TMP}/deploy.log"
SITE_URL="$(sed 's/\x1b\[[0-9;]*m//g' "${TMP}/deploy.log" | grep -oE 'https://[a-z0-9.-]+\.workers\.dev' | head -n1 || true)"

if [[ -n "${UPLOAD_PASSWORD:-}" ]]; then
  printf '%s' "${UPLOAD_PASSWORD}" | wr secret put UPLOAD_PASSWORD
else
  echo "UPLOAD_PASSWORD is not set, so the archive stays read-only until it is added." >&2
fi

if [[ -z "${SITE_URL}" ]]; then
  echo "Deployed, but could not read the workers.dev URL. See Workers & Pages > chao-phraya-3d in the Cloudflare dashboard." >&2
  exit 0
fi
echo "Published: ${SITE_URL}"

# Keep the earlier r2.dev link working by sending it to the Worker.
cat > "${TMP}/redirect.html" <<HTML
<!doctype html><meta charset="utf-8"><title>แผนระบายเจ้าพระยา 3 มิติ</title>
<meta http-equiv="refresh" content="0; url=${SITE_URL}/">
<p>หน้านี้ย้ายไปที่ <a href="${SITE_URL}/">${SITE_URL}/</a></p>
HTML
wr r2 object put "${BUCKET}/index.html" --file "${TMP}/redirect.html" --ct "text/html; charset=utf-8" --cc "public, max-age=300" --remote

if [[ -n "${GITHUB_STEP_SUMMARY:-}" ]]; then
  printf '### แผนระบายเจ้าพระยา 3 มิติ\n\nเปิดเว็บ: %s\n' "${SITE_URL}" >> "${GITHUB_STEP_SUMMARY}"
fi
