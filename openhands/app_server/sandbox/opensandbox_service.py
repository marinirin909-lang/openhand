import hashlib
import logging
import secrets
from dataclasses import dataclass
from typing import Any, AsyncGenerator

import httpx
from fastapi import Request
from pydantic import Field
from sqlalchemy import Column, String, func, select
from sqlalchemy.ext.asyncio import AsyncSession

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
from openhands.app_server.user.user_context import UserContext
from openhands.app_server.utils.sql_utils import Base, UtcDateTime

_logger = logging.getLogger(__name__)

# OpenSandbox state -> OpenHands SandboxStatus mapping
OPENSANDBOX_STATUS_MAPPING = {
    'Pending': SandboxStatus.STARTING,
    'Running': SandboxStatus.RUNNING,
    'Pausing': SandboxStatus.RUNNING,  # Transitional state
    'Paused': SandboxStatus.PAUSED,
    'Stopping': SandboxStatus.MISSING,
    'Terminated': SandboxStatus.MISSING,
    'Failed': SandboxStatus.ERROR,
}

AGENT_SERVER_PORT = 60000
VSCODE_PORT = 60001
WORKER_1_PORT = 12000
WORKER_2_PORT = 12001


def _hash_session_api_key(session_api_key: str) -> str:
    """Hash a session API key using SHA-256."""
    return hashlib.sha256(session_api_key.encode()).hexdigest()


class StoredOpenSandbox(Base):  # type: ignore
    """Local storage for OpenSandbox sandbox info."""

    __tablename__ = 'v1_opensandbox'
    id = Column(String, primary_key=True)
    opensandbox_id = Column(String, nullable=False, index=True)
    created_by_user_id = Column(String, nullable=True, index=True)
    sandbox_spec_id = Column(String, index=True)
    session_api_key = Column(String, nullable=True)
    session_api_key_hash = Column(String, nullable=True, index=True)
    created_at = Column(UtcDateTime, server_default=func.now(), index=True)


