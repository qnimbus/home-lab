#!/bin/bash

# Activate mise for the current session
eval "$(~/.local/bin/mise activate bash)"

# Refresh agent skills on every start so skill assets (schemas, scripts) are current
claude skills update

# Sync scripts/validate.sh and Flux OpenAPI schemas from the just-updated gitops-repo-audit skill
task validate:update
