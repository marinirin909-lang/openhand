import { useTranslation } from "react-i18next";
import { usePostHog } from "posthog-js/react";
import { I18nKey } from "#/i18n/declaration";
import { Typography } from "#/ui/typography";
import ServerIcon from "#/icons/server.svg?react";

const ENTERPRISE_URL = "https://openhands.dev/enterprise";

export function EnterpriseBanner() {
  const { t } = useTranslation();
  const posthog = usePostHog();

  const handleLearnMoreClick = () => {
    posthog.capture("saas_selfhosted_inquiry");
  };

  const features = [
    t(I18nKey.ENTERPRISE$FEATURE_ON_PREMISES),
    t(I18nKey.ENTERPRISE$FEATURE_DATA_CONTROL),
    t(I18nKey.ENTERPRISE$FEATURE_COMPLIANCE),
    t(I18nKey.ENTERPRISE$FEATURE_SUPPORT),
  ];

  return (
    <div
      className="flex flex-col gap-4 p-6 rounded-xl w-full"
      style={{
        background: "#0A0A0A80",
        borderTop: "1px solid #24242499",
        boxShadow: "0px 4px 6px -4px #0000001A, 0px 10px 15px -3px #0000001A",
      }}
      data-testid="enterprise-banner"
    >
      <ServerIcon className="w-8 h-8 text-neutral-400" />

      <Typography.H2 className="text-lg">
        {t(I18nKey.ENTERPRISE$TITLE)}
      </Typography.H2>

      <Typography.Text className="text-sm text-neutral-400">
        {t(I18nKey.ENTERPRISE$DESCRIPTION)}
      </Typography.Text>

      <ul className="flex flex-col gap-2 text-sm text-neutral-400">
        {features.map((feature) => (
          <li key={feature} className="flex items-start gap-2">
            <Typography.Text className="text-neutral-400">•</Typography.Text>
            <Typography.Text className="text-neutral-400">
              {feature}
            </Typography.Text>
          </li>
        ))}
      </ul>

      <a
        href={ENTERPRISE_URL}
        target="_blank"
        rel="noopener noreferrer"
        onClick={handleLearnMoreClick}
        className="mt-2 px-4 py-2 bg-tertiary border border-neutral-600 rounded text-sm text-white hover:bg-neutral-500 hover:cursor-pointer transition-colors w-fit"
      >
        {t(I18nKey.ENTERPRISE$LEARN_MORE)}
      </a>
    </div>
  );
}
