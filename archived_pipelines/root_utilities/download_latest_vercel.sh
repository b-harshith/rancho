#!/usr/bin/env bash
set -euo pipefail

: "${VERCEL_TOKEN:?Set VERCEL_TOKEN first}"

PROJECT_ID="prj_8WutmnkMVIB2iEhfd7BmgLo7exZ1"
PROJECT_NAME="ranchoblr"
OUT_DIR="web_platform_vercel_latest"
API="https://api.vercel.com"

mkdir -p "$OUT_DIR"

echo "Fetching latest production deployment..."
DEPLOYMENTS_JSON="$(
  curl -sS \
    -H "Authorization: Bearer ${VERCEL_TOKEN}" \
    "${API}/v6/deployments?projectId=${PROJECT_ID}&limit=20"
)"

LATEST_DEPLOYMENT="$(
  printf '%s' "$DEPLOYMENTS_JSON" | node -e '
    const fs = require("fs");
    const data = JSON.parse(fs.readFileSync(0, "utf8"));
    const deps = data.deployments || [];
    if (!deps.length) process.exit(2);
    const ready = deps.filter(d => String(d.state || d.readyState || "").toUpperCase() === "READY");
    const pick = (ready.length ? ready : deps).sort((a,b) => new Date(b.created || b.createdAt || 0) - new Date(a.created || a.createdAt || 0))[0];
    process.stdout.write(JSON.stringify(pick));
  '
)"

DEPLOYMENT_URL="$(printf '%s' "$LATEST_DEPLOYMENT" | node -e 'const d=JSON.parse(require("fs").readFileSync(0,"utf8")); process.stdout.write(String(d.url || d.alias || ""));')"
DEPLOYMENT_ID="$(printf '%s' "$LATEST_DEPLOYMENT" | node -e 'const d=JSON.parse(require("fs").readFileSync(0,"utf8")); process.stdout.write(String(d.uid || d.id || ""));')"
COMMIT_SHA="$(printf '%s' "$LATEST_DEPLOYMENT" | node -e 'const d=JSON.parse(require("fs").readFileSync(0,"utf8")); process.stdout.write(String((d.meta && (d.meta.githubCommitSha || d.meta.commitSha)) || d.gitCommitSha || d.commitSha || ""));')"
CREATED_AT="$(printf '%s' "$LATEST_DEPLOYMENT" | node -e 'const d=JSON.parse(require("fs").readFileSync(0,"utf8")); process.stdout.write(String(d.createdAt || d.created || ""));')"

printf '%s\n' "$LATEST_DEPLOYMENT" > "${OUT_DIR}/latest-deployment.json"

cat > "${OUT_DIR}/README.txt" <<EOF
Project: ${PROJECT_NAME}
Project ID: ${PROJECT_ID}
Deployment ID: ${DEPLOYMENT_ID}
Deployment URL: ${DEPLOYMENT_URL}
Commit SHA: ${COMMIT_SHA}
Created At: ${CREATED_AT}
EOF

echo "Latest deployment:"
echo "  Deployment ID: ${DEPLOYMENT_ID}"
echo "  URL:           ${DEPLOYMENT_URL}"
echo "  Commit SHA:    ${COMMIT_SHA}"
echo "  Created At:    ${CREATED_AT}"

if [[ -n "${DEPLOYMENT_ID}" ]]; then
  echo "Fetching deployment details..."
  curl -sS \
    -H "Authorization: Bearer ${VERCEL_TOKEN}" \
    "${API}/v13/deployments/${DEPLOYMENT_ID}" \
    > "${OUT_DIR}/deployment-details.json" || true
fi

if [[ -n "${DEPLOYMENT_URL}" ]]; then
  echo "Trying to mirror accessible files from the live deployment..."
  mkdir -p "${OUT_DIR}/site"
  if command -v wget >/dev/null 2>&1; then
    wget \
      --mirror \
      --convert-links \
      --adjust-extension \
      --page-requisites \
      --no-parent \
      --directory-prefix="${OUT_DIR}/site" \
      "https://${DEPLOYMENT_URL}" || true
  else
    curl -L "https://${DEPLOYMENT_URL}" -o "${OUT_DIR}/site/index.html" || true
  fi
fi

echo "Done. Output folder: ${OUT_DIR}"
