"""Tests for OpenSandboxService.

This module tests the OpenSandboxService implementation, focusing on:
- OpenSandbox Lifecycle API communication and error handling
- Sandbox lifecycle management (start, pause, resume, delete)
- Status mapping from OpenSandbox states to internal sandbox statuses
- Environment variable injection for session API keys, CORS and webhooks
- Data transformation from OpenSandbox API to SandboxInfo objects
- Endpoint URL building for exposed services
"""

from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from openhands.app_server.errors import SandboxError
from openhands.app_server.sandbox.opensandbox_service import (
    AGENT_SERVER_PORT,
    VSCODE_PORT,
    WORKER_1_PORT,
    WORKER_2_PORT,
    OpenSandboxService,
    StoredOpenSandbox,
    _hash_session_api_key,
)
from openhands.app_server.sandbox.sandbox_models import (
    AGENT_SERVER,
    VSCODE,
    WORKER_1,
    WORKER_2,
    SandboxStatus,
)
from openhands.app_server.sandbox.sandbox_service import (
    ALLOW_CORS_ORIGINS_VARIABLE,
    SESSION_API_KEY_VARIABLE,
    WEBHOOK_CALLBACK_VARIABLE,
)
from openhands.app_server.sandbox.sandbox_spec_models import SandboxSpecInfo
from openhands.app_server.user.user_context import UserContext


@pytest.fixture
def mock_sandbox_spec_service():
    mock_service = AsyncMock()
    mock_spec = SandboxSpecInfo(
        id='test-image:latest',
        command=['--port', '8000'],
        initial_env={'TEST_VAR': 'test_value'},
        working_dir='/workspace/project',
    )
    mock_service.get_default_sandbox_spec.return_value = mock_spec
    mock_service.get_sandbox_spec.return_value = mock_spec
    return mock_service


@pytest.fixture
def mock_user_context():
    mock_context = AsyncMock(spec=UserContext)
    mock_context.get_user_id.return_value = 'test-user-123'
    return mock_context


@pytest.fixture
def mock_httpx_client():
    return AsyncMock(spec=httpx.AsyncClient)


@pytest.fixture
def mock_db_session():
    return AsyncMock(spec=AsyncSession)


@pytest.fixture
def opensandbox_service(
    mock_sandbox_spec_service, mock_user_context, mock_httpx_client, mock_db_session
):
    return OpenSandboxService(
        sandbox_spec_service=mock_sandbox_spec_service,
        api_url='https://api.example.com/v1',
        api_key='test-api-key',
        web_url='https://web.example.com',
        sandbox_timeout=3600,
        max_num_sandboxes=10,
        user_context=mock_user_context,
        httpx_client=mock_httpx_client,
        db_session=mock_db_session,
    )


def create_opensandbox_data(
    sandbox_id: str = 'os-sandbox-456',
    state: str = 'Running',
) -> dict[str, Any]:
    """Helper to create OpenSandbox API response data."""
    return {
        'id': sandbox_id,
        'status': {
            'state': state,
            'reason': None,
            'message': None,
        },
        'image': {'uri': 'test-image:latest'},
    }


def create_stored_sandbox(
    sandbox_id: str = 'test-sandbox-123',
    opensandbox_id: str = 'os-sandbox-456',
    user_id: str = 'test-user-123',
    spec_id: str = 'test-image:latest',
    session_api_key: str = 'test-session-key',
    created_at: datetime | None = None,
) -> StoredOpenSandbox:
    if created_at is None:
        created_at = datetime.now(timezone.utc)
    return StoredOpenSandbox(
        id=sandbox_id,
        opensandbox_id=opensandbox_id,
        created_by_user_id=user_id,
        sandbox_spec_id=spec_id,
        session_api_key=session_api_key,
        session_api_key_hash=_hash_session_api_key(session_api_key),
        created_at=created_at,
    )


