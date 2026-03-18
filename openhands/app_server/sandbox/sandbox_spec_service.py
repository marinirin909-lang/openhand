import asyncio
import os
from abc import ABC, abstractmethod

from openhands.agent_server import env_parser
from openhands.app_server.errors import SandboxError
from openhands.app_server.sandbox.sandbox_spec_models import (
    SandboxSpecInfo,
    SandboxSpecInfoPage,
)
from openhands.app_server.services.injector import Injector
from openhands.sdk.utils.models import DiscriminatedUnionMixin

# The version of the agent server to use for deployments.
# Typically this will be the same as the values from the pyproject.toml
AGENT_SERVER_IMAGE = 'ghcr.io/openhands/agent-server:1.14.0-python'


class SandboxSpecService(ABC):
    """Service for managing Sandbox specs.

    At present this is read only. The plan is that later this class will allow building
    and deleting sandbox specs and limiting access by user and group. It would also be
    nice to be able to set the desired number of warm sandboxes for a spec and scale
    this up and down.
    """

    @abstractmethod
    async def search_sandbox_specs(
        self, page_id: str | None = None, limit: int = 100
    ) -> SandboxSpecInfoPage:
        """Search for sandbox specs."""

    @abstractmethod
    async def get_sandbox_spec(self, sandbox_spec_id: str) -> SandboxSpecInfo | None:
        """Get a single sandbox spec, returning None if not found."""

    async def get_default_sandbox_spec(self) -> SandboxSpecInfo:
        """Get the default sandbox spec."""
        page = await self.search_sandbox_specs()
        if not page.items:
            raise SandboxError('No sandbox specs available!')
        return page.items[0]

    async def batch_get_sandbox_specs(
        self, sandbox_spec_ids: list[str]
    ) -> list[SandboxSpecInfo | None]:
        """Get a batch of sandbox specs, returning None for any not found."""
        results = await asyncio.gather(
            *[
                self.get_sandbox_spec(sandbox_spec_id)
                for sandbox_spec_id in sandbox_spec_ids
            ]
        )
        return results


class SandboxSpecServiceInjector(
    DiscriminatedUnionMixin, Injector[SandboxSpecService], ABC
):
    pass


def get_agent_server_image() -> str:
    agent_server_image_repository = os.getenv('AGENT_SERVER_IMAGE_REPOSITORY')
    agent_server_image_tag = os.getenv('AGENT_SERVER_IMAGE_TAG')
    if agent_server_image_repository and agent_server_image_tag:
        return f'{agent_server_image_repository}:{agent_server_image_tag}'
    return AGENT_SERVER_IMAGE


def get_agent_server_env() -> dict[str, str]:
    """Get environment variables to be injected into agent server sandbox environments.

    Forwards all LLM_* variables from the app process (e.g. LLM_TIMEOUT) so agent-server
    containers receive the same LLM config. Additional or overriding variables can be
    set via OH_AGENT_SERVER_ENV (JSON); values in OH_AGENT_SERVER_ENV override LLM_*.

    Usage:
        App env LLM_TIMEOUT=3600 -> agent-server gets LLM_TIMEOUT=3600.
        OH_AGENT_SERVER_ENV='{"LLM_TIMEOUT": "1200", "DEBUG": "true"}' overrides
        LLM_TIMEOUT and adds DEBUG.

    Returns:
        dict[str, str]: Environment variables for agent server (LLM_* from os.environ
        merged with OH_AGENT_SERVER_ENV; OH_AGENT_SERVER_ENV wins on conflict).

    Raises:
        JSONDecodeError: If OH_AGENT_SERVER_ENV is set but contains invalid JSON.
    """
    llm_vars = {k: v for k, v in os.environ.items() if k.startswith('LLM_')}
    overrides = env_parser.from_env(dict[str, str], 'OH_AGENT_SERVER_ENV')
    return {**llm_vars, **overrides}
