import { openHands } from "../open-hands-axios";
import { UsageStats } from "./usage.types";

export const usageService = {
  getUsageStats: async ({ orgId }: { orgId: string }): Promise<UsageStats> => {
    const { data } = await openHands.get<UsageStats>(
      `/api/organizations/${orgId}/usage`,
    );
    return data;
  },
};