class TestApiRequest:
    """Test cases for OpenSandbox API communication."""

    @pytest.mark.asyncio
    async def test_send_api_request_success(self, opensandbox_service):
        mock_response = MagicMock()
        mock_response.json.return_value = {'result': 'success'}
        opensandbox_service.httpx_client.request.return_value = mock_response

        response = await opensandbox_service._send_api_request(
            'GET', '/sandboxes/test-id'
        )

        assert response == mock_response
        opensandbox_service.httpx_client.request.assert_called_once_with(
            'GET',
            'https://api.example.com/v1/sandboxes/test-id',
            headers={'OPEN-SANDBOX-API-KEY': 'test-api-key'},
        )

    @pytest.mark.asyncio
    async def test_send_api_request_timeout(self, opensandbox_service):
        opensandbox_service.httpx_client.request.side_effect = httpx.TimeoutException(
            'Request timeout'
        )

        with pytest.raises(httpx.TimeoutException):
            await opensandbox_service._send_api_request('GET', '/sandboxes')

    @pytest.mark.asyncio
    async def test_send_api_request_http_error(self, opensandbox_service):
        opensandbox_service.httpx_client.request.side_effect = httpx.HTTPError(
            'HTTP error'
        )

        with pytest.raises(httpx.HTTPError):
            await opensandbox_service._send_api_request('GET', '/sandboxes')


class TestStatusMapping:
    """Test cases for OpenSandbox state to SandboxStatus mapping."""

    def test_status_mapping_all_states(self, opensandbox_service):
        test_cases = [
            ('Pending', SandboxStatus.STARTING),
            ('Running', SandboxStatus.RUNNING),
            ('Pausing', SandboxStatus.RUNNING),
            ('Paused', SandboxStatus.PAUSED),
            ('Stopping', SandboxStatus.MISSING),
            ('Terminated', SandboxStatus.MISSING),
            ('Failed', SandboxStatus.ERROR),
        ]

        for state, expected in test_cases:
            sandbox_data = create_opensandbox_data(state=state)
            status = opensandbox_service._get_sandbox_status(sandbox_data)
            assert status == expected, f'Failed for state: {state}'

    def test_status_mapping_none_data(self, opensandbox_service):
        status = opensandbox_service._get_sandbox_status(None)
        assert status == SandboxStatus.MISSING

    def test_status_mapping_unknown_state(self, opensandbox_service):
        sandbox_data = create_opensandbox_data(state='UnknownState')
        status = opensandbox_service._get_sandbox_status(sandbox_data)
        assert status == SandboxStatus.ERROR

    def test_status_mapping_empty_status(self, opensandbox_service):
        sandbox_data: dict[str, Any] = {'id': 'test', 'status': {}}
        status = opensandbox_service._get_sandbox_status(sandbox_data)
        assert status == SandboxStatus.ERROR

    def test_status_mapping_missing_status_key(self, opensandbox_service):
        sandbox_data: dict[str, Any] = {'id': 'test'}
        status = opensandbox_service._get_sandbox_status(sandbox_data)
        assert status == SandboxStatus.ERROR


class TestEnvironmentInitialization:
    """Test cases for environment variable initialization."""

    @pytest.mark.asyncio
    async def test_init_environment_with_web_url(self, opensandbox_service):
        sandbox_spec = SandboxSpecInfo(
            id='test-image',
            command=['test'],
            initial_env={'EXISTING_VAR': 'existing_value'},
            working_dir='/workspace',
        )

        environment = await opensandbox_service._init_environment(
            sandbox_spec, 'test-session-key'
        )

        assert environment['EXISTING_VAR'] == 'existing_value'
        assert environment[SESSION_API_KEY_VARIABLE] == 'test-session-key'
        assert (
            environment[WEBHOOK_CALLBACK_VARIABLE]
            == 'https://web.example.com/api/v1/webhooks'
        )
        assert environment[ALLOW_CORS_ORIGINS_VARIABLE] == 'https://web.example.com'
        assert environment[WORKER_1] == '12000'
        assert environment[WORKER_2] == '12001'

    @pytest.mark.asyncio
    async def test_init_environment_without_web_url(self, opensandbox_service):
        opensandbox_service.web_url = None
        sandbox_spec = SandboxSpecInfo(
            id='test-image',
            command=['test'],
            initial_env={'EXISTING_VAR': 'existing_value'},
            working_dir='/workspace',
        )

        environment = await opensandbox_service._init_environment(
            sandbox_spec, 'test-session-key'
        )

        assert environment['EXISTING_VAR'] == 'existing_value'
        assert environment[SESSION_API_KEY_VARIABLE] == 'test-session-key'
        assert WEBHOOK_CALLBACK_VARIABLE not in environment
        assert ALLOW_CORS_ORIGINS_VARIABLE not in environment
        assert environment[WORKER_1] == '12000'
        assert environment[WORKER_2] == '12001'


