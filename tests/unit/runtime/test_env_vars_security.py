"""Tests for environment variable security in runtime.

Tests that secret values are NOT exposed in error messages when
add_env_vars fails (e.g., due to invalid variable names).

These tests use a minimal test subclass of Runtime that overrides only the
`run` and `run_ipython` methods to simulate command execution, while keeping
the real implementation of `add_env_vars` and its helper methods. This ensures
we test the actual code paths, not a Frankenstein mock.
"""

from typing import Callable

import pytest

from openhands.events.action import CmdRunAction, IPythonRunCellAction
from openhands.events.observation import (
    CmdOutputObservation,
    ErrorObservation,
    IPythonRunCellObservation,
    Observation,
)
from openhands.runtime.base import Runtime
from openhands.runtime.plugins import JupyterRequirement


class StubRuntime(Runtime):
    """A minimal test subclass of Runtime for unit testing.

    This stub overrides the external boundary methods (`run`, `run_ipython`)
    to allow controlled simulation of command execution, while keeping the real
    implementation of `add_env_vars`, `_run_cmd_with_retry`, `_run_env_cmd_redacted`,
    and all other internal methods.

    This approach ensures we test the actual code paths rather than rebinding
    methods onto a mock object.
    """

    def __init__(
        self,
        run_handler: Callable[[CmdRunAction], Observation] | None = None,
        ipython_handler: Callable[[IPythonRunCellAction], Observation] | None = None,
        plugins: list | None = None,
    ):
        # Don't call super().__init__() as it requires complex setup.
        # Instead, set only the attributes that add_env_vars needs.
        self.plugins = plugins or []
        self._run_handler = run_handler
        self._ipython_handler = ipython_handler

    def run(self, action: CmdRunAction) -> Observation:
        """Execute a command action using the configured handler."""
        if self._run_handler is None:
            raise NotImplementedError('run_handler not configured')
        return self._run_handler(action)

    def run_ipython(self, action: IPythonRunCellAction) -> Observation:
        """Execute an IPython action using the configured handler."""
        if self._ipython_handler is None:
            # Default: return success
            return IPythonRunCellObservation(content='', code=action.code)
        return self._ipython_handler(action)

    # Implement abstract methods with stubs (not used in these tests)
    async def connect(self) -> None:
        pass

    def browse(self, action) -> Observation:
        raise NotImplementedError

    def browse_interactive(self, action) -> Observation:
        raise NotImplementedError

    async def call_tool_mcp(self, action) -> Observation:
        raise NotImplementedError

    def copy_from(self, path: str):
        raise NotImplementedError

    def copy_to(self, host_src: str, sandbox_dest: str, recursive: bool = False):
        raise NotImplementedError

    def edit(self, action) -> Observation:
        raise NotImplementedError

    def get_mcp_config(self):
        raise NotImplementedError

    def list_files(self, path: str | None = None) -> list[str]:
        raise NotImplementedError

    def read(self, action) -> Observation:
        raise NotImplementedError

    def write(self, action) -> Observation:
        raise NotImplementedError


