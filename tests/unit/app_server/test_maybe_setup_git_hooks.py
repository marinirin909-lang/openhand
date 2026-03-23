"""Unit tests for maybe_setup_git_hooks in AppConversationServiceBase.

This module tests the git hooks setup functionality for V1 conversations,
specifically the async maybe_setup_git_hooks method.

These tests were added after PR #13395 fixed a bug where workspace.file_download()
was called without await, causing conversations to fail to start.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from openhands.app_server.app_conversation.app_conversation_service_base import (
    PRE_COMMIT_HOOK,
    PRE_COMMIT_LOCAL,
    AppConversationServiceBase,
)


class MockCommandResult:
    """Mock class for command execution result."""

    def __init__(self, exit_code: int = 0, stderr: str = ''):
        self.exit_code = exit_code
        self.stderr = stderr


@pytest.fixture
def mock_workspace():
    """Create a mock AsyncRemoteWorkspace with all async methods."""
    workspace = AsyncMock()
    workspace.working_dir = '/workspace'
    workspace.execute_command = AsyncMock(return_value=MockCommandResult(exit_code=0))
    workspace.file_download = AsyncMock(return_value={'success': False})
    workspace.file_upload = AsyncMock()
    return workspace


@pytest.fixture
def service_instance():
    """Create a mock service instance that has the maybe_setup_git_hooks method.

    Since AppConversationServiceBase is abstract with many methods, we create
    a MagicMock and bind the real maybe_setup_git_hooks method to it.
    """
    mock_service = MagicMock()
    # Bind the real method to our mock instance
    mock_service.maybe_setup_git_hooks = lambda workspace, project_dir: (
        AppConversationServiceBase.maybe_setup_git_hooks(
            mock_service, workspace, project_dir
        )
    )
    return mock_service


class TestMaybeSetupGitHooks:
    """Tests for the maybe_setup_git_hooks method."""

    @pytest.mark.asyncio
    async def test_returns_early_when_pre_commit_script_missing(
        self, mock_workspace, service_instance
    ):
        """Test that function returns early when .openhands/pre-commit.sh doesn't exist.

        When the mkdir/chmod command fails (exit_code != 0), it means the
        pre-commit.sh script doesn't exist and we should return early.
        """
        mock_workspace.execute_command = AsyncMock(
            return_value=MockCommandResult(exit_code=1)
        )

        await service_instance.maybe_setup_git_hooks(mock_workspace, '/project')

        # Should only call execute_command once (the mkdir/chmod)
        mock_workspace.execute_command.assert_called_once()
        # Should not attempt file_download since we returned early
        mock_workspace.file_download.assert_not_called()
        mock_workspace.file_upload.assert_not_called()

    @pytest.mark.asyncio
    async def test_installs_hook_when_no_existing_hook(
        self, mock_workspace, service_instance
    ):
        """Test successful hook installation when no existing pre-commit hook exists."""
        mock_workspace.execute_command = AsyncMock(
            return_value=MockCommandResult(exit_code=0)
        )
        mock_workspace.file_download = AsyncMock(return_value={'success': False})

        await service_instance.maybe_setup_git_hooks(mock_workspace, '/project')

        # Should call file_download to check for existing hook
        mock_workspace.file_download.assert_awaited_once()
        # Should upload the new hook
        mock_workspace.file_upload.assert_awaited_once()
        # Should make the hook executable (2nd execute_command call)
        assert mock_workspace.execute_command.await_count >= 2

    @pytest.mark.asyncio
    async def test_file_download_is_awaited(self, mock_workspace, service_instance):
        """Regression test for PR #13395: ensure file_download is awaited.

        This test specifically verifies that workspace.file_download() is called
        with await. Without await, file_download returns a coroutine object
        instead of the actual result, which would break the subsequent logic.
        """
        mock_workspace.execute_command = AsyncMock(
            return_value=MockCommandResult(exit_code=0)
        )
        mock_workspace.file_download = AsyncMock(return_value={'success': False})

        await service_instance.maybe_setup_git_hooks(mock_workspace, '/project')

        # The key assertion: file_download must be awaited, not just called
        mock_workspace.file_download.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_preserves_existing_non_openhands_hook(
        self, mock_workspace, service_instance
    ):
        """Test that existing non-OpenHands hooks are moved to pre-commit.local."""
        mock_workspace.execute_command = AsyncMock(
            return_value=MockCommandResult(exit_code=0)
        )

        # Simulate an existing hook that was NOT installed by OpenHands
        existing_hook_content = "#!/bin/bash\necho 'My custom hook'\nexit 0"

        # Create a mock that simulates file_download writing to the temp file
        async def mock_file_download(path, temp_file_path):
            # Write content to simulate successful download
            with open(temp_file_path, 'w') as f:
                f.write(existing_hook_content)
            return {'success': True}

        mock_workspace.file_download = AsyncMock(side_effect=mock_file_download)

        await service_instance.maybe_setup_git_hooks(mock_workspace, '/project')

        # Verify the move command was executed
        calls = mock_workspace.execute_command.call_args_list
        move_cmd_found = any(
            f'mv {PRE_COMMIT_HOOK} {PRE_COMMIT_LOCAL}' in str(call) for call in calls
        )
        assert move_cmd_found, 'Expected mv command to preserve existing hook'

    @pytest.mark.asyncio
    async def test_skips_move_for_openhands_installed_hook(
        self, mock_workspace, service_instance
    ):
        """Test that hooks installed by OpenHands are not moved.

        Note: The implementation uses tempfile.TemporaryFile and writes content
        to it, then reads from it. For this to work correctly, the file position
        must be reset (seek to 0) before reading. We simulate this by patching
        tempfile to use a real file that we control.
        """
        mock_workspace.execute_command = AsyncMock(
            return_value=MockCommandResult(exit_code=0)
        )

        # Simulate an existing hook that WAS installed by OpenHands
        openhands_hook_content = (
            "#!/bin/bash\n# This hook was installed by OpenHands\necho 'test'"
        )

        # We need to patch tempfile.TemporaryFile to control the file content
        # that gets read after file_download writes to it
        class MockTempFile:
            """Mock temp file that returns OpenHands hook content on read."""

            def __init__(self, *args, **kwargs):
                self._content = openhands_hook_content

            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

            def read(self):
                return self._content

            def __str__(self):
                return '/tmp/mock_temp_file'

        async def mock_file_download(path, temp_file_path):
            return {'success': True}

        mock_workspace.file_download = AsyncMock(side_effect=mock_file_download)

        with patch(
            'openhands.app_server.app_conversation.app_conversation_service_base.tempfile.TemporaryFile',
            MockTempFile,
        ):
            await service_instance.maybe_setup_git_hooks(mock_workspace, '/project')

        # The mv command should NOT be in the calls since it's an OpenHands hook
        calls = mock_workspace.execute_command.call_args_list
        move_cmd_found = any(
            f'mv {PRE_COMMIT_HOOK} {PRE_COMMIT_LOCAL}' in str(call) for call in calls
        )
        assert not move_cmd_found, 'Should not move OpenHands-installed hooks'

    @pytest.mark.asyncio
    async def test_returns_early_when_move_fails(
        self, mock_workspace, service_instance
    ):
        """Test that function returns early if moving existing hook fails."""
        call_count = 0

        async def mock_execute_command(command, *args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # First call: mkdir/chmod succeeds
                return MockCommandResult(exit_code=0)
            elif 'mv' in command:
                # Move command fails
                return MockCommandResult(exit_code=1, stderr='Permission denied')
            return MockCommandResult(exit_code=0)

        mock_workspace.execute_command = AsyncMock(side_effect=mock_execute_command)

        # Existing non-OpenHands hook
        async def mock_file_download(path, temp_file_path):
            with open(temp_file_path, 'w') as f:
                f.write("#!/bin/bash\necho 'custom hook'")
            return {'success': True}

        mock_workspace.file_download = AsyncMock(side_effect=mock_file_download)

        with patch(
            'openhands.app_server.app_conversation.app_conversation_service_base._logger'
        ) as mock_logger:
            await service_instance.maybe_setup_git_hooks(mock_workspace, '/project')

            # Should log the error
            mock_logger.error.assert_called()
            error_msg = str(mock_logger.error.call_args)
            assert 'Failed to preserve existing pre-commit hook' in error_msg

        # Should NOT call file_upload since we returned early
        mock_workspace.file_upload.assert_not_called()

    @pytest.mark.asyncio
    async def test_returns_early_when_chmod_fails(
        self, mock_workspace, service_instance
    ):
        """Test that function returns early if making hook executable fails."""
        call_count = 0

        async def mock_execute_command(command, *args, **kwargs):
            nonlocal call_count
            call_count += 1
            if 'chmod +x .git/hooks/pre-commit' in command and 'mkdir' not in command:
                # The final chmod fails
                return MockCommandResult(exit_code=1, stderr='Permission denied')
            return MockCommandResult(exit_code=0)

        mock_workspace.execute_command = AsyncMock(side_effect=mock_execute_command)
        mock_workspace.file_download = AsyncMock(return_value={'success': False})

        with patch(
            'openhands.app_server.app_conversation.app_conversation_service_base._logger'
        ) as mock_logger:
            await service_instance.maybe_setup_git_hooks(mock_workspace, '/project')

            # Should log the error about chmod failure
            error_calls = [str(call) for call in mock_logger.error.call_args_list]
            chmod_error = any(
                'Failed to make pre-commit hook executable' in call
                for call in error_calls
            )
            assert chmod_error, 'Expected chmod failure to be logged'

    @pytest.mark.asyncio
    async def test_logs_success_on_completion(self, mock_workspace, service_instance):
        """Test that successful installation is logged."""
        mock_workspace.execute_command = AsyncMock(
            return_value=MockCommandResult(exit_code=0)
        )
        mock_workspace.file_download = AsyncMock(return_value={'success': False})

        with patch(
            'openhands.app_server.app_conversation.app_conversation_service_base._logger'
        ) as mock_logger:
            await service_instance.maybe_setup_git_hooks(mock_workspace, '/project')

            mock_logger.info.assert_called_with(
                'Git pre-commit hook installed successfully'
            )

    @pytest.mark.asyncio
    async def test_uses_correct_paths(self, mock_workspace, service_instance):
        """Test that the correct file paths are used for hooks."""
        mock_workspace.execute_command = AsyncMock(
            return_value=MockCommandResult(exit_code=0)
        )
        mock_workspace.file_download = AsyncMock(return_value={'success': False})

        await service_instance.maybe_setup_git_hooks(mock_workspace, '/project')

        # Verify file_download was called with the correct hook path
        download_call = mock_workspace.file_download.call_args
        assert PRE_COMMIT_HOOK in str(download_call)

        # Verify file_upload destination is correct
        upload_call = mock_workspace.file_upload.call_args
        assert upload_call.kwargs.get('destination_path') == PRE_COMMIT_HOOK

    @pytest.mark.asyncio
    async def test_uploads_pre_commit_script_from_git_directory(
        self, mock_workspace, service_instance
    ):
        """Test that the pre-commit script is uploaded from the correct source."""
        mock_workspace.execute_command = AsyncMock(
            return_value=MockCommandResult(exit_code=0)
        )
        mock_workspace.file_download = AsyncMock(return_value={'success': False})

        await service_instance.maybe_setup_git_hooks(mock_workspace, '/project')

        # Verify file_upload source path ends with git/pre-commit.sh
        upload_call = mock_workspace.file_upload.call_args
        source_path = upload_call.kwargs.get('source_path')
        assert source_path is not None
        assert str(source_path).endswith('git/pre-commit.sh')
