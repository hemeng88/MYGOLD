import { useEffect, useMemo, useState } from "react";
import {
  ActionIcon,
  Badge,
  Button,
  Group,
  Modal,
  NumberInput,
  Paper,
  Select,
  SimpleGrid,
  Skeleton,
  Stack,
  Text,
  TextInput,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { IconPlus, IconRefresh, IconSearch, IconTrash } from "@tabler/icons-react";
import { api } from "./api";
import { FUNDS_CHANGED_EVENT, usePolling } from "./usePolling";
import type { FundDetail, FundItem, FundSearchItem } from "./types";

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
  return `${value > 0 ? "+" : ""}${value.toFixed(2)}`;
}

const CONFIDENCE: Record<string, { label: string; color: string }> = {
  high: { label: "覆盖高", color: "teal" },
  medium: { label: "覆盖中", color: "yellow" },
  low: { label: "仅参考", color: "gray" },
};

type FundSort = "default" | "cost" | "total_pnl" | "total_pnl_pct" | "today_pnl" | "today_pnl_pct" | "estimate_pct";

const SORT_OPTIONS = [
  { value: "default", label: "默认顺序" },
  { value: "cost", label: "成本金额" },
  { value: "total_pnl", label: "累计收益金额" },
  { value: "total_pnl_pct", label: "累计收益率" },
  { value: "today_pnl", label: "当日收益金额" },
  { value: "today_pnl_pct", label: "当日收益率" },
  { value: "estimate_pct", label: "估算涨跌幅" },
];

