#!/usr/bin/env bash
set -euo pipefail

api_url="${1:?usage: smoke-production.sh https://api.example.com}"
api_url="${api_url%/}"

curl --fail --silent --show-error "${api_url}/health" >/dev/null
curl --fail --silent --show-error "${api_url}/ready" >/dev/null

echo "AURA production health and readiness checks passed."
