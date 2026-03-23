"""
Integration test for V1 GitHub Resolver webhook flow.

This test verifies:
1. Webhook triggers agent server creation
2. "I'm on it" message is sent to GitHub
3. Eyes reaction is added to acknowledge the request

Uses MockGitHubService for real HTTP calls to a mock GitHub API.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from .conftest import (
    TEST_GITHUB_USER_ID,
    TEST_GITHUB_USERNAME,
    create_issue_comment_payload,
)


class TestV1GitHubResolverE2E:
    """E2E test for V1 GitHub Resolver with MockGitHubService."""

    @pytest.mark.asyncio
    async def test_webhook_flow_with_mock_github_service(
        self, patched_session_maker, mock_keycloak, mock_github_service
    ):
        """
        E2E test: Webhook → Agent Server → Real HTTP calls to MockGitHubService.

        This test:
        1. Receives a GitHub webhook payload
        2. Routes to V1 path (v1_enabled=True)
        3. Starts agent server via start_app_conversation
        4. Makes REAL HTTP calls to MockGitHubService
        5. Verifies "I'm on it" and eyes reaction via service state
        """
        from openhands.app_server.app_conversation.app_conversation_models import (
            AppConversationStartTask,
            AppConversationStartTaskStatus,
        )

        # Configure the mock GitHub service
        mock_github_service.configure_repo('test-owner/test-repo')
        mock_github_service.configure_issue(
            'test-owner/test-repo',
            number=1,
            title='Test Issue',
            body='This is a test issue',
        )
        mock_github_service.configure_comment(
            'test-owner/test-repo',
            comment_id=12345,
            body='@openhands please fix this bug',
        )

        # Create webhook payload
        payload = create_issue_comment_payload(
            comment_body='@openhands please fix this bug',
            sender_id=TEST_GITHUB_USER_ID,
            sender_login=TEST_GITHUB_USERNAME,
        )

        # Track agent server start
        agent_started = asyncio.Event()
        captured_request = None

        # Mock start_app_conversation to simulate agent server
        async def mock_start_app_conversation(request):
            from uuid import uuid4

            nonlocal captured_request
            captured_request = request
            agent_started.set()

            task_id = uuid4()
            conv_id = uuid4()

            yield AppConversationStartTask(
                id=task_id,
                created_by_user_id='test-user',
                status=AppConversationStartTaskStatus.WORKING,
                request=request,
            )

            await asyncio.sleep(0.1)

            yield AppConversationStartTask(
                id=task_id,
                created_by_user_id='test-user',
                status=AppConversationStartTaskStatus.READY,
                app_conversation_id=conv_id,
                request=request,
            )

        # Mock GithubServiceImpl (for fetching issue details)
        mock_github_service_impl = MagicMock()
        mock_github_service_impl.get_issue_or_pr_comments = AsyncMock(return_value=[])
        mock_github_service_impl.get_issue_or_pr_title_and_body = AsyncMock(
            return_value=('Test Issue', 'This is a test issue body')
        )
        mock_github_service_impl.get_review_thread_comments = AsyncMock(return_value=[])

        # Mock app conversation service
        mock_app_service = MagicMock()
        mock_app_service.start_app_conversation = mock_start_app_conversation

        with patch(
            'integrations.github.github_view.get_user_v1_enabled_setting',
            return_value=True,
        ), patch(
            'integrations.github.github_view.get_app_conversation_service'
        ) as mock_get_service, patch(
            'github.GithubIntegration'
        ) as mock_integration, patch(
            'integrations.github.github_solvability.summarize_issue_solvability',
            new_callable=AsyncMock,
            return_value=None,
        ), patch(
            'server.auth.token_manager.TokenManager.get_idp_token_from_idp_user_id',
            new_callable=AsyncMock,
            return_value='mock-token',
        ), patch(
            'integrations.v1_utils.get_saas_user_auth',
            new_callable=AsyncMock,
        ) as mock_saas_auth, patch(
            'integrations.github.github_view.GithubServiceImpl',
            return_value=mock_github_service_impl,
        ):
            # Setup mock service context
            mock_context = MagicMock()
            mock_context.__aenter__ = AsyncMock(return_value=mock_app_service)
            mock_context.__aexit__ = AsyncMock(return_value=None)
            mock_get_service.return_value = mock_context

            # Setup user auth
            mock_user_auth = MagicMock()
            mock_user_auth.get_provider_tokens = AsyncMock(
                return_value={'github': 'mock-token'}
            )
            mock_saas_auth.return_value = mock_user_auth

            # Setup GitHub integration
            mock_token = MagicMock()
            mock_token.token = 'test-installation-token'
            mock_integration.return_value.get_access_token.return_value = mock_token

            # Run the test
            from integrations.github.github_manager import GithubManager
            from integrations.models import Message, SourceType
            from server.auth.token_manager import TokenManager

            token_manager = TokenManager()
            token_manager.load_org_token = MagicMock(return_value='mock-token')

            data_collector = MagicMock()
            data_collector.process_payload = MagicMock()
            data_collector.fetch_issue_details = AsyncMock(
                return_value={'description': 'Test', 'previous_comments': []}
            )
            data_collector.save_data = AsyncMock()

            manager = GithubManager(token_manager, data_collector)
            manager.github_integration = mock_integration.return_value

            # Send webhook
            message = Message(
                source=SourceType.GITHUB,
                message={
                    'payload': payload,
                    'installation': payload['installation']['id'],
                },
            )
            await manager.receive_message(message)

            # Wait for agent to start
            await asyncio.wait_for(agent_started.wait(), timeout=10.0)

            # Give time for GitHub API calls to complete
            await asyncio.sleep(0.5)

        # Verify via MockGitHubService state (no more async events!)
        assert agent_started.is_set(), 'Agent server should start'
        assert captured_request is not None
        assert captured_request.selected_repository == 'test-owner/test-repo'

        # Verify GitHub API calls were made
        mock_github_service.assert_comment_sent("I'm on it")
        mock_github_service.assert_reaction_added('eyes')

        # Print verification
        comments = mock_github_service.get_comments()
        reactions = mock_github_service.get_reactions()

        print('✅ Agent server started')
        print(f'✅ "I\'m on it" message sent: {comments[0]["body"][:60]}...')
        print(f'✅ Eyes reaction added: {reactions[0]["content"]}')
