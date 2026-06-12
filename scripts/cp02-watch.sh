#!/usr/bin/env bash
# cp02-watch.sh — live pre-crash vitals watch for the recurring cp-02 hard-downs.
#
# WHY THIS EXISTS
#   cp-02 (Lenovo M920Q) has gone hard-down several times with a silent signature
#   (100% packet loss on both NICs, nothing in dmesg). Every crash was unforensicable
#   post-reboot. This streams cp-02's last-known vitals so a hard-down is preceded by a
#   dense record, and warns *before* a thermal runaway reaches the BIOS shutdown.
#   Background: docs/ROADMAP.md → "cp-02 Thermal Stability"; memory
#   project-cp02-outage-investigation. The durable record lives in Prometheus
#   (node-exporter @10s on ceph-block, off-node) — this script is the live alerter.
#
# HOW IT WORKS
#   Polls Prometheus every $POLL seconds via the kube-apiserver proxy (no port-forward —
#   each poll is self-contained and self-healing). Emits a line ONLY when something is
#   actionable, plus a heartbeat every ~10 min so silence can't be mistaken for "watch died":
#     - board/PCH temp (platform_nct6683_2592/temp2 — the sensor that ran away to 72°C on
#       2026-06-01) crossing RISING(>=58) / HIGH(>=65) / CRITICAL(>=72)
#     - CPU package >= 82°C
#     - a NIC error BURST (>=1/s — reboot link-flaps are filtered out)
#     - node unscraped for 2 consecutive polls  => possible hard-down (with last board temp)
#
# USAGE
#   Direct (terminal):   KUBECONFIG=$(pwd)/kubeconfig bash scripts/cp02-watch.sh
#   In a Claude session: run this script via the Monitor tool with persistent:true so each
#                        emitted line streams into the chat as an event. (This is the
#                        recommended way to keep eyes on cp-02 across a troubleshooting session.)
#   Tunables (env):      NODE_IP POLL BOARD_RISING BOARD_HIGH BOARD_CRIT CPU_HIGH NIC_BURST HEARTBEAT_POLLS
#
# NOTE: the board sensor (nct6683) exists only on the M920Q nodes (cp-01/cp-02); on cp-03
#       (AMD) it reads n/a — this watch is intended for cp-02.
set -uo pipefail

NODE_IP="${NODE_IP:-10.60.0.205}"
POLL="${POLL:-25}"
BOARD_RISING="${BOARD_RISING:-58}"
BOARD_HIGH="${BOARD_HIGH:-65}"
BOARD_CRIT="${BOARD_CRIT:-72}"
CPU_HIGH="${CPU_HIGH:-82}"
NIC_BURST="${NIC_BURST:-1}"
HEARTBEAT_POLLS="${HEARTBEAT_POLLS:-24}"   # 24 * 25s ≈ 10 min
: "${KUBECONFIG:=$(git -C "$(dirname "$0")/.." rev-parse --show-toplevel 2>/dev/null)/kubeconfig}"
export KUBECONFIG

PROXY="/api/v1/namespaces/observability/services/kube-prometheus-stack-prometheus:9090/proxy"
I="instance=\"${NODE_IP}:9100\""

enc() { python3 -c "import urllib.parse,sys;print(urllib.parse.quote(sys.argv[1]))" "$1"; }
q()   { kubectl get --raw "${PROXY}/api/v1/query?query=$(enc "$1")" 2>/dev/null | jq -r '.data.result[0].value[1] // "NaN"'; }

echo "$(date -u +%H:%M:%SZ) START cp02-watch NODE=${NODE_IP} POLL=${POLL}s thresholds board≥${BOARD_RISING}/${BOARD_HIGH}/${BOARD_CRIT} cpu≥${CPU_HIGH} nic≥${NIC_BURST}/s"
n=0; downcount=0
while true; do
  n=$((n+1))
  board=$(q "max_over_time(node_hwmon_temp_celsius{chip=\"platform_nct6683_2592\",sensor=\"temp2\",$I}[35s])")
  cpu=$(q   "max_over_time(node_hwmon_temp_celsius{chip=\"platform_coretemp_0\",sensor=\"temp1\",$I}[35s])")
  upv=$(q   "up{job=\"node-exporter\",$I}")
  nicerr=$(q "sum(rate(node_network_receive_errs_total{$I}[2m]))+sum(rate(node_network_transmit_errs_total{$I}[2m]))")
  ts=$(date -u +%H:%M:%SZ)
  if [ "$upv" = "0" ] || [ "$upv" = "NaN" ]; then
    downcount=$((downcount+1))
    if [ "$downcount" -ge 2 ]; then
      lastb=$(q "last_over_time(node_hwmon_temp_celsius{chip=\"platform_nct6683_2592\",sensor=\"temp2\",$I}[10m])")
      echo "$ts CRITICAL ${NODE_IP} DOWN/unscraped x${downcount} (up=${upv}) — last board=${lastb}C — POSSIBLE HARD-DOWN, check node"
    fi
    sleep "$POLL"; continue
  fi
  downcount=0
  alert=$(awk -v b="$board" -v c="$cpu" -v e="$nicerr" -v r="$BOARD_RISING" -v h="$BOARD_HIGH" -v x="$BOARD_CRIT" -v ch="$CPU_HIGH" -v nb="$NIC_BURST" 'BEGIN{
    m="";
    if(b+0>=x)m=m" CRITICAL(board>="x" near shutdown)"; else if(b+0>=h)m=m" HIGH(board>="h" alert)"; else if(b+0>=r)m=m" RISING(board>="r")";
    if(c+0>=ch)m=m" cpuHIGH"; if(e+0>=nb)m=m" nicErrBURST"; print m}')
  if [ -n "$alert" ]; then
    echo "$ts ALERT ${NODE_IP}:$alert board=${board}C cpu=${cpu}C nicErr=${nicerr}/s"
  elif [ $(( (n-1) % HEARTBEAT_POLLS )) -eq 0 ]; then
    echo "$ts OK ${NODE_IP} board=${board}C cpu=${cpu}C nicErr=${nicerr}/s up=1 (watch alive)"
  fi
  sleep "$POLL"
done
