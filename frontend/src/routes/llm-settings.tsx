import React from "react";
import { useTranslation } from "react-i18next";
import { useSearchParams } from "react-router";

import { SettingsInput } from "#/components/features/settings/settings-input";
import { FIELD_HELP_LINKS } from "#/components/features/settings/sdk-settings/schema-field";
import {
  SdkSectionPage,
  SdkSectionHeaderProps,
} from "#/components/features/settings/sdk-settings/sdk-section-page";
import { ModelSelector } from "#/components/shared/modals/settings/model-selector";
import { useAIConfigOptions } from "#/hooks/query/use-ai-config-options";
import { I18nKey } from "#/i18n/declaration";
import { HelpLink } from "#/ui/help-link";
import {
  displayErrorToast,
  displaySuccessToast,
} from "#/utils/custom-toast-handlers";
import { createPermissionGuard } from "#/utils/org/permission-guard";
import { organizeModelsAndProviders } from "#/utils/organize-models-and-providers";
import { SPECIALLY_RENDERED_KEYS } from "#/utils/sdk-settings-schema";

// ---------------------------------------------------------------------------
// Specially-rendered critical fields (llm.model, llm.api_key, llm.base_url)
// ---------------------------------------------------------------------------
function CriticalFields({
  models,
  values,
  isDisabled,
  onChange,
}: SdkSectionHeaderProps & { models: string[] }) {
  const currentModel = String(values["llm.model"] ?? "");
  const currentApiKey = String(values["llm.api_key"] ?? "");
  const currentBaseUrl = String(values["llm.base_url"] ?? "");
  const isApiKeySet = currentApiKey === "<hidden>" || currentApiKey.length > 0;
  const apiKeyHelp = FIELD_HELP_LINKS["llm.api_key"];

  return (
    <div className="flex flex-col gap-4">
      <ModelSelector
        models={organizeModelsAndProviders(models)}
        currentModel={currentModel || undefined}
        isDisabled={isDisabled}
        onChange={(provider, model) => {
          if (model !== null && provider) {
            // OpenAI models are listed without a prefix in LiteLLM
            const fullModel =
              provider === "openai" ? model : `${provider}/${model}`;
            onChange("llm.model", fullModel);
          }
        }}
      />

      <SettingsInput
        testId="sdk-settings-llm.api_key"
        name="llm.api_key"
        label="API Key"
        type="password"
        value={currentApiKey}
        required={false}
        showOptionalTag
        isDisabled={isDisabled}
        placeholder={isApiKeySet ? "<hidden>" : ""}
        onChange={(val) => onChange("llm.api_key", val)}
        className="w-full"
      />
      {apiKeyHelp ? (
        <HelpLink
          testId="help-link-llm.api_key"
          text={apiKeyHelp.text}
          linkText={apiKeyHelp.linkText}
          href={apiKeyHelp.href}
          size="settings"
          linkColor="white"
        />
      ) : null}

      <SettingsInput
        testId="sdk-settings-llm.base_url"
        name="llm.base_url"
        label="Base URL"
        type="text"
        value={currentBaseUrl}
        required={false}
        showOptionalTag
        isDisabled={isDisabled}
        onChange={(val) => onChange("llm.base_url", val)}
        className="w-full"
      />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main screen – LLM section only, with CriticalFields header
// ---------------------------------------------------------------------------
function LlmSettingsScreen() {
  const { t } = useTranslation();
  const [searchParams, setSearchParams] = useSearchParams();
  const { data: aiConfigOptions } = useAIConfigOptions();

  React.useEffect(() => {
    const checkout = searchParams.get("checkout");
    if (checkout === "success") {
      displaySuccessToast(t(I18nKey.SUBSCRIPTION$SUCCESS));
      setSearchParams({});
    } else if (checkout === "cancel") {
      displayErrorToast(t(I18nKey.SUBSCRIPTION$FAILURE));
      setSearchParams({});
    }
  }, [searchParams, setSearchParams, t]);

  const models = aiConfigOptions?.models ?? [];

  const renderHeader = React.useCallback(
    ({ values, isDisabled, onChange }: SdkSectionHeaderProps) => (
      <CriticalFields
        values={values}
        isDisabled={isDisabled}
        onChange={onChange}
        models={models}
      />
    ),
    [models],
  );

  return (
    <SdkSectionPage
      sectionKeys={["llm"]}
      excludeKeys={SPECIALLY_RENDERED_KEYS}
      testId="llm-settings-screen"
      header={renderHeader}
    />
  );
}

export const clientLoader = createPermissionGuard("view_llm_settings");

export default LlmSettingsScreen;
