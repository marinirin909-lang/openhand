# Sandbox Management

Manages sandbox environments for secure agent execution within OpenHands.

## Overview

Since agents can do things that may harm your system, they are typically run inside a sandbox (like a Docker container). This module provides services for creating, managing, and monitoring these sandbox environments.

## Key Components

- **SandboxService**: Abstract service for sandbox lifecycle management
- **DockerSandboxService**: Docker-based sandbox implementation
- **KataSandboxService**: Kata Containers-based sandbox for enhanced VM isolation
- **RemoteSandboxService**: Remote sandbox via runtime API
- **ProcessSandboxService**: Local process-based sandbox for development
- **SandboxSpecService**: Manages sandbox specifications and templates
- **SandboxRouter**: FastAPI router for sandbox endpoints

## Features

- Secure containerized execution environments
- Sandbox lifecycle management (create, start, stop, destroy)
- Multiple sandbox backend support (Docker, Kata, Remote, Process)
- User-scoped sandbox access control

## Sandbox Types

### Docker Sandbox (Default)
Standard Docker containers providing process-level isolation. Set `RUNTIME=docker` or leave unset.

### Kata Sandbox
Kata Containers provide VM-level isolation by running containers inside lightweight VMs. This is ideal for untrusted workloads requiring stronger security boundaries.

**Usage:**
```bash
export RUNTIME=kata
export KATA_RUNTIME_TYPE=io.containerd.kata.v2  # or kata-qemu, kata-clh, kata-fc
export KATA_CONTAINERD_NAMESPACE=openhands
```

**Configuration options:**
- `KATA_RUNTIME_TYPE`: Kata runtime to use (default: `io.containerd.kata.v2`)
  - `io.containerd.kata.v2` - Default Kata runtime
  - `io.containerd.kata-qemu.v2` - Kata with QEMU hypervisor
  - `io.containerd.kata-clh.v2` - Kata with Cloud Hypervisor
  - `io.containerd.kata-fc.v2` - Kata with Firecracker
- `KATA_CONTAINERD_NAMESPACE`: Containerd namespace (default: `openhands`)
- `KATA_CONTAINER_URL_PATTERN`: URL pattern for services (default: `http://{host}:{port}`)
- `KATA_MAX_NUM_SANDBOXES`: Max concurrent sandboxes (default: 5)
- `KATA_STARTUP_TIMEOUT`: Startup timeout in seconds (default: 120)
- `KATA_ENABLE_HOST_NETWORK`: Enable host networking (default: false)

**Requirements:**
- containerd with Kata Containers runtime installed
- nerdctl (or compatible containerd CLI)
- Kata Containers 2.x or later

### Remote Sandbox
Uses a remote runtime API for sandbox management. Set `RUNTIME=remote` with:
- `SANDBOX_API_KEY`: API key for authentication
- `SANDBOX_REMOTE_RUNTIME_API_URL`: Remote runtime API URL

### Process Sandbox
Local process-based sandbox for development. Set `RUNTIME=process` or `RUNTIME=local`.
