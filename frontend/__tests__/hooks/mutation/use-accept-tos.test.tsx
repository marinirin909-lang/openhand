import { renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React from "react";
import { useAcceptTos } from "#/hooks/mutation/use-accept-tos";

vi.mock("react-router", () => ({
  useNavigate: () => vi.fn(),
}));

const mockCapture = vi.fn();
vi.mock("posthog-js/react", () => ({
  usePostHog: vi.fn(() => ({
    identify: vi.fn(),
    capture: mockCapture,
  })),
}));

vi.mock("#/api/open-hands-axios", () => ({
  openHands: {
    post: vi.fn().mockResolvedValue({ data: { redirect_url: "/dashboard" } }),
  },
}));

vi.mock("#/utils/handle-capture-consent", () => ({
  handleCaptureConsent: vi.fn(),
}));

const createWrapper = () =>
  ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider
      client={
        new QueryClient({
          defaultOptions: { mutations: { retry: false } },
        })
      }
    >
      {children}
    </QueryClientProvider>
  );

describe("useAcceptTos", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    sessionStorage.clear();
    vi.stubGlobal("location", { href: "" });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("sets sessionStorage 'oh_signup_pending' with ISO timestamp on TOS acceptance", async () => {
    const { result } = renderHook(() => useAcceptTos(), {
      wrapper: createWrapper(),
    });

    result.current.mutate({ redirectUrl: "/dashboard" });

    await waitFor(() => {
      expect(result.current.isSuccess).toBe(true);
    });

    const stored = sessionStorage.getItem("oh_signup_pending");
    expect(stored).not.toBeNull();
    // Should be a valid ISO 8601 timestamp
    expect(new Date(stored!).toISOString()).toBe(stored);
  });

  it("does NOT fire posthog 'user_signup_completed' capture during TOS acceptance", async () => {
    const { result } = renderHook(() => useAcceptTos(), {
      wrapper: createWrapper(),
    });

    result.current.mutate({ redirectUrl: "/dashboard" });

    await waitFor(() => {
      expect(result.current.isSuccess).toBe(true);
    });

    expect(mockCapture).not.toHaveBeenCalledWith(
      "user_signup_completed",
      expect.anything(),
    );
  });
});
