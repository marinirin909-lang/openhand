from __future__ import annotations

from openhands.storage.data_models.settings import Settings, SandboxGroupingStrategy
from openhands.storage.data_models.settings_groups import (
    AgentSettings,
    LLMProfile,
    ResourceSettings,
    SettingsGroups,
    UserSettingsPayload,
)
from storage.org import Org
from storage.org_member import OrgMember
from storage.user import User
from storage.user_settings import UserSettings


def _normalize_sandbox_grouping_strategy(
    value: object,
) -> SandboxGroupingStrategy | None:
    if value is None:
        return None
    if isinstance(value, SandboxGroupingStrategy):
        return value
    if isinstance(value, str):
        try:
            return SandboxGroupingStrategy(value)
        except ValueError:
            return None
    return None



def build_settings_groups(
    user: User,
    org: Org,
    org_member: OrgMember,
) -> SettingsGroups:
    """Build scope-free settings payloads from enterprise ORM entities."""

    return SettingsGroups(
        llm=LLMProfile(
            model=(
                org_member.llm_model
                if org_member.llm_model is not None
                else org.default_llm_model
            ),
            base_url=(
                org_member.llm_base_url
                if org_member.llm_base_url is not None
                else org.default_llm_base_url
            ),
            api_key=org_member.llm_api_key,
            api_key_for_byor=org_member.llm_api_key_for_byor,
        ),
        agent=AgentSettings(
            agent=org.agent,
            max_iterations=(
                org_member.max_iterations
                if org_member.max_iterations is not None
                else org.default_max_iterations
            ),
            security_analyzer=org.security_analyzer,
            confirmation_mode=org.confirmation_mode,
            enable_default_condenser=org.enable_default_condenser,
            condenser_max_size=org.condenser_max_size,
        ),
        resource=ResourceSettings(
            mcp_config=org.mcp_config,
            search_api_key=org.search_api_key,
            sandbox_api_key=org.sandbox_api_key,
            remote_runtime_resource_factor=org.remote_runtime_resource_factor,
            enable_proactive_conversation_starters=org.enable_proactive_conversation_starters,
            sandbox_base_container_image=org.sandbox_base_container_image,
            sandbox_runtime_container_image=org.sandbox_runtime_container_image,
            max_budget_per_task=org.max_budget_per_task,
            enable_solvability_analysis=org.enable_solvability_analysis,
            v1_enabled=org.v1_enabled,
            sandbox_grouping_strategy=_normalize_sandbox_grouping_strategy(
                getattr(user, 'sandbox_grouping_strategy', None)
                if getattr(user, 'sandbox_grouping_strategy', None) is not None
                else getattr(org, 'sandbox_grouping_strategy', None)
            ),
        ),
        user=UserSettingsPayload(
            language=user.language,
            enable_sound_notifications=user.enable_sound_notifications,
            user_consents_to_analytics=user.user_consents_to_analytics,
            accepted_tos=user.accepted_tos,
            email=user.email,
            email_verified=user.email_verified,
            git_user_name=user.git_user_name,
            git_user_email=user.git_user_email,
        ),
    )


def build_resolved_settings(user: User, org: Org, org_member: OrgMember) -> Settings:
    """Build the shared app-server ``Settings`` model from enterprise entities."""

    return build_settings_groups(user=user, org=org, org_member=org_member).to_settings()


def build_user_settings(
    user_id: str,
    user: User,
    org: Org,
    org_member: OrgMember,
) -> UserSettings:
    """Build a legacy ``UserSettings`` row from normalized enterprise entities."""

    groups = build_settings_groups(user=user, org=org, org_member=org_member)

    return UserSettings(
        keycloak_user_id=user_id,
        language=groups.user.language,
        agent=groups.agent.agent,
        max_iterations=groups.agent.max_iterations,
        security_analyzer=groups.agent.security_analyzer,
        confirmation_mode=groups.agent.confirmation_mode,
        llm_model=groups.llm.model,
        llm_api_key=groups.llm.api_key.get_secret_value()
        if groups.llm.api_key
        else None,
        llm_api_key_for_byor=groups.llm.api_key_for_byor.get_secret_value()
        if groups.llm.api_key_for_byor
        else None,
        llm_base_url=groups.llm.base_url,
        remote_runtime_resource_factor=groups.resource.remote_runtime_resource_factor,
        enable_default_condenser=groups.agent.enable_default_condenser
        if groups.agent.enable_default_condenser is not None
        else True,
        condenser_max_size=groups.agent.condenser_max_size,
        user_consents_to_analytics=groups.user.user_consents_to_analytics,
        accepted_tos=groups.user.accepted_tos,
        billing_margin=org.billing_margin,
        enable_sound_notifications=groups.user.enable_sound_notifications,
        enable_proactive_conversation_starters=groups.resource.enable_proactive_conversation_starters,
        sandbox_base_container_image=groups.resource.sandbox_base_container_image,
        sandbox_runtime_container_image=groups.resource.sandbox_runtime_container_image,
        user_version=org.org_version,
        mcp_config=groups.resource.mcp_config,
        search_api_key=groups.resource.search_api_key.get_secret_value()
        if groups.resource.search_api_key
        else None,
        sandbox_api_key=groups.resource.sandbox_api_key.get_secret_value()
        if groups.resource.sandbox_api_key
        else None,
        max_budget_per_task=groups.resource.max_budget_per_task,
        enable_solvability_analysis=groups.resource.enable_solvability_analysis,
        email=groups.user.email,
        email_verified=groups.user.email_verified,
        git_user_name=groups.user.git_user_name,
        git_user_email=groups.user.git_user_email,
        v1_enabled=groups.resource.v1_enabled,
        sandbox_grouping_strategy=groups.resource.sandbox_grouping_strategy,
        already_migrated=False,
    )