class TestSandboxInfoConversion:
    """Test cases for converting stored sandbox and API data to SandboxInfo."""

    def test_to_sandbox_info_running(self, opensandbox_service):
        stored = create_stored_sandbox()
        sandbox_data = create_opensandbox_data(state='Running')
        from openhands.app_server.sandbox.sandbox_models import ExposedUrl

        exposed_urls = [
            ExposedUrl(name=AGENT_SERVER, url='http://agent.example.com', port=60000)
        ]

        info = opensandbox_service._to_sandbox_info(stored, sandbox_data, exposed_urls)

        assert info.id == 'test-sandbox-123'
        assert info.created_by_user_id == 'test-user-123'
        assert info.sandbox_spec_id == 'test-image:latest'
        assert info.status == SandboxStatus.RUNNING
        assert info.session_api_key == 'test-session-key'
        assert info.exposed_urls == exposed_urls

    def test_to_sandbox_info_starting(self, opensandbox_service):
        stored = create_stored_sandbox()
        sandbox_data = create_opensandbox_data(state='Pending')

        info = opensandbox_service._to_sandbox_info(stored, sandbox_data, None)

        assert info.status == SandboxStatus.STARTING
        assert info.session_api_key is None
        assert info.exposed_urls is None

    def test_to_sandbox_info_paused(self, opensandbox_service):
        stored = create_stored_sandbox()
        sandbox_data = create_opensandbox_data(state='Paused')

        info = opensandbox_service._to_sandbox_info(stored, sandbox_data, None)

        assert info.status == SandboxStatus.PAUSED
        assert info.session_api_key is None
        assert info.exposed_urls is None

    def test_to_sandbox_info_missing(self, opensandbox_service):
        stored = create_stored_sandbox()

        info = opensandbox_service._to_sandbox_info(stored, None, None)

        assert info.status == SandboxStatus.MISSING
        assert info.session_api_key is None


class TestBuildExposedUrls:
    """Test cases for building exposed URLs from OpenSandbox endpoints."""

    @pytest.mark.asyncio
    async def test_build_exposed_urls_all_endpoints(self, opensandbox_service):
        """Test building URLs when all endpoints are available."""
        endpoint_responses = {
            AGENT_SERVER_PORT: 'agent.sandbox.example.com',
            VSCODE_PORT: 'vscode.sandbox.example.com',
            WORKER_1_PORT: 'worker1.sandbox.example.com',
            WORKER_2_PORT: 'worker2.sandbox.example.com',
        }

        async def mock_get_endpoint(opensandbox_id, port):
            return endpoint_responses.get(port)

        opensandbox_service._get_endpoint_url = AsyncMock(side_effect=mock_get_endpoint)

        urls = await opensandbox_service._build_exposed_urls(
            'os-sandbox-456', 'test-key'
        )

        assert len(urls) == 4
        url_names = {u.name for u in urls}
        assert url_names == {AGENT_SERVER, VSCODE, WORKER_1, WORKER_2}

        # Check agent server URL
        agent = next(u for u in urls if u.name == AGENT_SERVER)
        assert agent.url == 'http://agent.sandbox.example.com'
        assert agent.port == AGENT_SERVER_PORT

        # Check vscode URL includes token
        vscode = next(u for u in urls if u.name == VSCODE)
        assert 'tkn=test-key' in vscode.url

    @pytest.mark.asyncio
    async def test_build_exposed_urls_no_agent_server(self, opensandbox_service):
        """Test building URLs when agent server endpoint is not available."""
        opensandbox_service._get_endpoint_url = AsyncMock(return_value=None)

        urls = await opensandbox_service._build_exposed_urls(
            'os-sandbox-456', 'test-key'
        )

        assert len(urls) == 0

    @pytest.mark.asyncio
    async def test_build_exposed_urls_with_http_prefix(self, opensandbox_service):
        """Test that URLs already starting with http are not double-prefixed."""

        async def mock_get_endpoint(opensandbox_id, port):
            if port == AGENT_SERVER_PORT:
                return 'https://agent.sandbox.example.com'
            return None

        opensandbox_service._get_endpoint_url = AsyncMock(side_effect=mock_get_endpoint)

        urls = await opensandbox_service._build_exposed_urls(
            'os-sandbox-456', 'test-key'
        )

        assert len(urls) == 1
        assert urls[0].url == 'https://agent.sandbox.example.com'


