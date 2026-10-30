import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Badge, Button, Group, Paper, SegmentedControl, Select, SimpleGrid, Skeleton, Stack, Text, TextInput } from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { IconRefresh, IconSearch } from "@tabler/icons-react";
import { api } from "./api";
import { MainboardDetailModal } from "./MainboardDetail";
import { usePolling } from "./usePolling";
import type { MainboardBlockedItem, MainboardItem, MainboardPeriod } from "./types";

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

function money(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return Math.round(value).toLocaleString("zh-CN");
}

type Filter = "all" | "below" | "above" | "cheapLot";
const FILTERS = [
  { value: "all", label: "全部可买" },
  { value: "below", label: "低于均价" },
  { value: "above", label: "高于均价" },
  { value: "cheapLot", label: "一手低于 1.5 万" },
];

const PERIODS: { value: MainboardPeriod; label: string }[] = [
  { value: "1m", label: "近1月" },
  { value: "3m", label: "近3月" },
  { value: "6m", label: "近6月" },
  { value: "ytd", label: "今年来" },
  { value: "1y", label: "近1年" },
];

type SortKey = keyof MainboardItem;
const SORTS: { value: string; label: string; key: SortKey; desc: boolean }[] = [
  { value: "vs_asc", label: "低于均价最多", key: "vs_avg_pct", desc: false },
  { value: "vs_desc", label: "高于均价最多", key: "vs_avg_pct", desc: true },
  { value: "day_desc", label: "当日涨幅", key: "change_pct", desc: true },
  { value: "day_asc", label: "当日跌幅", key: "change_pct", desc: false },
  { value: "period_desc", label: "区间涨幅", key: "period_change_pct", desc: true },
  { value: "period_asc", label: "区间跌幅", key: "period_change_pct", desc: false },
  { value: "price_asc", label: "现价从低到高", key: "last", desc: false },
  { value: "price_desc", label: "现价从高到低", key: "last", desc: true },
];

