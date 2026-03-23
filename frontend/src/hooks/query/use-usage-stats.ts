import { useQuery } from "@tanstack/react-query";
import { usageService } from "#/api/usage-service/usage-service.api";
import { useSelectedOrganizationId } from "#/context/use-selected-organization";

export const useUsageStats = () => {
  const { organizationId } = useSelectedOrganizationId();

  return useQuery({
    queryKey: ["usage-stats", organizationId],
    queryFn: () => usageService.getUsageStats({ orgId: organizationId! }),
    enabled: !!organizationId,
  });
};
