import React from "react";
import { AxiosError } from "axios";
import { useTranslation } from "react-i18next";
import { BrandButton } from "#/components/features/settings/brand-button";
import { LlmSettingsInputsSkeleton } from "#/components/features/settings/llm-settings/llm-settings-inputs-skeleton";
import { useSaveSettings } from "#/hooks/mutation/use-save-settings";
import { usePermission } from "#/hooks/organizations/use-permissions";
import { useConfig } from "#/hooks/query/use-config";
import { useMe } from "#/hooks/query/use-me";
import { useSettings } from "#/hooks/query/use-settings";
import { I18nKey } from "#/i18n/declaration";
import { Typography } from "#/ui/typography";
import {
  displayErrorToast,
  displaySuccessToast,
} from "#/utils/custom-toast-handlers";
import { retrieveAxiosErrorMessage } from "#/utils/retrieve-axios-error-message";
import {
  buildInitialSettingsFormValues,
  buildSdkSettingsPayload,
  getVisibleSettingsSections,
  hasAdvancedSettings,
  hasMinorSettings,
  inferInitialView,
  SettingsDirtyState,
  SettingsFormValues,
  type SettingsView,
} from "#/utils/sdk-settings-schema";
import { SchemaField } from "./schema-field";

// ---------------------------------------------------------------------------
// View tier toggle
// ---------------------------------------------------------------------------
function ViewToggle({
  view,
  setView,
  showAdvanced,
  showAll,
}: {
  view: SettingsView;
  setView: (v: SettingsView) => void;
  showAdvanced: boolean;
  showAll: boolean;
}) {
  const { t } = useTranslation();

  if (!showAdvanced && !showAll) return null;

  return (
    <div className="flex items-center gap-2 mb-6">
      <BrandButton
        testId="sdk-section-basic-toggle"
        variant={view === "basic" ? "primary" : "secondary"}
        type="button"
        onClick={() => setView("basic")}
      >
        {t(I18nKey.SETTINGS$BASIC)}
      </BrandButton>
      {showAdvanced ? (
        <BrandButton
          testId="sdk-section-advanced-toggle"
          variant={view === "advanced" ? "primary" : "secondary"}
          type="button"
          onClick={() => setView("advanced")}
        >
          {t(I18nKey.SETTINGS$ADVANCED)}
        </BrandButton>
      ) : null}
      {showAll ? (
        <BrandButton
          testId="sdk-section-all-toggle"
          variant={view === "all" ? "primary" : "secondary"}
          type="button"
          onClick={() => setView("all")}
        >
          {t(I18nKey.SETTINGS$ALL)}
        </BrandButton>
      ) : null}
    </div>
  );
}

export interface SdkSectionHeaderProps {
  values: SettingsFormValues;
  isDisabled: boolean;
  onChange: (key: string, value: string | boolean) => void;
}

/**
 * A generic SDK-schema–driven settings page that renders fields
 * from one or more schema sections.
 *
 * @param sectionKeys - which schema section(s) this page owns (e.g. ["condenser"])
 * @param excludeKeys - field keys to skip (rendered elsewhere by the caller)
 * @param header      - optional render prop receiving shared state to render above fields
 * @param testId      - data-testid for the page wrapper
 */