export function FundsPanel() {
  const { data: list, loading, error, reload: loadList } = usePolling(api.funds);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [picked, setPicked] = useState<string | null>(null);
  const [editingCode, setEditingCode] = useState<string | null>(null);
  const [detail, setDetail] = useState<FundDetail | null>(null);
  const [keyword, setKeyword] = useState("");
  const [results, setResults] = useState<FundSearchItem[] | null>(null);
  const [searching, setSearching] = useState(false);
  const [busyCode, setBusyCode] = useState<string | null>(null);
  const [sharesInput, setSharesInput] = useState<number | string>("");
  const [costInput, setCostInput] = useState<number | string>("");
  const [savingPos, setSavingPos] = useState(false);
  const [sortBy, setSortBy] = useState<FundSort>("default");

  useEffect(() => {
    setDetailError(null);
    if (!picked) {
      setDetail(null);
      return;
    }
    const controller = new AbortController();
    api.fund(picked, controller.signal).then((next) => {
      if (!controller.signal.aborted) setDetail(next);
    }).catch((err) => {
      if (!controller.signal.aborted) {
        setDetailError(err instanceof Error ? err.message : "详情读取失败");
      }
    });
    return () => controller.abort();
  }, [picked, list]);

  useEffect(() => {
    if (!editingCode) {
      setSharesInput("");
      setCostInput("");
      return;
    }
    const item = (list?.items || []).find((row) => row.code === editingCode);
    setSharesInput(item?.shares ?? "");
    setCostInput(item?.cost_price ?? "");
    // 只在切换基金时回填，不跟 list 联动，否则 20 秒一次的轮询会把正在输入的内容冲掉
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [editingCode]);

  const onRefresh = async (includeHoldings = false) => {
    setRefreshing(true);
    try {
      const result = await api.refreshFunds(includeHoldings);
      await loadList();
      window.dispatchEvent(new Event(FUNDS_CHANGED_EVENT));
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
      window.dispatchEvent(new Event(FUNDS_CHANGED_EVENT));
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

  const onSavePosition = async () => {
    if (!editingCode) return;
    const shares = sharesInput === "" ? null : Number(sharesInput);
    const costPrice = costInput === "" ? null : Number(costInput);
    if (shares !== null && (!Number.isFinite(shares) || shares < 0)) {
      notifications.show({ color: "red", title: "份额不对", message: "填个大于 0 的数，或者留空清掉持仓" });
      return;
    }
    if (costPrice !== null && (!Number.isFinite(costPrice) || costPrice < 0)) {
      notifications.show({ color: "red", title: "成本价不对", message: "请输入有效的非负成本价" });
      return;
    }
    if (shares && !costPrice) {
      notifications.show({ color: "red", title: "还差成本价", message: "填了份额也要填成本价，不然算不出盈亏" });
      return;
    }
    setSavingPos(true);
    try {
      await api.saveFundPosition(editingCode, shares, costPrice);
      await loadList();
      window.dispatchEvent(new Event(FUNDS_CHANGED_EVENT));
      notifications.show({
        color: "gold",
        title: shares ? "持仓已记下" : "已清掉持仓",
        message: shares ? `${shares} 份 · 成本 ${costPrice}` : "只保留收藏，不算盈亏",
      });
      setEditingCode(null);
    } catch (err) {
      notifications.show({
        color: "red",
        title: "保存失败",
        message: err instanceof Error ? err.message : "稍后重试",
      });
    } finally {
      setSavingPos(false);
    }
  };

  const onRemove = async (code: string) => {
    const item = items.find((row) => row.code === code);
    if (!window.confirm(`确定要删除「${item?.name || code}」吗？\n删除后不会影响基金账户，只会从本项目收藏中移除。`)) return;
    try {
      await api.deleteFund(code);
      window.dispatchEvent(new Event(FUNDS_CHANGED_EVENT));
      if (picked === code) setPicked(null);
      if (editingCode === code) setEditingCode(null);
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
  const sortedItems = useMemo(() => {
    if (sortBy === "default") return items;
    const value = (item: FundItem): number | null => {
      if (sortBy === "cost") return item.cost;
      if (sortBy === "total_pnl") return item.total_pnl;
      if (sortBy === "total_pnl_pct") return item.total_pnl_pct;
      if (sortBy === "today_pnl") return item.today_pnl;
      if (sortBy === "today_pnl_pct") {
        if (item.today_pnl == null || item.nav_value == null || item.nav_value === 0) return null;
        return (item.today_pnl / item.nav_value) * 100;
      }
      return item.estimate_pct;
    };
    return items
      .map((item, index) => ({ item, index, value: value(item) }))
      .sort((a, b) => {
        if (a.value == null && b.value == null) return a.index - b.index;
        if (a.value == null) return 1;
        if (b.value == null) return -1;
        return b.value - a.value || a.index - b.index;
      })
      .map(({ item }) => item);
  }, [items, sortBy]);

  // 只统计填了持仓、而且确实算出盈亏的基金。没填份额的当自选看；
  // 净值临时取不到的也排除，否则成本进了分母、盈亏没进分子，合计会自相矛盾。
  const totals = useMemo(() => {
    const held = items.filter((item) => item.shares && item.cost && item.total_pnl != null);
    if (!held.length) return null;
    const sum = (pick: (item: FundItem) => number | null) =>
      held.reduce((acc, item) => acc + (pick(item) ?? 0), 0);
    const cost = sum((item) => item.cost);
    const total = sum((item) => item.total_pnl);
    // 净值已经把上一个交易日结算进去时后端不给 today_pnl，这时合计要显示「—」，
    // 不能当 0 加进去 —— 那样看着像今天真的没涨没跌
    const live = held.filter((item) => item.today_pnl != null);
    return {
      count: held.length,
      cost,
      value: sum((item) => item.estimate_value ?? item.nav_value),
      today: live.length ? live.reduce((acc, item) => acc + (item.today_pnl ?? 0), 0) : null,
      settled: held.every((item) => item.settled),
      total,
      totalPct: cost ? (total / cost) * 100 : null,
    };
  }, [items]);

  return (
    <Paper className="glass" p="md">
      <Group justify="space-between" mb="sm" wrap="wrap" gap="sm" align="flex-end">
        <div style={{ minWidth: 0, flex: "1 1 160px" }}>
          <Text fw={600}>基金估值</Text>
          <Text size="xs" c="dimmed" mt={4}>
            {list?.session || "读取时段中"} · 按公示仓位×持仓股涨幅估算
          </Text>
        </div>
        <Group gap="xs" wrap="nowrap">
          <Select
            size="sm"
            style={{ width: 128 }}
            data={SORT_OPTIONS}
            value={sortBy}
            onChange={(value) => value && setSortBy(value as FundSort)}
            allowDeselect={false}
            comboboxProps={{ withinPortal: true }}
            aria-label="基金排序方式"
          />
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
      </Group>

      <Text fw={600} size="sm" mb={4}>添加基金</Text>
      <Text size="xs" c="dimmed" mb="xs">搜索代码或名称，在结果中点击“添加”。已有基金可点击“编辑持仓”修改份额和成本价。</Text>
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

      {totals ? (
        <SimpleGrid cols={{ base: 2, sm: 4 }} spacing="xs" mb="sm">
          <Paper className="stat-tile" p="xs">
            <Text size="xs" c="dimmed">
              今日估算盈亏
            </Text>
            <Text fw={700} size="sm" c={tone(totals.today)}>
              {money(totals.today)} 元
            </Text>
          </Paper>
          <Paper className="stat-tile" p="xs">
            <Text size="xs" c="dimmed">
              累计盈亏
            </Text>
            <Text fw={700} size="sm" c={tone(totals.total)}>
              {money(totals.total)} 元
            </Text>
          </Paper>
          <Paper className="stat-tile" p="xs">
            <Text size="xs" c="dimmed">
              {totals.settled ? "最新净值市值" : "估算总市值"}
            </Text>
            <Text fw={600} size="sm">
              {fmt(totals.value)} 元
            </Text>
          </Paper>
          <Paper className="stat-tile" p="xs">
            <Text size="xs" c="dimmed">
              总成本 · {totals.count}/{items.length} 只
            </Text>
            <Text fw={600} size="sm">
              {fmt(totals.cost)} 元
            </Text>
          </Paper>
        </SimpleGrid>
      ) : null}

      {totals && totals.count < items.length ? (
        <Text size="xs" c="yellow" mb="sm">
          合计只算了 {totals.count} 只，还有 {items.length - totals.count} 只没填持仓或暂时取不到净值，没计入
        </Text>
      ) : null}

      {totals?.settled ? (
        <Text size="xs" c="dimmed" mb="sm">
          上一个交易日的净值已经公布，涨跌都算进净值里了，所以现在的累计盈亏是准确值，
          今日估算要等下一个交易日开盘才有。
        </Text>
      ) : null}

      {!totals && items.length ? (
        <Text size="xs" c="dimmed" mb="sm">
          点开基金填上份额和成本价，这里会显示合计盈亏
        </Text>
      ) : null}

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
                  <Button
                    size="compact-sm"
                    variant="light"
                    color="gold"
                    loading={busyCode === row.code}
                    onClick={() => onAdd(row.code)}
                    aria-label={`收藏 ${row.name}`}
                    leftSection={<IconPlus size={14} />}
                  >
                    添加
                  </Button>
                )}
              </Group>
            </Paper>
          ))}
        </Stack>
      ) : null}

      {error ? (
        <Group mb="sm" role="status">
          <Text size="sm" c="red">{error}{list ? " 当前显示上次成功的数据。" : ""}</Text>
          <Button size="compact-xs" variant="subtle" onClick={() => void loadList()}>重试</Button>
        </Group>
      ) : null}
      {error && !list ? null : loading && !list ? (
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
          {sortedItems.map((item) => (
            <FundRow
              key={item.code}
              item={item}
              active={picked === item.code}
              onPick={() => setPicked(picked === item.code ? null : item.code)}
              onEdit={() => setEditingCode(item.code)}
              onRemove={() => onRemove(item.code)}
            />
          ))}
        </Stack>
      )}

      <Modal
        opened={picked !== null}
        onClose={() => setPicked(null)}
        title={`基金详情 · ${items.find((item) => item.code === picked)?.name || picked || ""}`}
        size="lg"
        centered
      >
      {picked && detailError ? (
        <Group mt="sm" role="status">
          <Text size="sm" c="red">{detailError}</Text>
          <Button size="compact-xs" variant="subtle" onClick={() => void loadList()}>重试</Button>
        </Group>
      ) : null}
      {picked && !detailError && detail?.fund?.code !== picked ? <Skeleton mt="md" height={100} /> : null}
      {picked && detail?.fund?.code === picked ? (
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
                {detail.fund.is_cash_fund ? "万份收益" : "估算净值"}
              </Text>
              <Text fw={600} size="sm">
                {detail.fund.is_cash_fund ? fmt(detail.fund.yield_10k, 4) : fmt(detail.fund.estimate_nav, 4)}
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
      </Modal>
      <Modal
        opened={editingCode !== null}
        onClose={() => setEditingCode(null)}
        title={`修改持仓 · ${items.find((item) => item.code === editingCode)?.name || editingCode || ""}`}
        centered
      >
        <Stack gap="sm">
          <Text size="sm" c="dimmed">
            修改份额和成本价后，基金卡片上的盈亏会同步更新。两个输入都留空则只保留收藏。
          </Text>
          <SimpleGrid cols={2} spacing="xs">
            <NumberInput
              size="sm"
              label="持有份额"
              placeholder="例如 1000"
              min={0}
              step={100}
              decimalScale={4}
              hideControls
              value={sharesInput}
              onChange={setSharesInput}
            />
            <NumberInput
              size="sm"
              label="成本价"
              placeholder="元/份"
              min={0}
              decimalScale={4}
              hideControls
              value={costInput}
              onChange={setCostInput}
            />
          </SimpleGrid>
          <Button color="gold" fullWidth loading={savingPos} onClick={onSavePosition}>
            保存持仓
          </Button>
        </Stack>
      </Modal>
    </Paper>
  );
}

function FundRow({
  item,
  active,
  onPick,
  onEdit,
  onRemove,
}: {
  item: FundItem;
  active: boolean;
  onPick: () => void;
  onEdit: () => void;
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
          <Button
            mt="xs"
            size="compact-xs"
            variant="light"
            color="gold"
            aria-label={`编辑持仓 ${item.name}`}
            onClick={(event) => {
              event.stopPropagation();
              onEdit();
            }}
          >
            编辑持仓
          </Button>
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
            {item.shares && item.cost ? (
              <>
                <Text size="sm" fw={600} c={tone(item.today_pnl)}>
                  今日{money(item.today_pnl)}
                </Text>
                <Text size="xs" c={tone(item.total_pnl)}>
                  累计{money(item.total_pnl)}
                </Text>
              </>
            ) : (
              <Text size="xs" c="dimmed">
                {item.estimate_nav != null ? `估${fmt(item.estimate_nav, 4)}` : fmt(item.nav, 4)}
              </Text>
            )}
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
