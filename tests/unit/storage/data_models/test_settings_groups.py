import json
import os

from pydantic import SecretStr

from openhands.storage.data_models.settings import SandboxGroupingStrategy
from openhands.storage.data_models.settings_groups import (
    AgentSettings,
    LLMProfile,
    ResourceSettings,
    SettingsGroups,
    UserSettingsPayload,
)

os.environ.setdefault('OPENHANDS_SUPPRESS_BANNER', '1')


def test_settings_groups_to_settings_keeps_scope_fields_out_of_payloads() -> None:
    groups = SettingsGroups(
        llm=LLMProfile(
            model='anthropic/claude-sonnet-4-5-20250929',
            base_url='https://llm.example.com',
            api_key=SecretStr('secret-key'),
        ),
        agent=AgentSettings(
            agent='CodeActAgent',
            max_iterations=42,
            confirmation_mode=False,
        ),
        resource=ResourceSettings(),
        user=UserSettingsPayload(language='fr', enable_sound_notifications=False),
    )

    dumped = json.dumps(groups.model_dump(mode='json'))
    for forbidden_field in ('scope', 'org_id', 'user_id', 'keycloak_user_id'):
        assert forbidden_field not in dumped

    settings = groups.to_settings()
    assert settings.llm_model == 'anthropic/claude-sonnet-4-5-20250929'
    assert settings.llm_base_url == 'https://llm.example.com'
    assert settings.llm_api_key is not None
    assert settings.llm_api_key.get_secret_value() == 'secret-key'
    assert settings.max_iterations == 42
    assert settings.language == 'fr'
    assert settings.v1_enabled is True
    assert settings.sandbox_grouping_strategy == SandboxGroupingStrategy.NO_GROUPING


def test_llm_profile_round_trips_with_sdk_llm() -> None:
    profile = LLMProfile(
        model='openai/gpt-4o',
        base_url='https://api.example.com',
        api_key=SecretStr('sdk-secret'),
    )

    sdk_llm = profile.to_sdk_llm(usage_id='fast', temperature=0.3)
    round_trip = LLMProfile.from_sdk_llm(sdk_llm)

    assert sdk_llm.usage_id == 'fast'
    assert sdk_llm.temperature == 0.3
    assert round_trip.model == 'openai/gpt-4o'
    assert round_trip.base_url == 'https://api.example.com'
    assert round_trip.api_key is not None
    assert round_trip.api_key.get_secret_value() == 'sdk-secret'