export function MainboardPanel() {
  const [period, setPeriod] = useState<MainboardPeriod>("3m");
  const fetchList = useCallback((signal: AbortSignal) => api.mainboard(period, signal), [period]);
  const { data, loading, error, reload } = usePolling(fetchList);
  const [keyword, setKeyword] = useState("");
  const [filter, setFilter] = useState<Filter>("all");
  const [sort, setSort] = useState("vs_asc");
  const [picked, setPicked] = useState<MainboardItem | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const bootstrapped = useRef(false);
  const periodLabel = PERIODS.find((item) => item.value === period)?.label || "";
  const stale = data != null && data.period !== period;

  const onRefresh = useCallback(async (includeKlines = false) => {
    setRefreshing(true);
    try {
      const result = await api.refreshMainboard(includeKlines);
      await reload();
      notifications.show({
        color: result.ok ? "teal" : "yellow",
        title: result.ok ? (includeKlines ? "各周期均价已重算" : "现价已更新") : "只更新了一部分",
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
  }, [reload]);

  useEffect(() => {
    if (bootstrapped.current || loading || !data || data.ready || refreshing) return;
    bootstrapped.current = true;
    void onRefresh(true);
  }, [data, loading, refreshing, onRefresh]);

  const items = useMemo(() => {
    const key = keyword.trim();
    const rule = SORTS.find((item) => item.value === sort) || SORTS[0];
    const rows = (data?.items || []).filter((row) => {
      if (key && !row.code.includes(key) && !row.name.includes(key)) return false;
      if (filter === "below" && (row.vs_avg_pct == null || row.vs_avg_pct >= 0)) return false;
      if (filter === "above" && (row.vs_avg_pct == null || row.vs_avg_pct < 0)) return false;
      if (filter === "cheapLot" && (row.lot_cost == null || row.lot_cost >= 15000)) return false;
      return true;
    });
    // 缺值的一律沉底，不管升序降序
    return rows.sort((a, b) => {
      const av = a[rule.key] as number | null;
      const bv = b[rule.key] as number | null;
      if (av == null && bv == null) return 0;
      if (av == null) return 1;
      if (bv == null) return -1;
      return rule.desc ? bv - av : av - bv;
    });
  }, [data?.items, keyword, filter, sort]);

  const blockedByReason = useMemo(() => {
    const groups: Record<string, MainboardBlockedItem[]> = {};
    for (const row of data?.blocked_items || []) {
      (groups[row.reason] ||= []).push(row);
    }
    return groups;
  }, [data?.blocked_items]);

  return (
    <Paper className="glass" p="md">
      <Group justify="space-between" mb="sm" wrap="wrap" gap="sm" align="flex-end">
        <div style={{ minWidth: 0, flex: "1 1 180px" }}>
          <Text fw={600}>新账户可买主板</Text>
          <Text size="xs" c="dimmed" mt={4}>
            {data?.session || "读取时段中"}
            {data?.window_start && data?.window_end && !stale ? ` · ${periodLabel}均价 ${data.window_start} 至 ${data.window_end}` : ""}
            {data?.usable ? ` · ${data.usable} 只` : ""}
          </Text>
        </div>
        <Group gap="xs" wrap="nowrap">
          <Button
            variant="light"
            color="gold"
            size="sm"
            loading={refreshing}
            onClick={() => void onRefresh(false)}
            leftSection={<IconRefresh size={14} />}
          >
            刷现价
          </Button>
          <Button variant="subtle" color="gray" size="sm" loading={refreshing} onClick={() => void onRefresh(true)}>
            重算均价
          </Button>
        </Group>
      </Group>

      {error ? (
        <Group mb="sm" role="status">
          <Text size="sm" c="red">{error}</Text>
          <Button size="compact-xs" variant="subtle" onClick={() => void reload()}>重试</Button>
        </Group>
      ) : null}

      {loading && !data ? (
        <Stack gap="xs">
          {Array.from({ length: 4 }).map((_, index) => (
            <Skeleton key={index} height={56} radius="lg" />
          ))}
        </Stack>
      ) : (
        <Stack gap="sm">
          <Text size="xs" c="dimmed">
            新开普通账户一般只能买沪深主板。样本是沪深300里的主板非 ST，盘中刷现价，收盘后重拉近一年日线、重算各周期均价。点开个股看走势和大盘对比。不是买卖建议。
          </Text>
          <SegmentedControl
            fullWidth
            size="xs"
            data={PERIODS}
            value={period}
            onChange={(value) => setPeriod(value as MainboardPeriod)}
            aria-label="均价周期"
          />
          <SimpleGrid cols={{ base: 2, sm: 4 }} spacing="xs">
            <Paper className="stat-tile" p="xs">
              <Text size="xs" c="dimmed">沪深主板</Text>
              <Text className="stat-value">{data?.main_est ? data.main_est.toLocaleString("zh-CN") : "—"}</Text>
            </Paper>
            <Paper className="stat-tile" p="xs">
              <Text size="xs" c="dimmed">创业板 / 科创板</Text>
              <Text className="stat-value">{data ? `${data.cyb} / ${data.kcb}` : "—"}</Text>
            </Paper>
            <Paper className="stat-tile" p="xs">
              <Text size="xs" c="dimmed">低于{periodLabel}均价</Text>
              <Text className="stat-value">{data ? `${data.below} / ${data.usable}` : "—"}</Text>
            </Paper>
            <Paper className="stat-tile" p="xs">
              <Text size="xs" c="dimmed">相对均价平均</Text>
              <Text className="stat-value" c={tone(data?.mean_vs)}>{data?.mean_vs == null ? "—" : `${signed(data.mean_vs)}%`}</Text>
            </Paper>
          </SimpleGrid>

          <Group gap="xs" wrap="wrap" align="flex-end">
            <TextInput
              size="sm"
              style={{ flex: "1 1 160px" }}
              placeholder="搜代码或名称"
              value={keyword}
              onChange={(event) => setKeyword(event.currentTarget.value)}
              leftSection={<IconSearch size={14} />}
              aria-label="搜索主板股票"
            />
            <Select
              size="sm"
              style={{ width: 150 }}
              data={FILTERS}
              value={filter}
              onChange={(value) => value && setFilter(value as Filter)}
              allowDeselect={false}
              comboboxProps={{ withinPortal: true }}
              aria-label="筛选主板股票"
            />
            <Select
              size="sm"
              style={{ width: 150 }}
              data={SORTS.map(({ value, label }) => ({ value, label }))}
              value={sort}
              onChange={(value) => value && setSort(value)}
              allowDeselect={false}
              comboboxProps={{ withinPortal: true }}
              aria-label="排序主板股票"
            />
            <Text size="xs" c="dimmed">{items.length} 只</Text>
          </Group>

          {data?.message && !data.ready ? (
            <Text size="sm" c="dimmed">{data.message}</Text>
          ) : null}

          <Stack gap={8} style={{ opacity: stale ? 0.5 : 1 }}>
            {items.map((row) => (
              <MainboardRow key={row.secid} item={row} periodLabel={periodLabel} onOpen={() => setPicked(row)} />
            ))}
          </Stack>

          {data?.blocked_items?.length ? (
            <Stack gap={6}>
              <Text size="xs" c="dimmed">沪深300里新户通常买不了</Text>
              {Object.entries(blockedByReason).map(([reason, rows]) => (
                <Text key={reason} size="xs" c="dimmed">
                  {reason} {rows.length}：{rows.map((row) => row.name).join("、")}
                </Text>
              ))}
            </Stack>
          ) : null}
        </Stack>
      )}
      <MainboardDetailModal
        code={picked?.code ?? null}
        name={picked?.name || ""}
        initialPeriod={period}
        onClose={() => setPicked(null)}
      />
    </Paper>
  );
}

function MainboardRow({ item, periodLabel, onOpen }: { item: MainboardItem; periodLabel: string; onOpen: () => void }) {
  return (
    <Paper
      className="day-card"
      p="sm"
      role="button"
      tabIndex={0}
      onClick={onOpen}
      onKeyDown={(event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          onOpen();
        }
      }}
    >
      <Group className="fund-row-main" justify="space-between" align="flex-start" wrap="nowrap" gap="sm">
        <div style={{ minWidth: 0 }}>
          <Group gap={6} wrap="wrap">
            <Text fw={600}>{item.name}</Text>
            <Badge size="sm" variant="light" color="gray">{item.code}</Badge>
          </Group>
          <Text size="xs" c="dimmed" mt={4}>
            {periodLabel}均价 {fmt(item.avg)} · 一手约 {money(item.lot_cost)}
          </Text>
          <Text size="xs" c={tone(item.period_change_pct)} mt={2}>
            {periodLabel}涨跌 {item.period_change_pct == null ? "—" : `${signed(item.period_change_pct)}%`}
          </Text>
        </div>
        <div style={{ textAlign: "right", flex: "0 0 auto" }}>
          <Text fw={600}>{fmt(item.last)}</Text>
          <Text size="xs" c={tone(item.vs_avg_pct)}>
            相对均价 {item.vs_avg_pct == null ? "—" : `${signed(item.vs_avg_pct)}%`}
          </Text>
          <Text size="xs" c={tone(item.change_pct)}>
            当日 {item.change_pct == null ? "—" : `${signed(item.change_pct)}%`}
          </Text>
        </div>
      </Group>
    </Paper>
  );
}
