import { I18nKey } from "#/i18n/declaration";
import { Provider } from "#/types/settings";

export interface Tip {
  key: I18nKey;
  link?: string;
  providers?: Provider[]; // Optional: only show tip if user has these providers
}

export const TIPS: Tip[] = [
  // Generic tips (shown to everyone)
  {
    key: I18nKey.TIPS$CUSTOMIZE_MICROAGENT,
    link: "https://docs.all-hands.dev/usage/prompting/microagents-repo",
  },
  {
    key: I18nKey.TIPS$SETUP_SCRIPT,
    link: "https://docs.all-hands.dev/usage/prompting/repository#setup-script",
  },
  { key: I18nKey.TIPS$VSCODE_INSTANCE },
  { key: I18nKey.TIPS$SAVE_WORK },
  {
    key: I18nKey.TIPS$SPECIFY_FILES,
    link: "https://docs.all-hands.dev/usage/prompting/prompting-best-practices",
  },
  {
    key: I18nKey.TIPS$HEADLESS_MODE,
    link: "https://docs.all-hands.dev/usage/how-to/headless-mode",
  },
  {
    key: I18nKey.TIPS$CLI_MODE,
    link: "https://docs.all-hands.dev/usage/how-to/cli-mode",
  },
  {
    key: I18nKey.TIPS$BLOG_SIGNUP,
    link: "https://www.all-hands.dev/blog",
  },
  {
    key: I18nKey.TIPS$API_USAGE,
    link: "https://docs.all-hands.dev/api-reference/health-check",
  },
  // Provider-specific tips
  {
    key: I18nKey.TIPS$GITHUB_HOOK,
    link: "https://docs.all-hands.dev/usage/cloud/github-installation#working-on-github-issues-and-pull-requests-using-openhands",
    providers: ["github"],
  },
  {
    key: I18nKey.TIPS$GITLAB_HOOK,
    link: "https://docs.all-hands.dev/usage/cloud/gitlab-installation",
    providers: ["gitlab"],
  },
];

/**
 * Returns a random tip filtered by user's connected providers.
 * Tips without a providers field are shown to everyone.
 * Tips with a providers field are only shown if the user has at least one of those providers.
 *
 * @param userProviders - Optional array of providers the user has connected
 * @returns A random tip from the filtered list
 */
export function getRandomTip(userProviders?: Provider[]): Tip {
  const filteredTips =
    userProviders && userProviders.length > 0
      ? TIPS.filter(
          (tip) =>
            !tip.providers ||
            tip.providers.some((p) => userProviders.includes(p)),
        )
      : TIPS.filter((tip) => !tip.providers); // If no providers, only show generic tips

  // Fallback to generic tips if filter results in empty array
  const tipsToChooseFrom =
    filteredTips.length > 0
      ? filteredTips
      : TIPS.filter((tip) => !tip.providers);

  const randomIndex = Math.floor(Math.random() * tipsToChooseFrom.length);
  return tipsToChooseFrom[randomIndex];
}
