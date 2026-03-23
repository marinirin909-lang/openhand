export interface DailyConversationCount {
  date: string; // ISO date format YYYY-MM-DD
  count: number;
}

export interface UsageStats {
  total_conversations: number;
  merged_prs: number;
  average_cost: number;
  daily_conversations: DailyConversationCount[];
}
