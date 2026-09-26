#!/bin/sh
# sensors-textfile — replacement for node-exporter's permanently-disabled
# --collector.hwmon (see docker-compose.yaml comment on that flag for the
# incident). Reads the same already-populated kernel hwmon sysfs tree
# directly (no lm-sensors dependency — that's all the broken in-process
# collector code did too) and writes Prometheus text-exposition output that
# node-exporter's (unaffected) --collector.textfile.directory folds into its
# own /metrics. No separate Prometheus target is needed as a result.
#
# Metric names/labels deliberately MIRROR node_exporter's real hwmon output
# byte-for-byte (chip id derived from the hwmon device's sysfs path the same
# way node_exporter's hwmonName()/cleanMetricName() do) so this plugs into
# the existing fleet-wide `hardware-temperatures` PrometheusRule
# (kubernetes/apps/observability/kube-prometheus-stack/app/prometheusrules/hardware-temps.yaml)
# and the "Node Exporter Full" dashboard's hwmon panels/joins without any
# changes there. This is only safe as long as node-exporter's own hwmon
# collector stays disabled on this host — see --no-collector.hwmon.
#
# Version coupling: chip_id() below was verified against node_exporter
# v1.11.1's hwmonName()/cleanMetricName() (node-exporter image tag in ../docker-compose.yaml).
# If that version is bumped and node_exporter's own chip-naming algorithm
# ever changes upstream, this script's output would drift out of sync with
# it silently — hardware-temps.yaml's chip=~"..." regexes just stop matching,
# no error anywhere, the Grafana hwmon panels for this host quietly go blank.
# Re-verify chip_id()'s output against a real hwmon.prom capture whenever
# NODE_EXPORTER_VERSION changes.
set -eu

OUT_DIR="/textfile"
OUT_FILE="$OUT_DIR/hwmon.prom"
INTERVAL="${INTERVAL:-15}"

trap 'exit 0' TERM INT

# Mirrors node_exporter's cleanMetricName(): lowercase, replace anything
# outside [a-z0-9:_] with '_', trim leading/trailing '_'. ASCII-only on
# purpose, like upstream — hence A-Z/a-z rather than [:upper:]/[:lower:].
# shellcheck disable=SC2018,SC2019
clean() {
  printf '%s' "$1" | tr 'A-Z' 'a-z' | tr -c 'a-z0-9:_' '_' | sed 's/^_*//; s/_*$//'
}

# Chip id for a /sys/class/hwmon/hwmonN dir, matching node_exporter's own
# device-path-derived identifier (e.g. "platform_coretemp_0",
# "pci0000:00_0000:00:18_3") instead of the raw (often ambiguous) `name` file.
# See the version-coupling note at the top of this file before touching this.
chip_id() {
  hwmon="$1"
  if [ -e "$hwmon/device" ]; then
    device_path="$(readlink -f "$hwmon/device" 2>/dev/null || true)"
    if [ -n "$device_path" ]; then
      name="$(clean "$(basename "$device_path")")"
      type="$(clean "$(basename "$(dirname "$device_path")")")"
      if [ -n "$type" ] && [ -n "$name" ]; then
        printf '%s_%s' "$type" "$name"
        return
      fi
    fi
  fi
  if [ -r "$hwmon/name" ]; then
    n="$(clean "$(cat "$hwmon/name" 2>/dev/null || true)")"
    if [ -n "$n" ]; then
      printf '%s' "$n"
      return
    fi
  fi
  clean "$(basename "$(readlink -f "$hwmon" 2>/dev/null || echo "$hwmon")")"
}

# Escapes a value for use inside a double-quoted Prometheus label.
esc() { printf '%s' "$1" | sed 's/\\/\\\\/g; s/"/\\"/g'; }

collect() {
  # Self-heal from any work dir left behind by a killed/failed previous run.
  find "$OUT_DIR" -maxdepth 1 -name '.hwmon-work.*' -mmin +1 -exec rm -rf {} + 2>/dev/null || true

  work="$(mktemp -d "$OUT_DIR/.hwmon-work.XXXXXX")"
  : > "$work/chip_names"
  : > "$work/sensor_label"
  : > "$work/temp"
  : > "$work/fan"

  for hwmon in /sys/class/hwmon/hwmon*; do
    [ -d "$hwmon" ] || continue
    chip="$(chip_id "$hwmon")"
    [ -n "$chip" ] || continue

    raw_name="unknown"
    [ -r "$hwmon/name" ] && raw_name="$(cat "$hwmon/name" 2>/dev/null || echo unknown)"
    echo "node_hwmon_chip_names{chip=\"$(esc "$chip")\",chip_name=\"$(esc "$raw_name")\"} 1" >> "$work/chip_names"

    for f in "$hwmon"/temp*_input "$hwmon"/fan*_input; do
      [ -e "$f" ] || continue
      base="${f%_input}"
      sensor="$(basename "$base")"       # e.g. "temp1", "fan1"
      kind="${sensor%%[0-9]*}"           # "temp" or "fan"
      raw="$(cat "$f" 2>/dev/null || true)"
      [ -n "$raw" ] || continue

      if [ -r "${base}_label" ]; then
        label="$(cat "${base}_label" 2>/dev/null || true)"
        [ -n "$label" ] && echo "node_hwmon_sensor_label{chip=\"$(esc "$chip")\",sensor=\"$sensor\",label=\"$(esc "$label")\"} 1" >> "$work/sensor_label"
      fi

      case "$kind" in
        temp)
          value="$(awk -v r="$raw" 'BEGIN { printf "%.3f", r / 1000 }')"
          echo "node_hwmon_temp_celsius{chip=\"$(esc "$chip")\",sensor=\"$sensor\"} $value" >> "$work/temp"
          ;;
        fan)
          echo "node_hwmon_fan_rpm{chip=\"$(esc "$chip")\",sensor=\"$sensor\"} $raw" >> "$work/fan"
          ;;
      esac
    done
  done

  # Write metric families as contiguous blocks (Prometheus text format
  # requires all samples of one metric name grouped together, uninterrupted
  # by another metric's samples) then rename atomically within the same
  # volume/filesystem so node-exporter's textfile collector never reads a
  # half-written file.
  tmp="$(mktemp "$OUT_DIR/.hwmon.XXXXXX")"
  # mktemp always creates files mode 0600 regardless of umask — node-exporter's
  # image runs as non-root (nobody, UID 65534) while this container runs as
  # root, so without this the target file is unreadable by node-exporter
  # ("permission denied" opening hwmon.prom, confirmed in production 2026-07-17).
  chmod 644 "$tmp"
  {
    echo "# HELP node_hwmon_chip_names Annotation metric (value=1) mapping a hwmon chip id to its raw kernel driver name."
    echo "# TYPE node_hwmon_chip_names gauge"
    cat "$work/chip_names"

    echo "# HELP node_hwmon_sensor_label Annotation metric (value=1) mapping a chip+sensor to its sysfs *_label text."
    echo "# TYPE node_hwmon_sensor_label gauge"
    cat "$work/sensor_label"

    echo "# HELP node_hwmon_temp_celsius Hardware monitor for temperature (celsius)"
    echo "# TYPE node_hwmon_temp_celsius gauge"
    cat "$work/temp"

    echo "# HELP node_hwmon_fan_rpm Hardware monitor for fan (rpm)"
    echo "# TYPE node_hwmon_fan_rpm gauge"
    cat "$work/fan"
  } > "$tmp"
  rm -rf "$work"
  mv -f "$tmp" "$OUT_FILE"
}

while true; do
  collect || true
  sleep "$INTERVAL"
done
