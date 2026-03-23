import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router";
import { Card } from "#/ui/card";
import { CardTitle } from "#/ui/card-title";
import { Typography } from "#/ui/typography";
import { I18nKey } from "#/i18n/declaration";
import { cn } from "#/utils/utils";
import StackedIcon from "#/icons/stacked.svg?react";
import { useTracking } from "#/hooks/use-tracking";

export function LoginCTA() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { trackSaasSelfhostedInquiry } = useTracking();

  const handleLearnMoreClick = () => {
    trackSaasSelfhostedInquiry({ location: "login_page" });
    navigate("/onboarding/information-request");
  };

  return (
    <Card
      testId="login-cta"
      theme="dark"
      className={cn("w-full max-w-80 h-auto flex-col", "cta-card-gradient")}
    >
      <div className={cn("flex flex-col gap-[11px] p-6")}>
        <div className={cn("size-10")}>
          <StackedIcon width={40} height={40} />
        </div>

        <CardTitle>{t(I18nKey.CTA$ENTERPRISE)}</CardTitle>

        <Typography.Text className="text-[#8C8C8C] font-inter font-normal text-sm leading-5">
          {t(I18nKey.CTA$ENTERPRISE_DEPLOY)}
        </Typography.Text>

        <ul
          className={cn(
            "text-[#8C8C8C] font-inter font-normal text-sm leading-5 list-disc list-inside flex flex-col gap-1",
          )}
        >
          <li>{t(I18nKey.CTA$FEATURE_ON_PREMISES)}</li>
          <li>{t(I18nKey.CTA$FEATURE_DATA_CONTROL)}</li>
          <li>{t(I18nKey.CTA$FEATURE_COMPLIANCE)}</li>
          <li>{t(I18nKey.CTA$FEATURE_SUPPORT)}</li>
        </ul>

        <div className={cn("h-10 flex justify-start")}>
          <button
            type="button"
            onClick={handleLearnMoreClick}
            className={cn(
              "inline-flex items-center justify-center",
              "h-10 px-4 rounded",
              "bg-[#050505] border border-[#242424]",
              "text-white hover:bg-[#0a0a0a]",
              "font-semibold text-sm",
            )}
          >
            {t(I18nKey.CTA$LEARN_MORE)}
          </button>
        </div>
      </div>
    </Card>
  );
}
