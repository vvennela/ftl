FROM debian:bookworm-slim

ENV DEBIAN_FRONTEND=noninteractive

# System deps in one layer
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    git \
    && rm -rf /var/lib/apt/lists/*

# Node.js 22 LTS
RUN curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/* \
    && npm cache clean --force

# TypeScript + React tooling + Claude Code
RUN npm install -g typescript ts-node create-react-app @anthropic-ai/claude-code \
    && npm cache clean --force

# Python 3.11 (ships with bookworm) + pip + venv
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 \
    python3-venv \
    python3-pip \
    && rm -rf /var/lib/apt/lists/* \
    && ln -sf /usr/bin/python3 /usr/bin/python

# Strip unnecessary files
RUN find /usr -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null; \
    find /usr -type f -name "*.md" -delete 2>/dev/null; \
    true

# Create non-root user for Claude Code (refuses --dangerously-skip-permissions as root)
RUN useradd -m -s /bin/bash ftl
ENV PATH="/home/ftl/.local/bin:${PATH}"

WORKDIR /workspace
RUN chown ftl:ftl /workspace

USER ftl

CMD ["sleep", "infinity"]
