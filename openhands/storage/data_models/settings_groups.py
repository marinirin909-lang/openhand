from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, Field, SecretStr

from openhands.core.config.mcp_config import MCPConfig
from openhands.storage.data_models.settings import SandboxGroupingStrategy, Settings

if TYPE_CHECKING:
    from openhands.sdk.llm.llm import LLM as SDKLLM


class LLMProfile(BaseModel):
    """Scope-free LLM settings payload.

    The SDK currently persists full ``openhands.sdk.llm.LLM`` objects in its
    profile store. This payload keeps just the profile fields currently present
    on the app-server execution path, while still supporting conversion to and
    from the SDK ``LLM`` object when needed.
    """

    model: str | None = None
    base_url: str | None = None
    api_key: SecretStr | None = None
    api_key_for_byor: SecretStr | None = None

    model_config = ConfigDict(validate_assignment=True)

    @classmethod
    def from_sdk_llm(cls, llm: 'SDKLLM') -> 'LLMProfile':
        """Create a lightweight profile payload from an SDK ``LLM``."""

        return cls(
            model=llm.model,
            base_url=llm.base_url,
            api_key=llm.api_key,
        )

    def to_sdk_llm(self, **overrides: Any) -> 'SDKLLM':
        """Promote this profile payload to an SDK ``LLM`` instance."""

        from openhands.sdk.llm.llm import LLM

        kwargs = {
            'model': self.model,
            'base_url': self.base_url,
            'api_key': self.api_key,
            **overrides,
        }
        return LLM(**{key: value for key, value in kwargs.items() if value is not None})


class AgentSettings(BaseModel):
    """Scope-free agent execution settings."""

    agent: str | None = None
    max_iterations: int | None = None
    security_analyzer: str | None = None
    confirmation_mode: bool | None = None
    enable_default_condenser: bool | None = None
    condenser_max_size: int | None = None

    model_config = ConfigDict(validate_assignment=True)


class ResourceSettings(BaseModel):
    """Scope-free runtime and resource settings."""

    mcp_config: MCPConfig | dict[str, Any] | None = None
    search_api_key: SecretStr | None = None
    sandbox_api_key: SecretStr | None = None
    remote_runtime_resource_factor: int | None = None
    enable_proactive_conversation_starters: bool | None = None
    sandbox_base_container_image: str | None = None
    sandbox_runtime_container_image: str | None = None
    max_budget_per_task: float | None = None
    enable_solvability_analysis: bool | None = None
    v1_enabled: bool | None = None
    sandbox_grouping_strategy: SandboxGroupingStrategy | None = None

    model_config = ConfigDict(validate_assignment=True)


class UserSettingsPayload(BaseModel):
    """Scope-free user preferences and profile fields."""

    language: str | None = None
    enable_sound_notifications: bool | None = None
    user_consents_to_analytics: bool | None = None
    accepted_tos: datetime | None = None
    email: str | None = None
    email_verified: bool | None = None
    git_user_name: str | None = None
    git_user_email: str | None = None

    model_config = ConfigDict(validate_assignment=True)


class SettingsGroups(BaseModel):
    """Grouped settings payloads decoupled from storage scope metadata."""

    llm: LLMProfile = Field(default_factory=LLMProfile)
    agent: AgentSettings = Field(default_factory=AgentSettings)
    resource: ResourceSettings = Field(default_factory=ResourceSettings)
    user: UserSettingsPayload = Field(default_factory=UserSettingsPayload)

    model_config = ConfigDict(validate_assignment=True)

    def to_settings(self) -> Settings:
        """Flatten grouped payloads into the shared app-server ``Settings`` model."""

        settings_kwargs: dict[str, object] = {}

        llm_mappings = {
            'llm_model': self.llm.model,
            'llm_base_url': self.llm.base_url,
            'llm_api_key': self.llm.api_key,
        }
        for field_name, value in llm_mappings.items():
            if value is not None:
                settings_kwargs[field_name] = value

        for field_name, value in self.agent.model_dump(exclude_none=True).items():
            settings_kwargs[field_name] = value

        for field_name, value in self.resource.model_dump(exclude_none=True).items():
            settings_kwargs[field_name] = value

        for field_name, value in self.user.model_dump(exclude_none=True).items():
            if field_name == 'accepted_tos':
                continue
            settings_kwargs[field_name] = value

        return Settings.model_validate(settings_kwargs)
