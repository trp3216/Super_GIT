#!/usr/bin/env bash
# Publish the Chao Phraya 3D page to a Cloudflare R2 bucket with a public r2.dev URL.
#
# Required env: CLOUDFLARE_API_TOKEN (Account > Workers R2 Storage: Edit), CLOUDFLARE_ACCOUNT_ID
# Optional env: BUCKET (default: chao-phraya-3d), WRANGLER_VERSION
set -euo pipefail

BUCKET="${BUCKET:-chao-phraya-3d}"
WRANGLER_VERSION="${WRANGLER_VERSION:-4.140.0}"
SITE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

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

put() { # put <key> <content-type> <cache-control>
  echo "Uploading ${1}"
  wr r2 object put "${BUCKET}/${1}" --file "${SITE_DIR}/${1}" --ct "${2}" --cc "${3}" --remote
}
put vendor/three.min.js      "application/javascript; charset=utf-8" "public, max-age=31536000, immutable"
put vendor/OrbitControls.js  "application/javascript; charset=utf-8" "public, max-age=31536000, immutable"
put index.html               "text/html; charset=utf-8"              "public, max-age=300"

wr r2 bucket dev-url enable "${BUCKET}" -y
DEV_URL="$(wr r2 bucket dev-url get "${BUCKET}" | sed 's/\x1b\[[0-9;]*m//g' | grep -oE 'https://[a-z0-9.-]+\.r2\.dev' | head -n1 || true)"

if [[ -n "${DEV_URL}" ]]; then
  # r2.dev does not serve index documents, so link to the file itself.
  PAGE_URL="${DEV_URL}/index.html"
  echo "Published: ${PAGE_URL}"
  if [[ -n "${GITHUB_STEP_SUMMARY:-}" ]]; then
    printf '### แผนระบายเจ้าพระยา 3 มิติ\n\nเปิดเว็บ: %s\n' "${PAGE_URL}" >> "${GITHUB_STEP_SUMMARY}"
  fi
else
  echo "Uploaded, but could not read the r2.dev URL. Check R2 > ${BUCKET} > Settings in the Cloudflare dashboard." >&2
fi
