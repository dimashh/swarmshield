#!/usr/bin/env bash
# Starts hub :8000, target :9000, gateway :8080, then the swarm. Ctrl-C stops everything. Logs in logs/.
set -uo pipefail
cd "$(dirname "$0")"
mkdir -p logs
pids=()
cleanup() { trap - EXIT INT TERM; kill "${pids[@]}" 2>/dev/null; wait 2>/dev/null; echo "stopped"; }
trap cleanup EXIT INT TERM

start() {
  local name=$1 port=$2; shift 2
  if curl -s -o /dev/null "http://127.0.0.1:$port"; then echo "port $port already in use (stop it first)"; exit 1; fi
  "$@" >"logs/$name.log" 2>&1 & pids+=($!)
  for _ in $(seq 50); do
    curl -s -o /dev/null "http://127.0.0.1:$port" && { echo "$name up on :$port"; return; }
    sleep 0.2
  done
  echo "$name failed to start, see logs/$name.log"; exit 1
}

HUB_APP=hub.app:app
[ -f hub/app.py ] || { HUB_APP=shield.stubhub:app; echo "hub/app.py not found: using stand-in hub (no dashboard)"; }
start hub 8000 python -m uvicorn "$HUB_APP" --port 8000
start target 9000 python -m uvicorn target.app:app --port 9000
start gateway 8080 python -m uvicorn shield.proxy:app --port 8080
echo "dashboard: http://127.0.0.1:8000"

if [ -f swarm/run.py ]; then
  python -m swarm.run 2>&1 | tee logs/swarm.log
else
  echo "swarm/run.py not found. Rehearse with: python -m shield.rehearse"
  wait
fi
