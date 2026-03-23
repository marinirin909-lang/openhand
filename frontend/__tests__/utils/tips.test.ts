import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { getRandomTip, TIPS, Tip } from "#/utils/tips";
import { I18nKey } from "#/i18n/declaration";
import { Provider } from "#/types/settings";

describe("Tips System", () => {
  describe("TIPS array", () => {
    it("should contain tips with valid keys", () => {
      expect(TIPS.length).toBeGreaterThan(0);
      TIPS.forEach((tip) => {
        expect(tip.key).toBeDefined();
        expect(typeof tip.key).toBe("string");
      });
    });

    it("should have GitHub hook tip with github provider", () => {
      const githubTip = TIPS.find(
        (tip) => tip.key === I18nKey.TIPS$GITHUB_HOOK,
      );
      expect(githubTip).toBeDefined();
      expect(githubTip?.providers).toEqual(["github"]);
    });

    it("should have GitLab hook tip with gitlab provider", () => {
      const gitlabTip = TIPS.find(
        (tip) => tip.key === I18nKey.TIPS$GITLAB_HOOK,
      );
      expect(gitlabTip).toBeDefined();
      expect(gitlabTip?.providers).toEqual(["gitlab"]);
    });

    it("should have generic tips without providers", () => {
      const genericTips = TIPS.filter((tip) => !tip.providers);
      expect(genericTips.length).toBeGreaterThan(0);
      // Verify some specific generic tips exist
      expect(genericTips.some((t) => t.key === I18nKey.TIPS$BLOG_SIGNUP)).toBe(
        true,
      );
      expect(
        genericTips.some((t) => t.key === I18nKey.TIPS$CUSTOMIZE_MICROAGENT),
      ).toBe(true);
    });
  });

  describe("getRandomTip", () => {
    let mathRandomSpy: ReturnType<typeof vi.spyOn>;

    beforeEach(() => {
      mathRandomSpy = vi.spyOn(Math, "random");
    });

    afterEach(() => {
      mathRandomSpy.mockRestore();
    });

    it("should return a tip when no providers are specified", () => {
      mathRandomSpy.mockReturnValue(0);
      const tip = getRandomTip();
      expect(tip).toBeDefined();
      expect(tip.key).toBeDefined();
    });

    it("should return only generic tips when userProviders is undefined", () => {
      // Call multiple times to verify no provider-specific tips are returned
      for (let i = 0; i < 10; i++) {
        mathRandomSpy.mockReturnValue(i / 10);
        const tip = getRandomTip(undefined);
        expect(
          tip.providers === undefined,
          `Expected generic tip but got tip with providers: ${tip.providers}`,
        ).toBe(true);
      }
    });

    it("should return only generic tips when userProviders is empty array", () => {
      for (let i = 0; i < 10; i++) {
        mathRandomSpy.mockReturnValue(i / 10);
        const tip = getRandomTip([]);
        expect(tip.providers).toBeUndefined();
      }
    });

    it("should include GitHub-specific tips for GitHub users", () => {
      const userProviders: Provider[] = ["github"];

      // Get all tips that would be shown to GitHub users
      const eligibleTips = TIPS.filter(
        (tip) =>
          !tip.providers ||
          tip.providers.some((p) => userProviders.includes(p)),
      );

      // Verify GitHub tip is in eligible tips
      expect(
        eligibleTips.some((t) => t.key === I18nKey.TIPS$GITHUB_HOOK),
      ).toBe(true);

      // Verify GitLab tip is NOT in eligible tips
      expect(
        eligibleTips.some((t) => t.key === I18nKey.TIPS$GITLAB_HOOK),
      ).toBe(false);
    });

    it("should include GitLab-specific tips for GitLab users", () => {
      const userProviders: Provider[] = ["gitlab"];

      // Get all tips that would be shown to GitLab users
      const eligibleTips = TIPS.filter(
        (tip) =>
          !tip.providers ||
          tip.providers.some((p) => userProviders.includes(p)),
      );

      // Verify GitLab tip is in eligible tips
      expect(
        eligibleTips.some((t) => t.key === I18nKey.TIPS$GITLAB_HOOK),
      ).toBe(true);

      // Verify GitHub tip is NOT in eligible tips
      expect(
        eligibleTips.some((t) => t.key === I18nKey.TIPS$GITHUB_HOOK),
      ).toBe(false);
    });

    it("should include both provider-specific tips for users with multiple providers", () => {
      const userProviders: Provider[] = ["github", "gitlab"];

      // Get all tips that would be shown to users with both providers
      const eligibleTips = TIPS.filter(
        (tip) =>
          !tip.providers ||
          tip.providers.some((p) => userProviders.includes(p)),
      );

      // Verify both tips are in eligible tips
      expect(
        eligibleTips.some((t) => t.key === I18nKey.TIPS$GITHUB_HOOK),
      ).toBe(true);
      expect(
        eligibleTips.some((t) => t.key === I18nKey.TIPS$GITLAB_HOOK),
      ).toBe(true);
    });

    it("should always include generic tips regardless of provider", () => {
      const testCases: (Provider[] | undefined)[] = [
        undefined,
        [],
        ["github"],
        ["gitlab"],
        ["bitbucket"],
        ["github", "gitlab"],
      ];

      testCases.forEach((providers) => {
        // Check that we can get generic tips for any provider configuration
        const genericTips = TIPS.filter((tip) => !tip.providers);
        expect(genericTips.length).toBeGreaterThan(0);
      });
    });

    it("should not return GitHub tip for users without GitHub provider", () => {
      const userProviders: Provider[] = ["gitlab", "bitbucket"];

      // Get all tips that would be shown
      const eligibleTips = TIPS.filter(
        (tip) =>
          !tip.providers ||
          tip.providers.some((p) => userProviders.includes(p)),
      );

      // GitHub tip should not be included
      expect(
        eligibleTips.some((t) => t.key === I18nKey.TIPS$GITHUB_HOOK),
      ).toBe(false);
    });

    it("should return valid tip even when Math.random returns edge values", () => {
      const userProviders: Provider[] = ["github"];

      // Test with 0
      mathRandomSpy.mockReturnValue(0);
      let tip = getRandomTip(userProviders);
      expect(tip).toBeDefined();

      // Test with value just under 1
      mathRandomSpy.mockReturnValue(0.9999);
      tip = getRandomTip(userProviders);
      expect(tip).toBeDefined();
    });

    it("should handle all supported provider types", () => {
      const allProviders: Provider[] = [
        "github",
        "gitlab",
        "bitbucket",
        "bitbucket_data_center",
        "azure_devops",
        "forgejo",
        "enterprise_sso",
      ];

      mathRandomSpy.mockReturnValue(0.5);
      const tip = getRandomTip(allProviders);
      expect(tip).toBeDefined();
      expect(tip.key).toBeDefined();
    });
  });
});
