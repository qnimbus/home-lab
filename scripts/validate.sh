#!/usr/bin/env bash
# Delegates to the gitops-repo-audit skill's validate.sh so the skill's
# bundled Flux OpenAPI schemas are automatically resolved via $BASH_SOURCE.
exec "$(dirname "$0")/../.claude/skills/gitops-repo-audit/scripts/validate.sh" "$@"
