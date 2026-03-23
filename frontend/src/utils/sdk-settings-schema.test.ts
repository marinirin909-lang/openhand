import { describe, expect, it } from "vitest";

import {
  buildInitialSettingsFormValues,
  buildSdkSettingsPayload,
  getVisibleSettingsSections,
  hasAdvancedSettingsOverrides,
  inferInitialView,
  SPECIALLY_RENDERED_KEYS,
} from "./sdk-settings-schema";
import { Settings } from "#/types/settings";

const BASE_SETTINGS: Settings = {
  language: "en",
  llm_api_key_set: false,
  search_api_key_set: false,
  remote_runtime_resource_factor: 1,
  provider_tokens_set: {},
  enable_sound_notifications: false,
  enable_proactive_conversation_starters: false,
  enable_solvability_analysis: false,
  user_consents_to_analytics: false,
  search_api_key: "",
  is_new_user: true,
  max_budget_per_task: null,
  email: "",
  email_verified: true,
  git_user_name: "openhands",
  git_user_email: "openhands@all-hands.dev",
  v1_enabled: false,
  agent_settings_schema: {
    model_name: "AgentSettings",
    sections: [
      {
        key: "llm",
        label: "LLM",
        fields: [
          {
            key: "llm.model",
            label: "Model",
            section: "llm",
            section_label: "LLM",
            value_type: "string",
            default: "claude-sonnet-4-20250514",
            choices: [],
            depends_on: [],
            prominence: "critical",
            secret: false,
            required: true,
          },
          {
            key: "llm.api_key",
            label: "API Key",
            section: "llm",
            section_label: "LLM",
            value_type: "string",
            default: null,
            choices: [],
            depends_on: [],
            prominence: "critical",
            secret: true,
            required: false,
          },
          {
            key: "llm.base_url",
            label: "Base URL",
            section: "llm",
            section_label: "LLM",
            value_type: "string",
            default: null,
            choices: [],
            depends_on: [],
            prominence: "critical",
            secret: false,
            required: false,
          },
          {
            key: "llm.litellm_extra_body",
            label: "LiteLLM Extra Body",
            section: "llm",
            section_label: "LLM",
            value_type: "object",
            default: {},
            choices: [],
            depends_on: [],
            prominence: "minor",
            secret: false,
            required: false,
          },
        ],
      },
      {
        key: "critic",
        label: "Critic",
        fields: [
          {
            key: "critic.enabled",
            label: "Enable critic",
            section: "critic",
            section_label: "Critic",
            value_type: "boolean",
            default: false,
            choices: [],
            depends_on: [],
            prominence: "critical",
            secret: false,
            required: true,
          },
          {
            key: "critic.mode",
            label: "Mode",
            section: "critic",
            section_label: "Critic",
            value_type: "string",
            default: "finish_and_message",
            choices: [
              { label: "finish_and_message", value: "finish_and_message" },
              { label: "all_actions", value: "all_actions" },
            ],
            depends_on: ["critic.enabled"],
            prominence: "minor",
            secret: false,
            required: true,
          },
        ],
      },
    ],
  },
  agent_settings: {
    agent: "CodeActAgent",
    "critic.mode": "finish_and_message",
    "critic.enabled": false,
    "llm.api_key": null,
    "llm.model": "openai/gpt-4o",
    "verification.confirmation_mode": false,
    "condenser.enabled": true,
    "condenser.max_size": 240,
  },
};

describe("sdk settings schema helpers", () => {
  it("builds initial form values from the current settings", () => {
    expect(buildInitialSettingsFormValues(BASE_SETTINGS)).toEqual({
      "critic.mode": "finish_and_message",
      "critic.enabled": false,
      "llm.api_key": "",
      "llm.base_url": "",
      "llm.litellm_extra_body": "{}",
      "llm.model": "openai/gpt-4o",
    });
  });

  it("detects advanced overrides from non-default values", () => {
    expect(hasAdvancedSettingsOverrides(BASE_SETTINGS)).toBe(false);
    expect(inferInitialView(BASE_SETTINGS)).toBe("basic");

    const withMinorOverride: Settings = {
      ...BASE_SETTINGS,
      agent_settings: {
        ...BASE_SETTINGS.agent_settings,
        "critic.mode": "all_actions",
      },
    };
    expect(hasAdvancedSettingsOverrides(withMinorOverride)).toBe(true);
    expect(inferInitialView(withMinorOverride)).toBe("all");
  });

  it("filters fields by view tier and excludes specially-rendered keys", () => {
    const values = buildInitialSettingsFormValues(BASE_SETTINGS);

    const basicSections = getVisibleSettingsSections(
      BASE_SETTINGS.agent_settings_schema!,
      values,
      "basic",
    );
    const allBasicFields = basicSections.flatMap((s) => s.fields);
    for (const field of allBasicFields) {
      expect(SPECIALLY_RENDERED_KEYS.has(field.key)).toBe(false);
      expect(field.prominence).toBe("critical");
    }

    const allSections = getVisibleSettingsSections(
      BASE_SETTINGS.agent_settings_schema!,
      { ...values, "critic.enabled": true },
      "all",
    );
    const criticSection = allSections.find((s) => s.key === "critic");
    expect(criticSection?.fields).toHaveLength(2);
  });

  it("passes through all fields when excludeKeys is empty", () => {
    const values = buildInitialSettingsFormValues(BASE_SETTINGS);
    const sections = getVisibleSettingsSections(
      BASE_SETTINGS.agent_settings_schema!,
      values,
      "basic",
      new Set(),
    );
    const allFieldKeys = sections.flatMap((s) => s.fields.map((f) => f.key));
    expect(allFieldKeys).toContain("llm.model");
    expect(allFieldKeys).toContain("llm.api_key");
  });

  it("builds a typed payload from dirty schema values", () => {
    const payload = buildSdkSettingsPayload(
      BASE_SETTINGS.agent_settings_schema!,
      {
        ...buildInitialSettingsFormValues(BASE_SETTINGS),
        "critic.enabled": true,
        "llm.api_key": "new-key",
        "llm.litellm_extra_body": JSON.stringify(
          { metadata: { tier: "enterprise" } },
          null,
          2,
        ),
      },
      {
        "critic.enabled": true,
        "llm.api_key": true,
        "llm.litellm_extra_body": true,
        "llm.model": false,
      },
    );

    expect(payload).toEqual({
      "critic.enabled": true,
      "llm.api_key": "new-key",
      "llm.litellm_extra_body": { metadata: { tier: "enterprise" } },
    });
  });
});