class TestSandboxLifecycle:
    """Test cases for sandbox lifecycle operations."""

    @pytest.mark.asyncio
    async def test_start_sandbox_success(self, opensandbox_service):
        mock_response = MagicMock()
        mock_response.json.return_value = {'id': 'os-sandbox-new'}
        mock_response.raise_for_status = MagicMock()
        opensandbox_service.httpx_client.request.return_value = mock_response
        opensandbox_service.pause_old_sandboxes = AsyncMock(return_value=[])
        opensandbox_service.db_session.add = MagicMock()

        with patch(
            'secrets.token_urlsafe',
            side_effect=['custom-sandbox-id', 'session-key-abc'],
        ):
            sandbox_info = await opensandbox_service.start_sandbox()

        assert sandbox_info.id == 'custom-sandbox-id'
        assert sandbox_info.status == SandboxStatus.STARTING
        assert sandbox_info.session_api_key is None
        opensandbox_service.pause_old_sandboxes.assert_called_once_with(9)
        opensandbox_service.db_session.add.assert_called_once()

        # Verify the API request was made correctly
        call_args = opensandbox_service.httpx_client.request.call_args
        assert call_args[0][0] == 'POST'
        assert '/sandboxes' in call_args[0][1]
        request_data = call_args[1]['json']
        assert request_data['image']['uri'] == 'test-image:latest'
        assert request_data['timeout'] == 3600
        assert request_data['metadata']['oh_sandbox_id'] == 'custom-sandbox-id'
        assert request_data['metadata']['oh_user_id'] == 'test-user-123'
        assert request_data['entrypoint'] == ['--port', '8000']

    @pytest.mark.asyncio
    async def test_start_sandbox_with_specific_spec(
        self, opensandbox_service, mock_sandbox_spec_service
    ):
        mock_response = MagicMock()
        mock_response.json.return_value = {'id': 'os-sandbox-new'}
        mock_response.raise_for_status = MagicMock()
        opensandbox_service.httpx_client.request.return_value = mock_response
        opensandbox_service.pause_old_sandboxes = AsyncMock(return_value=[])
        opensandbox_service.db_session.add = MagicMock()

        await opensandbox_service.start_sandbox('custom-spec-id')

        mock_sandbox_spec_service.get_sandbox_spec.assert_called_once_with(
            'custom-spec-id'
        )

    @pytest.mark.asyncio
    async def test_start_sandbox_spec_not_found(
        self, opensandbox_service, mock_sandbox_spec_service
    ):
        mock_sandbox_spec_service.get_sandbox_spec.return_value = None
        opensandbox_service.pause_old_sandboxes = AsyncMock(return_value=[])

        with pytest.raises(ValueError, match='Sandbox Spec not found'):
            await opensandbox_service.start_sandbox('non-existent-spec')

    @pytest.mark.asyncio
    async def test_start_sandbox_with_sandbox_id(self, opensandbox_service):
        mock_response = MagicMock()
        mock_response.json.return_value = {'id': 'os-sandbox-new'}
        mock_response.raise_for_status = MagicMock()
        opensandbox_service.httpx_client.request.return_value = mock_response
        opensandbox_service.pause_old_sandboxes = AsyncMock(return_value=[])
        opensandbox_service.db_session.add = MagicMock()

        sandbox_info = await opensandbox_service.start_sandbox(
            sandbox_id='my-custom-id'
        )

        assert sandbox_info.id == 'my-custom-id'
        add_call_args = opensandbox_service.db_session.add.call_args[0][0]
        assert add_call_args.id == 'my-custom-id'

    @pytest.mark.asyncio
    async def test_start_sandbox_http_error(self, opensandbox_service):
        opensandbox_service.httpx_client.request.side_effect = httpx.HTTPError(
            'API Error'
        )
        opensandbox_service.pause_old_sandboxes = AsyncMock(return_value=[])
        opensandbox_service.db_session.add = MagicMock()

        with pytest.raises(SandboxError, match='Failed to start sandbox'):
            await opensandbox_service.start_sandbox()

    @pytest.mark.asyncio
    async def test_resume_sandbox_success(self, opensandbox_service):
        stored = create_stored_sandbox()
        opensandbox_service._get_stored_sandbox = AsyncMock(return_value=stored)
        opensandbox_service.pause_old_sandboxes = AsyncMock(return_value=[])

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        opensandbox_service.httpx_client.request.return_value = mock_response

        result = await opensandbox_service.resume_sandbox('test-sandbox-123')

        assert result is True
        opensandbox_service.pause_old_sandboxes.assert_called_once_with(9)
        opensandbox_service.httpx_client.request.assert_called_once_with(
            'POST',
            'https://api.example.com/v1/sandboxes/os-sandbox-456/resume',
            headers={'OPEN-SANDBOX-API-KEY': 'test-api-key'},
        )

    @pytest.mark.asyncio
    async def test_resume_sandbox_not_found(self, opensandbox_service):
        opensandbox_service._get_stored_sandbox = AsyncMock(return_value=None)
        opensandbox_service.pause_old_sandboxes = AsyncMock(return_value=[])

        result = await opensandbox_service.resume_sandbox('non-existent')

        assert result is False

    @pytest.mark.asyncio
    async def test_resume_sandbox_404(self, opensandbox_service):
        stored = create_stored_sandbox()
        opensandbox_service._get_stored_sandbox = AsyncMock(return_value=stored)
        opensandbox_service.pause_old_sandboxes = AsyncMock(return_value=[])

        mock_response = MagicMock()
        mock_response.status_code = 404
        opensandbox_service.httpx_client.request.return_value = mock_response

        result = await opensandbox_service.resume_sandbox('test-sandbox-123')

        assert result is False

    @pytest.mark.asyncio
    async def test_pause_sandbox_success(self, opensandbox_service):
        stored = create_stored_sandbox()
        opensandbox_service._get_stored_sandbox = AsyncMock(return_value=stored)

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        opensandbox_service.httpx_client.request.return_value = mock_response

        result = await opensandbox_service.pause_sandbox('test-sandbox-123')

        assert result is True
        opensandbox_service.httpx_client.request.assert_called_once_with(
            'POST',
            'https://api.example.com/v1/sandboxes/os-sandbox-456/pause',
            headers={'OPEN-SANDBOX-API-KEY': 'test-api-key'},
        )

    @pytest.mark.asyncio
    async def test_pause_sandbox_not_found(self, opensandbox_service):
        opensandbox_service._get_stored_sandbox = AsyncMock(return_value=None)

        result = await opensandbox_service.pause_sandbox('non-existent')

        assert result is False

    @pytest.mark.asyncio
    async def test_delete_sandbox_success(self, opensandbox_service):
        stored = create_stored_sandbox()
        opensandbox_service._get_stored_sandbox = AsyncMock(return_value=stored)
        opensandbox_service.db_session.delete = AsyncMock()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        opensandbox_service.httpx_client.request.return_value = mock_response

        result = await opensandbox_service.delete_sandbox('test-sandbox-123')

        assert result is True
        opensandbox_service.db_session.delete.assert_called_once_with(stored)
        opensandbox_service.httpx_client.request.assert_called_once_with(
            'DELETE',
            'https://api.example.com/v1/sandboxes/os-sandbox-456',
            headers={'OPEN-SANDBOX-API-KEY': 'test-api-key'},
        )

    @pytest.mark.asyncio
    async def test_delete_sandbox_not_found(self, opensandbox_service):
        opensandbox_service._get_stored_sandbox = AsyncMock(return_value=None)

        result = await opensandbox_service.delete_sandbox('non-existent')

        assert result is False

    @pytest.mark.asyncio
    async def test_delete_sandbox_404_ignored(self, opensandbox_service):
        stored = create_stored_sandbox()
        opensandbox_service._get_stored_sandbox = AsyncMock(return_value=stored)
        opensandbox_service.db_session.delete = AsyncMock()

        mock_response = MagicMock()
        mock_response.status_code = 404
        opensandbox_service.httpx_client.request.return_value = mock_response

        result = await opensandbox_service.delete_sandbox('test-sandbox-123')

        assert result is True

    @pytest.mark.asyncio
    async def test_delete_sandbox_http_error(self, opensandbox_service):
        stored = create_stored_sandbox()
        opensandbox_service._get_stored_sandbox = AsyncMock(return_value=stored)
        opensandbox_service.httpx_client.request.side_effect = httpx.HTTPError(
            'API Error'
        )

        result = await opensandbox_service.delete_sandbox('test-sandbox-123')

        assert result is False


