import { useQuery } from "@tanstack/react-query";
import V1ConversationService from "#/api/conversation-service/v1-conversation-service.api";

export const useSearchConversations = (
  selectedRepository?: string,
  conversationTrigger?: string,
  limit: number = 100,
  cacheDisabled: boolean = false,
) =>
  useQuery({
    queryKey: [
      "conversations",
      "search",
      selectedRepository,
      conversationTrigger,
      limit,
    ],
    queryFn: async () => {
      const result = await V1ConversationService.searchConversations(
        limit,
        undefined, // pageId
        selectedRepository,
        conversationTrigger,
      );
      return result.results;
    },
    enabled: true, // Always enabled since parameters are optional
    staleTime: cacheDisabled ? 0 : 1000 * 60 * 5, // 5 minutes
    gcTime: cacheDisabled ? 0 : 1000 * 60 * 15, // 15 minutes
  });
