#!/bin/bash

# Restore correct permissions for home directory
sudo chown -R 1000:1000 /home/vscode

# Update package lists
sudo apt-get update

# Install required packages
# sudo apt-get install -y gnupg ca-certificates iputils-ping dnsutils trash-cli tree libgtk2.0-0 libgtk-3-0 libgbm-dev libnotify-dev libnss3 libxss1 libasound2 libxtst6 xauth xvfb nmap
sudo apt-get install -y netcat-openbsd nmap iputils-ping

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

# Install helm plugins (helm-diff is required by helmfile)
helm plugin install https://github.com/databus23/helm-diff --verify=false || true
