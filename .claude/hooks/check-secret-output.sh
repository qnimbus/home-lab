#!/usr/bin/env bash
# PostToolUse hook: warn when sensitive secret material appears in tool output.
# Outputs {"continue":false,"stopReason":"..."} to pause and alert if secrets are detected.
# Applies to: Bash (command stdout), Read (file contents).

INPUT=$(cat)

# Flatten tool_response to a searchable string.
# Raw-string responses (Bash stdout) are used as-is; object responses (Read, MCP)
# are serialised to JSON — key patterns are still detectable in either form.
RESPONSE=$(printf '%s' "$INPUT" | jq -r '
  (.tool_response // .tool_result // "") |
  if type == "string" then .
  else tojson
  end
' 2>/dev/null)

[[ -z "$RESPONSE" ]] && exit 0

FINDINGS=()

# PEM private key blocks — RSA, EC, OpenSSH, PKCS8, encrypted variants
# Use -- to prevent grep parsing the leading dashes as options
if printf '%s' "$RESPONSE" | grep -qP -- '-----BEGIN\s+(\w+\s+)*PRIVATE KEY-----'; then
    FINDINGS+=("PEM private key  (-----BEGIN ... PRIVATE KEY-----)")
fi

# age(1) private key — bech32, always AGE-SECRET-KEY-1 prefix
if printf '%s' "$RESPONSE" | grep -qP 'AGE-SECRET-KEY-1[A-Z2-7]{10,}'; then
    FINDINGS+=("age private key  (AGE-SECRET-KEY-1...)")
fi

# Kubernetes kubeconfig: client-key-data (base64-encoded private key)
if printf '%s' "$RESPONSE" | grep -qP 'client-key-data:\s+\S{40,}'; then
    FINDINGS+=("kubeconfig client-key-data field")
fi

# Kubernetes kubeconfig / ServiceAccount: bearer token
if printf '%s' "$RESPONSE" | grep -qP '^\s*token:\s+[A-Za-z0-9._-]{40,}'; then
    FINDINGS+=("Kubernetes bearer token  (token: ...)")
fi

[[ ${#FINDINGS[@]} -eq 0 ]] && exit 0

TOOL=$(printf '%s' "$INPUT" | jq -r '.tool_name // "unknown"' 2>/dev/null)
LIST=$(printf '\n  • %s' "${FINDINGS[@]}")

MSG=$(printf \
    'Sensitive material detected in %s output:%s\n\nThis content is now in conversation context. Do not reproduce it verbatim in responses.\nIf this was unintentional, start a fresh conversation to avoid the material being referenced further.' \
    "$TOOL" "$LIST")

jq -n --arg m "$MSG" '{"continue":false,"stopReason":$m}'
