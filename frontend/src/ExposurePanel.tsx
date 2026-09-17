import { useEffect, useState } from "react";
import { Badge, Group, Paper, Progress, SimpleGrid, Skeleton, Stack, Text } from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { api } from "./api";
import type { Exposure, ExposureItem } from "./types";

function fmt(n: number | null | undefined, digits = 2) {
  if (n === null || n === undefined || Number.isNaN(n)) return "—";
  return n.toFixed(digits);
}

function money(value: number | null | undefined) {
  if (value === null || value === undefined) return "—";
  return `${value > 0 ? "+" : ""}${value.toFixed(2)}`;
}

function tone(value: number | null | undefined) {
  if (value === null || value === undefined || value === 0) return "gray";
  return value > 0 ? "red" : "teal";
}

export function ExposurePanel() {
  const [data, setData] = useState<Exposure | null>(null);
  const [loading, setLoading] = useState(true);
  const [opened, setOpened] = useState<string | null>(null);

  const load = async () => {
    setData(await api.exposure());
    setLoading(false);
  };

  useEffect(() => {
    load().catch((err) => {
      setLoading(false);
      notifications.show({
        color: "red",
        title: "穿透读不到",
        message: err instanceof Error ? err.message : "稍后重试",
      });
    });
    const timer = window.setInterval(() => {
      load().catch(() => undefined);
    }, 20000);
    return () => window.clearInterval(timer);
  }, []);

  return (
    <Paper className="glass" p="md">
      <Group justify="space-between" mb="sm" wrap="wrap" gap="sm" align="flex-end">
        <div style={{ minWidth: 0, flex: "1 1 160px" }}>
          <Text fw={600}>穿透到个股</Text>
          <Text size="xs" c="dimmed" mt={4}>
            {data?.session || "读取时段中"} · 份额 × 净值 × 公示仓位，同一只股票跨基金合并
          </Text>
        </div>
      </Group>

      {loading && !data ? (
        <Stack gap="xs">
          {Array.from({ length: 4 }).map((_, index) => (
            <Skeleton key={index} height={52} radius="lg" />
          ))}
        </Stack>
      ) : !data?.ready ? (
        <Text size="sm" c="dimmed" py="sm" ta="center">
          {data?.message || "填了份额的基金才能穿透"}
        </Text>
      ) : (
        <Stack gap="sm">
          <SimpleGrid cols={{ base: 2, sm: 4 }} spacing="xs">
            <Paper className="stat-tile" p="xs">
              <Text size="xs" c="dimmed">
                基金总市值
              </Text>
              <Text fw={600} size="sm">
                {fmt(data.total_value, 0)} 元
              </Text>
            </Paper>
            <Paper className="stat-tile" p="xs">
              <Text size="xs" c="dimmed">
                能看到的部分
              </Text>
              <Text fw={600} size="sm">
                {fmt(data.disclosed_value, 0)} 元
              </Text>
            </Paper>
            <Paper className="stat-tile" p="xs">
              <Text size="xs" c="dimmed">
                穿透到 {data.stock_count} 只股票
              </Text>
              <Text fw={700} size="sm" c={tone(data.today_pnl)}>
                今日 {money(data.today_pnl)}
              </Text>
            </Paper>
            <Paper className="stat-tile" p="xs">
              <Text size="xs" c="dimmed">
                覆盖率
              </Text>
              <Text fw={600} size="sm">
                {fmt(data.coverage_pct, 1)}%
              </Text>
            </Paper>
          </SimpleGrid>

          <div>
            <Progress value={data.coverage_pct ?? 0} color="gold" size="sm" radius="xl" />
            <Text size="xs" c="dimmed" mt={4}>
              季报只公示前十大重仓，剩下 {fmt(100 - (data.coverage_pct ?? 0), 1)}% 是未公示仓位、债券和现金，看不到
              {data.message ? ` · ${data.message}` : ""}
            </Text>
          </div>

          <Stack gap={6}>
            {data.items.map((item) => (
              <ExposureRow
                key={item.code}
                item={item}
                open={opened === item.code}
                onToggle={() => setOpened(opened === item.code ? null : item.code)}
              />
            ))}
          </Stack>

          <Text size="xs" c="dimmed">
            金额按已公布净值摊算，所以每只股票的今日盈亏加起来正好等于各基金「保守估算」口径的今日盈亏。
            持仓来自季报，实际已可能调过仓。
          </Text>
        </Stack>
      )}
    </Paper>
  );
}

function ExposureRow({
  item,
  open,
  onToggle,
}: {
  item: ExposureItem;
  open: boolean;
  onToggle: () => void;
}) {
  return (
    <Paper className={open ? "day-card day-card-active" : "day-card"} p="sm" onClick={onToggle}>
      <Group justify="space-between" align="flex-start" wrap="nowrap" gap="xs">
        <div style={{ minWidth: 0 }}>
          <Group gap={6} wrap="nowrap">
            <Text fw={600} truncate>
              {item.name}
            </Text>
            {item.market ? (
              <Badge size="xs" variant="light" color="gray">
                {item.market}
              </Badge>
            ) : null}
            {item.fund_count > 1 ? (
              <Badge size="xs" variant="light" color="gold">
                {item.fund_count} 只基金
              </Badge>
            ) : null}
          </Group>
          <Text size="xs" c="dimmed" mt={4}>
            {item.code}
            {item.pct_of_total != null ? ` · 占总市值${fmt(item.pct_of_total, 1)}%` : ""}
            {item.change_pct != null ? ` · 今日${money(item.change_pct)}%` : ""}
          </Text>
        </div>
        <div style={{ textAlign: "right", flexShrink: 0 }}>
          <Text fw={700}>{fmt(item.value, 0)} 元</Text>
          {item.today_pnl != null ? (
            <Text size="xs" c={tone(item.today_pnl)}>
              今日 {money(item.today_pnl)}
            </Text>
          ) : null}
        </div>
      </Group>

      {open ? (
        <Stack gap={4} mt="xs">
          {item.funds.map((fund) => (
            <Group key={fund.code} justify="space-between" wrap="nowrap" gap="xs">
              <Text size="xs" c="dimmed" truncate>
                {fund.name || fund.code} · 占其净值{fmt(fund.weight_pct, 2)}%
              </Text>
              <Text size="xs" style={{ flexShrink: 0 }}>
                {fmt(fund.value, 0)} 元
              </Text>
            </Group>
          ))}
        </Stack>
      ) : null}
    </Paper>
  );
}
