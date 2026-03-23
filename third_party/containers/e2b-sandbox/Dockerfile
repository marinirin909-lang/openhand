# E2B sandbox template for OpenHands V1
# This template uses the standard OpenHands agent-server image
# and configures it to run within an E2B micro VM.
#
# Build this template using the E2B CLI:
#   e2b template build --dockerfile ./Dockerfile --name "openhands"
#
# The agent server will be started automatically when the sandbox boots.

# Use the official OpenHands agent-server image as base
# This can be overridden via build args for testing different versions
ARG AGENT_SERVER_IMAGE=ghcr.io/openhands/agent-server:latest
FROM ${AGENT_SERVER_IMAGE}

# E2B requires the sandbox to run as root for some operations
USER root

# Install additional packages that E2B needs for sandbox management
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Set up workspace directory
RUN mkdir -p /workspace && chmod 777 /workspace

# Environment variables for the agent server
# These can be overridden when starting the sandbox
ENV OH_WORKSPACE_DIR=/workspace
ENV OH_LOG_LEVEL=INFO

# Expose the standard agent server ports
# 8000 - Agent Server API
# 8001 - VSCode Server
# 8011 - Worker 1 (user applications)
# 8012 - Worker 2 (user applications)
EXPOSE 8000 8001 8011 8012

# Set working directory
WORKDIR /workspace

# The agent server is started via the entrypoint from the base image
# E2B will manage the process lifecycle
