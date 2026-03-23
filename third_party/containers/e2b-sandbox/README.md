# E2B Sandbox Template for OpenHands V1

This directory contains the E2B sandbox template for running OpenHands agent servers in E2B micro VMs.

## Overview

[E2B](https://e2b.dev) is an [open-source](https://github.com/e2b-dev/e2b) secure cloud environment (sandbox) made for running AI-generated code and agents. This template configures E2B to run the OpenHands agent server, enabling secure, isolated execution environments for AI agents.

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    OpenHands App Server                      │
│                    (Your local machine)                      │
└─────────────────────┬───────────────────────────────────────┘
                      │ HTTP API calls
                      ▼
┌─────────────────────────────────────────────────────────────┐
│              Self-Hosted E2B Infrastructure                  │
│                    (GCP / Your Cloud)                        │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐          │
│  │ E2B Micro VM│  │ E2B Micro VM│  │ E2B Micro VM│   ...    │
│  │ ┌─────────┐ │  │ ┌─────────┐ │  │ ┌─────────┐ │          │
│  │ │  Agent  │ │  │ │  Agent  │ │  │ │  Agent  │ │          │
│  │ │  Server │ │  │ │  Server │ │  │ │  Server │ │          │
│  │ └─────────┘ │  │ └─────────┘ │  │ └─────────┘ │          │
│  └─────────────┘  └─────────────┘  └─────────────┘          │
└─────────────────────────────────────────────────────────────┘
```

Each conversation gets its own E2B micro VM running an isolated agent server.

## Prerequisites

1. **Self-hosted E2B infrastructure** deployed in your cloud (see [e2b-dev/infra](https://github.com/e2b-dev/infra))
2. **E2B CLI** installed for building templates

## Building the Template

1. Install the E2B CLI:
   ```sh
   npm install -g @e2b/cli@latest
   ```

2. Configure CLI to use your self-hosted E2B:
   ```sh
   export E2B_API_URL=https://api.e2b.your-domain.com
   export E2B_API_KEY=your-api-key
   ```

3. Build and push the template:
   ```sh
   cd third_party/containers/e2b-sandbox
   e2b template build --dockerfile ./Dockerfile --name "openhands"
   ```

4. Note the template ID returned by the build command.

## Configuring OpenHands to Use E2B

Set the following environment variables when running OpenHands:

```sh
# E2B API configuration
export OH_E2B_API_URL=https://api.e2b.your-domain.com
export OH_E2B_API_KEY=your-api-key

# Configure sandbox service to use E2B
export OH_SANDBOX_SERVICE=e2b

# Optional: Configure webhook URL for event callbacks
export OH_WEB_URL=https://your-openhands-server.com
```

## Exposed Ports

The template exposes the following ports:

| Port | Service | Description |
|------|---------|-------------|
| 8000 | Agent Server | Main API endpoint for agent communication |
| 8001 | VSCode Server | Web-based IDE for code editing |
| 8011 | Worker 1 | User application server |
| 8012 | Worker 2 | Additional user application server |

## Customizing the Template

### Using a Different Agent Server Version

```sh
e2b template build \
  --dockerfile ./Dockerfile \
  --name "openhands" \
  --build-arg AGENT_SERVER_IMAGE=ghcr.io/openhands/agent-server:v1.0.0
```

### Resource Configuration

Edit `e2b.toml` to adjust sandbox resources:

```toml
[sandbox]
timeout = 3600  # Sandbox lifetime in seconds
memory = 2048   # Memory in MB
cpus = 2        # Number of vCPUs
```

## Debugging

### List running sandboxes
```sh
e2b sandbox list
```

### Connect to a sandbox
```sh
e2b sandbox connect <sandbox-id>
```

### View sandbox logs
```sh
e2b sandbox logs <sandbox-id>
```

## Links

- [E2B Documentation](https://e2b.dev/docs)
- [E2B GitHub](https://github.com/e2b-dev/e2b)
- [E2B Infrastructure (Self-Hosting)](https://github.com/e2b-dev/infra)
- [OpenHands Documentation](https://docs.all-hands.dev)
