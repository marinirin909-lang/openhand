import { Outlet } from "react-router";

export default function OnboardingLayout() {
  return (
    <div
      data-testid="onboarding-layout"
      className="min-h-screen bg-black flex flex-col items-center justify-center"
      style={{ backgroundColor: "#000", minHeight: "100vh" }}
    >
      <Outlet />
    </div>
  );
}
