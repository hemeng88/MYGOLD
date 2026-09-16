import { useEffect, useState } from "react";
import { Badge, Button, Group, Paper, Select, Skeleton, Stack, Text } from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { IconRefresh } from "@tabler/icons-react";
import { api } from "./api";
import type { FundRank } from "./types";

function fmt(n: number | null | undefined, digits = 2) {
  if (n === null || n === undefined || Number.isNaN(n)) return "—";
  return n.toFixed(digits);
}

function signed(value: number | null | undefined, digits = 2) {
  if (value === null || value === undefined) return "—";
  return `${value > 0 ? "+" : ""}${value.toFixed(digits)}`;
}

function tone(value: number | null | undefined) {
  if (value === null || value === undefined || value === 0) return "gray";
  return value > 0 ? "red" : "teal";
}

export function FundRankPanel() {
  const [data, setData] = useState<FundRank | null>(null);
  const [period, setPeriod] = useState<string>("jnzf");
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const load = async (nextPeriod: string) => {
    setData(await api.fundRankings(nextPeriod));
    setLoading(false);
  };

  useEffect(() => {
    load(period).catch((err) => {
      setLoading(false);
      notifications.show({
        color: "red",
        title: "榜单读不到",
        message: err instanceof Error ? err.message : "稍后重试",
      });
    });
  }, [period]);

  const onRefresh = async () => {
    setRefreshing(true);
    try {
      const result = await api.refreshFundRankings();
      await load(period);
      notifications.show({
        color: result.ok ? "teal" : "yellow",
        title: result.ok ? "榜单已更新" : "只更新了一部分",
        message: result.message,
      });
    } catch (err) {
      notifications.show({
        color: "red",
        title: "刷新失败",
        message: err instanceof Error ? err.message : "稍后重试",
      });
    } finally {
      setRefreshing(false);
    }
  };

  const total = data?.funds.length || 0;

  return (
    <Paper className="glass" p="md">
      <Group justify="space-between" mb="sm" wrap="wrap" gap="sm" align="flex-end">
        <div style={{ minWidth: 0, flex: "1 1 140px" }}>
          <Text fw={600}>涨幅榜看方向</Text>
          <Text size="xs" c="dimmed" mt={4}>
            把榜首基金的重仓穿透汇总，被反复重仓的才是主线
          </Text>
        </div>
        <Group gap="xs" wrap="nowrap">
          <Select
            size="sm"
            style={{ width: 110 }}
            data={(data?.periods || []).map((item) => ({ value: item.key, label: item.label }))}
            value={period}
            onChange={(value) => value && setPeriod(value)}
            allowDeselect={false}
            comboboxProps={{ withinPortal: true }}
            aria-label="选择周期"
          />
          <Button
            variant="light"
            color="gold"
            size="sm"
            loading={refreshing}
            onClick={onRefresh}
            leftSection={<IconRefresh size={14} />}
          >
            刷新
          </Button>
        </Group>
      </Group>

      {loading && !data ? (
        <Stack gap="xs">
          {Array.from({ length: 4 }).map((_, index) => (
            <Skeleton key={index} height={44} radius="lg" />
          ))}
        </Stack>
      ) : (
        <Stack gap="sm">
          {data?.message ? (
            <Text size="xs" c="dimmed">
              {data.message}
            </Text>
          ) : null}

          {data?.hot_stocks?.length ? (
            <div>
              <Text size="xs" fw={600} mb={6}>
                {data.period_label} 领涨方向 · 榜单前 {total} 只基金的共同重仓
              </Text>
              <Stack gap={6}>
                {data.hot_stocks.map((stock) => (
                  <Paper key={stock.code} className="stat-tile" p="xs">
                    <Group justify="space-between" wrap="nowrap" gap="xs">
                      <div style={{ minWidth: 0 }}>
                        <Text size="sm" fw={600} truncate>
                          {stock.name || stock.code}
                        </Text>
                        <Text size="xs" c="dimmed">
                          {stock.code}
                        </Text>
                      </div>
                      <div style={{ textAlign: "right", flexShrink: 0 }}>
                        <Badge size="sm" variant="light" color={stock.fund_count >= total ? "gold" : "gray"}>
                          {stock.fund_count}/{total} 只重仓
                        </Badge>
                        <Text size="xs" c="dimmed" mt={2}>
                          合计权重 {fmt(stock.weight_sum, 1)}%
                        </Text>
                      </div>
                    </Group>
                  </Paper>
                ))}
              </Stack>
            </div>
          ) : null}

          {data?.top_holders?.length ? (
            <div>
              <Text size="xs" fw={600} mb={2}>
                全市场押注这条主线最重的基金
              </Text>
              <Text size="xs" c="dimmed" mb={8}>
                主线仓位 = 该基金净值里压在这条主线
                {data.theme_stock_n > 0 ? ` ${data.theme_stock_n} ` : ""}
                只代表股上的比例。候选来自全市场按股票反查
                {data.holder_report_date ? `（${data.holder_report_date} 季报）` : ""}，不局限于上榜基金
              </Text>
              <Stack gap={6}>
                {data.top_holders.map((holder) => (
                  <Paper key={holder.code} className="stat-tile" p="xs">
                    <Group justify="space-between" wrap="nowrap" gap="xs">
                      <div style={{ minWidth: 0 }}>
                        <Group gap={6} wrap="nowrap">
                          <Badge size="xs" variant="light" color="gray">
                            {holder.rank}
                          </Badge>
                          <Text size="sm" fw={600} truncate>
                            {holder.name || holder.code}
                          </Text>
                        </Group>
                        <Text size="xs" c="dimmed" mt={2}>
                          {[
                            holder.code,
                            holder.hit_count > 0 && holder.theme_stock_count > 0
                              ? `命中 ${holder.hit_count}/${holder.theme_stock_count} 只`
                              : null,
                            holder.fund_type || null,
                            holder.alt_codes.length ? `同门份额 ${holder.alt_codes.join("、")}` : null,
                          ]
                            .filter(Boolean)
                            .join(" · ")}
                        </Text>
                      </div>
                      {holder.theme_pct > 0 ? (
                        <div style={{ textAlign: "right", flexShrink: 0 }}>
                          <Text fw={700} size="sm" c="gold">
                            {fmt(holder.theme_pct, 1)}%
                          </Text>
                          <Text size="xs" c="dimmed">
                            主线仓位
                          </Text>
                        </div>
                      ) : null}
                    </Group>
                  </Paper>
                ))}
              </Stack>
            </div>
          ) : null}

          {data?.funds?.length ? (
            <div>
              <Text size="xs" fw={600} mb={6}>
                {data.period_label} 涨幅榜
              </Text>
              <Stack gap={6}>
                {data.funds.map((fund) => (
                  <Paper key={`${fund.code}-${fund.rank}`} className="stat-tile" p="xs">
                    <Group justify="space-between" wrap="nowrap" gap="xs">
                      <div style={{ minWidth: 0 }}>
                        <Group gap={6} wrap="nowrap">
                          <Badge size="xs" variant="light" color="gray">
                            {fund.rank}
                          </Badge>
                          <Text size="sm" fw={600} truncate>
                            {fund.name}
                          </Text>
                        </Group>
                        <Text size="xs" c="dimmed" mt={2}>
                          {fund.code}
                          {fund.nav != null ? ` · 净值${fmt(fund.nav, 4)}` : ""}
                          {fund.nav_date ? ` · ${fund.nav_date}` : ""}
                        </Text>
                      </div>
                      <Text fw={700} size="sm" c={tone(fund.return_pct)} style={{ flexShrink: 0 }}>
                        {signed(fund.return_pct)}%
                      </Text>
                    </Group>
                  </Paper>
                ))}
              </Stack>
            </div>
          ) : null}

          <Text size="xs" c="dimmed">
            榜单按 T-1 净值排，每晚更新一次。涨幅榜是后视镜，照着它买就是追高。
          </Text>
        </Stack>
      )}
    </Paper>
  );
}
