#!/usr/bin/env bash
# Writes only jenkins/kubeconfig, pointing at the Minikube node's own address on the shared
# Docker network. Never touches ~/.kube/config. The file is rewritten in place because it is
# bind-mounted: replacing it would leave the running container with the old content.
set -euo pipefail
cd "$(dirname "$0")"

tmp=$(mktemp)
trap 'rm -f "$tmp"' EXIT
kubectl config view --flatten --minify --context minikube > "$tmp"
kubectl config set-cluster minikube --server="https://$(minikube ip):8443" --kubeconfig "$tmp" > /dev/null
touch kubeconfig
chmod 600 kubeconfig
cat "$tmp" > kubeconfig
