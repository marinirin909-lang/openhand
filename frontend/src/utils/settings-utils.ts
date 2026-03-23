import { WebClientFeatureFlags } from "#/api/option-service/option.types";
import { Settings } from "#/types/settings";
import { getProviderId } from "#/utils/map-provider";

const extractBasicFormData = (formData: FormData) => {
  const providerDisplay = formData.get("llm-provider-input")?.toString();
  const provider = providerDisplay ? getProviderId(providerDisplay) : undefined;
  const model = formData.get("llm-model-input")?.toString();

  return {
    llmModel: provider && model ? `${provider}/${model}` : undefined,
    llmApiKey: formData.get("llm-api-key-input")?.toString(),
    agent: formData.get("agent")?.toString(),
    language: formData.get("language")?.toString(),
  };
};

/**
 * Parses and validates a max budget per task value.
 * Ensures the value is at least 1 dollar.
 * @param value - The string value to parse
 * @returns The parsed number if valid (>= 1), null otherwise
 */
export const parseMaxBudgetPerTask = (value: string): number | null => {
  if (!value) {
    return null;
  }

  const parsedValue = parseFloat(value);
  return parsedValue && parsedValue >= 1 && Number.isFinite(parsedValue)
    ? parsedValue
    : null;
};

export const extractSettings = (
  formData: FormData,
): Partial<Settings> & Record<string, unknown> => {
  const { llmModel, llmApiKey, agent, language } =
    extractBasicFormData(formData);

  return {
    ...(llmModel ? { "llm.model": llmModel } : {}),
    ...(llmApiKey !== undefined ? { "llm.api_key": llmApiKey } : {}),
    ...(agent ? { agent } : {}),
    ...(language ? { language } : {}),
  };
};

/**
 * Checks if a settings page should be hidden based on feature flags.
 * Used by both the route loader and navigation hook to keep logic in sync.
 */
export function isSettingsPageHidden(
  path: string,
  featureFlags: WebClientFeatureFlags | undefined,
): boolean {
  if (featureFlags?.hide_llm_settings && path === "/settings") return true;
  if (featureFlags?.hide_users_page && path === "/settings/user") return true;
  if (featureFlags?.hide_billing_page && path === "/settings/billing")
    return true;
  if (featureFlags?.hide_integrations_page && path === "/settings/integrations")
    return true;
  return false;
}

/**
 * Find the first available settings page that is not hidden.
 * Returns null if no page is available (shouldn't happen in practice).
 */
export function getFirstAvailablePath(
  isSaas: boolean,
  featureFlags: WebClientFeatureFlags | undefined,
): string | null {
  const saasFallbackOrder = [
    { path: "/settings/user", hidden: !!featureFlags?.hide_users_page },
    {
      path: "/settings/integrations",
      hidden: !!featureFlags?.hide_integrations_page,
    },
    { path: "/settings/app", hidden: false },
    { path: "/settings", hidden: !!featureFlags?.hide_llm_settings },
    { path: "/settings/billing", hidden: !!featureFlags?.hide_billing_page },
    { path: "/settings/secrets", hidden: false },
    { path: "/settings/api-keys", hidden: false },
    { path: "/settings/mcp", hidden: false },
  ];

  const ossFallbackOrder = [
    { path: "/settings", hidden: !!featureFlags?.hide_llm_settings },
    { path: "/settings/mcp", hidden: false },
    {
      path: "/settings/integrations",
      hidden: !!featureFlags?.hide_integrations_page,
    },
    { path: "/settings/app", hidden: false },
    { path: "/settings/secrets", hidden: false },
  ];

  const fallbackOrder = isSaas ? saasFallbackOrder : ossFallbackOrder;
  const firstAvailable = fallbackOrder.find((item) => !item.hidden);

  return firstAvailable?.path ?? null;
}
