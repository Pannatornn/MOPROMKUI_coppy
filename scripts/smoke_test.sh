#!/bin/sh
set -eu

base_url=${1:-https://team6.105app.site}

curl --fail --silent --show-error "$base_url/healthz"
curl --fail --silent --show-error "$base_url/" >/dev/null

response=$(curl --fail --silent --show-error \
  -H 'Content-Type: application/json' \
  -d '{"age_group":"18-39","sex_at_birth":"prefer_not_to_say","pregnancy_status":"unknown","chief_complaint":"ปวดศีรษะเล็กน้อยตั้งแต่เช้า","consent":true}' \
  "$base_url/api/cases")

python3 -c 'import json,sys; d=json.loads(sys.argv[1]); assert d["reference"].startswith("MPK-"); assert d["messages"]' "$response"
echo "Smoke test passed for $base_url"

