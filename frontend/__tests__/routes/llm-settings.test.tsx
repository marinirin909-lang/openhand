import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import SettingsService from "#/api/settings-service/settings-service.api";
import {
  MOCK_DEFAULT_USER_SETTINGS,
  resetTestHandlersMockSettings,
} from "#/mocks/handlers";
import LlmSettingsScreen from "#/routes/llm-settings";
import { useSelectedOrganizationStore } from "#/stores/selected-organization-store";
import { OrganizationMember } from "#/types/org";
import { Settings } from "#/types/settings";

const mockUseSearchParams = vi.fn();
vi.mock("react-router", async () => {
  const actual =
    await vi.importActual<typeof import("react-router")>("react-router");
  return {
    ...actual,
    useSearchParams: () => mockUseSearchParams(),
    useRevalidator: () => ({
      revalidate: vi.fn(),
    }),
  };
});

const mockUseIsAuthed = vi.fn();
vi.mock("#/hooks/query/use-is-authed", () => ({
  useIsAuthed: () => mockUseIsAuthed(),
}));

const mockUseConfig = vi.fn();
vi.mock("#/hooks/query/use-config", () => ({
  useConfig: () => mockUseConfig(),
}));

function buildSettings(overrides: Partial<Settings> = {}): Settings {
  const hasSchemaOverride = Object.prototype.hasOwnProperty.call(
    overrides,
    "agent_settings_schema",
  );

  return {
    ...MOCK_DEFAULT_USER_SETTINGS,
    ...overrides,
    agent_settings_schema: hasSchemaOverride
      ? (overrides.agent_settings_schema ?? null)
      : MOCK_DEFAULT_USER_SETTINGS.agent_settings_schema,
    agent_settings: {
      ...MOCK_DEFAULT_USER_SETTINGS.agent_settings,
      ...overrides.agent_settings,
    },
  };
}

function buildOrganizationMember(
  overrides: Partial<OrganizationMember> = {},
): OrganizationMember {
  return {
    org_id: "1",
    user_id: "99",
    email: "owner@example.com",
    role: "owner",
    status: "active",
    llm_api_key: "",
    max_iterations: 20,
    llm_model: "",
    llm_api_key_for_byor: null,
    llm_base_url: "",
    ...overrides,
  };
}

function renderLlmSettingsScreen(
  options: {
    appMode?: "oss" | "saas";
    organizationId?: string;
    meData?: OrganizationMember;
  } = {},
) {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
      },
    },
  });
  const organizationId = options.organizationId ?? "1";
  const appMode = options.appMode ?? "oss";

  useSelectedOrganizationStore.setState({ organizationId });
  mockUseConfig.mockReturnValue({
    data: { app_mode: appMode },
    isLoading: false,
  });

  if (appMode === "saas") {
    queryClient.setQueryData(
      ["organizations", organizationId, "me"],
      options.meData ?? buildOrganizationMember({ org_id: organizationId }),
    );
  }

  return render(<LlmSettingsScreen />, {
    wrapper: ({ children }) => (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    ),
  });
}

beforeEach(() => {
  vi.restoreAllMocks();
  resetTestHandlersMockSettings();

  mockUseSearchParams.mockReturnValue([
    {
      get: () => null,
    },
    vi.fn(),
  ]);
  mockUseIsAuthed.mockReturnValue({ data: true, isLoading: false });
  mockUseConfig.mockReturnValue({
    data: { app_mode: "oss" },
    isLoading: false,
  });
  useSelectedOrganizationStore.setState({ organizationId: "1" });
});

describe("LlmSettingsScreen", () => {
  it("renders critical LLM fields from agent_settings_schema", async () => {
    vi.spyOn(SettingsService, "getSettings").mockResolvedValue(buildSettings());

    renderLlmSettingsScreen();

    await screen.findByTestId("llm-settings-screen");
    // Critical fields rendered by CriticalFields component
    expect(screen.getByTestId("sdk-settings-llm.api_key")).toBeInTheDocument();
    expect(screen.getByTestId("sdk-settings-llm.base_url")).toBeInTheDocument();
    // Condenser/critic fields should NOT appear (they have their own pages)
    expect(
      screen.queryByTestId("sdk-settings-critic.enabled"),
    ).not.toBeInTheDocument();
  });

  it("renders schema-driven settings when backend returns canonical agent_settings fields", async () => {
    const canonicalSettings: Settings = {
      ...buildSettings(),
      agent_settings_schema: MOCK_DEFAULT_USER_SETTINGS.agent_settings_schema,
      agent_settings: MOCK_DEFAULT_USER_SETTINGS.agent_settings,
    };

    vi.spyOn(SettingsService, "getSettings").mockResolvedValue(
      canonicalSettings,
    );

    renderLlmSettingsScreen();

    await screen.findByTestId("llm-settings-screen");
    expect(screen.getByTestId("sdk-settings-llm.api_key")).toBeInTheDocument();
    expect(screen.getByTestId("sdk-settings-llm.base_url")).toBeInTheDocument();
  });

  it("saves changed schema-driven fields through the generic settings payload", async () => {
    vi.spyOn(SettingsService, "getSettings").mockResolvedValue(buildSettings());
    const saveSettingsSpy = vi
      .spyOn(SettingsService, "saveSettings")
      .mockResolvedValue(true);

    renderLlmSettingsScreen();

    // Change the API key (always visible in CriticalFields)
    const apiKeyInput = await screen.findByTestId("sdk-settings-llm.api_key");
    await userEvent.clear(apiKeyInput);
    await userEvent.type(apiKeyInput, "sk-test-key");
    await userEvent.click(screen.getByTestId("save-button"));

    await waitFor(() => {
      expect(saveSettingsSpy).toHaveBeenCalledWith(
        expect.objectContaining({
          "llm.api_key": "sk-test-key",
        }),
      );
    });
  });

  it("hides the save button for read-only SaaS members", async () => {
    vi.spyOn(SettingsService, "getSettings").mockResolvedValue(buildSettings());

    renderLlmSettingsScreen({
      appMode: "saas",
      organizationId: "2",
      meData: buildOrganizationMember({ org_id: "2", role: "member" }),
    });

    await screen.findByTestId("llm-settings-screen");
    expect(screen.queryByTestId("save-button")).not.toBeInTheDocument();
    expect(screen.getByTestId("sdk-settings-llm.api_key")).toBeDisabled();
  });

  it("shows a fallback message when agent settings schema is unavailable", async () => {
    vi.spyOn(SettingsService, "getSettings").mockResolvedValue(
      buildSettings({ agent_settings_schema: null }),
    );

    renderLlmSettingsScreen();

    expect(
      await screen.findByText("SETTINGS$SDK_SCHEMA_UNAVAILABLE"),
    ).toBeInTheDocument();
  });

  it("renders help link for api key field", async () => {
    vi.spyOn(SettingsService, "getSettings").mockResolvedValue(buildSettings());

    renderLlmSettingsScreen();

    await screen.findByTestId("llm-settings-screen");
    expect(screen.getByTestId("help-link-llm.api_key")).toBeInTheDocument();
  });
});
