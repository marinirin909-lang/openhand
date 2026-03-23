import { useMutation, useQueryClient } from "@tanstack/react-query";
import { usePostHog } from "posthog-js/react";
import SettingsService from "#/api/settings-service/settings-service.api";
import { MCPConfig, Settings } from "#/types/settings";
import { useSettings } from "../query/use-settings";
import { useSelectedOrganizationId } from "#/context/use-selected-organization";

type SettingsUpdate = Partial<Settings> & Record<string, unknown>;

const saveSettingsMutationFn = async (settings: SettingsUpdate) => {
  const settingsToSave: SettingsUpdate = { ...settings };
  delete settingsToSave.agent_settings_schema;
  delete settingsToSave.agent_settings;

  if (typeof settingsToSave["llm.api_key"] === "string") {
    const apiKey = settingsToSave["llm.api_key"].trim();
    settingsToSave["llm.api_key"] = apiKey === "" ? "" : apiKey;
  }

  if (typeof settingsToSave.search_api_key === "string") {
    settingsToSave.search_api_key = settingsToSave.search_api_key.trim();
  }
  if (typeof settingsToSave.git_user_name === "string") {
    settingsToSave.git_user_name = settingsToSave.git_user_name.trim();
  }
  if (typeof settingsToSave.git_user_email === "string") {
    settingsToSave.git_user_email = settingsToSave.git_user_email.trim();
  }

  await SettingsService.saveSettings(settingsToSave);
};

export const useSaveSettings = () => {
  const posthog = usePostHog();
  const queryClient = useQueryClient();
  const { data: currentSettings } = useSettings();
  const { organizationId } = useSelectedOrganizationId();

  return useMutation({
    mutationFn: async (settings: SettingsUpdate) => {
      const nextMcpConfig = settings.mcp_config as MCPConfig | undefined;
      const currentMcpConfig = currentSettings?.agent_settings?.mcp_config as
        | MCPConfig
        | undefined;

      if (nextMcpConfig && currentMcpConfig !== nextMcpConfig) {
        posthog.capture("mcp_config_updated", {
          has_mcp_config: true,
          sse_servers_count: nextMcpConfig.sse_servers?.length || 0,
          stdio_servers_count: nextMcpConfig.stdio_servers?.length || 0,
        });
      }

      await saveSettingsMutationFn(settings);
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({
        queryKey: ["settings", organizationId],
      });
    },
    meta: {
      disableToast: true,
    },
  });
};
