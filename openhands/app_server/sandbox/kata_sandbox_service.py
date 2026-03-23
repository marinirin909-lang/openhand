"""Kata Containers sandbox service implementation.

This service creates sandboxes using Kata Containers, which runs containers inside
lightweight VMs for enhanced security and isolation. This is ideal for running
agent-server instances that need stronger isolation than standard containers.

Kata Containers integration uses containerd as the container runtime with kata-runtime
as the container runtime class.
"""

import asyncio
import hashlib
import json
import logging
import secrets
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, AsyncGenerator

import base62
import httpx
from fastapi import Request
from pydantic import Field

from openhands.agent_server.utils import utc_now
from openhands.app_server.errors import SandboxError
from openhands.app_server.sandbox.sandbox_models import (
    AGENT_SERVER,
    VSCODE,
    WORKER_1,
    WORKER_2,
    ExposedUrl,
    SandboxInfo,
    SandboxPage,
    SandboxStatus,
)
from openhands.app_server.sandbox.sandbox_service import (
    ALLOW_CORS_ORIGINS_VARIABLE,
    SESSION_API_KEY_VARIABLE,
    WEBHOOK_CALLBACK_VARIABLE,
    SandboxService,
    SandboxServiceInjector,
)
from openhands.app_server.sandbox.sandbox_spec_models import SandboxSpecInfo
from openhands.app_server.sandbox.sandbox_spec_service import SandboxSpecService
from openhands.app_server.services.injector import InjectorState

_logger = logging.getLogger(__name__)

# Container label used to identify OpenHands Kata sandboxes
KATA_SANDBOX_LABEL = 'openhands.kata.sandbox'
KATA_SANDBOX_ID_LABEL = 'openhands.sandbox.id'
KATA_SESSION_API_KEY_HASH_LABEL = 'openhands.session.api.key.hash'
KATA_USER_ID_LABEL = 'openhands.user.id'
KATA_SANDBOX_SPEC_ID_LABEL = 'openhands.sandbox.spec.id'
KATA_CREATED_AT_LABEL = 'openhands.created.at'

# Default ports for services
AGENT_SERVER_PORT = 8000
VSCODE_PORT = 8001
WORKER_1_PORT = 8011
WORKER_2_PORT = 8012


def _hash_session_api_key(session_api_key: str) -> str:
    """Hash a session API key using SHA-256."""
    return hashlib.sha256(session_api_key.encode()).hexdigest()


def _generate_session_api_key() -> str:
    """Generate a secure session API key."""
    return base62.encodebytes(secrets.token_bytes(32))


@dataclass
class KataContainerInfo:
    """Information about a Kata container."""

    container_id: str
    sandbox_id: str
    user_id: str | None
    sandbox_spec_id: str
    session_api_key_hash: str | None
    status: str
    ip_address: str | None
    created_at: datetime
    exposed_ports: dict[int, int] | None = None  # container_port -> host_port