class TestAddEnvVarsSecretRedaction:
    """Tests that add_env_vars redacts secrets from error messages."""

    def test_invalid_env_var_name_error_does_not_contain_secret_value(self):
        """Test that invalid env var names raise error WITHOUT exposing secret values.

        This tests the fix for the security issue where error messages like:
        'bash: export: `MY_DUMMY-SECRET=secret_value': not a valid identifier'
        were being logged, exposing the secret value.
        """
        secret_value = 'super_secret_password_xyz123'

        def run_handler(action: CmdRunAction) -> Observation:
            # Simulate bash rejecting an invalid variable name (contains hyphen)
            return CmdOutputObservation(
                content=(
                    f"bash: export: `MY_INVALID-VAR={secret_value}': "
                    'not a valid identifier'
                ),
                command=action.command,
                exit_code=1,
            )

        runtime = StubRuntime(run_handler=run_handler)

        with pytest.raises(RuntimeError) as exc_info:
            runtime.add_env_vars({'MY_INVALID-VAR': secret_value})

        error_message = str(exc_info.value)

        # The error message should contain the variable NAME (key)
        assert 'MY_INVALID-VAR' in error_message

        # The error message should NOT contain the secret VALUE
        assert secret_value not in error_message

        # The error message should NOT contain the raw bash error output
        assert 'not a valid identifier' not in error_message

        # The error message should provide helpful guidance
        assert 'valid bash identifier' in error_message.lower()

    def test_multiple_env_vars_error_does_not_expose_any_secrets(self):
        """Test that when multiple env vars fail, no secrets are exposed."""
        secrets = {
            'API_KEY': 'secret_api_key_12345',
            'MY-BAD-VAR': 'another_super_secret_value',
        }

        def run_handler(action: CmdRunAction) -> Observation:
            # Simulate bash error with secrets potentially in output
            return CmdOutputObservation(
                content=(
                    f'export API_KEY="{secrets["API_KEY"]}"; '
                    f'export MY-BAD-VAR="{secrets["MY-BAD-VAR"]}"\n'
                    f"bash: export: `MY-BAD-VAR={secrets['MY-BAD-VAR']}': "
                    'not a valid identifier'
                ),
                command=action.command,
                exit_code=1,
            )

        runtime = StubRuntime(run_handler=run_handler)

        with pytest.raises(RuntimeError) as exc_info:
            runtime.add_env_vars(secrets)

        error_message = str(exc_info.value)

        # Should NOT contain any secret values
        for secret in secrets.values():
            assert secret not in error_message, (
                f'Secret "{secret}" leaked in error message'
            )

        # Should contain the variable names (keys) - they get uppercased
        assert 'API_KEY' in error_message
        assert 'MY-BAD-VAR' in error_message

    def test_bashrc_error_does_not_expose_secrets(self):
        """Test that .bashrc persistence errors also don't expose secrets."""
        secret_value = 'very_sensitive_token_abc789'
        call_count = 0

        def run_handler(action: CmdRunAction) -> Observation:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # First call (export) succeeds
                return CmdOutputObservation(
                    content='', command=action.command, exit_code=0
                )
            else:
                # Second call (.bashrc update) fails with secret in output
                return CmdOutputObservation(
                    content=f'bash: some error with {secret_value}',
                    command=action.command,
                    exit_code=1,
                )

        runtime = StubRuntime(run_handler=run_handler)

        with pytest.raises(RuntimeError) as exc_info:
            runtime.add_env_vars({'VALID_VAR': secret_value})

        error_message = str(exc_info.value)

        # Should NOT contain the secret value
        assert secret_value not in error_message

        # Should mention .bashrc in the error
        assert '.bashrc' in error_message

        # Should contain the variable name
        assert 'VALID_VAR' in error_message

    def test_ipython_error_does_not_expose_secrets(self):
        """Test that IPython/Jupyter env var errors don't expose secrets."""
        secret_value = 'jupyter_secret_token_456'

        def ipython_handler(action: IPythonRunCellAction) -> Observation:
            # Simulate an error that might contain the secret
            return ErrorObservation(
                content=f'NameError: invalid variable with {secret_value}'
            )

        # Enable Jupyter plugin
        runtime = StubRuntime(
            ipython_handler=ipython_handler,
            plugins=[JupyterRequirement()],
        )

        with pytest.raises(RuntimeError) as exc_info:
            runtime.add_env_vars({'MY_VAR': secret_value})

        error_message = str(exc_info.value)

        # Should NOT contain the secret value
        assert secret_value not in error_message

        # Should mention IPython in the error
        assert 'IPython' in error_message

        # Should contain the variable name
        assert 'MY_VAR' in error_message

    def test_empty_env_vars_returns_early(self):
        """Test that empty env_vars dict returns early without errors."""
        call_count = 0

        def run_handler(action: CmdRunAction) -> Observation:
            nonlocal call_count
            call_count += 1
            return CmdOutputObservation(content='', command=action.command, exit_code=0)

        runtime = StubRuntime(run_handler=run_handler)

        # Should not raise and should not call run
        runtime.add_env_vars({})

        assert call_count == 0, 'run() should not be called for empty env_vars'

    def test_non_runtime_error_propagates(self):
        """Test that non-RuntimeError exceptions from run() propagate correctly."""

        def run_handler(action: CmdRunAction) -> Observation:
            raise ValueError('Unexpected internal error')

        runtime = StubRuntime(run_handler=run_handler)

        # ValueError should propagate, not be caught and converted
        with pytest.raises(ValueError, match='Unexpected internal error'):
            runtime.add_env_vars({'MY_VAR': 'some_value'})

    def test_successful_env_vars_do_not_raise(self):
        """Test that valid env vars are set successfully without errors."""

        def run_handler(action: CmdRunAction) -> Observation:
            return CmdOutputObservation(content='', command=action.command, exit_code=0)

        runtime = StubRuntime(run_handler=run_handler)

        # Should not raise
        runtime.add_env_vars(
            {
                'VALID_VAR_1': 'value1',
                'VALID_VAR_2': 'value2',
            }
        )

    def test_var_names_are_uppercased_in_error(self):
        """Test that variable names in errors are uppercased as they would be set."""
        secret_value = 'secret_for_case_test'

        def run_handler(action: CmdRunAction) -> Observation:
            return CmdOutputObservation(
                content='bash: export error',
                command=action.command,
                exit_code=1,
            )

        runtime = StubRuntime(run_handler=run_handler)

        with pytest.raises(RuntimeError) as exc_info:
            runtime.add_env_vars({'lower_case_var': secret_value})

        error_message = str(exc_info.value)

        # Variable name should be uppercased in the error
        assert 'LOWER_CASE_VAR' in error_message
        # Secret should not be present
        assert secret_value not in error_message
