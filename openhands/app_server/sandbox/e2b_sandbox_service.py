"""E2B Sandbox Service for OpenHands V1.

This module provides sandbox management using E2B (https://e2b.dev) micro VMs.
It's designed to work with self-hosted E2B infrastructure.

Configuration:
    - E2B_API_KEY: API key for E2B authentication
    - E2B_API_URL: URL of the self-hosted E2B API (e.g., https://api.e2b.your-domain.com)
"""

import logging
import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import AsyncGenerator

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

# Default ports exposed by the agent server
AGENT_SERVER_PORT = 8000
VSCODE_PORT = 8001
WORKER_1_PORT = 8011
WORKER_2_PORT = 8012

# E2B sandbox status mapping
E2B_STATUS_MAPPING = {
    'running': SandboxStatus.RUNNING,
    'starting': SandboxStatus.STARTING,
    'paused': SandboxStatus.PAUSED,
    'stopped': SandboxStatus.PAUSED,
    'error': SandboxStatus.ERROR,
}


@dataclass
class E2BSandboxService(SandboxService):
    """Sandbox service that uses E2B micro VMs.

    This service communicates with a self-hosted E2B API to create and manage
    sandboxes running the OpenHands agent server.
    """

    sandbox_spec_service: SandboxSpecService
    api_url: str
    api_key: str
    web_url: str | None
    webhook_url: str | None
    max_num_sandboxes: int
    sandbox_timeout: int
    httpx_client: httpx.AsyncClient
    _sandbox_cache: dict[str, SandboxInfo] = field(default_factory=dict)

    async def _send_e2b_request(
        self,
        method: str,
        path: str,
        **kwargs,
    ) -> httpx.Response:
        """Send a request to the E2B API."""
        url = f'{self.api_url.rstrip("/")}{path}'
        headers = kwargs.pop('headers', {})
        headers['X-API-Key'] = self.api_key
        headers['Content-Type'] = 'application/json'

        try:
            response = await self.httpx_client.request(
                method, url, headers=headers, **kwargs
            )
            return response
        except httpx.TimeoutException:
            _logger.error(f'E2B API request timed out: {method} {url}')
            raise SandboxError(f'E2B API request timed out: {path}')
        except httpx.HTTPError as e:
            _logger.error(f'E2B API request failed: {method} {url} - {e}')
            raise SandboxError(f'E2B API request failed: {e}')

    def _e2b_status_to_sandbox_status(self, e2b_status: str) -> SandboxStatus:
        """Convert E2B sandbox status to SandboxStatus."""
        return E2B_STATUS_MAPPING.get(e2b_status.lower(), SandboxStatus.ERROR)

    def _build_exposed_urls(
        self,
        sandbox_id: str,
        sandbox_host: str,
        session_api_key: str,
        working_dir: str = '/workspace',
    ) -> list[ExposedUrl]:
        """Build the list of exposed URLs for a sandbox."""
        exposed_urls = []

        # Agent server URL
        agent_server_url = f'https://{AGENT_SERVER_PORT}-{sandbox_id}.{sandbox_host}'
        exposed_urls.append(
            ExposedUrl(name=AGENT_SERVER, url=agent_server_url, port=AGENT_SERVER_PORT)
        )

        # VSCode URL
        vscode_url = f'https://{VSCODE_PORT}-{sandbox_id}.{sandbox_host}'
        vscode_url += f'/?tkn={session_api_key}&folder={working_dir}'
        exposed_urls.append(ExposedUrl(name=VSCODE, url=vscode_url, port=VSCODE_PORT))

        # Worker URLs
        worker_1_url = f'https://{WORKER_1_PORT}-{sandbox_id}.{sandbox_host}'
        exposed_urls.append(
            ExposedUrl(name=WORKER_1, url=worker_1_url, port=WORKER_1_PORT)
        )

        worker_2_url = f'https://{WORKER_2_PORT}-{sandbox_id}.{sandbox_host}'
        exposed_urls.append(
            ExposedUrl(name=WORKER_2, url=worker_2_url, port=WORKER_2_PORT)
        )

        return exposed_urls

    def _e2b_sandbox_to_info(
        self,
        e2b_sandbox: dict,
        session_api_key: str | None = None,
    ) -> SandboxInfo:
        """Convert E2B sandbox response to SandboxInfo."""
        sandbox_id = e2b_sandbox.get('sandboxId') or e2b_sandbox.get('sandbox_id', '')
        status = self._e2b_status_to_sandbox_status(
            e2b_sandbox.get('status', 'unknown')
        )

        # Get created_at timestamp
        created_at_str = e2b_sandbox.get('createdAt') or e2b_sandbox.get('created_at')
        if created_at_str:
            try:
                created_at = datetime.fromisoformat(
                    created_at_str.replace('Z', '+00:00')
                )
            except (ValueError, AttributeError):
                created_at = utc_now()
        else:
            created_at = utc_now()

        # Build exposed URLs if sandbox is running
        exposed_urls = None
        if status == SandboxStatus.RUNNING and session_api_key:
            sandbox_host = e2b_sandbox.get('clientId') or self._get_sandbox_host()
            working_dir = e2b_sandbox.get('cwd', '/workspace')
            exposed_urls = self._build_exposed_urls(
                sandbox_id, sandbox_host, session_api_key, working_dir
            )

        return SandboxInfo(
            id=sandbox_id,
            created_by_user_id=e2b_sandbox.get('userId'),
            sandbox_spec_id=e2b_sandbox.get('templateId', 'openhands'),
            status=status,
            session_api_key=session_api_key
            if status == SandboxStatus.RUNNING
            else None,
            exposed_urls=exposed_urls,
            created_at=created_at,
        )

    def _get_sandbox_host(self) -> str:
        """Extract the sandbox host from the API URL."""
        # E2B sandboxes are typically accessible at {port}-{sandbox_id}.{host}
        # Extract host from API URL (e.g., api.e2b.example.com -> e2b.example.com)
        from urllib.parse import urlparse

        parsed = urlparse(self.api_url)
        host = parsed.netloc
        if host.startswith('api.'):
            host = host[4:]
        return host

    async def search_sandboxes(
        self,
        page_id: str | None = None,
        limit: int = 100,
    ) -> SandboxPage:
        """Search for sandboxes."""
        params: dict[str, str | int] = {'limit': limit}
        if page_id:
            params['cursor'] = page_id

        response = await self._send_e2b_request('GET', '/sandboxes', params=params)

        if response.status_code == 200:
            data = response.json()
            sandboxes = data.get('sandboxes', data) if isinstance(data, dict) else data

            items = []
            for e2b_sandbox in sandboxes:
                sandbox_id = e2b_sandbox.get('sandboxId') or e2b_sandbox.get(
                    'sandbox_id', ''
                )
                # Try to get session_api_key from cache
                cached = self._sandbox_cache.get(sandbox_id)
                session_api_key = cached.session_api_key if cached else None
                items.append(self._e2b_sandbox_to_info(e2b_sandbox, session_api_key))

            next_page_id = data.get('nextCursor') if isinstance(data, dict) else None
            return SandboxPage(items=items, next_page_id=next_page_id)

        _logger.warning(f'Failed to search E2B sandboxes: {response.status_code}')
        return SandboxPage(items=[])

    async def get_sandbox(self, sandbox_id: str) -> SandboxInfo | None:
        """Get a single sandbox."""
        response = await self._send_e2b_request('GET', f'/sandboxes/{sandbox_id}')

        if response.status_code == 200:
            e2b_sandbox = response.json()
            # Try to get session_api_key from cache
            cached = self._sandbox_cache.get(sandbox_id)
            session_api_key = cached.session_api_key if cached else None
            sandbox_info = self._e2b_sandbox_to_info(e2b_sandbox, session_api_key)

            # Update cache
            if session_api_key:
                self._sandbox_cache[sandbox_id] = sandbox_info

            return sandbox_info

        if response.status_code == 404:
            # Remove from cache if not found
            self._sandbox_cache.pop(sandbox_id, None)
            return None

        _logger.warning(
            f'Failed to get E2B sandbox {sandbox_id}: {response.status_code}'
        )
        return None

    async def get_sandbox_by_session_api_key(
        self, session_api_key: str
    ) -> SandboxInfo | None:
        """Get a sandbox by its session API key."""
        # Search through cached sandboxes first
        for sandbox_id, sandbox_info in self._sandbox_cache.items():
            if sandbox_info.session_api_key == session_api_key:
                # Verify it still exists
                current = await self.get_sandbox(sandbox_id)
                if current and current.status == SandboxStatus.RUNNING:
                    return current

        # Fall back to searching all sandboxes
        async for sandbox in self._iter_all_sandboxes():
            if sandbox.session_api_key == session_api_key:
                return sandbox

        return None

    async def _iter_all_sandboxes(self):
        """Iterate through all sandboxes."""
        page_id = None
        while True:
            page = await self.search_sandboxes(page_id=page_id)
            for sandbox in page.items:
                yield sandbox
            if not page.next_page_id:
                break
            page_id = page.next_page_id

    async def start_sandbox(
        self, sandbox_spec_id: str | None = None, sandbox_id: str | None = None
    ) -> SandboxInfo:
        """Start a new E2B sandbox."""
        # Enforce sandbox limits
        await self.pause_old_sandboxes(self.max_num_sandboxes - 1)

        # Get sandbox spec (template)
        sandbox_spec: SandboxSpecInfo
        if sandbox_spec_id is None:
            sandbox_spec = await self.sandbox_spec_service.get_default_sandbox_spec()
            sandbox_spec_id = sandbox_spec.id
        else:
            sandbox_spec_maybe = await self.sandbox_spec_service.get_sandbox_spec(
                sandbox_spec_id
            )
            if sandbox_spec_maybe is None:
                raise SandboxError(f'Sandbox spec not found: {sandbox_spec_id}')
            sandbox_spec = sandbox_spec_maybe

        # Generate session API key
        session_api_key = base62.encodebytes(os.urandom(32))

        # Prepare environment variables
        env_vars = sandbox_spec.initial_env.copy()
        env_vars[SESSION_API_KEY_VARIABLE] = session_api_key

        # Set webhook callback URL
        if self.webhook_url:
            env_vars[WEBHOOK_CALLBACK_VARIABLE] = f'{self.webhook_url}/api/v1/webhooks'

        # Set CORS origins for remote browser access
        if self.web_url:
            env_vars[ALLOW_CORS_ORIGINS_VARIABLE] = self.web_url

        # Prepare request payload
        payload = {
            'templateId': sandbox_spec_id,
            'timeout': self.sandbox_timeout,
            'envVars': env_vars,
        }

        # Include custom sandbox ID if provided
        if sandbox_id:
            payload['sandboxId'] = sandbox_id

        response = await self._send_e2b_request('POST', '/sandboxes', json=payload)

        if response.status_code in (200, 201):
            e2b_sandbox = response.json()
            sandbox_info = self._e2b_sandbox_to_info(e2b_sandbox, session_api_key)

            # Cache the sandbox info with session_api_key
            self._sandbox_cache[sandbox_info.id] = sandbox_info

            _logger.info(f'Started E2B sandbox: {sandbox_info.id}')
            return sandbox_info

        error_msg = f'Failed to start E2B sandbox: {response.status_code}'
        try:
            error_detail = response.json()
            error_msg += f' - {error_detail}'
        except Exception:
            pass

        _logger.error(error_msg)
        raise SandboxError(error_msg)

    async def resume_sandbox(self, sandbox_id: str) -> bool:
        """Resume a paused sandbox."""
        # Enforce sandbox limits
        await self.pause_old_sandboxes(self.max_num_sandboxes - 1)

        response = await self._send_e2b_request(
            'POST', f'/sandboxes/{sandbox_id}/resume'
        )

        if response.status_code in (200, 204):
            _logger.info(f'Resumed E2B sandbox: {sandbox_id}')
            return True

        if response.status_code == 404:
            return False

        _logger.warning(
            f'Failed to resume E2B sandbox {sandbox_id}: {response.status_code}'
        )
        return False

    async def pause_sandbox(self, sandbox_id: str) -> bool:
        """Pause a running sandbox."""
        response = await self._send_e2b_request(
            'POST', f'/sandboxes/{sandbox_id}/pause'
        )

        if response.status_code in (200, 204):
            _logger.info(f'Paused E2B sandbox: {sandbox_id}')
            return True

        if response.status_code == 404:
            return False

        _logger.warning(
            f'Failed to pause E2B sandbox {sandbox_id}: {response.status_code}'
        )
        return False

    async def delete_sandbox(self, sandbox_id: str) -> bool:
        """Delete a sandbox."""
        response = await self._send_e2b_request('DELETE', f'/sandboxes/{sandbox_id}')

        if response.status_code in (200, 204):
            # Remove from cache
            self._sandbox_cache.pop(sandbox_id, None)
            _logger.info(f'Deleted E2B sandbox: {sandbox_id}')
            return True

        if response.status_code == 404:
            self._sandbox_cache.pop(sandbox_id, None)
            return False

        _logger.warning(
            f'Failed to delete E2B sandbox {sandbox_id}: {response.status_code}'
        )
        return False