@dataclass
class OpenSandboxService(SandboxService):
    """Sandbox service that uses OpenSandbox Lifecycle API to manage sandboxes."""

    sandbox_spec_service: SandboxSpecService
    api_url: str
    api_key: str
    web_url: str | None
    sandbox_timeout: int
    max_num_sandboxes: int
    user_context: UserContext
    httpx_client: httpx.AsyncClient
    db_session: AsyncSession

    async def _send_api_request(
        self, method: str, path: str, **kwargs: Any
    ) -> httpx.Response:
        """Send a request to the OpenSandbox API."""
        try:
            url = self.api_url.rstrip('/') + path
            headers = kwargs.pop('headers', {})
            headers['OPEN-SANDBOX-API-KEY'] = self.api_key
            return await self.httpx_client.request(
                method, url, headers=headers, **kwargs
            )
        except httpx.TimeoutException:
            _logger.error(f'No response received within timeout for URL: {url}')
            raise
        except httpx.HTTPError as e:
            _logger.error(f'HTTP error for URL {url}: {e}')
            raise

    def _get_sandbox_status(self, sandbox_data: dict[str, Any] | None) -> SandboxStatus:
        """Convert OpenSandbox state to OpenHands SandboxStatus."""
        if not sandbox_data:
            return SandboxStatus.MISSING
        status = sandbox_data.get('status', {})
        state = status.get('state', '') if isinstance(status, dict) else ''
        return OPENSANDBOX_STATUS_MAPPING.get(state, SandboxStatus.ERROR)

    async def _get_endpoint_url(self, opensandbox_id: str, port: int) -> str | None:
        """Get the public endpoint URL for a specific port."""
        try:
            response = await self._send_api_request(
                'GET', f'/sandboxes/{opensandbox_id}/endpoints/{port}'
            )
            if response.status_code == 200:
                data = response.json()
                return data.get('endpoint', None)
            return None
        except Exception:
            _logger.debug(
                f'Failed to get endpoint for sandbox {opensandbox_id} port {port}'
            )
            return None

    async def _build_exposed_urls(
        self, opensandbox_id: str, session_api_key: str | None
    ) -> list[ExposedUrl]:
        """Build exposed URLs by querying OpenSandbox endpoint API."""
        exposed_urls = []

        # Get agent server endpoint
        agent_url = await self._get_endpoint_url(opensandbox_id, AGENT_SERVER_PORT)
        if agent_url:
            # Ensure proper URL format
            if not agent_url.startswith('http'):
                agent_url = f'http://{agent_url}'
            exposed_urls.append(
                ExposedUrl(name=AGENT_SERVER, url=agent_url, port=AGENT_SERVER_PORT)
            )

            # Get VSCode endpoint
            vscode_url = await self._get_endpoint_url(opensandbox_id, VSCODE_PORT)
            if vscode_url:
                if not vscode_url.startswith('http'):
                    vscode_url = f'http://{vscode_url}'
                if session_api_key:
                    vscode_url += (
                        f'?tkn={session_api_key}&folder=%2Fworkspace%2Fproject'
                    )
                exposed_urls.append(
                    ExposedUrl(name=VSCODE, url=vscode_url, port=VSCODE_PORT)
                )

            # Get worker endpoints
            for worker_name, worker_port in [
                (WORKER_1, WORKER_1_PORT),
                (WORKER_2, WORKER_2_PORT),
            ]:
                worker_url = await self._get_endpoint_url(opensandbox_id, worker_port)
                if worker_url:
                    if not worker_url.startswith('http'):
                        worker_url = f'http://{worker_url}'
                    exposed_urls.append(
                        ExposedUrl(name=worker_name, url=worker_url, port=worker_port)
                    )

        return exposed_urls

    def _to_sandbox_info(
        self,
        stored: StoredOpenSandbox,
        sandbox_data: dict[str, Any] | None = None,
        exposed_urls: list[ExposedUrl] | None = None,
    ) -> SandboxInfo:
        """Convert stored sandbox and API data to SandboxInfo."""
        status = self._get_sandbox_status(sandbox_data)

        session_api_key = (
            stored.session_api_key if status == SandboxStatus.RUNNING else None
        )

        return SandboxInfo(
            id=stored.id,
            created_by_user_id=stored.created_by_user_id,
            sandbox_spec_id=stored.sandbox_spec_id,
            status=status,
            session_api_key=session_api_key,
            exposed_urls=exposed_urls if status == SandboxStatus.RUNNING else None,
            created_at=stored.created_at,
        )

    async def _secure_select(self):
        query = select(StoredOpenSandbox)
        user_id = await self.user_context.get_user_id()
        if user_id:
            query = query.where(StoredOpenSandbox.created_by_user_id == user_id)
        return query

    async def _get_stored_sandbox(self, sandbox_id: str) -> StoredOpenSandbox | None:
        stmt = await self._secure_select()
        stmt = stmt.where(StoredOpenSandbox.id == sandbox_id)
        result = await self.db_session.execute(stmt)
        return result.scalar_one_or_none()

    async def _get_opensandbox_data(self, opensandbox_id: str) -> dict[str, Any] | None:
        """Fetch sandbox data from OpenSandbox API."""
        try:
            response = await self._send_api_request(
                'GET', f'/sandboxes/{opensandbox_id}'
            )
            if response.status_code == 404:
                return None
            response.raise_for_status()
            return response.json()
        except Exception:
            _logger.exception(
                f'Error getting OpenSandbox data: {opensandbox_id}', stack_info=True
            )
            return None

    async def _init_environment(
        self, sandbox_spec: SandboxSpecInfo, session_api_key: str
    ) -> dict[str, str]:
        """Initialize environment variables for the sandbox."""
        environment = sandbox_spec.initial_env.copy()

        # Inject the session API key
        environment[SESSION_API_KEY_VARIABLE] = session_api_key

        # If a public facing url is defined, add webhook callback and CORS settings
        if self.web_url:
            environment[WEBHOOK_CALLBACK_VARIABLE] = f'{self.web_url}/api/v1/webhooks'
            environment[ALLOW_CORS_ORIGINS_VARIABLE] = self.web_url

        # Add worker port environment variables
        environment[WORKER_1] = str(WORKER_1_PORT)
        environment[WORKER_2] = str(WORKER_2_PORT)

        return environment

    async def search_sandboxes(
        self,
        page_id: str | None = None,
        limit: int = 100,
    ) -> SandboxPage:
        stmt = await self._secure_select()

        if page_id is not None:
            try:
                offset = int(page_id)
                stmt = stmt.offset(offset)
            except ValueError:
                offset = 0
        else:
            offset = 0

        stmt = stmt.limit(limit + 1).order_by(StoredOpenSandbox.created_at.desc())
        result = await self.db_session.execute(stmt)
        stored_sandboxes = result.scalars().all()

        has_more = len(stored_sandboxes) > limit
        if has_more:
            stored_sandboxes = stored_sandboxes[:limit]

        next_page_id = str(offset + limit) if has_more else None

        # Fetch sandbox data from OpenSandbox API for each stored sandbox
        items = []
        for stored in stored_sandboxes:
            sandbox_data = await self._get_opensandbox_data(stored.opensandbox_id)
            status = self._get_sandbox_status(sandbox_data)
            exposed_urls = None
            if status == SandboxStatus.RUNNING:
                exposed_urls = await self._build_exposed_urls(
                    stored.opensandbox_id, stored.session_api_key
                )
            items.append(self._to_sandbox_info(stored, sandbox_data, exposed_urls))

        return SandboxPage(items=items, next_page_id=next_page_id)

    async def get_sandbox(self, sandbox_id: str) -> SandboxInfo | None:
        stored = await self._get_stored_sandbox(sandbox_id)
        if stored is None:
            return None

        sandbox_data = await self._get_opensandbox_data(stored.opensandbox_id)
        status = self._get_sandbox_status(sandbox_data)
        exposed_urls = None
        if status == SandboxStatus.RUNNING:
            exposed_urls = await self._build_exposed_urls(
                stored.opensandbox_id, stored.session_api_key
            )
        return self._to_sandbox_info(stored, sandbox_data, exposed_urls)

    async def get_sandbox_by_session_api_key(
        self, session_api_key: str
    ) -> SandboxInfo | None:
        session_api_key_hash = _hash_session_api_key(session_api_key)

        stmt = await self._secure_select()
        stmt = stmt.where(
            StoredOpenSandbox.session_api_key_hash == session_api_key_hash
        )
        result = await self.db_session.execute(stmt)
        stored = result.scalar_one_or_none()

        if stored is None:
            return None

        sandbox_data = await self._get_opensandbox_data(stored.opensandbox_id)
        status = self._get_sandbox_status(sandbox_data)
        exposed_urls = None
        if status == SandboxStatus.RUNNING:
            exposed_urls = await self._build_exposed_urls(
                stored.opensandbox_id, stored.session_api_key
            )
        return self._to_sandbox_info(stored, sandbox_data, exposed_urls)

    async def start_sandbox(
        self, sandbox_spec_id: str | None = None, sandbox_id: str | None = None
    ) -> SandboxInfo:
        try:
            # Enforce sandbox limits
            await self.pause_old_sandboxes(self.max_num_sandboxes - 1)

            # Get sandbox spec
            if sandbox_spec_id is None:
                sandbox_spec = (
                    await self.sandbox_spec_service.get_default_sandbox_spec()
                )
            else:
                sandbox_spec_maybe = await self.sandbox_spec_service.get_sandbox_spec(
                    sandbox_spec_id
                )
                if sandbox_spec_maybe is None:
                    raise ValueError('Sandbox Spec not found')
                sandbox_spec = sandbox_spec_maybe

            # Generate sandbox ID and session API key
            if sandbox_id is None:
                sandbox_id = secrets.token_urlsafe(16)

            session_api_key = secrets.token_urlsafe(32)
            user_id = await self.user_context.get_user_id()

            # Prepare environment
            environment = await self._init_environment(sandbox_spec, session_api_key)

            # Build entrypoint
            entrypoint = sandbox_spec.command or []

            # Build create request for OpenSandbox API
            create_request: dict[str, Any] = {
                'image': {
                    'uri': sandbox_spec.id,
                },
                'timeout': self.sandbox_timeout,
                'env': environment,
                'metadata': {
                    'oh_sandbox_id': sandbox_id,
                    'oh_user_id': user_id or '',
                },
            }
            if entrypoint:
                create_request['entrypoint'] = entrypoint

            # Call OpenSandbox API to create sandbox
            response = await self._send_api_request(
                'POST', '/sandboxes', json=create_request
            )
            response.raise_for_status()
            create_data = response.json()
            opensandbox_id = create_data.get('id', '')

            # Store locally
            stored = StoredOpenSandbox(
                id=sandbox_id,
                opensandbox_id=opensandbox_id,
                created_by_user_id=user_id,
                sandbox_spec_id=sandbox_spec.id,
                session_api_key=session_api_key,
                session_api_key_hash=_hash_session_api_key(session_api_key),
                created_at=utc_now(),
            )
            self.db_session.add(stored)

            _logger.info(
                f'Started OpenSandbox {opensandbox_id} for sandbox {sandbox_id}'
            )

            return SandboxInfo(
                id=sandbox_id,
                created_by_user_id=user_id,
                sandbox_spec_id=sandbox_spec.id,
                status=SandboxStatus.STARTING,
                session_api_key=None,
                exposed_urls=None,
                created_at=stored.created_at,
            )

        except httpx.HTTPError as e:
            _logger.error(f'Failed to start OpenSandbox: {e}')
            raise SandboxError(f'Failed to start sandbox: {e}')

    async def resume_sandbox(self, sandbox_id: str) -> bool:
        await self.pause_old_sandboxes(self.max_num_sandboxes - 1)

        try:
            stored = await self._get_stored_sandbox(sandbox_id)
            if not stored:
                return False
            response = await self._send_api_request(
                'POST', f'/sandboxes/{stored.opensandbox_id}/resume'
            )
            if response.status_code == 404:
                return False
            response.raise_for_status()
            return True
        except httpx.HTTPError as e:
            _logger.error(f'Error resuming sandbox {sandbox_id}: {e}')
            return False

    async def pause_sandbox(self, sandbox_id: str) -> bool:
        try:
            stored = await self._get_stored_sandbox(sandbox_id)
            if not stored:
                return False
            response = await self._send_api_request(
                'POST', f'/sandboxes/{stored.opensandbox_id}/pause'
            )
            if response.status_code == 404:
                return False
            response.raise_for_status()
            return True
        except httpx.HTTPError as e:
            _logger.error(f'Error pausing sandbox {sandbox_id}: {e}')
            return False

    async def delete_sandbox(self, sandbox_id: str) -> bool:
        try:
            stored = await self._get_stored_sandbox(sandbox_id)
            if not stored:
                return False
            response = await self._send_api_request(
                'DELETE', f'/sandboxes/{stored.opensandbox_id}'
            )
            if response.status_code != 404:
                response.raise_for_status()
            await self.db_session.delete(stored)
            return True
        except httpx.HTTPError as e:
            _logger.error(f'Error deleting sandbox {sandbox_id}: {e}')
            return False


