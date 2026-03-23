import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useSettings } from "#/hooks/query/use-settings";
import SettingsService from "#/api/settings-service/settings-service.api";
import {
  MCPSHTTPServer,
  MCPConfig,
  MCPSSEServer,
  MCPStdioServer,
} from "#/types/settings";
import { useSelectedOrganizationId } from "#/context/use-selected-organization";

type MCPServerType = "sse" | "stdio" | "shttp";

interface MCPServerConfig {
  type: MCPServerType;
  name?: string;
  url?: string;
  api_key?: string;
  timeout?: number;
  command?: string;
  args?: string[];
  env?: Record<string, string>;
}

export function useAddMcpServer() {
  const queryClient = useQueryClient();
  const { data: settings } = useSettings();
  const { organizationId } = useSelectedOrganizationId();

  return useMutation({
    mutationFn: async (server: MCPServerConfig): Promise<void> => {
      if (!settings) return;

      const currentConfig = (settings.agent_settings?.mcp_config as
        | MCPConfig
        | undefined) || {
        sse_servers: [],
        stdio_servers: [],
        shttp_servers: [],
      };

      const newConfig: MCPConfig = {
        sse_servers: [...currentConfig.sse_servers],
        stdio_servers: [...currentConfig.stdio_servers],
        shttp_servers: [...currentConfig.shttp_servers],
      };

      if (server.type === "sse") {
        const sseServer: MCPSSEServer = {
          url: server.url!,
          ...(server.api_key && { api_key: server.api_key }),
        };
        newConfig.sse_servers.push(sseServer);
      } else if (server.type === "stdio") {
        const stdioServer: MCPStdioServer = {
          name: server.name!,
          command: server.command!,
          ...(server.args && { args: server.args }),
          ...(server.env && { env: server.env }),
        };
        newConfig.stdio_servers.push(stdioServer);
      } else if (server.type === "shttp") {
        const shttpServer: MCPSHTTPServer = {
          url: server.url!,
          ...(server.api_key && { api_key: server.api_key }),
          ...(server.timeout !== undefined && { timeout: server.timeout }),
        };
        newConfig.shttp_servers.push(shttpServer);
      }

      await SettingsService.saveSettings({
        mcp_config: newConfig,
        v1_enabled: settings.v1_enabled,
      });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ["settings", organizationId],
      });
    },
  });
}