class E2BSandboxServiceInjector(SandboxServiceInjector):
    """Dependency injector for E2B sandbox services."""

    api_url: str = Field(
        description=(
            'URL of the self-hosted E2B API. '
            'Configure via OH_E2B_API_URL environment variable.'
        ),
    )
    api_key: str = Field(
        description=(
            'API key for E2B authentication. '
            'Configure via OH_E2B_API_KEY environment variable.'
        ),
    )
    max_num_sandboxes: int = Field(
        default=10,
        description='Maximum number of sandboxes allowed to run simultaneously.',
    )
    sandbox_timeout: int = Field(
        default=3600,
        description='Timeout in seconds for sandbox lifetime (default: 1 hour).',
    )
    webhook_url: str | None = Field(
        default=None,
        description=(
            'URL for webhook callbacks from agent servers. '
            'If not set, will use web_url if available.'
        ),
    )

    async def inject(
        self, state: InjectorState, request: Request | None = None
    ) -> AsyncGenerator[SandboxService, None]:
        from openhands.app_server.config import (
            get_global_config,
            get_httpx_client,
            get_sandbox_spec_service,
        )

        config = get_global_config()
        web_url = config.web_url
        webhook_url = self.webhook_url or web_url

        async with (
            get_httpx_client(state) as httpx_client,
            get_sandbox_spec_service(state) as sandbox_spec_service,
        ):
            yield E2BSandboxService(
                sandbox_spec_service=sandbox_spec_service,
                api_url=self.api_url,
                api_key=self.api_key,
                web_url=web_url,
                webhook_url=webhook_url,
                max_num_sandboxes=self.max_num_sandboxes,
                sandbox_timeout=self.sandbox_timeout,
                httpx_client=httpx_client,
            )