@dataclass
class KataSandboxService(SandboxService):
    """Sandbox service that uses Kata Containers for VM-based isolation.

    Kata Containers provides enhanced security by running each container inside
    a lightweight virtual machine. This service manages the lifecycle of these
    sandboxes using containerd with the kata-runtime class.

    The service supports two modes:
    1. Direct containerd mode: Uses containerd API directly with kata-runtime
    2. Kubernetes mode: Uses Kubernetes with Kata as a RuntimeClass

    This implementation uses containerd's ctr/nerdctl commands for simplicity,
    but can be extended to use the containerd gRPC API for more control.
    """

    sandbox_spec_service: SandboxSpecService
    user_id: str | None
    httpx_client: httpx.AsyncClient
    container_name_prefix: str
    containerd_namespace: str
    runtime_type: str  # 'io.containerd.kata.v2' or similar
    container_url_pattern: str
    max_num_sandboxes: int
    web_url: str | None
    host_port: int
    nerdctl_bin: str = 'nerdctl'
    enable_host_network: bool = False
    startup_timeout: int = 120
    kata_config_path: str | None = None
    _sandboxes: dict[str, KataContainerInfo] = field(default_factory=dict)

    async def _run_command(
        self,
        cmd: list[str],
        check: bool = True,
        capture_output: bool = True,
    ) -> tuple[int, str, str]:
        """Run a command asynchronously and return exit code, stdout, stderr."""
        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE if capture_output else None,
                stderr=asyncio.subprocess.PIPE if capture_output else None,
            )
            stdout, stderr = await process.communicate()

            stdout_str = stdout.decode() if stdout else ''
            stderr_str = stderr.decode() if stderr else ''

            if check and process.returncode != 0:
                _logger.error(
                    f'Command failed: {" ".join(cmd)}\n'
                    f'Exit code: {process.returncode}\n'
                    f'Stderr: {stderr_str}'
                )

            return process.returncode or 0, stdout_str, stderr_str

        except Exception as e:
            _logger.error(f'Failed to run command {" ".join(cmd)}: {e}')
            raise SandboxError(f'Failed to execute command: {e}')

    def _get_container_name(self, sandbox_id: str) -> str:
        """Get the container name for a sandbox."""
        return f'{self.container_name_prefix}{sandbox_id}'

    async def _get_container_info(self, container_name: str) -> dict[str, Any] | None:
        """Get container information using nerdctl inspect."""
        cmd = [
            self.nerdctl_bin,
            '-n',
            self.containerd_namespace,
            'inspect',
            container_name,
        ]
        exit_code, stdout, stderr = await self._run_command(cmd, check=False)

        if exit_code != 0:
            return None

        try:
            # nerdctl inspect returns a JSON array
            data = json.loads(stdout)
            if isinstance(data, list) and len(data) > 0:
                return data[0]
            return data
        except json.JSONDecodeError:
            _logger.error(f'Failed to parse container info: {stdout}')
            return None

    async def _list_containers(self) -> list[dict[str, Any]]:
        """List all OpenHands Kata containers."""
        cmd = [
            self.nerdctl_bin,
            '-n',
            self.containerd_namespace,
            'ps',
            '-a',
            '--filter',
            f'label={KATA_SANDBOX_LABEL}=true',
            '--format',
            'json',
        ]
        exit_code, stdout, stderr = await self._run_command(cmd, check=False)

        if exit_code != 0:
            _logger.warning(f'Failed to list containers: {stderr}')
            return []

        containers = []
        for line in stdout.strip().split('\n'):
            if line:
                try:
                    containers.append(json.loads(line))
                except json.JSONDecodeError:
                    continue

        return containers

    def _container_status_to_sandbox_status(self, status: str) -> SandboxStatus:
        """Convert container status to SandboxStatus."""
        status_lower = status.lower()
        if 'running' in status_lower:
            return SandboxStatus.RUNNING
        elif 'paused' in status_lower:
            return SandboxStatus.PAUSED
        elif 'created' in status_lower or 'starting' in status_lower:
            return SandboxStatus.STARTING
        elif 'exited' in status_lower or 'stopped' in status_lower:
            return SandboxStatus.PAUSED
        elif 'dead' in status_lower or 'removing' in status_lower:
            return SandboxStatus.MISSING
        else:
            return SandboxStatus.ERROR

    async def _parse_container_to_kata_info(
        self, container: dict[str, Any]
    ) -> KataContainerInfo | None:
        """Parse container info into KataContainerInfo."""
        try:
            labels = container.get('Labels', {}) or {}
            sandbox_id = labels.get(KATA_SANDBOX_ID_LABEL)
            if not sandbox_id:
                return None

            # Get IP address from network settings
            ip_address = None
            networks = container.get('NetworkSettings', {})
            if networks:
                # Try to get IP from default network
                ip_address = networks.get('IPAddress')
                if not ip_address:
                    # Try networks map
                    networks_map = networks.get('Networks', {})
                    for net in networks_map.values():
                        if net.get('IPAddress'):
                            ip_address = net['IPAddress']
                            break

            # Parse created_at
            created_at_str = labels.get(KATA_CREATED_AT_LABEL)
            if created_at_str:
                try:
                    created_at = datetime.fromisoformat(created_at_str)
                except (ValueError, TypeError):
                    created_at = utc_now()
            else:
                created_at = utc_now()

            # Get container status
            status = container.get('Status', container.get('State', 'unknown'))
            if isinstance(status, dict):
                status = status.get('Status', 'unknown')

            return KataContainerInfo(
                container_id=container.get('Id', container.get('ID', '')),
                sandbox_id=sandbox_id,
                user_id=labels.get(KATA_USER_ID_LABEL),
                sandbox_spec_id=labels.get(KATA_SANDBOX_SPEC_ID_LABEL, ''),
                session_api_key_hash=labels.get(KATA_SESSION_API_KEY_HASH_LABEL),
                status=status,
                ip_address=ip_address,
                created_at=created_at,
            )
        except Exception as e:
            _logger.error(f'Failed to parse container info: {e}')
            return None

    def _kata_info_to_sandbox_info(
        self,
        kata_info: KataContainerInfo,
        session_api_key: str | None = None,
    ) -> SandboxInfo:
        """Convert KataContainerInfo to SandboxInfo."""
        status = self._container_status_to_sandbox_status(kata_info.status)

        exposed_urls = None
        if status == SandboxStatus.RUNNING and kata_info.ip_address:
            ip = kata_info.ip_address
            exposed_urls = [
                ExposedUrl(
                    name=AGENT_SERVER,
                    url=self.container_url_pattern.format(
                        host=ip, port=AGENT_SERVER_PORT
                    ),
                    port=AGENT_SERVER_PORT,
                ),
                ExposedUrl(
                    name=VSCODE,
                    url=self.container_url_pattern.format(host=ip, port=VSCODE_PORT),
                    port=VSCODE_PORT,
                ),
                ExposedUrl(
                    name=WORKER_1,
                    url=self.container_url_pattern.format(host=ip, port=WORKER_1_PORT),
                    port=WORKER_1_PORT,
                ),
                ExposedUrl(
                    name=WORKER_2,
                    url=self.container_url_pattern.format(host=ip, port=WORKER_2_PORT),
                    port=WORKER_2_PORT,
                ),
            ]

        return SandboxInfo(
            id=kata_info.sandbox_id,
            created_by_user_id=kata_info.user_id,
            sandbox_spec_id=kata_info.sandbox_spec_id,
            status=status,
            session_api_key=session_api_key,
            exposed_urls=exposed_urls,
            created_at=kata_info.created_at,
        )

    async def search_sandboxes(
        self,
        page_id: str | None = None,
        limit: int = 100,
    ) -> SandboxPage:
        """Search for Kata sandboxes."""
        containers = await self._list_containers()

        # Parse containers into KataContainerInfo
        kata_infos = []
        for container in containers:
            info = await self._parse_container_to_kata_info(container)
            if info:
                # Filter by user if applicable
                if self.user_id and info.user_id and info.user_id != self.user_id:
                    continue
                kata_infos.append(info)

        # Sort by creation time (newest first)
        kata_infos.sort(key=lambda x: x.created_at, reverse=True)

        # Apply pagination
        start_idx = 0
        if page_id:
            try:
                start_idx = int(page_id)
            except ValueError:
                start_idx = 0

        end_idx = start_idx + limit
        paginated_infos = kata_infos[start_idx:end_idx]

        # Convert to SandboxInfo
        items = [self._kata_info_to_sandbox_info(info) for info in paginated_infos]

        # Determine next page ID
        next_page_id = None
        if end_idx < len(kata_infos):
            next_page_id = str(end_idx)

        return SandboxPage(items=items, next_page_id=next_page_id)

    async def get_sandbox(self, sandbox_id: str) -> SandboxInfo | None:
        """Get a single Kata sandbox."""
        container_name = self._get_container_name(sandbox_id)
        container_info = await self._get_container_info(container_name)

        if not container_info:
            return None

        kata_info = await self._parse_container_to_kata_info(container_info)
        if not kata_info:
            return None

        # Get full info with session_api_key from our local cache
        cached = self._sandboxes.get(sandbox_id)
        if cached:
            # Return session_api_key only for matching users
            if not self.user_id or cached.user_id == self.user_id:
                # We store the key temporarily in memory for security
                pass  # Session key is retrieved from env in the container

        return self._kata_info_to_sandbox_info(kata_info)

    async def get_sandbox_by_session_api_key(
        self, session_api_key: str
    ) -> SandboxInfo | None:
        """Get a sandbox by its session API key."""
        hashed_key = _hash_session_api_key(session_api_key)

        containers = await self._list_containers()
        for container in containers:
            info = await self._parse_container_to_kata_info(container)
            if info and info.session_api_key_hash == hashed_key:
                return self._kata_info_to_sandbox_info(info, session_api_key)

        return None

    async def _prepare_environment(
        self,
        sandbox_spec: SandboxSpecInfo,
        sandbox_id: str,
        session_api_key: str,
    ) -> dict[str, str]:
        """Prepare environment variables for the container."""
        env = dict(sandbox_spec.initial_env)
        env[SESSION_API_KEY_VARIABLE] = session_api_key

        # Add webhook callback URL if web_url is configured
        if self.web_url:
            callback_url = f'{self.web_url}/api/conversations'
            env[WEBHOOK_CALLBACK_VARIABLE] = callback_url
            env[ALLOW_CORS_ORIGINS_VARIABLE] = self.web_url

        return env

    async def start_sandbox(
        self, sandbox_spec_id: str | None = None, sandbox_id: str | None = None
    ) -> SandboxInfo:
        """Start a new Kata sandbox."""
        # Enforce sandbox limits
        await self.pause_old_sandboxes(self.max_num_sandboxes - 1)

        # Get sandbox spec
        if sandbox_spec_id is None:
            sandbox_spec = await self.sandbox_spec_service.get_default_sandbox_spec()
        else:
            sandbox_spec_maybe = await self.sandbox_spec_service.get_sandbox_spec(
                sandbox_spec_id
            )
            if sandbox_spec_maybe is None:
                raise SandboxError(f'Sandbox spec not found: {sandbox_spec_id}')
            sandbox_spec = sandbox_spec_maybe

        # Generate IDs
        if sandbox_id is None:
            sandbox_id = base62.encodebytes(secrets.token_bytes(16))
        session_api_key = _generate_session_api_key()

        # Prepare environment
        env = await self._prepare_environment(sandbox_spec, sandbox_id, session_api_key)

        # Prepare container labels
        created_at = utc_now()
        labels = {
            KATA_SANDBOX_LABEL: 'true',
            KATA_SANDBOX_ID_LABEL: sandbox_id,
            KATA_SESSION_API_KEY_HASH_LABEL: _hash_session_api_key(session_api_key),
            KATA_SANDBOX_SPEC_ID_LABEL: sandbox_spec.id,
            KATA_CREATED_AT_LABEL: created_at.isoformat(),
        }
        if self.user_id:
            labels[KATA_USER_ID_LABEL] = self.user_id

        # Build the nerdctl run command
        container_name = self._get_container_name(sandbox_id)
        cmd = [
            self.nerdctl_bin,
            '-n',
            self.containerd_namespace,
            'run',
            '-d',  # Detached mode
            '--name',
            container_name,
            '--runtime',
            self.runtime_type,
        ]

        # Add labels
        for key, value in labels.items():
            cmd.extend(['--label', f'{key}={value}'])

        # Add environment variables
        for key, value in env.items():
            cmd.extend(['-e', f'{key}={value}'])

        # Add port mappings
        if not self.enable_host_network:
            cmd.extend(['-p', f'{AGENT_SERVER_PORT}:{AGENT_SERVER_PORT}'])
            cmd.extend(['-p', f'{VSCODE_PORT}:{VSCODE_PORT}'])
            cmd.extend(['-p', f'{WORKER_1_PORT}:{WORKER_1_PORT}'])
            cmd.extend(['-p', f'{WORKER_2_PORT}:{WORKER_2_PORT}'])
        else:
            cmd.append('--network=host')

        # Add working directory
        cmd.extend(['--workdir', '/workspace'])

        # Add the image
        cmd.append(sandbox_spec.id)

        # Add command if specified
        if sandbox_spec.command:
            cmd.extend(sandbox_spec.command)

        _logger.info(
            f'Starting Kata sandbox {sandbox_id} with command: {" ".join(cmd)}'
        )

        try:
            exit_code, stdout, stderr = await self._run_command(cmd)

            if exit_code != 0:
                raise SandboxError(f'Failed to start Kata container: {stderr}')

            # Store sandbox info in local cache
            kata_info = KataContainerInfo(
                container_id=stdout.strip()[:12],
                sandbox_id=sandbox_id,
                user_id=self.user_id,
                sandbox_spec_id=sandbox_spec.id,
                session_api_key_hash=_hash_session_api_key(session_api_key),
                status='running',
                ip_address=None,
                created_at=created_at,
            )
            self._sandboxes[sandbox_id] = kata_info

            # Wait for container to be ready and get its IP
            sandbox_info = await self._wait_for_container_ready(sandbox_id)

            return sandbox_info

        except Exception as e:
            _logger.error(f'Failed to start Kata sandbox {sandbox_id}: {e}')
            # Cleanup on failure
            await self.delete_sandbox(sandbox_id)
            raise SandboxError(f'Failed to start Kata sandbox: {e}')

    async def _wait_for_container_ready(
        self, sandbox_id: str, timeout: int | None = None
    ) -> SandboxInfo:
        """Wait for the Kata container to be ready and return its info."""
        if timeout is None:
            timeout = self.startup_timeout

        container_name = self._get_container_name(sandbox_id)
        start_time = asyncio.get_event_loop().time()

        while (asyncio.get_event_loop().time() - start_time) < timeout:
            container_info = await self._get_container_info(container_name)

            if container_info:
                kata_info = await self._parse_container_to_kata_info(container_info)
                if kata_info:
                    status = self._container_status_to_sandbox_status(kata_info.status)

                    if status == SandboxStatus.RUNNING:
                        # Verify the agent server is alive
                        if kata_info.ip_address:
                            url = f'http://{kata_info.ip_address}:{AGENT_SERVER_PORT}/alive'
                            try:
                                response = await self.httpx_client.get(url, timeout=5.0)
                                if response.is_success:
                                    return self._kata_info_to_sandbox_info(kata_info)
                            except Exception:
                                pass  # Server not ready yet

                    elif status == SandboxStatus.ERROR:
                        raise SandboxError(
                            f'Kata container {sandbox_id} entered error state'
                        )

            await asyncio.sleep(2)

        raise SandboxError(
            f'Kata sandbox {sandbox_id} failed to start within {timeout}s'
        )

    async def resume_sandbox(self, sandbox_id: str) -> bool:
        """Resume a paused Kata sandbox."""
        await self.pause_old_sandboxes(self.max_num_sandboxes - 1)

        container_name = self._get_container_name(sandbox_id)
        container_info = await self._get_container_info(container_name)

        if not container_info:
            return False

        # Determine current state
        state = container_info.get('State', {})
        if isinstance(state, dict):
            if state.get('Paused'):
                # Container is paused, unpause it
                cmd = [
                    self.nerdctl_bin,
                    '-n',
                    self.containerd_namespace,
                    'unpause',
                    container_name,
                ]
            elif state.get('Status') == 'exited' or not state.get('Running', True):
                # Container is stopped, start it
                cmd = [
                    self.nerdctl_bin,
                    '-n',
                    self.containerd_namespace,
                    'start',
                    container_name,
                ]
            else:
                # Container is already running
                return True

            exit_code, stdout, stderr = await self._run_command(cmd, check=False)
            return exit_code == 0

        return False

    async def pause_sandbox(self, sandbox_id: str) -> bool:
        """Pause a running Kata sandbox."""
        container_name = self._get_container_name(sandbox_id)
        container_info = await self._get_container_info(container_name)

        if not container_info:
            return False

        state = container_info.get('State', {})
        if isinstance(state, dict) and state.get('Running') and not state.get('Paused'):
            cmd = [
                self.nerdctl_bin,
                '-n',
                self.containerd_namespace,
                'pause',
                container_name,
            ]
            exit_code, stdout, stderr = await self._run_command(cmd, check=False)
            return exit_code == 0

        return True  # Already paused or not running

    async def delete_sandbox(self, sandbox_id: str) -> bool:
        """Delete a Kata sandbox."""
        container_name = self._get_container_name(sandbox_id)

        # First, try to stop the container
        stop_cmd = [
            self.nerdctl_bin,
            '-n',
            self.containerd_namespace,
            'stop',
            '-t',
            '10',  # 10 second timeout
            container_name,
        ]
        await self._run_command(stop_cmd, check=False)

        # Then remove the container
        rm_cmd = [
            self.nerdctl_bin,
            '-n',
            self.containerd_namespace,
            'rm',
            '-f',
            container_name,
        ]
        exit_code, stdout, stderr = await self._run_command(rm_cmd, check=False)

        # Remove from local cache
        self._sandboxes.pop(sandbox_id, None)

        return exit_code == 0 or 'no such container' in stderr.lower()