export function SdkSectionPage({
  sectionKeys,
  excludeKeys = new Set<string>(),
  header,
  testId = "sdk-section-settings-screen",
}: {
  sectionKeys: string[];
  excludeKeys?: Set<string>;
  header?: (props: SdkSectionHeaderProps) => React.ReactNode;
  testId?: string;
}) {
  const { t } = useTranslation();
  const { mutate: saveSettings, isPending } = useSaveSettings();
  const { data: settings, isLoading, isFetching } = useSettings();
  const { data: config } = useConfig();
  const { data: me } = useMe();
  const { hasPermission } = usePermission(me?.role ?? "member");

  const isOssMode = config?.app_mode === "oss";
  const isReadOnly = isOssMode ? false : !hasPermission("edit_llm_settings");

  const [view, setView] = React.useState<SettingsView>("basic");
  const [values, setValues] = React.useState<SettingsFormValues>({});
  const [dirty, setDirty] = React.useState<SettingsDirtyState>({});

  const fullSchema = settings?.agent_settings_schema ?? null;

  // Build a filtered schema containing only the requested sections
  const filteredSchema = React.useMemo(() => {
    if (!fullSchema) return null;
    const sectionSet = new Set(sectionKeys);
    return {
      ...fullSchema,
      sections: fullSchema.sections.filter((s) => sectionSet.has(s.key)),
    };
  }, [fullSchema, sectionKeys]);

  const showAdvanced = hasAdvancedSettings(filteredSchema);
  const showAll = hasMinorSettings(filteredSchema);

  React.useEffect(() => {
    if (!settings?.agent_settings_schema) return;
    setValues(buildInitialSettingsFormValues(settings));
    setDirty({});
    setView(inferInitialView(settings, filteredSchema));
  }, [settings, filteredSchema]);

  const visibleSections = React.useMemo(() => {
    if (!filteredSchema) return [];
    return getVisibleSettingsSections(
      filteredSchema,
      values,
      view,
      excludeKeys,
    );
  }, [filteredSchema, values, view, excludeKeys]);

  const handleFieldChange = React.useCallback(
    (fieldKey: string, nextValue: string | boolean) => {
      setValues((prev) => ({ ...prev, [fieldKey]: nextValue }));
      setDirty((prev) => ({ ...prev, [fieldKey]: true }));
    },
    [],
  );

  const handleError = React.useCallback(
    (error: AxiosError) => {
      const msg = retrieveAxiosErrorMessage(error);
      displayErrorToast(msg || t(I18nKey.ERROR$GENERIC));
    },
    [t],
  );

  const handleSave = () => {
    if (!fullSchema || isReadOnly) return;

    let payload: ReturnType<typeof buildSdkSettingsPayload>;
    try {
      payload = buildSdkSettingsPayload(fullSchema, values, dirty);
    } catch (error) {
      displayErrorToast(
        error instanceof Error ? error.message : t(I18nKey.ERROR$GENERIC),
      );
      return;
    }

    if (Object.keys(payload).length === 0) return;

    saveSettings(payload, {
      onError: handleError,
      onSuccess: () => {
        displaySuccessToast(t(I18nKey.SETTINGS$SAVED_WARNING));
        setDirty({});
      },
    });
  };

  if (isLoading || isFetching) return <LlmSettingsInputsSkeleton />;

  if (!filteredSchema || filteredSchema.sections.length === 0) {
    return (
      <Typography.Paragraph className="text-tertiary-alt">
        {t(I18nKey.SETTINGS$SDK_SCHEMA_UNAVAILABLE)}
      </Typography.Paragraph>
    );
  }

  if (Object.keys(values).length === 0) return <LlmSettingsInputsSkeleton />;

  return (
    <div data-testid={testId} className="h-full relative">
      <ViewToggle
        view={view}
        setView={setView}
        showAdvanced={showAdvanced}
        showAll={showAll}
      />

      <div className="flex flex-col gap-8 pb-20">
        {header?.({
          values,
          isDisabled: isReadOnly,
          onChange: handleFieldChange,
        })}

        {visibleSections.map((section) => (
          <section key={section.key} className="flex flex-col gap-4">
            <div className="grid gap-4 xl:grid-cols-2">
              {section.fields.map((field) => (
                <SchemaField
                  key={field.key}
                  field={field}
                  value={values[field.key]}
                  isDisabled={isReadOnly}
                  onChange={(nextValue) =>
                    handleFieldChange(field.key, nextValue)
                  }
                />
              ))}
            </div>
          </section>
        ))}
      </div>

      {!isReadOnly ? (
        <div className="sticky bottom-0 bg-base py-4">
          <BrandButton
            testId="save-button"
            type="button"
            variant="primary"
            isDisabled={isPending || Object.keys(dirty).length === 0}
            onClick={handleSave}
          >
            {isPending
              ? t(I18nKey.SETTINGS$SAVING)
              : t(I18nKey.SETTINGS$SAVE_CHANGES)}
          </BrandButton>
        </div>
      ) : null}
    </div>
  );
}
