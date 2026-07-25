#!/bin/bash

# Fix permissions on mounted volumes (they're owned by root from the host)
sudo chown -R vscode:vscode /home/vscode/.local
sudo chown -R vscode:vscode /home/vscode/.claude
sudo chown -R vscode:vscode /home/vscode/.kube

# Update package lists
sudo apt-get update

# Install required packages
# sudo apt-get install -y gnupg ca-certificates iputils-ping dnsutils trash-cli tree libgtk2.0-0 libgtk-3-0 libgbm-dev libnotify-dev libnss3 libxss1 libasound2 libxtst6 xauth xvfb nmap
sudo apt-get install -y netcat-openbsd nmap iputils-ping dnsutils

# Provide the Docker CLI and Compose plugin without enabling nested Docker daemon support.
sudo apt-get install -y docker.io docker-compose

# Install chezmoi to ~/.local/bin if not already present
# if ! command -v chezmoi &>/dev/null; then
#     sh -c "$(curl -fsLS get.chezmoi.io)" -- -b "$HOME/.local/bin"
# fi

# Clone dotfiles repo and apply (ephemeral=true auto-detected via VSCODE_REMOTE_CONTAINERS_SESSION)
# chezmoi init --apply https://github.com/qnimbus/dotfiles

# Find the most recent .claude.json backup in ~/.claude/backups and restore it to ~/.claude.json
BACKUP_FILE=$(ls -t ~/.claude/backups/.*.json.backup* 2>/dev/null | head -n 1)
if [ -f "$BACKUP_FILE" ]; then
    cp "$BACKUP_FILE" ~/.claude.json
    echo "Restored Claude settings from backup: $BACKUP_FILE"
else
    echo "No backup found in ~/.claude/backups. Skipping restore."
fi

# Download and install Claude Code
curl -fsSL https://claude.ai/install.sh | bash

# Download and install mise
curl -L https://mise.jdx.dev/install.sh | bash
echo 'eval "$(~/.local/bin/mise activate bash)"' >> ~/.bashrc

# Install Claude Code settings (MCP servers, etc.)
cp .devcontainer/claude-settings.json ~/.claude/settings.json

# Source bashrc to apply changes immediately
source ~/.bashrc
mise trust
mise install

# Activate mise for the current session
eval "$(~/.local/bin/mise activate bash)"

# Point git at the committed hooks directory
git config core.hooksPath .githooks

# Install FluxCD Agent Skills
flux-operator skills install ghcr.io/fluxcd/agent-skills --agent claude-code

# Install KubeShark - Kubernetes Skill
if [ -d ".claude/skills/kubernetes-skill" ]; then
    git -C .claude/skills/kubernetes-skill pull --ff-only
else
    git clone https://github.com/LukasNiessen/kubernetes-skill.git .claude/skills/kubernetes-skill
fi

# Install helm plugins (helm-diff is required by helmfile)
helm plugin list | awk '{print $1}' | grep -qx diff \
  || helm plugin install https://github.com/databus23/helm-diff --verify=false

# Install fj (Forgejo CLI, https://codeberg.org/forgejo-contrib/forgejo-cli), for interacting
# with a Forgejo instance the way `gh` is used for GitHub. No devcontainer feature exists for
# this yet and it isn't in Debian trixie's apt repos, so install the pre-built release binary
# directly, following the same pattern as kubectl above (resolve latest version, download,
# install to /usr/local/bin) rather than a fixed version.
case "$(dpkg --print-architecture)" in
    amd64) FJ_ARCH=x86_64-linux ;;
    arm64) FJ_ARCH=aarch64-linux ;;
    *) echo "fj: unsupported architecture $(dpkg --print-architecture), skipping install" >&2 ;;
esac
if [ -n "${FJ_ARCH:-}" ]; then
    FJ_VERSION=$(curl -fsSL https://codeberg.org/api/v1/repos/forgejo-contrib/forgejo-cli/releases/latest | jq -r .tag_name)
    curl -fsSL -o /tmp/fj.tar.gz "https://codeberg.org/forgejo-contrib/forgejo-cli/releases/download/${FJ_VERSION}/forgejo-cli-${FJ_ARCH}.tar.gz"
    tar -xzf /tmp/fj.tar.gz -C /tmp fj
    sudo install -o root -g root -m 0755 /tmp/fj /usr/local/bin/fj
    rm -f /tmp/fj.tar.gz /tmp/fj
    fj version
fi