class TestGetSandbox:
    """Test cases for sandbox retrieval operations."""

    @pytest.mark.asyncio
    async def test_get_sandbox_running(self, opensandbox_service):
        stored = create_stored_sandbox()
        opensandbox_service._get_stored_sandbox = AsyncMock(return_value=stored)
        opensandbox_service._get_opensandbox_data = AsyncMock(
            return_value=create_opensandbox_data(state='Running')
        )

        from openhands.app_server.sandbox.sandbox_models import ExposedUrl

        mock_urls = [
            ExposedUrl(name=AGENT_SERVER, url='http://agent.example.com', port=60000)
        ]
        opensandbox_service._build_exposed_urls = AsyncMock(return_value=mock_urls)

        info = await opensandbox_service.get_sandbox('test-sandbox-123')

        assert info is not None
        assert info.status == SandboxStatus.RUNNING
        assert info.session_api_key == 'test-session-key'
        assert info.exposed_urls == mock_urls
        opensandbox_service._build_exposed_urls.assert_called_once_with(
            'os-sandbox-456', 'test-session-key'
        )

    @pytest.mark.asyncio
    async def test_get_sandbox_not_found(self, opensandbox_service):
        opensandbox_service._get_stored_sandbox = AsyncMock(return_value=None)

        info = await opensandbox_service.get_sandbox('non-existent')

        assert info is None

    @pytest.mark.asyncio
    async def test_get_sandbox_paused(self, opensandbox_service):
        stored = create_stored_sandbox()
        opensandbox_service._get_stored_sandbox = AsyncMock(return_value=stored)
        opensandbox_service._get_opensandbox_data = AsyncMock(
            return_value=create_opensandbox_data(state='Paused')
        )

        info = await opensandbox_service.get_sandbox('test-sandbox-123')

        assert info is not None
        assert info.status == SandboxStatus.PAUSED
        assert info.session_api_key is None
        assert info.exposed_urls is None

    @pytest.mark.asyncio
    async def test_get_sandbox_by_session_api_key(self, opensandbox_service):
        stored = create_stored_sandbox()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = stored
        opensandbox_service.db_session.execute = AsyncMock(return_value=mock_result)

        opensandbox_service._get_opensandbox_data = AsyncMock(
            return_value=create_opensandbox_data(state='Running')
        )

        from openhands.app_server.sandbox.sandbox_models import ExposedUrl

        mock_urls = [
            ExposedUrl(name=AGENT_SERVER, url='http://agent.example.com', port=60000)
        ]
        opensandbox_service._build_exposed_urls = AsyncMock(return_value=mock_urls)

        info = await opensandbox_service.get_sandbox_by_session_api_key(
            'test-session-key'
        )

        assert info is not None
        assert info.status == SandboxStatus.RUNNING

    @pytest.mark.asyncio
    async def test_get_sandbox_by_session_api_key_not_found(self, opensandbox_service):
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        opensandbox_service.db_session.execute = AsyncMock(return_value=mock_result)

        info = await opensandbox_service.get_sandbox_by_session_api_key(
            'nonexistent-key'
        )

        assert info is None


