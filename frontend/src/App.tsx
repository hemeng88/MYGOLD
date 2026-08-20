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
} from "@mantine/core";
import { useMediaQuery } from "@mantine/hooks";
import { notifications } from "@mantine/notifications";
import {
  IconArrowDownRight,
  IconArrowUpRight,
  IconChartCandle,
  IconChartPie,
  IconExternalLink,
  IconMinus,
  IconNews,
  IconRefresh,
  IconSparkles,
  IconWallet,
} from "@tabler/icons-react";
import { api } from "./api";
import { AttributionPanel } from "./AttributionPanel";
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

function tagColor(tag: string) {
  switch (tag) {
    case "美联储":
      return "gold";
    case "汇率":
      return "cyan";
    case "石油":
      return "orange";
    case "通胀":
      return "pink";
    case "就业":
      return "teal";
    case "地缘":
      return "grape";
    case "央行":
      return "violet";
    case "利率":
      return "yellow";
    case "金市":
      return "gold";
    default:
      return "gray";
  }
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
  const [mobileTab, setMobileTab] = useState<"market" | "holdings" | "events" | "weights">("market");
  const [eventTag, setEventTag] = useState<string | null>(null);
  const isMobile = useMediaQuery("(max-width: 52em)") ?? true;

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
      grid: { left: isMobile ? 36 : 52, right: 8, top: compareCurve ? 40 : 16, bottom: 28 },
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
                symbolSize: isMobile ? 22 : 36,
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
  }, [compareCurve, compareDate, curve, events, isMobile, selectedDate]);

  const daysPanel = (
    <Paper className="glass" p="md">
      <Group justify="space-between" mb="sm">
        <Text fw={600}>历史交易日</Text>
        <Badge variant="light" color="gold">
          {days.length} 天
        </Badge>
      </Group>
      <ScrollArea type="auto" offsetScrollbars className={isMobile ? "day-scroll-x" : undefined} h={isMobile ? undefined : 640}>
        {isMobile ? (
          <Group gap={8} wrap="nowrap" className="day-row-inner">
            {loading && days.length === 0
              ? Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} height={64} width={120} radius="lg" />)
              : days.map((day) => {
                  const active = day.date === selectedDate;
                  return (
                    <Paper
                      key={day.date}
                      className={active ? "day-card day-card-active day-chip" : "day-card day-chip"}
                      p="sm"
                      onClick={() => onSelectDay(day.date)}
                    >
                      <Text fw={600}>{day.date.slice(5)}</Text>
                      <Text size="xs" c="dimmed">
                        {fmt(day.close)}
                      </Text>
                      <Badge mt={6} variant="light" color={tone(day.change_amt)}>
                        {signed(day.change_amt)}
                      </Badge>
                    </Paper>
                  );
                })}
          </Group>
        ) : (
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
                      <Group justify="space-between" align="flex-start" wrap="nowrap">
                        <div>
                          <Text fw={600}>{day.date}</Text>
                          <Text size="xs" c="dimmed">
                            {fmt(day.close)}
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
        )}
      </ScrollArea>
    </Paper>
  );

  const heroPanel = (
    <Paper className="glass hero" p={isMobile ? "md" : "xl"}>
      <Group justify="space-between" mb={8} wrap="wrap">
        <Text className="eyebrow">{selectedDate || "今日"} · 元 / 克</Text>
        {rule ? (
          <Badge variant="light" color="gold">
            卖出 {(rule.sell_fee_rate * 100).toFixed(1)}% · 保本 {rule.breakeven_rate_pct.toFixed(2)}%
          </Badge>
        ) : (
          <Badge leftSection={<IconChartCandle size={12} />} variant="outline" color="gold">
            浙商积存金
          </Badge>
        )}
      </Group>
      <Group align="flex-end" justify="space-between" wrap="wrap" gap="xs">
        <Text className="price">{fmt(displayPrice)}</Text>
        <Group gap={8}>
          <ThemeIcon size={isMobile ? 36 : 42} radius="xl" color={tone(displayChange)} variant="light">
            <ChangeIcon size={20} />
          </ThemeIcon>
          <div>
            <Text fw={700} c={tone(displayChange)} size={isMobile ? "md" : "lg"}>
              {signed(displayChange)}
              {displayRate === null || displayRate === undefined ? "" : `  (${signed(displayRate)}%)`}
            </Text>
            <Text size="xs" c="dimmed">
              较昨日 {fmt(summary?.prev_close ?? latest?.yesterday_price)}
            </Text>
          </div>
        </Group>
      </Group>
      <SimpleGrid cols={2} mt="lg" spacing="sm">
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
  );

  const chartPanel = (
    <Paper className="glass" p={isMobile ? "md" : "lg"}>
      <Group justify="space-between" mb="md" wrap="wrap">
        <Text fw={600}>当日价格曲线</Text>
        <Select
          placeholder="对比"
          clearable
          w={isMobile ? "100%" : 180}
          value={compareDate}
          onChange={setCompareDate}
          data={days.filter((d) => d.date !== selectedDate).map((d) => d.date)}
        />
      </Group>
      {curve && curve.points.length > 0 ? (
        <ReactECharts option={option} style={{ height: isMobile ? 280 : 420 }} notMerge />
      ) : (
        <Skeleton height={isMobile ? 280 : 420} radius="lg" visible={loading}>
          <Text ta="center" c="dimmed" py={80}>
            这一天还没有曲线，先点右上角采集一次。
          </Text>
        </Skeleton>
      )}
    </Paper>
  );

  const eventsPanel = (
    <Paper className="glass" p={isMobile ? "md" : "lg"}>
      <Group justify="space-between" mb="md" wrap="wrap">
        <div>
          <Group gap={8}>
            <IconNews size={16} />
            <Text fw={600}>行情事件</Text>
          </Group>
          <Text size="xs" c="dimmed" mt={4}>
            涨跌持续超过保本幅度时自动记录
          </Text>
        </div>
        <Group gap={8}>
          {isMobile ? (
            <Select
              placeholder="日期"
              w={140}
              value={selectedDate || null}
              onChange={(value) => value && onSelectDay(value)}
              data={days.map((d) => d.date)}
            />
          ) : null}
          <Badge variant="light" color="gray">
            {events.length} 条
          </Badge>
        </Group>
      </Group>
      <Stack gap="sm">
        {events.length === 0 && (
          <Text ta="center" c="dimmed" py="md">
            这一天还没有触发记录。
          </Text>
        )}
        {Array.from(new Set(events.flatMap((event) => event.tags || []))).length > 1 ? (
          <Group gap={6}>
            <Badge
              variant={eventTag ? "outline" : "filled"}
              color="gray"
              style={{ cursor: "pointer" }}
              onClick={() => setEventTag(null)}
            >
              全部
            </Badge>
            {Array.from(new Set(events.flatMap((event) => event.tags || []))).map((tag) => (
              <Badge
                key={tag}
                variant={eventTag === tag ? "filled" : "light"}
                color={tagColor(tag)}
                style={{ cursor: "pointer" }}
                onClick={() => setEventTag(eventTag === tag ? null : tag)}
              >
                {tag}
              </Badge>
            ))}
          </Group>
        ) : null}
        {events
          .filter((event) => !eventTag || (event.tags || []).includes(eventTag))
          .map((event) => (
          <Paper key={event.id} className="stat-tile" p="md">
            <Group justify="space-between" align="flex-start" wrap="wrap">
              <div>
                <Group gap={8} mb={6}>
                  <Badge variant="light" color={event.direction === "up" ? "red" : "teal"}>
                    {event.direction === "up" ? "上涨" : "下跌"} {signed(event.change_rate)}%
                  </Badge>
                  {(event.tags || []).map((tag) => (
                    <Badge key={tag} variant="light" color={tagColor(tag)}>
                      {tag}
                    </Badge>
                  ))}
                  <Text size="xs" c="dimmed">
                    {event.triggered_at.replace("T", " ")}
                  </Text>
                </Group>
                <Text fw={600}>{event.headline}</Text>
                <Text size="xs" c="dimmed" mt={4}>
                  {fmt(event.start_price)} → {fmt(event.end_price)}
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
  );

  return (
    <Box className={isMobile ? "app-shell app-shell-mobile" : "app-shell"}>
      <Group justify="space-between" align="center" mb={isMobile ? 16 : 28} wrap="nowrap" gap="sm">
        <div>
          <Text className="eyebrow" mb={4}>
            Zhejiang Gold
          </Text>
          <Title order={1} className="brand">
            MYGOLD
          </Title>
          {!isMobile ? (
            <Text c="dimmed" size="sm" mt={4}>
              浙商积存金每日曲线 · {status}
            </Text>
          ) : null}
        </div>
        <Group gap={8}>
          <ActionIcon variant="default" size={40} radius="xl" onClick={() => loadAll(selectedDate)} loading={loading}>
            <IconRefresh size={18} />
          </ActionIcon>
          <Button color="gold" size={isMobile ? "sm" : "md"} leftSection={!isMobile ? <IconSparkles size={16} /> : undefined} loading={collecting} onClick={onCollect}>
            {isMobile ? "采集" : "立即采集"}
          </Button>
        </Group>
      </Group>

      {isMobile ? (
        <Stack gap="md" pb={88}>
          {mobileTab === "market" && (
            <>
              {heroPanel}
              {daysPanel}
              {chartPanel}
            </>
          )}
          {mobileTab === "holdings" && (
            <HoldingsPanel holdings={holdings} onChanged={async () => setHoldings(await api.holdings())} />
          )}
          {mobileTab === "events" && eventsPanel}
          {mobileTab === "weights" && <AttributionPanel tagColor={tagColor} />}
        </Stack>
      ) : (
        <Grid gutter="lg">
          <Grid.Col span={4}>{daysPanel}</Grid.Col>
          <Grid.Col span={8}>
            <Stack gap="lg">
              {heroPanel}
              <HoldingsPanel holdings={holdings} onChanged={async () => setHoldings(await api.holdings())} />
              {chartPanel}
              <AttributionPanel tagColor={tagColor} />
              {eventsPanel}
            </Stack>
          </Grid.Col>
        </Grid>
      )}

      {isMobile ? (
        <nav className="mobile-tabbar">
          <button className={mobileTab === "market" ? "tab-on" : ""} type="button" onClick={() => setMobileTab("market")}>
            <IconChartCandle size={18} />
            行情
          </button>
          <button className={mobileTab === "holdings" ? "tab-on" : ""} type="button" onClick={() => setMobileTab("holdings")}>
            <IconWallet size={18} />
            持仓
          </button>
          <button className={mobileTab === "events" ? "tab-on" : ""} type="button" onClick={() => setMobileTab("events")}>
            <IconNews size={18} />
            事件
          </button>
          <button className={mobileTab === "weights" ? "tab-on" : ""} type="button" onClick={() => setMobileTab("weights")}>
            <IconChartPie size={18} />
            归因
          </button>
        </nav>
      ) : null}
    </Box>
  );
}
