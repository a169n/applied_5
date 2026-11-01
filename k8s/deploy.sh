#!/usr/bin/env bash
# Deploy an image, verify it with a smoke Job, and roll back automatically on failure.
# Usage: k8s/deploy.sh <image>
set -euo pipefail

image=${1:?usage: k8s/deploy.sh <image>}
cd "$(dirname "$0")"
ns=quakeloc
ROLLOUT_TIMEOUT=${ROLLOUT_TIMEOUT:-180s}
SMOKE_TIMEOUT_S=${SMOKE_TIMEOUT_S:-120}

render() { sed "s|__IMAGE__|$image|g" "$1"; }

rollback_and_fail() {
  echo "DEPLOY FAILED: $1" >&2
  kubectl -n "$ns" get pods >&2 || true
  revisions=$(kubectl -n "$ns" rollout history deploy/quakeloc | grep -cE '^[0-9]+ ')
  if [ "$revisions" -ge 2 ]; then
    echo "Rolling back to the previous revision." >&2
    kubectl -n "$ns" rollout undo deploy/quakeloc
    kubectl -n "$ns" rollout status deploy/quakeloc --timeout="$ROLLOUT_TIMEOUT"
  else
    echo "First revision: nothing to roll back to." >&2
  fi
  exit 1
}

kubectl apply -f namespace.yaml
render deployment.yaml | kubectl apply -f -
render service.yaml | kubectl apply -f -

kubectl -n "$ns" rollout status deploy/quakeloc --timeout="$ROLLOUT_TIMEOUT" \
  || rollback_and_fail "rollout did not complete"

kubectl -n "$ns" delete job quakeloc-smoke --ignore-not-found --wait=true
render smoke-job.yaml | kubectl create -f -

result=timeout
for _ in $(seq 1 "$SMOKE_TIMEOUT_S"); do
  succeeded=$(kubectl -n "$ns" get job quakeloc-smoke -o jsonpath='{.status.succeeded}')
  failed=$(kubectl -n "$ns" get job quakeloc-smoke -o jsonpath='{.status.failed}')
  if [ "${succeeded:-0}" -ge 1 ]; then result=ok; break; fi
  if [ "${failed:-0}" -ge 1 ]; then result=failed; break; fi
  sleep 1
done
kubectl -n "$ns" logs job/quakeloc-smoke || true

[ "$result" = ok ] || rollback_and_fail "smoke job: $result"
echo "Deployed $image"
