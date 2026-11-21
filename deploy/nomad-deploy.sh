#!/bin/sh
# Rolls a Nomad job out and waits for *its* deployment (CI step and manual use).
#   NOMAD_ADDR=http://192.0.2.30:4646 NOMAD_TOKEN=... deploy/nomad-deploy.sh deploy/nomad.hcl <image>
# A failed deployment reverts itself (auto_revert in the job); this script then exits 1.
set -eu
file="$1"; image="$2"
api() { curl -fsS -H "X-Nomad-Token: $NOMAD_TOKEN" "$@"; }

job=$(jq -n --rawfile hcl "$file" --arg vars "image = \"$image\"" \
  '{JobHCL: $hcl, Variables: $vars, Canonicalize: true}' | api -X POST "$NOMAD_ADDR/v1/jobs/parse" -d @-)
id=$(printf '%s' "$job" | jq -r .ID)
eval_id=$(jq -n --argjson job "$job" '{Job: $job}' | api -X POST "$NOMAD_ADDR/v1/jobs" -d @- | jq -r .EvalID)
echo "submitted $id with $image (evaluation $eval_id)"
if [ -z "$eval_id" ] || [ "$eval_id" = "null" ]; then
  echo "periodic or parameterized job registered (no evaluation, no deployment)"; exit 0
fi

# The deployment of THIS submission: the evaluation names it (the job endpoint would still
# return the previous, possibly failed one for a moment).
dep=""
i=0
while [ "$i" -lt 30 ]; do
  ev=$(api "$NOMAD_ADDR/v1/evaluation/$eval_id")
  if [ "$(printf '%s' "$ev" | jq -r .Status)" = "complete" ]; then
    dep=$(printf '%s' "$ev" | jq -r '.DeploymentID // ""'); break
  fi
  i=$((i + 1)); sleep 2
done
if [ -z "$dep" ]; then
  echo "no new deployment (nothing changed)"; exit 0
fi

i=0
while [ "$i" -lt 360 ]; do
  d=$(api "$NOMAD_ADDR/v1/deployment/$dep")
  status=$(printf '%s' "$d" | jq -r .Status)
  case "$status" in
    successful) echo "deployment successful"; exit 0 ;;
    failed|cancelled) echo "deployment $status: $(printf '%s' "$d" | jq -r .StatusDescription)" >&2; exit 1 ;;
  esac
  i=$((i + 1)); sleep 5
done
echo "timeout waiting for the deployment" >&2; exit 1
