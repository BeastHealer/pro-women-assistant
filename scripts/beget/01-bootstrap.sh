#!/usr/bin/env bash
# Bootstrap Beget VPS (Ubuntu) for PRO Women stack.
# Docs: https://beget.com/ru/kb/how-to/vps/sozdaniya-vps-nastrojka-i-monitoring
#       https://beget.com/ru/kb/how-to/vps/kak-rabotat-s-docker-cherez-portainer
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run as root: sudo bash scripts/beget/01-bootstrap.sh"
  exit 1
fi

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get upgrade -y
apt-get install -y ca-certificates curl gnupg ufw git

# Docker Engine (official repo) — Beget marketplace «Docker» also works
install -m 0755 -d /etc/apt/keyrings
if [[ ! -f /etc/apt/keyrings/docker.gpg ]]; then
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
  chmod a+r /etc/apt/keyrings/docker.gpg
fi
ARCH="$(dpkg --print-architecture)"
CODENAME="$(. /etc/os-release && echo "${VERSION_CODENAME}")"
echo "deb [arch=${ARCH} signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu ${CODENAME} stable" \
  > /etc/apt/sources.list.d/docker.list
apt-get update
apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
systemctl enable --now docker

# Deploy user
if ! id deployer &>/dev/null; then
  adduser --disabled-password --gecos "" deployer
fi
usermod -aG docker deployer

# Firewall (also mirror rules in Beget panel → VPS → Firewall)
ufw allow OpenSSH
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable
ufw status verbose

mkdir -p /home/deployer/workspace /home/deployer/backups /home/deployer/logs
chown -R deployer:deployer /home/deployer/workspace /home/deployer/backups /home/deployer/logs

echo
echo "OK. Next:"
echo "  1) Add SSH key for deployer (Beget panel or ~/.ssh/authorized_keys)"
echo "  2) su - deployer"
echo "  3) Place pro-women-assistant + tg_vk_parser under ~/workspace/"
echo "  4) bash scripts/beget/02-deploy.sh"
