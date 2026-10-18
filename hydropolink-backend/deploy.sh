#!/usr/bin/env bash
# Run on the LinuxONE VM from ~/hydrolink-backend:   bash deploy.sh
set -euo pipefail
IMG=registry.linuxone.cloud.marist.edu/l1cc/jupyterlab-image-s390x:latest
SHARED=$HOME/shared
REPO=$(cd "$(dirname "$0")" && pwd)
DOCKERFILE=${DOCKERFILE:-Dockerfile}

# Secrets live in ~/.hydrolink.env (chmod 600), generated once.
if [ ! -f ~/.hydrolink.env ]; then
  echo "HYDROLINK_MODEL_KEY=$(openssl rand -hex 32)"  >  ~/.hydrolink.env
  echo "JUPYTER_TOKEN=$(openssl rand -hex 16)"        >> ~/.hydrolink.env
  chmod 600 ~/.hydrolink.env
fi
grep -q HYDROLINK_INGEST_TOKEN ~/.hydrolink.env || echo "HYDROLINK_INGEST_TOKEN=$(openssl rand -hex 24)" >> ~/.hydrolink.env
source ~/.hydrolink.env

# Where does the Jupyter image's user live? Mount there (this was the bug).
JHOME=$(docker run --rm --entrypoint sh "$IMG" -c 'echo $HOME')
JUID=$(docker run --rm --entrypoint sh "$IMG" -c 'id -u')
echo "Jupyter image home=$JHOME uid=$JUID"

mkdir -p "$SHARED"
sudo chown -R "$JUID":"$JUID" "$SHARED" "$REPO/notebooks"

docker network create hydronet 2>/dev/null || true
docker build -f "$DOCKERFILE" -t hydrolink-backend "$REPO"
docker rm -f hydrolink-api notebook 2>/dev/null || true

docker run -d --name hydrolink-api --network hydronet --restart unless-stopped \
  -p 8000:8000 \
  -e HYDROLINK_MODEL_KEY="$HYDROLINK_MODEL_KEY" \
  -e HYDROLINK_INGEST_TOKEN="$HYDROLINK_INGEST_TOKEN" \
  ${ALLOW_SKEW:+-e HYDROLINK_ALLOW_VERSION_SKEW=1} \
  -v "$SHARED":/shared \
  hydrolink-backend

docker run -d --name notebook --network hydronet --restart unless-stopped \
  -p 38888:8888 --security-opt seccomp=unconfined \
  -e HYDROLINK_MODEL_KEY="$HYDROLINK_MODEL_KEY" \
  -e HYDROLINK_API=http://hydrolink-api:8000 \
  -v "$SHARED":"$JHOME"/shared \
  -v "$REPO"/backend:"$JHOME"/backend:ro \
  -v "$REPO"/notebooks:"$JHOME"/notebooks \
  "$IMG" jupyter lab --ServerApp.token="$JUPYTER_TOKEN"

sudo iptables -C INPUT -p tcp --dport 8000  -j ACCEPT 2>/dev/null || sudo iptables -I INPUT -p tcp --dport 8000  -j ACCEPT
sudo iptables -C INPUT -p tcp --dport 38888 -j ACCEPT 2>/dev/null || sudo iptables -I INPUT -p tcp --dport 38888 -j ACCEPT

sleep 8
echo; echo "API:     http://$(curl -s ifconfig.me 2>/dev/null || hostname -I | cut -d' ' -f1):8000/api/system"
echo "Jupyter: http://<VM-IP>:38888/lab?token=$JUPYTER_TOKEN   -> open notebooks/HydroLink_Train.ipynb, Run All"
curl -s localhost:8000/api/system; echo
