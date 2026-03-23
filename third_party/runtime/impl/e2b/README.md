# E2B Runtime (Legacy V0)

> **⚠️ DEPRECATED**: This is the legacy V0 E2B runtime implementation.
> For the new V1 implementation, see:
> - `openhands/app_server/sandbox/e2b_sandbox_service.py` - E2B sandbox service
> - `openhands/app_server/sandbox/e2b_sandbox_spec_service.py` - E2B template service
> - `third_party/containers/e2b-sandbox/` - E2B template configuration

## Overview

[E2B](https://e2b.dev) is an [open-source](https://github.com/e2b-dev/e2b) secure cloud environment (sandbox) made for running AI-generated code and agents.

## V1 Architecture

In OpenHands V1, E2B integration works differently:

1. **E2B Sandbox Service** (`e2b_sandbox_service.py`) communicates with the E2B API to create/manage micro VMs
2. **Agent Server** runs inside each E2B micro VM
3. **App Server** communicates with agent servers via HTTP

See `/third_party/containers/e2b-sandbox/README.md` for setup instructions.

## Legacy V0 Usage

The files in this directory (`e2b_runtime.py`, `sandbox.py`, `filestore.py`) are for the legacy V0 runtime and will be removed in a future version.

## Links

- [E2B Documentation](https://e2b.dev/docs)
- [E2B GitHub](https://github.com/e2b-dev/e2b)
- [E2B Infrastructure (Self-Hosting)](https://github.com/e2b-dev/infra)
