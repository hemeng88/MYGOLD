import { useEffect, useState } from "react";
import {
  Badge,
  Button,
  Group,
  Paper,
  Progress,
  SegmentedControl,
  SimpleGrid,
  Skeleton,
  Stack,
  Text,
  Tooltip,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { IconRefresh } from "@tabler/icons-react";
import { api } from "./api";
import type { Attribution } from "./types";

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

export function AttributionPanel({ tagColor }: { tagColor: (tag: string) => string }) {
  const [data, setData] = useState<Attribution | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [windowDays, setWindowDays] = useState("180");

  const load = async (days: string) => {
    setLoading(true);
    try {
      setData(await api.attribution(Number(days)));
    } catch (err) {
      notifications.show({
        color: "red",
        title: "归因加载失败",
        message: err instanceof Error ? err.message : "稍后再试",
      });
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load(windowDays);
  }, [windowDays]);

  const refresh = async () => {
    setRefreshing(true);
    try {
      const result = await api.refreshAttribution(Number(windowDays));
      notifications.show({ color: "gold", title: "数据已更新", message: result.message });
      await load(windowDays);
    } catch (err) {
      notifications.show({
        color: "red",
        title: "更新失败",
        message: err instanceof Error ? err.message : "稍后再试",
      });
    } finally {
      setRefreshing(false);
    }
  };

  if (loading && !data) {
    return (
      <Paper className="panel" p={{ base: "md", sm: "lg" }} radius="lg">
        <Skeleton height={220} radius="md" />
      </Paper>
    );
  }

  if (!data?.ready) {
    return (
      <Paper className="panel" p={{ base: "md", sm: "lg" }} radius="lg">
        <Stack gap="sm">
          <Text fw={600}>事件归因</Text>
          <Text size="sm" c="dimmed">
            {data?.message || "还没有归因数据"}
          </Text>
          <Button color="gold" loading={refreshing} onClick={refresh} leftSection={<IconRefresh size={16} />}>
            拉取历史数据
          </Button>
        </Stack>
      </Paper>
    );
  }

  const top = data.types[0];
  const vol = data.volatility;

  return (
    <Stack gap="md">
      <Paper className="panel" p={{ base: "md", sm: "lg" }} radius="lg">
        <Group justify="space-between" align="flex-start" mb="md" wrap="nowrap">
          <div>
            <Text className="eyebrow">Event Attribution</Text>
            <Text fw={600} size="lg">
              事件类型权重
            </Text>
            <Text size="xs" c="dimmed" mt={4}>
              {data.start_date} 至 {data.end_date} · {data.proxy_symbol} 代理 · {data.significant_days} 个波动日
            </Text>
          </div>
          <Button
            variant="subtle"
            color="gold"
            size="xs"
            loading={refreshing}
            onClick={refresh}
            leftSection={<IconRefresh size={14} />}
          >
            更新
          </Button>
        </Group>

        <SegmentedControl
          fullWidth
          size="xs"
          mb="md"
          value={windowDays}
          onChange={setWindowDays}
          data={[
            { label: "近 1 月", value: "30" },
            { label: "近 3 月", value: "90" },
            { label: "近 6 月", value: "180" },
          ]}
        />

        <SimpleGrid cols={{ base: 2, sm: 4 }} spacing="sm" mb="lg">
          <div>
            <Text size="xs" c="dimmed">
              区间涨跌
            </Text>
            <Text fw={600} c={tone(data.total_change_pct)}>
              {signed(data.total_change_pct, 1)}%
            </Text>
          </div>
          <div>
            <Text size="xs" c="dimmed">
              日均振幅
            </Text>
            <Text fw={600}>{fmt(data.baseline_abs_move)}%</Text>
          </div>
          <div>
            <Text size="xs" c="dimmed">
              最大推手
            </Text>
            <Text fw={600}>{top ? `${top.tag} ${fmt(top.weight_pct, 1)}%` : "—"}</Text>
          </div>
          <div>
            <Text size="xs" c="dimmed">
              归档快讯
            </Text>
            <Text fw={600}>{data.flash_count}</Text>
          </div>
        </SimpleGrid>

        <Stack gap="sm">
          {data.types.map((item) => (
            <div key={item.tag}>
              <Group justify="space-between" gap="xs" wrap="nowrap" mb={4}>
                <Group gap={6} wrap="nowrap">
                  <Badge color={tagColor(item.tag)} variant="light" size="sm">
                    {item.tag}
                  </Badge>
                  <Text size="xs" c="dimmed">
                    {item.days} 天 · 均幅 {fmt(item.avg_abs_move)}%
                  </Text>
                </Group>
                <Group gap={6} wrap="nowrap">
                  <Text size="sm" fw={600}>
                    {fmt(item.weight_pct, 1)}%
                  </Text>
                  {item.lift ? (
                    <Tooltip label="这类事件当天的平均振幅，是全期日均振幅的几倍" withArrow>
                      <Text size="xs" c={item.lift >= 1.2 ? "gold.4" : "dimmed"}>
                        ×{fmt(item.lift, 2)}
                      </Text>
                    </Tooltip>
                  ) : null}
                </Group>
              </Group>
              <Progress value={item.weight_pct} color={tagColor(item.tag)} size="sm" radius="xl" />
              {item.sample_headline ? (
                <Text size="xs" c="dimmed" mt={4} lineClamp={1}>
                  例：{item.sample_headline}
                </Text>
              ) : null}
            </div>
          ))}
        </Stack>

        <Text size="xs" c="dimmed" mt="lg">
          算法：挑出 |日涨跌| ≥ {fmt(data.threshold_pct, 1)}% 的交易日，比较当天各类快讯的声量与它在所有波动日的
          平均声量，只把异常放量的类型算作主因，再把当天振幅均摊过去。这是相关归因，不代表因果。
        </Text>
      </Paper>

      {vol ? (
        <Paper className="panel" p={{ base: "md", sm: "lg" }} radius="lg">
          <Text fw={600} mb="xs">
            波动与区间
          </Text>
          <SimpleGrid cols={{ base: 2, sm: 4 }} spacing="sm" mb="md">
            <div>
              <Text size="xs" c="dimmed">
                20 日波动率
              </Text>
              <Text fw={600}>{fmt(vol.daily_sd_20)}%</Text>
            </div>
            <div>
              <Text size="xs" c="dimmed">
                ATR14
              </Text>
              <Text fw={600}>
                {fmt(vol.atr14)} ({fmt(vol.atr14_pct)}%)
              </Text>
            </div>
            <div>
              <Text size="xs" c="dimmed">
                MA20 / MA60
              </Text>
              <Text fw={600}>
                {fmt(vol.ma20, 0)} / {fmt(vol.ma60, 0)}
              </Text>
            </div>
            <div>
              <Text size="xs" c="dimmed">
                区间高低
              </Text>
              <Text fw={600}>
                {fmt(vol.window_high, 0)} / {fmt(vol.window_low, 0)}
              </Text>
            </div>
          </SimpleGrid>
          <Stack gap={6}>
            {vol.projections.map((p) => (
              <Group key={p.label} justify="space-between" gap="xs">
                <Text size="sm" c="dimmed">
                  {p.label}（±1σ {fmt(p.sigma_pct)}%）
                </Text>
                <Text size="sm" fw={600}>
                  {fmt(p.low, 0)} – {fmt(p.high, 0)}
                </Text>
              </Group>
            ))}
          </Stack>
          <Text size="xs" c="dimmed" mt="sm">
            按当前收盘价和日波动率外推的一倍标准差区间，约有三分之二的时间落在里面，不是预测。
          </Text>
        </Paper>
      ) : null}

      <Paper className="panel" p={{ base: "md", sm: "lg" }} radius="lg">
        <Text fw={600} mb="sm">
          波动最大的交易日
        </Text>
        <Stack gap="sm">
          {data.top_moves.map((move) => (
            <Group key={move.trade_date} justify="space-between" align="flex-start" gap="xs" wrap="nowrap">
              <div style={{ minWidth: 0 }}>
                <Group gap={6} wrap="nowrap" mb={2}>
                  <Text size="sm" fw={600}>
                    {move.trade_date.slice(5)}
                  </Text>
                  {move.tags.map((tag) => (
                    <Badge key={tag} color={tagColor(tag)} variant="light" size="xs">
                      {tag}
                    </Badge>
                  ))}
                </Group>
                <Text size="xs" c="dimmed" lineClamp={2}>
                  {move.headline || "当天没有匹配到宏观快讯"}
                </Text>
              </div>
              <Text size="sm" fw={700} c={tone(move.change_pct)} style={{ whiteSpace: "nowrap" }}>
                {signed(move.change_pct)}%
              </Text>
            </Group>
          ))}
        </Stack>
      </Paper>
    </Stack>
  );
}
