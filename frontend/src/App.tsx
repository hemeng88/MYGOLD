import { useCallback, useEffect, useMemo, useState } from "react";
import ReactECharts from "echarts-for-react";
import {
  ActionIcon,
  Badge,
  Box,
  Button,
  Grid,
  Group,
  Paper,
  ScrollArea,
  Select,
  SimpleGrid,
  Skeleton,
  Stack,
  Text,
  ThemeIcon,
  Title,
  Tooltip,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import {
  IconArrowDownRight,
  IconArrowUpRight,
  IconChartCandle,
  IconExternalLink,
  IconMinus,
  IconNews,
  IconRefresh,
  IconSparkles,
} from "@tabler/icons-react";
import { api } from "./api";
import { HoldingsPanel } from "./HoldingsPanel";
import type { CurveResponse, DaySummary, FeeRule, HoldingSummary, LatestQuote, MarketEvent } from "./types";

function fmt(n: number | null | undefined, digits = 2) {
  if (n === null || n === undefined || Number.isNaN(n)) return "—";
  return n.toFixed(digits);
}

function signed(value: number | null | undefined) {
  if (value === null || value === undefined) return "—";
  return `${value > 0 ? "+" : ""}${value.toFixed(2)}`;
}

function tone(value: number | null | undefined) {
  if (value === null || value === undefined || value === 0) return "gray";
  return value > 0 ? "red" : "teal";
}

function clockToSec(value: string) {
  const parts = value.split(":").map(Number);
  return (parts[0] || 0) * 3600 + (parts[1] || 0) * 60 + (parts[2] || 0);
}

export default function App() {
  const [days, setDays] = useState<DaySummary[]>([]);
  const [selectedDate, setSelectedDate] = useState("");
  const [compareDate, setCompareDate] = useState<string | null>(null);
  const [curve, setCurve] = useState<CurveResponse | null>(null);
  const [compareCurve, setCompareCurve] = useState<CurveResponse | null>(null);
  const [latest, setLatest] = useState<LatestQuote | null>(null);
  const [loading, setLoading] = useState(true);
  const [collecting, setCollecting] = useState(false);
  const [status, setStatus] = useState("正在读取已归档曲线…");
  const [rule, setRule] = useState<FeeRule | null>(null);
  const [events, setEvents] = useState<MarketEvent[]>([]);
  const [holdings, setHoldings] = useState<HoldingSummary | null>(null);

  const loadAll = useCallback(async (date?: string) => {
    const [dayList, latestQuote, feeRule, nextHoldings] = await Promise.all([
      api.days(),
      api.latest().catch(() => null),
      api.rules().catch(() => null),
      api.holdings().catch(() => null),
    ]);
    setDays(dayList);
    setLatest(latestQuote);
    setRule(feeRule);
    setHoldings(nextHoldings);
    const nextDate = date || dayList[0]?.date || latestQuote?.trade_date || "";
    setSelectedDate(nextDate);
    if (nextDate) {
      const [nextCurve, dayEvents] = await Promise.all([api.curve(nextDate), api.events(nextDate)]);
      setCurve(nextCurve);
      setEvents(dayEvents);
    }
    setStatus(latestQuote?.collected_at ? `最近采集 ${latestQuote.collected_at.replace("T", " ")}` : "等待首次采集");
  }, []);

  useEffect(() => {
    loadAll()
      .catch((err: Error) => {
        notifications.show({ color: "red", title: "加载失败", message: err.message });
      })
      .finally(() => setLoading(false));
  }, [loadAll]);

  useEffect(() => {
    if (!compareDate) {
      setCompareCurve(null);
      return;
    }
    api.curve(compareDate).then(setCompareCurve).catch((err: Error) => {
      notifications.show({ color: "red", title: "对比日加载失败", message: err.message });
    });
  }, [compareDate]);

  const onSelectDay = async (date: string) => {
    setSelectedDate(date);
    const [nextCurve, dayEvents] = await Promise.all([api.curve(date), api.events(date)]);
    setCurve(nextCurve);
    setEvents(dayEvents);
  };

  const onCollect = async () => {
    setCollecting(true);
    try {
      const result = await api.collect();
      setStatus(result.message);
      await loadAll(selectedDate || result.tick?.trade_date);
      notifications.show({ color: "gold", title: "采集完成", message: result.message });
    } catch (err) {
      notifications.show({
        color: "red",
        title: "采集失败",
        message: err instanceof Error ? err.message : "请稍后重试",
      });
    } finally {
      setCollecting(false);
    }
  };

  const summary = curve?.summary;
  const displayPrice = selectedDate === latest?.trade_date ? latest?.price ?? summary?.close : summary?.close;
  const displayChange = summary?.change_amt ?? latest?.change_amt;
  const displayRate = summary?.change_rate;
  const ChangeIcon = !displayChange ? IconMinus : displayChange > 0 ? IconArrowUpRight : IconArrowDownRight;

  const option = useMemo(() => {
    const series = [
      {
        name: selectedDate || "当日",
        type: "line",
        showSymbol: false,
        smooth: 0.18,
        data: (curve?.points || []).map((p) => [p.time, p.p]),
        lineStyle: { width: 2.4, color: "#e0c25c" },
        areaStyle: {
          color: {
            type: "linear",
            x: 0,
            y: 0,
            x2: 0,
            y2: 1,
            colorStops: [
              { offset: 0, color: "rgba(212,175,55,0.32)" },
              { offset: 1, color: "rgba(212,175,55,0)" },
            ],
          },
        },
      },
    ];
    if (compareCurve) {
      series.push({
        name: compareDate || "对比",
        type: "line",
        showSymbol: false,
        smooth: 0.18,
        data: compareCurve.points.map((p) => [p.time, p.p]),
        lineStyle: { width: 1.8, color: "#7eb6d4" },
        areaStyle: {
          color: {
            type: "linear",
            x: 0,
            y: 0,
            x2: 0,
            y2: 1,
            colorStops: [
              { offset: 0, color: "rgba(126,182,212,0.18)" },
              { offset: 1, color: "rgba(126,182,212,0)" },
            ],
          },
        },
      });
    }
    return {
      backgroundColor: "transparent",
      tooltip: {
        trigger: "axis",
        backgroundColor: "rgba(20,17,12,0.92)",
        borderColor: "rgba(212,175,55,0.25)",
        textStyle: { color: "#f4ead6" },
      },
      legend: { show: Boolean(compareCurve), top: 4, textStyle: { color: "#c9b896" } },
      grid: { left: 52, right: 16, top: compareCurve ? 40 : 20, bottom: 32 },
      xAxis: {
        type: "category",
        boundaryGap: false,
        axisLine: { lineStyle: { color: "rgba(212,175,55,0.16)" } },
        axisLabel: { color: "#8c8170" },
        splitLine: { show: false },
      },
      yAxis: {
        type: "value",
        scale: true,
        axisLabel: { color: "#8c8170" },
        splitLine: { lineStyle: { color: "rgba(255,255,255,0.04)" } },
      },
      series: series.map((item, idx) =>
        idx === 0
          ? {
              ...item,
              markPoint: {
                symbol: "pin",
                symbolSize: 36,
                data: events.map((event) => {
                  const clock = event.triggered_at.slice(11, 19);
                  const target = clockToSec(clock);
                  const nearest = (curve?.points || []).reduce(
                    (best, point) =>
                      Math.abs(clockToSec(point.time) - target) < Math.abs(clockToSec(best.time) - target)
                        ? point
                        : best,
                    curve?.points[0] || { time: clock, p: event.end_price },
                  );
                  return {
                    name: event.headline.slice(0, 18),
                    coord: [nearest.time, event.end_price],
                    value: `${event.change_rate > 0 ? "+" : ""}${event.change_rate.toFixed(2)}%`,
                    itemStyle: { color: event.direction === "up" ? "#d24b3a" : "#2f9b6a" },
                  };
                }),
                label: { color: "#f4ead6", fontSize: 10 },
              },
            }
          : item,
      ),
    };
  }, [compareCurve, compareDate, curve, events, selectedDate]);

  return (
    <Box className="app-shell">
      <Group justify="space-between" align="flex-end" mb={28} wrap="wrap" gap="md">
        <div>
          <Text className="eyebrow" mb={6}>
            Zhejiang Gold Archive
          </Text>
          <Title order={1} className="brand">
            MYGOLD
          </Title>
          <Text c="dimmed" size="sm" mt={4}>
            浙商积存金每日曲线 · 今天看见昨天，以后也能看见今天
          </Text>
        </div>
        <Group gap="sm">
          <Text size="xs" c="dimmed" visibleFrom="sm">
            {status}
          </Text>
          <Tooltip label="重新读取本地档案">
            <ActionIcon variant="default" size={38} radius="xl" onClick={() => loadAll(selectedDate)} loading={loading}>
              <IconRefresh size={18} />
            </ActionIcon>
          </Tooltip>
          <Button
            color="gold"
            leftSection={<IconSparkles size={16} />}
            loading={collecting}
            onClick={onCollect}
          >
            立即采集
          </Button>
        </Group>
      </Group>

      <Grid gutter="lg">
        <Grid.Col span={{ base: 12, md: 4 }}>
        <Paper className="glass" p="md">
          <Group justify="space-between" mb="sm">
            <Text fw={600}>历史交易日</Text>
            <Badge variant="light" color="gold">
              {days.length} 天
            </Badge>
          </Group>
          <ScrollArea h={{ base: 240, md: 640 }} offsetScrollbars>
            <Stack gap={8}>
              {loading && days.length === 0
                ? Array.from({ length: 6 }).map((_, i) => <Skeleton key={i} height={64} radius="lg" />)
                : days.map((day) => {
                    const active = day.date === selectedDate;
                    return (
                      <Paper
                        key={day.date}
                        className={active ? "day-card day-card-active" : "day-card"}
                        p="sm"
                        onClick={() => onSelectDay(day.date)}
                      >
                        <Group justify="space-between" align="flex-start">
                          <div>
                            <Text fw={600}>{day.date}</Text>
                            <Text size="xs" c="dimmed">
                              收盘 {fmt(day.close)}
                            </Text>
                          </div>
                          <Badge variant="light" color={tone(day.change_amt)}>
                            {signed(day.change_amt)}
                          </Badge>
                        </Group>
                      </Paper>
                    );
                  })}
              {!loading && days.length === 0 && (
                <Text ta="center" c="dimmed" py="xl">
                  还没有归档日期
                </Text>
              )}
            </Stack>
          </ScrollArea>
        </Paper>
        </Grid.Col>

        <Grid.Col span={{ base: 12, md: 8 }}>
        <Stack gap="lg">
          <Paper className="glass hero" p={{ base: "lg", sm: "xl" }}>
            <Group justify="space-between" mb={8}>
              <Text className="eyebrow">{selectedDate || "今日"} · 元 / 克</Text>
              <Group gap={8}>
                {rule ? (
                  <Badge variant="light" color="gold">
                    卖出 { (rule.sell_fee_rate * 100).toFixed(1) }% · 保本涨幅 {rule.breakeven_rate_pct.toFixed(2)}%
                    {rule.example_needed_rise ? ` · 约 ${rule.example_needed_rise.toFixed(2)} 元/克` : ""}
                  </Badge>
                ) : null}
                <Badge leftSection={<IconChartCandle size={12} />} variant="outline" color="gold">
                  浙商积存金
                </Badge>
              </Group>
            </Group>
            <Group align="flex-end" justify="space-between" wrap="wrap">
              <Text className="price">{fmt(displayPrice)}</Text>
              <Group gap={8}>
                <ThemeIcon size={42} radius="xl" color={tone(displayChange)} variant="light">
                  <ChangeIcon size={22} />
                </ThemeIcon>
                <div>
                  <Text fw={700} c={tone(displayChange)} size="lg">
                    {signed(displayChange)}
                    {displayRate === null || displayRate === undefined ? "" : `  (${signed(displayRate)}%)`}
                  </Text>
                  <Text size="xs" c="dimmed">
                    较昨日 {fmt(summary?.prev_close ?? latest?.yesterday_price)}
                  </Text>
                </div>
              </Group>
            </Group>
            <SimpleGrid cols={{ base: 2, sm: 4 }} mt="xl" spacing="sm">
              {[
                ["开盘", summary?.open],
                ["最高", summary?.high],
                ["最低", summary?.low],
                ["点数", summary?.point_count],
              ].map(([label, value]) => (
                <Paper key={String(label)} className="stat-tile" p="md">
                  <Text size="xs" c="dimmed">
                    {label}
                  </Text>
                  <Text className="stat-value">{typeof value === "number" && label !== "点数" ? fmt(value) : value ?? "—"}</Text>
                </Paper>
              ))}
            </SimpleGrid>
          </Paper>

          <HoldingsPanel holdings={holdings} onChanged={async () => setHoldings(await api.holdings())} />

          <Paper className="glass" p="lg">
            <Group justify="space-between" mb="md" wrap="wrap">
              <div>
                <Text fw={600}>当日价格曲线</Text>
                <Text size="xs" c="dimmed">
                  可叠加另一天，方便对照高低点
                </Text>
              </div>
              <Select
                placeholder="叠加对比日"
                clearable
                w={180}
                value={compareDate}
                onChange={setCompareDate}
                data={days.filter((d) => d.date !== selectedDate).map((d) => d.date)}
              />
            </Group>
            {curve && curve.points.length > 0 ? (
              <ReactECharts option={option} style={{ height: 420 }} notMerge />
            ) : (
              <Skeleton height={420} radius="lg" visible={loading}>
                <Text ta="center" c="dimmed" py={180}>
                  这一天还没有曲线，先点右上角采集一次。
                </Text>
              </Skeleton>
            )}
          </Paper>

          <Paper className="glass" p="lg">
            <Group justify="space-between" mb="md">
              <div>
                <Group gap={8}>
                  <IconNews size={16} />
                  <Text fw={600}>超过手续费阈值的行情事件</Text>
                </Group>
                <Text size="xs" c="dimmed" mt={4}>
                  近 {rule ? Math.round(rule.watch_window_seconds / 60) : 15} 分钟涨跌持续超过保本幅度时，自动记录当时最主要的相关新闻
                </Text>
              </div>
              <Badge variant="light" color="gray">
                {events.length} 条
              </Badge>
            </Group>
            <Stack gap="sm">
              {events.length === 0 && (
                <Text ta="center" c="dimmed" py="md">
                  这一天还没有触发记录。金价持续波动超过保本幅度后会出现在这里。
                </Text>
              )}
              {events.map((event) => (
                <Paper key={event.id} className="stat-tile" p="md">
                  <Group justify="space-between" align="flex-start" wrap="wrap">
                    <div>
                      <Group gap={8} mb={6}>
                        <Badge variant="light" color={event.direction === "up" ? "red" : "teal"}>
                          {event.direction === "up" ? "上涨" : "下跌"} {signed(event.change_rate)}%
                        </Badge>
                        <Text size="xs" c="dimmed">
                          {event.triggered_at.replace("T", " ")} · {event.source || "monitor"}
                        </Text>
                      </Group>
                      <Text fw={600}>{event.headline}</Text>
                      <Text size="xs" c="dimmed" mt={4}>
                        {fmt(event.start_price)} → {fmt(event.end_price)}（{signed(event.change_amt)} 元/克）
                        ，阈值 {event.threshold_rate.toFixed(2)}%
                      </Text>
                    </div>
                    {event.url ? (
                      <Button
                        component="a"
                        href={event.url}
                        target="_blank"
                        rel="noreferrer"
                        variant="subtle"
                        color="gold"
                        size="xs"
                        rightSection={<IconExternalLink size={14} />}
                      >
                        原文
                      </Button>
                    ) : null}
                  </Group>
                </Paper>
              ))}
            </Stack>
          </Paper>
        </Stack>
        </Grid.Col>
      </Grid>
    </Box>
  );
}
