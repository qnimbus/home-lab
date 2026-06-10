#!/usr/bin/env bash
# cp-thermal-compare.sh — side-by-side board/VRM + CPU thermal comparison of the two
# identical Lenovo M920Q nodes (cp-01 vs cp-02), to isolate cp-02's degraded thermal path.
#
# WHY
#   cp-01 and cp-02 are identical hardware (i5-8500T, nct6683 super-I/O, X520) running the
#   same workloads. If cp-02's board/VRM runs hotter than cp-01 under comparable load, that
#   points to a physical thermal-path problem on cp-02 (dust-clogged heatsink / dried paste)
#   — the 2026-06-01 mechanism — as opposed to the *silent* idle hard-downs (RAM suspect,
#   which strike at ~28°C). cp-01 is the "what good looks like" reference.
#   Background: docs/ROADMAP.md → "cp-02 Thermal Stability"; memory project-cp02-outage-investigation;
#   record runs in docs/cp02-thermal-measurements.md.
#
# WHAT IT REPORTS (over a trailing $WINDOW)
#   board (nct6683 PCH/VRM sensor) NOW/MIN/AVG/MAX, CPU package NOW/MAX, CPU-busy NOW/MAX,
#   and the cp-02−cp-01 delta. CPU-busy is included so you can confirm the two nodes were
#   under *comparable* load — a board delta only means something at similar utilisation.
#
# USAGE
#   KUBECONFIG=$(pwd)/kubeconfig bash scripts/cp-thermal-compare.sh [LABEL]
#   Env: WINDOW (default 30m)  LABEL (run description, e.g. "fans-100 idle", "standard benchmark")
#   Take a run now (standard cooling), then again with cp-02 BIOS fans at 100%, and again
#   after a heatsink clean+repaste — append each as a row in docs/cp02-thermal-measurements.md.
#
# NOTE: the board sensor (platform_nct6683_2592) exists only on the M920Q nodes (cp-01/cp-02);
#       cp-03 is AMD and has no equivalent, so it is intentionally excluded.
set -uo pipefail

WINDOW="${WINDOW:-30m}"
LABEL="${1:-${LABEL:-adhoc}}"
CP01="${CP01:-10.60.0.201}"
CP02="${CP02:-10.60.0.202}"
: "${KUBECONFIG:=$(git -C "$(dirname "$0")/.." rev-parse --show-toplevel 2>/dev/null)/kubeconfig}"
export KUBECONFIG

PROXY="/api/v1/namespaces/observability/services/kube-prometheus-stack-prometheus:9090/proxy"
enc(){ python3 -c "import urllib.parse,sys;print(urllib.parse.quote(sys.argv[1]))" "$1"; }
q(){ kubectl get --raw "${PROXY}/api/v1/query?query=$(enc "$1")" 2>/dev/null | jq -r '.data.result[0].value[1] // "n/a"'; }
board(){ echo "node_hwmon_temp_celsius{chip=\"platform_nct6683_2592\",sensor=\"temp2\",instance=\"$1:9100\"}"; }
cpu(){   echo "node_hwmon_temp_celsius{chip=\"platform_coretemp_0\",sensor=\"temp1\",instance=\"$1:9100\"}"; }
busy(){  echo "100*(1-avg(rate(node_cpu_seconds_total{mode=\"idle\",instance=\"$1:9100\"}[2m])))"; }
n1(){ printf "%.1f" "$1" 2>/dev/null || echo "$1"; }

echo "### cp-thermal-compare  label='${LABEL}'  window=${WINDOW}  $(date -u +%Y-%m-%dT%H:%M:%SZ)"
printf "%-20s | %10s | %10s | %s\n" "metric" "cp-01" "cp-02" "Δ(02-01)"
printf -- "---------------------+------------+------------+--------\n"
row(){ local label="$1" e1="$2" e2="$3"
  local a b d; a=$(q "$e1"); b=$(q "$e2")
  d=$(awk -v x="$a" -v y="$b" 'BEGIN{if(x=="n/a"||y=="n/a"){print"-"}else{printf "%+.1f", y-x}}')
  printf "%-20s | %10s | %10s | %s\n" "$label" "$(n1 "$a")" "$(n1 "$b")" "$d"
}
row "board NOW (C)"     "$(board $CP01)"                       "$(board $CP02)"
row "board MIN ${WINDOW}"   "min_over_time($(board $CP01)[${WINDOW}])"   "min_over_time($(board $CP02)[${WINDOW}])"
row "board AVG ${WINDOW}"   "avg_over_time($(board $CP01)[${WINDOW}])"   "avg_over_time($(board $CP02)[${WINDOW}])"
row "board MAX ${WINDOW}"   "max_over_time($(board $CP01)[${WINDOW}])"   "max_over_time($(board $CP02)[${WINDOW}])"
row "CPU NOW (C)"      "$(cpu $CP01)"                          "$(cpu $CP02)"
row "CPU MAX ${WINDOW}"     "max_over_time($(cpu $CP01)[${WINDOW}])"     "max_over_time($(cpu $CP02)[${WINDOW}])"
row "CPU-busy NOW (%)"  "$(busy $CP01)"                        "$(busy $CP02)"
row "CPU-busy MAX ${WINDOW}" "max_over_time(($(busy $CP01))[${WINDOW}:30s])" "max_over_time(($(busy $CP02))[${WINDOW}:30s])"

# Markdown row to paste into docs/cp02-thermal-measurements.md
ba1=$(q "avg_over_time($(board $CP01)[${WINDOW}])"); ba2=$(q "avg_over_time($(board $CP02)[${WINDOW}])")
bm1=$(q "max_over_time($(board $CP01)[${WINDOW}])"); bm2=$(q "max_over_time($(board $CP02)[${WINDOW}])")
by2=$(q "max_over_time(($(busy $CP02))[${WINDOW}:30s])")
davg=$(awk -v x="$ba1" -v y="$ba2" 'BEGIN{printf "%+.1f", y-x}')
dmax=$(awk -v x="$bm1" -v y="$bm2" 'BEGIN{printf "%+.1f", y-x}')
echo
echo "log row → docs/cp02-thermal-measurements.md:"
printf "| %s | %s | cp01 %.0f/%.0f, cp02 %.0f/%.0f | **%s / %s** | cpu-busy max ~%.0f%% | |\n" \
  "$(date -u +%Y-%m-%d\ %H:%M)" "$LABEL" "$ba1" "$bm1" "$ba2" "$bm2" "$davg" "$dmax" "$by2"