class TestSearchSandboxes:
    """Test cases for sandbox search and pagination."""

    @pytest.mark.asyncio
    async def test_search_sandboxes_basic(self, opensandbox_service):
        stored_sandboxes = [
            create_stored_sandbox('sb1', 'os-1'),
            create_stored_sandbox('sb2', 'os-2'),
        ]

        mock_scalars = MagicMock()
        mock_scalars.all.return_value = stored_sandboxes
        mock_result = MagicMock()
        mock_result.scalars.return_value = mock_scalars
        opensandbox_service.db_session.execute = AsyncMock(return_value=mock_result)

        opensandbox_service._get_opensandbox_data = AsyncMock(
            return_value=create_opensandbox_data(state='Paused')
        )

        page = await opensandbox_service.search_sandboxes()

        assert len(page.items) == 2
        assert page.next_page_id is None

    @pytest.mark.asyncio
    async def test_search_sandboxes_with_pagination(self, opensandbox_service):
        # Return limit+1 items to trigger pagination
        stored_sandboxes = [
            create_stored_sandbox(f'sb{i}', f'os-{i}') for i in range(4)
        ]

        mock_scalars = MagicMock()
        mock_scalars.all.return_value = stored_sandboxes
        mock_result = MagicMock()
        mock_result.scalars.return_value = mock_scalars
        opensandbox_service.db_session.execute = AsyncMock(return_value=mock_result)

        opensandbox_service._get_opensandbox_data = AsyncMock(
            return_value=create_opensandbox_data(state='Paused')
        )

        page = await opensandbox_service.search_sandboxes(limit=3)

        assert len(page.items) == 3
        assert page.next_page_id == '3'


class TestHashSessionApiKey:
    """Test the session API key hashing utility."""

    def test_hash_deterministic(self):
        key = 'my-session-key'
        assert _hash_session_api_key(key) == _hash_session_api_key(key)

    def test_hash_different_keys(self):
        assert _hash_session_api_key('key-a') != _hash_session_api_key('key-b')