class OpenSandboxServiceInjector(SandboxServiceInjector):
    """Dependency injector for OpenSandbox services."""

    api_url: str = Field(
        default='http://localhost:8080/v1',
        description='The OpenSandbox API URL',
    )
    api_key: str = Field(description='The OpenSandbox API Key')
    sandbox_timeout: int = Field(
        default=3600,
        description='Sandbox timeout in seconds (default: 1 hour)',
    )
    start_sandbox_timeout: int = Field(
        default=120,
        description='Max time to wait for sandbox to start (seconds)',
    )
    max_num_sandboxes: int = Field(
        default=10,
        description='Maximum number of sandboxes allowed to run simultaneously',
    )

    async def inject(
        self, state: InjectorState, request: Request | None = None
    ) -> AsyncGenerator[SandboxService, None]:
        from openhands.app_server.config import (
            get_db_session,
            get_global_config,
            get_httpx_client,
            get_sandbox_spec_service,
            get_user_context,
        )

        config = get_global_config()
        web_url = config.web_url

        async with (
            get_user_context(state, request) as user_context,
            get_sandbox_spec_service(state, request) as sandbox_spec_service,
            get_httpx_client(state, request) as httpx_client,
            get_db_session(state, request) as db_session,
        ):
            yield OpenSandboxService(
                sandbox_spec_service=sandbox_spec_service,
                api_url=self.api_url,
                api_key=self.api_key,
                web_url=web_url,
                sandbox_timeout=self.sandbox_timeout,
                max_num_sandboxes=self.max_num_sandboxes,
                user_context=user_context,
                httpx_client=httpx_client,
                db_session=db_session,
            )
