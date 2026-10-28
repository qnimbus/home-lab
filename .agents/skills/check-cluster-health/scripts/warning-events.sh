#!/usr/bin/env bash
# The 30 most recent Warning events, fleet-wide, minus the warnings that fire
# routinely and have already resolved themselves. SKILL.md explains each one.
#
# Usage: warning-events.sh
set -euo pipefail

# kopiur Snapshots that have succeeded: their MissingDependency warnings are over.
succeeded=$(kubectl get snapshots.kopiur.home-operations.com -A -o json |
  jq -c '[.items[] | select(.status.phase == "Succeeded") | "\(.metadata.namespace)/\(.metadata.name)"]')
# PVs that still exist: a VolumeFailedDelete on any other PV ended in a successful delete.
pvs=$(kubectl get pv -o json | jq -c '[.items[].metadata.name]')
# PushSecrets that are Ready: their last push succeeded.
pushed=$(kubectl get pushsecrets -A -o json | jq -c '[.items[]
  | select(any(.status.conditions[]?; .type == "Ready" and .status == "True"))
  | "\(.metadata.namespace)/\(.metadata.name)"]')
# Pods still Pending: a FailedScheduling on one of these is still open.
pending=$(kubectl get pods -A --field-selector=status.phase=Pending -o json |
  jq -c '[.items[] | "\(.metadata.namespace)/\(.metadata.name)"]')

kubectl get events -A --field-selector type=Warning -o json |
  jq -r --argjson ok "$succeeded" --argjson pvs "$pvs" --argjson pushed "$pushed" --argjson pending "$pending" '
  .items | sort_by(.lastTimestamp // .eventTime) | .[] |
  "\(.involvedObject.namespace)/\(.involvedObject.name)" as $obj |
  select((.reason == "MissingDependency" and .involvedObject.kind == "Snapshot"
    and (.involvedObject.apiVersion | startswith("kopiur."))
    and ($ok | index($obj))) | not) |
  select((.reason == "VolumeFailedDelete"
    and (.involvedObject.name as $pv | $pvs | index($pv) | not)) | not) |
  select((.reason == "Errored" and .involvedObject.kind == "PushSecret"
    and .message == "set secret failed"
    and ($pushed | index($obj))) | not) |
  select((.reason == "FailedScheduling" and .involvedObject.kind == "Pod"
    and (.message | test("waiting for ephemeral volume"))
    and ($pending | index($obj) | not)) | not) |
  "\(.lastTimestamp // .eventTime)  \(.involvedObject.namespace // "-")  \(.reason)  \(.involvedObject.kind)/\(.involvedObject.name)  \(.message)"' |
  tail -30
