#!/usr/bin/env bash
# Starts Jenkins and, when Minikube is running, connects it for deployments.
# Order: minikube start, then this script. After a reboot or `minikube stop`, run it again.
set -euo pipefail
cd "$(dirname "$0")"

for f in secrets/admin_password secrets/dockerhub_token .env; do
  if [ ! -s "$f" ]; then
    echo "Missing jenkins/$f. See jenkins/secrets/README.md." >&2
    exit 1
  fi
done

if [ "$(minikube status --format '{{.Host}}' 2>/dev/null || true)" = "Running" ]; then
  cd_enabled=true
  ./make-kubeconfig.sh
else
  cd_enabled=false
  touch kubeconfig
  : > kubeconfig
fi

docker compose up -d --build

if [ "$cd_enabled" = true ]; then
  subnet=$(docker network inspect minikube -f '{{(index .IPAM.Config 0).Subnet}}')
  address="${subnet%.*}.250"  # a fixed high address; the node's own static .2 stays free
  if ! docker inspect jenkins -f '{{json .NetworkSettings.Networks}}' | grep -q '"minikube"'; then
    docker network connect --ip "$address" minikube jenkins
  fi
  echo "Jenkins: http://localhost:8080 (CD enabled, Minikube reachable from $address)"
else
  echo "Jenkins: http://localhost:8080 (CD DISABLED: Minikube is not running; start it and re-run)"
fi
