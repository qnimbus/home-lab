# Timezones

The cluster runs in UTC. A pod gets no `TZ`, a CronJob no `timeZone`, and a
cron expression means UTC, unless the exception below applies.

Why: nodes, Kubernetes events, Flux and CNPG are in UTC already, so logs in
UTC line up with everything else. A schedule in UTC also never meets a
daylight-saving change. In `Europe/Amsterdam`, 02:00 doesn't exist on one
night a year and happens twice on another, so a job set for that hour can
be skipped or run twice.

## Exception: local time is part of the app's data

Set the timezone only when a person would notice the difference in what
the app does, not in what it logs:

- it fires user-defined schedules on wall-clock time (`n8n`),
- it assigns a date to a record (`firefly`, `paperless`),
- it shows a clock or calendar, or runs its own nightly window (`homepage`,
  `plex`),
- it formats times for a person on the server, not in the browser
  (`unifi-voucher-site`; tested by running it without `TZ`).

Then use `${CLUSTER_TIMEZONE}` from `cluster-settings`, never a literal
zone: as `TZ`, or as the app's own setting where it has one
(`GENERIC_TIMEZONE`, `PAPERLESS_TIME_ZONE`).

Logs in local time are not a reason. Neither is a web UI: most render
times in the browser's timezone (the \*arr apps do).

## Schedules

- Write every cron expression in UTC: a CronJob `schedule`, a CNPG
  `ScheduledBackup`, a kopiur `cron`. Where the local hour matters, say so
  in the folder's `README.md` and give the UTC time there.
- Don't set `timeZone` on a CronJob, or `timezone` on a kopiur schedule or
  its `scheduleDefaults`.
- A job that must follow local time through daylight saving is an
  exception only the user decides on. Keep it out of 02:00–03:00 local.

## Not covered

- Outside the cluster: Compose stacks under `docker/` and the `timezone`
  inputs of GitHub workflows set their own.
