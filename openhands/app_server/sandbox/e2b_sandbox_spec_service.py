"""E2B Sandbox Spec Service for OpenHands V1.

This module provides sandbox spec (template) management for E2B.
It communicates with the self-hosted E2B API to list and retrieve templates.
"""

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import AsyncGenerator

import httpx
from fastapi import Request
from pydantic import Field

from openhands.agent_server.utils import utc_now
from openhands.app_server.sandbox.sandbox_spec_models import (
    SandboxSpecInfo,
    SandboxSpecInfoPage,
)
from openhands.app_server.sandbox.sandbox_spec_service import (
    SandboxSpecService,
    SandboxSpecServiceInjector,
    get_agent_server_env,
)
from openhands.app_server.services.injector import InjectorState

_logger = logging.getLogger(__name__)

# Default E2B template for OpenHands
DEFAULT_E2B_TEMPLATE = 'openhands'
DEFAULT_WORKING_DIR = '/workspace'


@dataclass
class E2BSandboxSpecService(SandboxSpecService):
    """Sandbox spec service that uses E2B templates.

    This service communicates with the self-hosted E2B API to manage templates.
    Templates in E2B are pre-built sandbox images that can be instantiated.
    """

    api_url: str
    api_key: str
    httpx_client: httpx.AsyncClient
    default_template: str = DEFAULT_E2B_TEMPLATE

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
            raise
        except httpx.HTTPError as e:
            _logger.error(f'E2B API request failed: {method} {url} - {e}')
            raise

    def _e2b_template_to_spec(self, e2b_template: dict) -> SandboxSpecInfo:
        """Convert E2B template response to SandboxSpecInfo."""
        template_id = (
            e2b_template.get('templateId')
            or e2b_template.get('template_id')
            or e2b_template.get('id', '')
        )

        # Get created_at timestamp
        created_at_str = (
            e2b_template.get('createdAt')
            or e2b_template.get('created_at')
            or e2b_template.get('buildFinishedAt')
        )
        if created_at_str:
            try:
                created_at = datetime.fromisoformat(
                    created_at_str.replace('Z', '+00:00')
                )
            except (ValueError, AttributeError):
                created_at = utc_now()
        else:
            created_at = utc_now()

        # Get initial environment variables
        initial_env = e2b_template.get('envVars', {})
        # Merge with agent server environment variables
        initial_env.update(get_agent_server_env())

        return SandboxSpecInfo(
            id=template_id,
            command=None,  # E2B templates have built-in commands
            created_at=created_at,
            initial_env=initial_env,
            working_dir=DEFAULT_WORKING_DIR,
        )

    async def search_sandbox_specs(
        self, page_id: str | None = None, limit: int = 100
    ) -> SandboxSpecInfoPage:
        """Search for sandbox specs (E2B templates)."""
        params: dict[str, str | int] = {'limit': limit}
        if page_id:
            params['cursor'] = page_id

        try:
            response = await self._send_e2b_request('GET', '/templates', params=params)

            if response.status_code == 200:
                data = response.json()
                templates = (
                    data.get('templates', data) if isinstance(data, dict) else data
                )

                items = [self._e2b_template_to_spec(t) for t in templates]

                # Ensure default template is first if present
                items.sort(key=lambda x: (x.id != self.default_template, x.id))

                next_page_id = (
                    data.get('nextCursor') if isinstance(data, dict) else None
                )
                return SandboxSpecInfoPage(items=items, next_page_id=next_page_id)

        except Exception as e:
            _logger.warning(f'Failed to fetch E2B templates: {e}')

        # Return default template if API fails
        return SandboxSpecInfoPage(
            items=[
                SandboxSpecInfo(
                    id=self.default_template,
                    command=None,
                    initial_env=get_agent_server_env(),
                    working_dir=DEFAULT_WORKING_DIR,
                )
            ]
        )

    async def get_sandbox_spec(self, sandbox_spec_id: str) -> SandboxSpecInfo | None:
        """Get a single sandbox spec (E2B template)."""
        try:
            response = await self._send_e2b_request(
                'GET', f'/templates/{sandbox_spec_id}'
            )

            if response.status_code == 200:
                e2b_template = response.json()
                return self._e2b_template_to_spec(e2b_template)

            if response.status_code == 404:
                return None

        except Exception as e:
            _logger.warning(f'Failed to get E2B template {sandbox_spec_id}: {e}')

        # Return a basic spec for the requested ID if API fails
        # This allows the system to attempt to use templates that might exist
        if sandbox_spec_id == self.default_template:
            return SandboxSpecInfo(
                id=sandbox_spec_id,
                command=None,
                initial_env=get_agent_server_env(),
                working_dir=DEFAULT_WORKING_DIR,
            )

        return None


class E2BSandboxSpecServiceInjector(SandboxSpecServiceInjector):
    """Dependency injector for E2B sandbox spec services."""

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
    default_template: str = Field(
        default=DEFAULT_E2B_TEMPLATE,
        description='Default E2B template name for OpenHands sandboxes.',
    )

    async def inject(
        self, state: InjectorState, request: Request | None = None
    ) -> AsyncGenerator[SandboxSpecService, None]:
        from openhands.app_server.config import get_httpx_client

        async with get_httpx_client(state) as httpx_client:
            yield E2BSandboxSpecService(
                api_url=self.api_url,
                api_key=self.api_key,
                httpx_client=httpx_client,
                default_template=self.default_template,
            )
