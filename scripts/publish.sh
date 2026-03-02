#!/usr/bin/env bash
# Build and push all ftl-sandbox tag variants to Docker Hub.
# Run from the repo root: ./scripts/publish.sh
#
# Requires:
#   docker login ftlhq (run once before publishing)
#   docker buildx with multi-platform support (included in Docker Desktop)
#
# Tags produced:
#   vvenne/ftl:latest  — claude-code only
#   vvenne/ftl:codex   — + Codex
#   vvenne/ftl:aider   — + Aider
#   vvenne/ftl:kiro    — + Kiro (arch-aware: amd64 deb / arm64 zip)
#   vvenne/ftl:full    — all agents

set -euo pipefail

REGISTRY="vvenne/ftl"
PLATFORMS="linux/amd64,linux/arm64"
BUILDER="ftl-builder"

# Ensure a multi-platform builder exists
if ! docker buildx inspect "$BUILDER" &>/dev/null; then
  docker buildx create --name "$BUILDER" --use
else
  docker buildx use "$BUILDER"
fi

echo "==> Building $REGISTRY:latest (claude-code only)"
docker buildx build \
  --platform "$PLATFORMS" \
  --tag "$REGISTRY:latest" \
  --push \
  .

# Agent Dockerfile snippets
CODEX_LAYER="RUN npm install -g @openai/codex && npm cache clean --force"

AIDER_LAYER="RUN pip3 install --break-system-packages aider-chat"

KIRO_LAYER=$(cat <<'KIRO'
RUN apt-get update && apt-get install -y --no-install-recommends unzip \
 && ARCH=$(uname -m) \
 && if [ "$ARCH" = "x86_64" ]; then \
      curl -fsSL https://desktop-release.q.us-east-1.amazonaws.com/latest/kiro-cli.deb -o /tmp/kiro-cli.deb \
      && dpkg -i /tmp/kiro-cli.deb && apt-get install -f -y --no-install-recommends \
      && rm -f /tmp/kiro-cli.deb; \
    elif [ "$ARCH" = "aarch64" ]; then \
      curl -fsSL https://desktop-release.q.us-east-1.amazonaws.com/latest/kirocli-aarch64-linux.zip -o /tmp/kiro.zip \
      && unzip /tmp/kiro.zip -d /tmp/kiro-extract \
      && if [ -f /tmp/kiro-extract/install.sh ]; then PREFIX=/usr/local bash /tmp/kiro-extract/install.sh; \
         else find /tmp/kiro-extract -type f -name kiro-cli -exec install -m755 {} /usr/local/bin/kiro-cli \;; fi \
      && rm -rf /tmp/kiro.zip /tmp/kiro-extract; \
    fi \
 && rm -rf /var/lib/apt/lists/*
KIRO
)

build_agent_tag() {
  local tag="$1"
  local layers="$2"
  echo "==> Building $REGISTRY:$tag"
  docker buildx build \
    --platform "$PLATFORMS" \
    --tag "$REGISTRY:$tag" \
    --push \
    - <<EOF
FROM $REGISTRY:latest
USER root
$layers
USER ftl
EOF
}

build_agent_tag "codex" "$CODEX_LAYER"
build_agent_tag "aider" "$AIDER_LAYER"
build_agent_tag "kiro"  "$KIRO_LAYER"
build_agent_tag "full"  "$CODEX_LAYER
$AIDER_LAYER
$KIRO_LAYER"

echo ""
echo "All tags pushed:"
echo "  $REGISTRY:latest"
echo "  $REGISTRY:codex"
echo "  $REGISTRY:aider"
echo "  $REGISTRY:kiro"
echo "  $REGISTRY:full"
