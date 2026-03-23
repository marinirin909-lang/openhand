import React from "react";
import { useTranslation } from "react-i18next";
import { usePostHog } from "posthog-js/react";
import { useSaveSettings } from "#/hooks/mutation/use-save-settings";
import { useSettings } from "#/hooks/query/use-settings";
import { AvailableLanguages } from "#/i18n";
import { DEFAULT_SETTINGS } from "#/services/settings";
import { BrandButton } from "#/components/features/settings/brand-button";
import { SettingsSwitch } from "#/components/features/settings/settings-switch";
import { SettingsInput } from "#/components/features/settings/settings-input";
import { SettingsDropdownInput } from "#/components/features/settings/settings-dropdown-input";
import { I18nKey } from "#/i18n/declaration";
import { LanguageInput } from "#/components/features/settings/app-settings/language-input";
import { handleCaptureConsent } from "#/utils/handle-capture-consent";
import {
  displayErrorToast,
  displaySuccessToast,
} from "#/utils/custom-toast-handlers";
import { retrieveAxiosErrorMessage } from "#/utils/retrieve-axios-error-message";
import { AppSettingsInputsSkeleton } from "#/components/features/settings/app-settings/app-settings-inputs-skeleton";
import { useConfig } from "#/hooks/query/use-config";
import {
  isValidMarketplacePath,
  parseMarketplacePath,
  parseMaxBudgetPerTask,
} from "#/utils/settings-utils";
import {
  SandboxGroupingStrategy,
  SandboxGroupingStrategyOptions,
} from "#/types/settings";
import { ENABLE_SANDBOX_GROUPING } from "#/utils/feature-flags";
import { createPermissionGuard } from "#/utils/org/permission-guard";

export const clientLoader = createPermissionGuard(
  "manage_application_settings",
);

type ChangedField =
  | "language"
  | "analytics"
  | "soundNotifications"
  | "proactiveConversations"
  | "solvabilityAnalysis"
  | "sandboxGroupingStrategy"
  | "maxBudgetPerTask"
  | "gitUserName"
  | "gitUserEmail"
  | "marketplacePath";

