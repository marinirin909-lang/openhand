import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import userEvent from "@testing-library/user-event";
import { EnterpriseBanner } from "#/components/features/auth/enterprise-banner";

const mockCapture = vi.fn();

vi.mock("posthog-js/react", () => ({
  usePostHog: () => ({
    capture: mockCapture,
  }),
}));

describe("EnterpriseBanner", () => {
  afterEach(() => {
    vi.clearAllMocks();
  });

  it("should render enterprise banner with title and description", () => {
    render(<EnterpriseBanner />);

    expect(screen.getByTestId("enterprise-banner")).toBeInTheDocument();
    expect(screen.getByText("ENTERPRISE$TITLE")).toBeInTheDocument();
    expect(screen.getByText("ENTERPRISE$DESCRIPTION")).toBeInTheDocument();
  });

  it("should render all enterprise features", () => {
    render(<EnterpriseBanner />);

    expect(
      screen.getByText("ENTERPRISE$FEATURE_ON_PREMISES"),
    ).toBeInTheDocument();
    expect(
      screen.getByText("ENTERPRISE$FEATURE_DATA_CONTROL"),
    ).toBeInTheDocument();
    expect(
      screen.getByText("ENTERPRISE$FEATURE_COMPLIANCE"),
    ).toBeInTheDocument();
    expect(screen.getByText("ENTERPRISE$FEATURE_SUPPORT")).toBeInTheDocument();
  });

  it("should render learn more link with correct href and target", () => {
    render(<EnterpriseBanner />);

    const learnMoreLink = screen.getByRole("link", {
      name: "ENTERPRISE$LEARN_MORE",
    });
    expect(learnMoreLink).toBeInTheDocument();
    expect(learnMoreLink).toHaveAttribute(
      "href",
      "https://openhands.dev/enterprise",
    );
    expect(learnMoreLink).toHaveAttribute("target", "_blank");
    expect(learnMoreLink).toHaveAttribute("rel", "noopener noreferrer");
  });

  it("should track posthog event when learn more link is clicked", async () => {
    const user = userEvent.setup();
    render(<EnterpriseBanner />);

    const learnMoreLink = screen.getByRole("link", {
      name: "ENTERPRISE$LEARN_MORE",
    });
    await user.click(learnMoreLink);

    expect(mockCapture).toHaveBeenCalledWith("saas_selfhosted_inquiry");
  });

  it("should have correct styling from Figma design", () => {
    render(<EnterpriseBanner />);

    const banner = screen.getByTestId("enterprise-banner");
    expect(banner).toHaveClass("w-full");
    // Check that the banner has the correct Figma styles
    const style = banner.getAttribute("style");
    expect(style).toContain("background");
    expect(style).toContain("box-shadow");
  });

  it("should render server icon", () => {
    render(<EnterpriseBanner />);

    // The banner should contain the SVG icon which has w-8 and h-8 classes
    const banner = screen.getByTestId("enterprise-banner");
    const icon = banner.querySelector("svg");
    expect(icon).toBeInTheDocument();
    expect(icon).toHaveClass("w-8", "h-8");
  });

  it("should have cursor-pointer class on learn more link", () => {
    render(<EnterpriseBanner />);

    const learnMoreLink = screen.getByRole("link", {
      name: "ENTERPRISE$LEARN_MORE",
    });
    expect(learnMoreLink).toHaveClass("hover:cursor-pointer");
  });
});
