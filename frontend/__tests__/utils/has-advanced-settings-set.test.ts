import { describe, expect, it, test } from "vitest";
import { hasAdvancedSettingsSet } from "#/utils/has-advanced-settings-set";
import { DEFAULT_SETTINGS } from "#/services/settings";

describe("hasAdvancedSettingsSet", () => {
  it("should return false by default", () => {
    expect(hasAdvancedSettingsSet(DEFAULT_SETTINGS)).toBe(false);
  });

  it("should return false if an empty object", () => {
    expect(hasAdvancedSettingsSet({})).toBe(false);
  });

  describe("should be true if", () => {
    test("llm.base_url is set", () => {
      expect(
        hasAdvancedSettingsSet({
          ...DEFAULT_SETTINGS,
          agent_settings: {
            ...DEFAULT_SETTINGS.agent_settings,
            "llm.base_url": "test",
          },
        }),
      ).toBe(true);
    });

    test("agent is not default value", () => {
      expect(
        hasAdvancedSettingsSet({
          ...DEFAULT_SETTINGS,
          agent_settings: {
            ...DEFAULT_SETTINGS.agent_settings,
            agent: "test",
          },
        }),
      ).toBe(true);
    });

    test("condenser.enabled is disabled", () => {
      // Arrange
      const settings = {
        ...DEFAULT_SETTINGS,
        agent_settings: {
          ...DEFAULT_SETTINGS.agent_settings,
          "condenser.enabled": false,
        },
      };

      // Act
      const result = hasAdvancedSettingsSet(settings);

      // Assert
      expect(result).toBe(true);
    });

    test("condenser.max_size is customized above default", () => {
      // Arrange
      const settings = {
        ...DEFAULT_SETTINGS,
        agent_settings: {
          ...DEFAULT_SETTINGS.agent_settings,
          "condenser.max_size": 200,
        },
      };

      // Act
      const result = hasAdvancedSettingsSet(settings);

      // Assert
      expect(result).toBe(true);
    });

    test("condenser.max_size is customized below default", () => {
      // Arrange
      const settings = {
        ...DEFAULT_SETTINGS,
        agent_settings: {
          ...DEFAULT_SETTINGS.agent_settings,
          "condenser.max_size": 50,
        },
      };

      // Act
      const result = hasAdvancedSettingsSet(settings);

      // Assert
      expect(result).toBe(true);
    });

    test("search_api_key is set to non-empty value", () => {
      // Arrange
      const settings = {
        ...DEFAULT_SETTINGS,
        search_api_key: "test-api-key-123",
      };

      // Act
      const result = hasAdvancedSettingsSet(settings);

      // Assert
      expect(result).toBe(true);
    });

    test("search_api_key with whitespace is treated as set", () => {
      // Arrange
      const settings = {
        ...DEFAULT_SETTINGS,
        search_api_key: "  test-key  ",
      };

      // Act
      const result = hasAdvancedSettingsSet(settings);

      // Assert
      expect(result).toBe(true);
    });
  });
});
