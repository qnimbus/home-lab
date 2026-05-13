---
# yaml-language-server: $schema=https://kubernetesjsonschema.dev/v1.18.1-standalone-strict/secret-v1.json
# Template — contains op:// references, safe to commit. Never encrypt this file.
# Generate the encrypted secret.sops.yaml from this template:
#   task sops:encrypt FILE=kubernetes/apps/external-secrets/onepassword-connect/app/secret.sops.yaml.tpl
apiVersion: v1
kind: Secret
metadata:
  name: onepassword-connect-secrets
stringData:
  1password-credentials.json: "op://kubernetes/HomeLab Credentials File/1password-credentials.json"
  token: "op://kubernetes/HomeLab Access Token/credential"