class KataSandboxServiceInjector(SandboxServiceInjector):
    """Dependency injector for Kata sandbox services.

    Configuration for running agent-server containers inside Kata VMs
    for enhanced isolation and security.
    """

    container_name_prefix: str = Field(
        default='oh-kata-sandbox-',
        description='Prefix for Kata container names',
    )
    containerd_namespace: str = Field(
        default='openhands',
        description=(
            'Containerd namespace for OpenHands sandboxes. '
            'Using a dedicated namespace helps with isolation and cleanup.'
        ),
    )
    runtime_type: str = Field(
        default='io.containerd.kata.v2',
        description=(
            'Kata runtime type to use. Common values:\n'
            '- io.containerd.kata.v2 (Kata Containers 2.x)\n'
            '- io.containerd.kata-qemu.v2 (Kata with QEMU)\n'
            '- io.containerd.kata-clh.v2 (Kata with Cloud Hypervisor)\n'
            '- io.containerd.kata-fc.v2 (Kata with Firecracker)'
        ),
    )
    container_url_pattern: str = Field(
        default='http://{host}:{port}',
        description=(
            'URL pattern for accessing services in the Kata container. '
            'Use {host} and {port} as placeholders.'
        ),
    )
    host_port: int = Field(
        default=3000,
        description='The port on which the main OpenHands app server is running.',
    )
    max_num_sandboxes: int = Field(
        default=5,
        description=(
            'Maximum number of Kata sandboxes allowed to run simultaneously. '
            'Kata VMs use more resources than standard containers.'
        ),
    )
    nerdctl_bin: str = Field(
        default='nerdctl',
        description=(
            'Path to nerdctl binary. nerdctl is a Docker-compatible CLI for containerd.'
        ),
    )
    enable_host_network: bool = Field(
        default=False,
        description=(
            'Whether to use host networking mode for Kata containers. '
            'When enabled, containers share the host network namespace.'
        ),
    )
    startup_timeout: int = Field(
        default=120,
        description=(
            'Maximum time in seconds to wait for a Kata sandbox to start. '
            'Kata VMs may take longer to start than regular containers.'
        ),
    )
    kata_config_path: str | None = Field(
        default=None,
        description=(
            'Path to custom Kata configuration file. '
            'If not specified, the system default is used.'
        ),
    )

    async def inject(
        self, state: InjectorState, request: Request | None = None
    ) -> AsyncGenerator[SandboxService, None]:
        # Import inline to prevent circular imports
        from openhands.app_server.config import (
            get_global_config,
            get_httpx_client,
            get_sandbox_spec_service,
            get_user_context,
        )

        config = get_global_config()
        web_url = config.web_url

        async with (
            get_httpx_client(state) as httpx_client,
            get_sandbox_spec_service(state) as sandbox_spec_service,
            get_user_context(state, request) as user_context,
        ):
            user_id = await user_context.get_user_id()

            yield KataSandboxService(
                sandbox_spec_service=sandbox_spec_service,
                user_id=user_id,
                httpx_client=httpx_client,
                container_name_prefix=self.container_name_prefix,
                containerd_namespace=self.containerd_namespace,
                runtime_type=self.runtime_type,
                container_url_pattern=self.container_url_pattern,
                max_num_sandboxes=self.max_num_sandboxes,
                web_url=web_url,
                host_port=self.host_port,
                nerdctl_bin=self.nerdctl_bin,
                enable_host_network=self.enable_host_network,
                startup_timeout=self.startup_timeout,
                kata_config_path=self.kata_config_path,
            )
