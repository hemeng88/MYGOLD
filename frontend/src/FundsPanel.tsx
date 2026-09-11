import { useEffect, useState } from "react";
import {
  ActionIcon,
  Badge,
  Button,
  Group,
  Paper,
  SimpleGrid,
  Skeleton,
  Stack,
  Text,
  TextInput,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { IconPlus, IconRefresh, IconSearch, IconTrash } from "@tabler/icons-react";
import { api } from "./api";
import type { FundDetail, FundItem, FundList, FundSearchItem } from "./types";

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

const CONFIDENCE: Record<string, { label: string; color: string }> = {
  high: { label: "覆盖高", color: "teal" },
  medium: { label: "覆盖中", color: "yellow" },
  low: { label: "仅参考", color: "gray" },
};

export function FundsPanel() {
  const [list, setList] = useState<FundList | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [picked, setPicked] = useState<string | null>(null);
  const [detail, setDetail] = useState<FundDetail | null>(null);
  const [keyword, setKeyword] = useState("");
  const [results, setResults] = useState<FundSearchItem[] | null>(null);
  const [searching, setSearching] = useState(false);
  const [busyCode, setBusyCode] = useState<string | null>(null);

  const loadList = async () => {
    setList(await api.funds());
    setLoading(false);
  };

  useEffect(() => {
    loadList().catch((err) => {
      setLoading(false);
      notifications.show({
        color: "red",
        title: "基金列表读不到",
        message: err instanceof Error ? err.message : "稍后重试",
      });
    });
    const timer = window.setInterval(() => {
      loadList().catch(() => undefined);
    }, 20000);
    return () => window.clearInterval(timer);
  }, []);

  useEffect(() => {
    if (!picked) {
      setDetail(null);
      return;
    }
    api
      .fund(picked)
      .then(setDetail)
      .catch((err) => {
        notifications.show({
          color: "red",
          title: "这只基金打不开",
          message: err instanceof Error ? err.message : "稍后重试",
        });
      });
  }, [picked, list]);

  const onRefresh = async (includeHoldings = false) => {
    setRefreshing(true);
    try {
      const result = await api.refreshFunds(includeHoldings);
      await loadList();
      if (picked) setDetail(await api.fund(picked));
      notifications.show({
        color: result.ok ? "teal" : "yellow",
        title: result.ok ? "基金估值已更新" : "只更新了一部分",
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

  const onSearch = async () => {
    const q = keyword.trim();
    if (!q) {
      setResults(null);
      return;
    }
    setSearching(true);
    try {
      setResults(await api.searchFunds(q));
    } catch (err) {
      notifications.show({
        color: "red",
        title: "搜不到",
        message: err instanceof Error ? err.message : "换个关键字试试",
      });
    } finally {
      setSearching(false);
    }
  };

  const onAdd = async (code: string) => {
    setBusyCode(code);
    try {
      const added = await api.addFund(code);
      await loadList();
      setResults((prev) => prev?.map((row) => (row.code === code ? { ...row, favorited: true } : row)) ?? null);
      notifications.show({ color: "gold", title: "已收藏", message: `${added.name} 正在按持仓估算涨跌` });
    } catch (err) {
      notifications.show({
        color: "red",
        title: "收藏失败",
        message: err instanceof Error ? err.message : "稍后重试",
      });
    } finally {
      setBusyCode(null);
    }
  };

  const onRemove = async (code: string) => {
    try {
      await api.deleteFund(code);
      if (picked === code) setPicked(null);
      setResults((prev) => prev?.map((row) => (row.code === code ? { ...row, favorited: false } : row)) ?? null);
      await loadList();
    } catch (err) {
      notifications.show({
        color: "red",
        title: "取消收藏失败",
        message: err instanceof Error ? err.message : "稍后重试",
      });
    }
  };

  const items = list?.items || [];

  return (
    <Paper className="glass" p="md">
      <Group justify="space-between" mb="sm" wrap="wrap" gap="sm" align="flex-end">
        <div style={{ minWidth: 0, flex: "1 1 160px" }}>
          <Text fw={600}>基金估值</Text>
          <Text size="xs" c="dimmed" mt={4}>
            {list?.session || "读取时段中"} · 按公示仓位×持仓股涨幅估算
          </Text>
        </div>
        <Button
          variant="light"
          color="gold"
          size="sm"
          loading={refreshing}
          onClick={() => onRefresh(false)}
          leftSection={<IconRefresh size={14} />}
        >
          刷新
        </Button>
      </Group>

      <Group gap="xs" mb="sm" wrap="nowrap">
        <TextInput
          style={{ flex: 1 }}
          size="sm"
          placeholder="基金代码或名称，例如 161725 / 白酒"
          value={keyword}
          onChange={(event) => setKeyword(event.currentTarget.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter") onSearch();
          }}
          aria-label="搜索基金"
        />
        <Button
          variant="light"
          color="gold"
          size="sm"
          loading={searching}
          onClick={onSearch}
          leftSection={<IconSearch size={14} />}
        >
          搜索
        </Button>
      </Group>

      {results ? (
        <Stack gap={6} mb="sm">
          {results.length === 0 ? (
            <Text size="xs" c="dimmed">
              没搜到基金，换个代码或名称
            </Text>
          ) : null}
          {results.map((row) => (
            <Paper key={row.code} className="stat-tile" p="xs">
              <Group justify="space-between" wrap="nowrap" gap="xs">
                <div style={{ minWidth: 0 }}>
                  <Text size="sm" fw={600} truncate>
                    {row.name}
                  </Text>
                  <Text size="xs" c="dimmed">
                    {row.code}
                    {row.fund_type ? ` · ${row.fund_type}` : ""}
                    {row.nav != null ? ` · 净值${fmt(row.nav, 4)}` : ""}
                  </Text>
                </div>
                {row.favorited ? (
                  <Badge size="xs" variant="light" color="gray">
                    已收藏
                  </Badge>
                ) : (
                  <ActionIcon
                    variant="light"
                    color="gold"
                    loading={busyCode === row.code}
                    onClick={() => onAdd(row.code)}
                    aria-label={`收藏 ${row.name}`}
                  >
                    <IconPlus size={16} />
                  </ActionIcon>
                )}
              </Group>
            </Paper>
          ))}
        </Stack>
      ) : null}

      {loading && !list ? (
        <Stack gap="xs">
          {Array.from({ length: 3 }).map((_, index) => (
            <Skeleton key={index} height={70} radius="lg" />
          ))}
        </Stack>
      ) : (
        <Stack gap={8}>
          {items.length === 0 ? (
            <Text ta="center" c="dimmed" py="sm" size="sm">
              还没收藏基金。上面搜一只，会用它公示的重仓股实时估算涨跌。
            </Text>
          ) : null}
          {items.map((item) => (
            <FundRow
              key={item.code}
              item={item}
              active={picked === item.code}
              onPick={() => setPicked(picked === item.code ? null : item.code)}
              onRemove={() => onRemove(item.code)}
            />
          ))}
        </Stack>
      )}

      {picked && detail?.fund ? (
        <Stack gap="sm" mt="md">
          <SimpleGrid cols={{ base: 2, sm: 4 }} spacing="xs">
            <Paper className="stat-tile" p="xs">
              <Text size="xs" c="dimmed">
                估算涨跌
              </Text>
              <Text fw={600} size="sm" c={tone(detail.fund.estimate_pct)}>
                {detail.fund.estimate_pct == null ? "—" : `${signed(detail.fund.estimate_pct)}%`}
              </Text>
            </Paper>
            <Paper className="stat-tile" p="xs">
              <Text size="xs" c="dimmed">
                保守估算
              </Text>
              <Text fw={600} size="sm" c={tone(detail.fund.conservative_pct)}>
                {detail.fund.conservative_pct == null ? "—" : `${signed(detail.fund.conservative_pct)}%`}
              </Text>
            </Paper>
            <Paper className="stat-tile" p="xs">
              <Text size="xs" c="dimmed">
                覆盖仓位
              </Text>
              <Text fw={600} size="sm">
                {detail.fund.covered_pct == null ? "—" : `${fmt(detail.fund.covered_pct, 1)}%`}
              </Text>
            </Paper>
            <Paper className="stat-tile" p="xs">
              <Text size="xs" c="dimmed">
                估算净值
              </Text>
              <Text fw={600} size="sm">
                {fmt(detail.fund.estimate_nav, 4)}
              </Text>
            </Paper>
          </SimpleGrid>

          <Text size="xs" c="dimmed">
            保守估算把没公示的仓位当成不动，估算涨跌则假设它们和重仓股同步。
            {detail.fund.report_label ? ` 持仓为 ${detail.fund.report_label} 报告。` : ""}
            {detail.fund.nav_date ? ` 官方净值 ${detail.fund.nav_date}：${fmt(detail.fund.nav, 4)}。` : ""}
          </Text>
          {detail.fund.message ? (
            <Text size="xs" c={detail.fund.stale ? "yellow" : "dimmed"}>
              {detail.fund.message}
            </Text>
          ) : null}

          <Group justify="space-between" align="center">
            <Text size="xs" fw={600}>
              公示重仓 {detail.holdings.length} 只
            </Text>
            <Button variant="subtle" color="gold" size="compact-xs" loading={refreshing} onClick={() => onRefresh(true)}>
              重拉季报持仓
            </Button>
          </Group>

          <Stack gap={6}>
            {detail.holdings.map((row) => (
              <Paper key={row.secid} className="stat-tile" p="xs">
                <Group justify="space-between" wrap="nowrap" gap="xs">
                  <div style={{ minWidth: 0 }}>
                    <Group gap={6} wrap="nowrap">
                      <Text size="sm" fw={600} truncate>
                        {row.name}
                      </Text>
                      {row.market ? (
                        <Badge size="xs" variant="light" color="gray">
                          {row.market}
                        </Badge>
                      ) : null}
                    </Group>
                    <Text size="xs" c="dimmed">
                      {row.code} · 占净值{fmt(row.weight_pct, 2)}%
                    </Text>
                  </div>
                  <div style={{ textAlign: "right", flexShrink: 0 }}>
                    <Text size="sm" fw={600} c={tone(row.change_pct)}>
                      {row.change_pct == null ? "无报价" : `${signed(row.change_pct)}%`}
                    </Text>
                    <Text size="xs" c={tone(row.contrib_pct)}>
                      {row.contrib_pct == null ? "—" : `贡献${signed(row.contrib_pct, 3)}pt`}
                    </Text>
                  </div>
                </Group>
              </Paper>
            ))}
          </Stack>
        </Stack>
      ) : null}
    </Paper>
  );
}

function FundRow({
  item,
  active,
  onPick,
  onRemove,
}: {
  item: FundItem;
  active: boolean;
  onPick: () => void;
  onRemove: () => void;
}) {
  const confidence = CONFIDENCE[item.confidence] || CONFIDENCE.low;
  return (
    <Paper className={active ? "day-card day-card-active" : "day-card"} p="sm" onClick={onPick}>
      <Group justify="space-between" align="flex-start" wrap="nowrap" gap="xs">
        <div style={{ minWidth: 0 }}>
          <Group gap={6} wrap="wrap">
            <Text fw={600} truncate>
              {item.name}
            </Text>
            <Badge size="xs" variant="light" color={confidence.color}>
              {confidence.label}
            </Badge>
          </Group>
          <Text size="xs" c="dimmed" mt={4}>
            {item.code}
            {item.covered_pct != null ? ` · 覆盖${fmt(item.covered_pct, 1)}%` : ""}
            {item.report_label ? ` · ${item.report_label}` : ""}
          </Text>
          {item.ready && (item.lead_name || item.drag_name) ? (
            <Text size="xs" c="dimmed" mt={2}>
              {item.lead_name ? `领涨${item.lead_name}` : ""}
              {item.lead_name && item.drag_name ? " · " : ""}
              {item.drag_name ? `拖累${item.drag_name}` : ""}
            </Text>
          ) : null}
          {!item.ready && item.message ? (
            <Text size="xs" c="dimmed" mt={2}>
              {item.message}
            </Text>
          ) : null}
        </div>
        <Group gap={4} wrap="nowrap" align="flex-start">
          <div style={{ textAlign: "right" }}>
            <Text fw={700} c={tone(item.estimate_pct)}>
              {item.estimate_pct == null ? "—" : `${signed(item.estimate_pct)}%`}
            </Text>
            <Text size="xs" c="dimmed">
              {item.estimate_nav != null ? `估${fmt(item.estimate_nav, 4)}` : fmt(item.nav, 4)}
            </Text>
          </div>
          <ActionIcon
            variant="subtle"
            color="gray"
            onClick={(event) => {
              event.stopPropagation();
              onRemove();
            }}
            aria-label={`取消收藏 ${item.name}`}
          >
            <IconTrash size={16} />
          </ActionIcon>
        </Group>
      </Group>
    </Paper>
  );
}
