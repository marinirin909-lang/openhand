import React from "react";
import { useTranslation } from "react-i18next";
import { createPermissionGuard } from "#/utils/org/permission-guard";
import { useUsageStats } from "#/hooks/query/use-usage-stats";
import { Typography } from "#/ui/typography";
import { I18nKey } from "#/i18n/declaration";
import { DailyConversationCount } from "#/api/usage-service/usage.types";

export const clientLoader = createPermissionGuard("view_billing");

export const handle = { hideTitle: true };

interface StatCardProps {
  title: string;
  value: string | number;
  isLoading?: boolean;
}

function StatCard({ title, value, isLoading }: StatCardProps) {
  return (
    <div className="rounded-xl border border-org-border bg-org-background p-6 flex flex-col gap-2">
      <span className="text-xs text-tertiary-alt font-medium">{title}</span>
      {isLoading ? (
        <div className="h-8 w-24 bg-tertiary animate-pulse rounded" />
      ) : (
        <span className="text-2xl font-bold text-white">{value}</span>
      )}
    </div>
  );
}

interface ConversationChartProps {
  data: DailyConversationCount[];
  isLoading?: boolean;
}

function ConversationChart({ data, isLoading }: ConversationChartProps) {
  const { t } = useTranslation();

  if (isLoading) {
    return (
      <div className="rounded-xl border border-org-border bg-org-background p-6">
        <div className="h-6 w-48 bg-tertiary animate-pulse rounded mb-4" />
        <div className="h-64 bg-tertiary animate-pulse rounded" />
      </div>
    );
  }

  // Group data by week for cleaner display (show last 13 weeks)
  const weeklyData: { label: string; count: number }[] = [];
  for (let i = 0; i < data.length; i += 7) {
    const weekSlice = data.slice(i, i + 7);
    const weekTotal = weekSlice.reduce((sum, d) => sum + d.count, 0);
    const startDate = weekSlice[0]?.date;
    if (startDate) {
      const date = new Date(startDate);
      const label = date.toLocaleDateString(undefined, {
        month: "short",
        day: "numeric",
      });
      weeklyData.push({ label, count: weekTotal });
    }
  }

  // Calculate weekly max for scaling
  const weeklyMax = Math.max(...weeklyData.map((d) => d.count), 1);

  return (
    <div className="rounded-xl border border-org-border bg-org-background p-6">
      <h3 className="text-sm font-medium text-white mb-4">
        {t(I18nKey.USAGE$CONVERSATIONS_OVER_TIME)}
      </h3>
      <div className="flex flex-col gap-2">
        {/* Y-axis labels and bars */}
        <div className="flex items-end gap-1 h-48">
          {weeklyData.map((week, index) => {
            const height = weeklyMax > 0 ? (week.count / weeklyMax) * 100 : 0;
            return (
              <div
                key={index}
                className="flex-1 flex flex-col items-center justify-end h-full"
              >
                <div
                  className="w-full bg-primary rounded-t transition-all duration-300 min-h-[2px]"
                  style={{ height: `${Math.max(height, 2)}%` }}
                  title={`${week.label}: ${week.count} conversations`}
                />
              </div>
            );
          })}
        </div>
        {/* X-axis labels */}
        <div className="flex gap-1 text-[10px] text-tertiary-alt overflow-hidden">
          {weeklyData.map((week, index) => (
            <div key={index} className="flex-1 text-center truncate">
              {index % 2 === 0 ? week.label : ""}
            </div>
          ))}
        </div>
      </div>
      {/* Summary stats */}
      <div className="flex items-center justify-between mt-4 pt-4 border-t border-org-divider text-xs text-tertiary-alt">
        <span>
          {t(I18nKey.USAGE$TOTAL_IN_PERIOD)}:{" "}
          {data.reduce((sum, d) => sum + d.count, 0)}
        </span>
        <span>
          {t(I18nKey.USAGE$DAILY_AVERAGE)}:{" "}
          {(
            data.reduce((sum, d) => sum + d.count, 0) / Math.max(data.length, 1)
          ).toFixed(1)}
        </span>
      </div>
    </div>
  );
}

function UsageSettings() {
  const { t } = useTranslation();
  const { data: usageStats, isLoading, error } = useUsageStats();

  return (
    <div data-testid="usage-settings" className="flex flex-col gap-6 h-full">
      <div className="flex items-center justify-between">
        <Typography.H2>{t(I18nKey.USAGE$TITLE)}</Typography.H2>
      </div>

      {error && (
        <div className="rounded-xl border border-red-500/30 bg-red-500/10 p-4 text-red-400">
          {t(I18nKey.USAGE$ERROR_LOADING)}
        </div>
      )}

      {/* Stats Grid */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <StatCard
          title={t(I18nKey.USAGE$TOTAL_CONVERSATIONS)}
          value={usageStats?.total_conversations ?? 0}
          isLoading={isLoading}
        />
        <StatCard
          title={t(I18nKey.USAGE$MERGED_PRS)}
          value={usageStats?.merged_prs ?? 0}
          isLoading={isLoading}
        />
        <StatCard
          title={t(I18nKey.USAGE$AVERAGE_COST)}
          value={
            usageStats ? `$${usageStats.average_cost.toFixed(2)}` : "$0.00"
          }
          isLoading={isLoading}
        />
      </div>

      {/* Conversations Chart */}
      <ConversationChart
        data={usageStats?.daily_conversations ?? []}
        isLoading={isLoading}
      />
    </div>
  );
}

export default UsageSettings;