function AppSettingsScreen() {
  const posthog = usePostHog();
  const { t } = useTranslation();

  const { mutate: saveSettings, isPending } = useSaveSettings();
  const { data: settings, isLoading } = useSettings();
  const { data: config } = useConfig();

  const [changedFields, setChangedFields] = React.useState<Set<ChangedField>>(
    new Set<ChangedField>(),
  );
  const [selectedSandboxGroupingStrategy, setSelectedSandboxGroupingStrategy] =
    React.useState<SandboxGroupingStrategy | null>(null);
  const [marketplacePathError, setMarketplacePathError] = React.useState<
    string | null
  >(null);

  const setFieldChanged = React.useCallback(
    (field: ChangedField, changed: boolean) => {
      setChangedFields((currentFields) => {
        const nextFields = new Set(currentFields);
        if (changed) {
          nextFields.add(field);
        } else {
          nextFields.delete(field);
        }
        return nextFields;
      });
    },
    [],
  );

  const formAction = (formData: FormData) => {
    const languageLabel = formData.get("language-input")?.toString();
    const languageValue = AvailableLanguages.find(
      ({ label }) => label === languageLabel,
    )?.value;
    const language = languageValue || DEFAULT_SETTINGS.language;

    const enableAnalytics =
      formData.get("enable-analytics-switch")?.toString() === "on";
    const enableSoundNotifications =
      formData.get("enable-sound-notifications-switch")?.toString() === "on";

    const enableProactiveConversations =
      formData.get("enable-proactive-conversations-switch")?.toString() ===
      "on";

    const enableSolvabilityAnalysis =
      formData.get("enable-solvability-analysis-switch")?.toString() === "on";

    const sandboxGroupingStrategy =
      selectedSandboxGroupingStrategy ||
      settings?.sandbox_grouping_strategy ||
      DEFAULT_SETTINGS.sandbox_grouping_strategy;

    const maxBudgetPerTaskValue = formData
      .get("max-budget-per-task-input")
      ?.toString();
    const maxBudgetPerTask = parseMaxBudgetPerTask(maxBudgetPerTaskValue || "");

    const gitUserName =
      formData.get("git-user-name-input")?.toString() ||
      DEFAULT_SETTINGS.git_user_name;
    const gitUserEmail =
      formData.get("git-user-email-input")?.toString() ||
      DEFAULT_SETTINGS.git_user_email;

    const marketplacePathValue = formData
      .get("marketplace-path-input")
      ?.toString();

    if (!isValidMarketplacePath(marketplacePathValue || "")) {
      setMarketplacePathError(t(I18nKey.SETTINGS$MARKETPLACE_PATH_INVALID));
      return;
    }

    const marketplacePath = parseMarketplacePath(marketplacePathValue);

    saveSettings(
      {
        language,
        user_consents_to_analytics: enableAnalytics,
        enable_sound_notifications: enableSoundNotifications,
        enable_proactive_conversation_starters: enableProactiveConversations,
        enable_solvability_analysis: enableSolvabilityAnalysis,
        sandbox_grouping_strategy: sandboxGroupingStrategy,
        max_budget_per_task: maxBudgetPerTask,
        git_user_name: gitUserName,
        git_user_email: gitUserEmail,
        marketplace_path: marketplacePath,
      },
      {
        onSuccess: () => {
          handleCaptureConsent(posthog, enableAnalytics);
          setChangedFields(new Set<ChangedField>());
          setSelectedSandboxGroupingStrategy(null);
          setMarketplacePathError(null);
          displaySuccessToast(t(I18nKey.SETTINGS$SAVED));
        },
        onError: (error) => {
          const errorMessage = retrieveAxiosErrorMessage(error);
          displayErrorToast(errorMessage || t(I18nKey.ERROR$GENERIC));
        },
      },
    );
  };

  const checkIfLanguageInputHasChanged = (value: string) => {
    const selectedLanguage = AvailableLanguages.find(
      ({ label: langValue }) => langValue === value,
    )?.label;
    const currentLanguage = AvailableLanguages.find(
      ({ value: langValue }) => langValue === settings?.language,
    )?.label;

    setFieldChanged("language", selectedLanguage !== currentLanguage);
  };

  const checkIfAnalyticsSwitchHasChanged = (checked: boolean) => {
    // Treat null as true since analytics is opt-in by default
    const currentAnalytics = settings?.user_consents_to_analytics ?? true;
    setFieldChanged("analytics", checked !== currentAnalytics);
  };

  const checkIfSoundNotificationsSwitchHasChanged = (checked: boolean) => {
    const currentSoundNotifications = !!settings?.enable_sound_notifications;
    setFieldChanged(
      "soundNotifications",
      checked !== currentSoundNotifications,
    );
  };

  const checkIfProactiveConversationsSwitchHasChanged = (checked: boolean) => {
    const currentProactiveConversations =
      !!settings?.enable_proactive_conversation_starters;
    setFieldChanged(
      "proactiveConversations",
      checked !== currentProactiveConversations,
    );
  };

  const checkIfSolvabilityAnalysisSwitchHasChanged = (checked: boolean) => {
    const currentSolvabilityAnalysis = !!settings?.enable_solvability_analysis;
    setFieldChanged(
      "solvabilityAnalysis",
      checked !== currentSolvabilityAnalysis,
    );
  };

  const handleSandboxGroupingStrategyChange = (key: React.Key | null) => {
    const newStrategy = key?.toString() as SandboxGroupingStrategy | undefined;
    setSelectedSandboxGroupingStrategy(newStrategy || null);
    const currentStrategy =
      settings?.sandbox_grouping_strategy ||
      DEFAULT_SETTINGS.sandbox_grouping_strategy;
    setFieldChanged("sandboxGroupingStrategy", newStrategy !== currentStrategy);
  };

  const checkIfMaxBudgetPerTaskHasChanged = (value: string) => {
    const newValue = parseMaxBudgetPerTask(value);
    const currentValue = settings?.max_budget_per_task;
    setFieldChanged("maxBudgetPerTask", newValue !== currentValue);
  };

  const checkIfGitUserNameHasChanged = (value: string) => {
    const currentValue = settings?.git_user_name;
    setFieldChanged("gitUserName", value !== currentValue);
  };

  const checkIfGitUserEmailHasChanged = (value: string) => {
    const currentValue = settings?.git_user_email;
    setFieldChanged("gitUserEmail", value !== currentValue);
  };

  const checkIfMarketplacePathHasChanged = (value: string) => {
    const currentValue = settings?.marketplace_path ?? null;
    const newValue = parseMarketplacePath(value);
    setFieldChanged("marketplacePath", newValue !== currentValue);

    if (!isValidMarketplacePath(value)) {
      setMarketplacePathError(t(I18nKey.SETTINGS$MARKETPLACE_PATH_INVALID));
      return;
    }

    setMarketplacePathError(null);
  };

  const formIsClean = changedFields.size === 0;
  const hasValidationErrors = !!marketplacePathError;
  const shouldBeLoading = !settings || isLoading || isPending;

  return (
    <form
      data-testid="app-settings-screen"
      action={formAction}
      className="flex flex-col h-full justify-between"
    >
      {shouldBeLoading && <AppSettingsInputsSkeleton />}
      {!shouldBeLoading && (
        <div className="flex flex-col gap-6">
          <LanguageInput
            name="language-input"
            defaultKey={settings.language}
            onChange={checkIfLanguageInputHasChanged}
          />

          <SettingsSwitch
            testId="enable-analytics-switch"
            name="enable-analytics-switch"
            defaultIsToggled={settings.user_consents_to_analytics ?? true}
            onToggle={checkIfAnalyticsSwitchHasChanged}
          >
            {t(I18nKey.ANALYTICS$SEND_ANONYMOUS_DATA)}
          </SettingsSwitch>

          <SettingsSwitch
            testId="enable-sound-notifications-switch"
            name="enable-sound-notifications-switch"
            defaultIsToggled={!!settings.enable_sound_notifications}
            onToggle={checkIfSoundNotificationsSwitchHasChanged}
          >
            {t(I18nKey.SETTINGS$SOUND_NOTIFICATIONS)}
          </SettingsSwitch>

          {config?.app_mode === "saas" && (
            <SettingsSwitch
              testId="enable-proactive-conversations-switch"
              name="enable-proactive-conversations-switch"
              defaultIsToggled={
                !!settings.enable_proactive_conversation_starters
              }
              onToggle={checkIfProactiveConversationsSwitchHasChanged}
            >
              {t(I18nKey.SETTINGS$PROACTIVE_CONVERSATION_STARTERS)}
            </SettingsSwitch>
          )}

          {config?.app_mode === "saas" && (
            <SettingsSwitch
              testId="enable-solvability-analysis-switch"
              name="enable-solvability-analysis-switch"
              defaultIsToggled={!!settings.enable_solvability_analysis}
              onToggle={checkIfSolvabilityAnalysisSwitchHasChanged}
            >
              {t(I18nKey.SETTINGS$SOLVABILITY_ANALYSIS)}
            </SettingsSwitch>
          )}

          {ENABLE_SANDBOX_GROUPING() && (
            <SettingsDropdownInput
              testId="sandbox-grouping-strategy-input"
              name="sandbox-grouping-strategy-input"
              label={t(I18nKey.SETTINGS$SANDBOX_GROUPING_STRATEGY)}
              items={Object.keys(SandboxGroupingStrategyOptions).map((key) => ({
                key,
                label: t(`SETTINGS$SANDBOX_GROUPING_${key}` as I18nKey),
              }))}
              selectedKey={
                selectedSandboxGroupingStrategy ||
                settings.sandbox_grouping_strategy ||
                DEFAULT_SETTINGS.sandbox_grouping_strategy
              }
              isClearable={false}
              onSelectionChange={handleSandboxGroupingStrategyChange}
              wrapperClassName="w-full max-w-[680px]"
            />
          )}

          {!settings?.v1_enabled && (
            <SettingsInput
              testId="max-budget-per-task-input"
              name="max-budget-per-task-input"
              type="number"
              label={t(I18nKey.SETTINGS$MAX_BUDGET_PER_CONVERSATION)}
              defaultValue={settings.max_budget_per_task?.toString() || ""}
              onChange={checkIfMaxBudgetPerTaskHasChanged}
              placeholder={t(I18nKey.SETTINGS$MAXIMUM_BUDGET_USD)}
              min={1}
              step={1}
              className="w-full max-w-[680px]"
            />
          )}

          <div className="border-t border-t-tertiary pt-6 mt-2">
            <h3 className="text-lg font-medium mb-2">
              {t(I18nKey.SETTINGS$GIT_SETTINGS)}
            </h3>
            <p className="text-xs mb-4">
              {t(I18nKey.SETTINGS$GIT_SETTINGS_DESCRIPTION)}
            </p>
            <div className="flex flex-col gap-6">
              <SettingsInput
                testId="git-user-name-input"
                name="git-user-name-input"
                type="text"
                label={t(I18nKey.SETTINGS$GIT_USERNAME)}
                defaultValue={settings.git_user_name || ""}
                onChange={checkIfGitUserNameHasChanged}
                placeholder="Username for git commits"
                className="w-full max-w-[680px]"
              />
              <SettingsInput
                testId="git-user-email-input"
                name="git-user-email-input"
                type="email"
                label={t(I18nKey.SETTINGS$GIT_EMAIL)}
                defaultValue={settings.git_user_email || ""}
                onChange={checkIfGitUserEmailHasChanged}
                placeholder="Email for git commits"
                className="w-full max-w-[680px]"
              />
            </div>
          </div>

          <div className="border-t border-t-tertiary pt-6 mt-2">
            <h3 className="text-lg font-medium mb-2">
              {t(I18nKey.SETTINGS$SKILLS_SETTINGS)}
            </h3>
            <p className="text-xs mb-4">
              {t(I18nKey.SETTINGS$SKILLS_SETTINGS_DESCRIPTION)}
            </p>
            <div className="flex flex-col gap-6">
              <div>
                <SettingsInput
                  testId="marketplace-path-input"
                  name="marketplace-path-input"
                  type="text"
                  label={t(I18nKey.SETTINGS$MARKETPLACE_PATH)}
                  defaultValue={settings.marketplace_path || ""}
                  onChange={checkIfMarketplacePathHasChanged}
                  className="w-full max-w-[680px]"
                />
                {marketplacePathError && (
                  <p className="text-xs text-red-500 mt-1">
                    {marketplacePathError}
                  </p>
                )}
              </div>
              <p className="text-xs text-gray-500">
                {t(I18nKey.SETTINGS$MARKETPLACE_PATH_DESCRIPTION)}
              </p>
            </div>
          </div>
        </div>
      )}

      <div className="flex gap-6 p-6 justify-end">
        <BrandButton
          testId="submit-button"
          variant="primary"
          type="submit"
          isDisabled={isPending || formIsClean || hasValidationErrors}
        >
          {!isPending && t("SETTINGS$SAVE_CHANGES")}
          {isPending && t("SETTINGS$SAVING")}
        </BrandButton>
      </div>
    </form>
  );
}

export default AppSettingsScreen;
