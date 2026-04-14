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
#   vvenne/ftl:full    — + Codex + Aider

set -euo pipefail

REGISTRY="vvenne/ftl"
PLATFORMS="linux/amd64,linux/arm64"
BUILDER="ftl-builder"
CLAUDE_CODE_VERSION="2.1.92"
CODEX_VERSION="0.118.0"

# Ensure a multi-platform builder exists
if ! docker buildx inspect "$BUILDER" &>/dev/null; then
  docker buildx create --name "$BUILDER" --use
else
  docker buildx use "$BUILDER"
fi

echo "==> Building $REGISTRY:latest (claude-code only)"
docker buildx build \
  --platform "$PLATFORMS" \
  --build-arg "CLAUDE_CODE_VERSION=$CLAUDE_CODE_VERSION" \
  --tag "$REGISTRY:latest" \
  --push \
  .

# Agent Dockerfile snippets
CODEX_LAYER="RUN npm install -g @openai/codex@$CODEX_VERSION && npm cache clean --force"

AIDER_LAYER="RUN pip3 install --break-system-packages aider-chat"

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
build_agent_tag "full"  "$CODEX_LAYER
$AIDER_LAYER"

echo ""
echo "All tags pushed:"
echo "  $REGISTRY:latest"
echo "  $REGISTRY:codex"
echo "  $REGISTRY:aider"
echo "  $REGISTRY:full"
