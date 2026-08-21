import { useEffect, useMemo, useState } from "react";
import ReactECharts from "echarts-for-react";
import { Badge, Button, Group, Paper, SimpleGrid, Skeleton, Stack, Text } from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { IconRefresh } from "@tabler/icons-react";
import { api } from "./api";
import type { StockAdvice, StockDetail, StockItem, StockList } from "./types";

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

const STANCE: Record<string, { label: string; color: string }> = {
  watch_buy: { label: "关注买入", color: "teal" },
  hold: { label: "观望", color: "gray" },
  no_chase: { label: "不追高", color: "yellow" },
};

const KIND: Record<string, string> = {
  index: "指数",
  etf: "ETF",
  stock: "个股",
};

export function StocksPanel() {
  const [list, setList] = useState<StockList | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [picked, setPicked] = useState<string | null>(null);
  const [detail, setDetail] = useState<StockDetail | null>(null);
  const [advice, setAdvice] = useState<StockAdvice | null>(null);

  const loadList = async () => {
    const next = await api.stocks();
    setList(next);
    setLoading(false);
  };

  useEffect(() => {
    loadList().catch((err) => {
      setLoading(false);
      notifications.show({ color: "red", title: "股票列表读不到", message: err instanceof Error ? err.message : "稍后重试" });
    });
    const timer = window.setInterval(() => {
      loadList().catch(() => undefined);
    }, 20000);
    return () => window.clearInterval(timer);
  }, []);

  useEffect(() => {
    if (!picked) {
      setDetail(null);
      setAdvice(null);
      return;
    }
    Promise.all([api.stock(picked), api.stockAdvice(picked)])
      .then(([nextDetail, nextAdvice]) => {
        setDetail(nextDetail);
        setAdvice(nextAdvice);
      })
      .catch((err) => {
        notifications.show({ color: "red", title: "这只暂时打不开", message: err instanceof Error ? err.message : "稍后重试" });
      });
  }, [picked]);

  const onRefresh = async () => {
    setRefreshing(true);
    try {
      const result = await api.refreshStocks(true);
      await loadList();
      if (picked) {
        const [nextDetail, nextAdvice] = await Promise.all([api.stock(picked), api.stockAdvice(picked)]);
        setDetail(nextDetail);
        setAdvice(nextAdvice);
      }
      notifications.show({ color: "teal", title: "股票数据已更新", message: result.message });
    } catch (err) {
      notifications.show({ color: "red", title: "刷新失败", message: err instanceof Error ? err.message : "稍后重试" });
    } finally {
      setRefreshing(false);
    }
  };

  const option = useMemo(() => {
    const bars = detail?.bars || [];
    return {
      backgroundColor: "transparent",
      tooltip: {
        trigger: "axis",
        backgroundColor: "rgba(20,17,12,0.92)",
        borderColor: "rgba(212,175,55,0.25)",
        textStyle: { color: "#f4ead6" },
      },
      grid: { left: 44, right: 10, top: 16, bottom: 28 },
      xAxis: {
        type: "category",
        data: bars.map((bar) => bar.date.slice(5)),
        axisLabel: { color: "#8c8170" },
        axisLine: { lineStyle: { color: "rgba(212,175,55,0.16)" } },
      },
      yAxis: {
        type: "value",
        scale: true,
        axisLabel: { color: "#8c8170" },
        splitLine: { lineStyle: { color: "rgba(255,255,255,0.04)" } },
      },
      series: [
        {
          type: "line",
          showSymbol: false,
          smooth: 0.18,
          data: bars.map((bar) => bar.close),
          lineStyle: { width: 2.2, color: "#e0c25c" },
        },
      ],
    };
  }, [detail]);

  return (
    <Paper className="glass" p="md">
      <Group justify="space-between" mb="sm" wrap="wrap">
        <div>
          <Text fw={600}>A股观察池</Text>
          <Text size="xs" c="dimmed" mt={4}>
            {list?.session || "读取时段中"} · 只给规则参考，系统不会下单
          </Text>
        </div>
        <Button variant="light" color="gold" size="xs" loading={refreshing} onClick={onRefresh} leftSection={<IconRefresh size={14} />}>
          刷新行情
        </Button>
      </Group>

      {loading && !list ? (
        <Stack gap="xs">
          {Array.from({ length: 4 }).map((_, index) => (
            <Skeleton key={index} height={64} radius="lg" />
          ))}
        </Stack>
      ) : (
        <Stack gap={8}>
          {(list?.items || []).map((item) => (
            <StockRow key={item.code} item={item} active={picked === item.code} onPick={() => setPicked(picked === item.code ? null : item.code)} />
          ))}
        </Stack>
      )}

      {picked && advice ? (
        <Stack gap="sm" mt="md">
          <Text size="sm">{advice.headline || advice.message}</Text>
          {detail?.bars?.length ? <ReactECharts option={option} style={{ height: 220 }} notMerge /> : null}
          {advice.ready ? (
            <>
              <SimpleGrid cols={3} spacing="xs">
                <Paper className="stat-tile" p="xs">
                  <Text size="xs" c="dimmed">
                    20 日均线
                  </Text>
                  <Text fw={600} size="sm">
                    {fmt(advice.ma20)}
                  </Text>
                </Paper>
                <Paper className="stat-tile" p="xs">
                  <Text size="xs" c="dimmed">
                    ATR
                  </Text>
                  <Text fw={600} size="sm">
                    {fmt(advice.atr)}
                  </Text>
                </Paper>
                <Paper className="stat-tile" p="xs">
                  <Text size="xs" c="dimmed">
                    偏离
                  </Text>
                  <Text fw={600} size="sm">
                    {signed(advice.z_score, 1)} ATR
                  </Text>
                </Paper>
              </SimpleGrid>
              <div>
                <Text size="xs" c="teal.4" fw={600} mb={4}>
                  关注档
                </Text>
                {advice.buy_levels.length ? (
                  advice.buy_levels.map((level) => (
                    <Group key={level.price} justify="space-between" gap="xs">
                      <Text size="sm">{fmt(level.price)}</Text>
                      <Text size="xs" c="dimmed">
                        {level.note}
                      </Text>
                    </Group>
                  ))
                ) : (
                  <Text size="xs" c="dimmed">
                    没有更低的参考档
                  </Text>
                )}
              </div>
              <div>
                <Text size="xs" c="red.4" fw={600} mb={4}>
                  上方档
                </Text>
                {advice.sell_levels.length ? (
                  advice.sell_levels.map((level) => (
                    <Group key={level.price} justify="space-between" gap="xs">
                      <Text size="sm">{fmt(level.price)}</Text>
                      <Text size="xs" c="dimmed">
                        {level.note}
                      </Text>
                    </Group>
                  ))
                ) : (
                  <Text size="xs" c="dimmed">
                    没有更高的参考档
                  </Text>
                )}
              </div>
              {advice.notes.map((note) => (
                <Text key={note} size="xs" c="dimmed">
                  {note}
                </Text>
              ))}
            </>
          ) : (
            <Text size="xs" c="dimmed">
              {advice.message}
            </Text>
          )}
        </Stack>
      ) : null}
    </Paper>
  );
}

function StockRow({ item, active, onPick }: { item: StockItem; active: boolean; onPick: () => void }) {
  const stance = item.stance ? STANCE[item.stance] : null;
  return (
    <Paper className={active ? "day-card day-card-active" : "day-card"} p="sm" onClick={onPick}>
      <Group justify="space-between" align="flex-start" wrap="nowrap">
        <div>
          <Group gap={6}>
            <Text fw={600}>{item.name}</Text>
            <Badge size="xs" variant="light" color="gray">
              {KIND[item.kind || ""] || item.kind}
            </Badge>
          </Group>
          <Text size="xs" c="dimmed" mt={4}>
            {item.code.toUpperCase()}
            {item.headline ? ` · ${item.headline}` : ""}
          </Text>
        </div>
        <div style={{ textAlign: "right" }}>
          <Text fw={700}>{fmt(item.price)}</Text>
          <Text size="xs" c={tone(item.change_amt)}>
            {signed(item.change_amt)} {item.change_rate != null ? `${signed(item.change_rate)}%` : ""}
          </Text>
          {stance ? (
            <Badge mt={4} size="xs" variant="light" color={stance.color}>
              {stance.label}
            </Badge>
          ) : null}
        </div>
      </Group>
    </Paper>
  );
}
