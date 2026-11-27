import { useCallback, useState } from "react";
import { Alert, Badge, Button, Group, Loader, MultiSelect, NumberInput, Paper, SegmentedControl, SimpleGrid, Stack, Switch, Table, Text } from "@mantine/core";
import { api } from "./api";
import { EquityCurve } from "./EquityCurve";
import type { StockSimConfig, StockSimPeriod, StockSimPosition, StockSimStrategy, StockSimTrade } from "./types";
import { usePolling } from "./usePolling";

const strategyOptions = [
  { value: "trend", label: "趋势延续" },
  { value: "pullback", label: "趋势回调" },
  { value: "low_vol", label: "低波动观察" },
];
const defaults: StockSimConfig = {
  starting_cash: 20000, strategies: ["trend", "pullback", "low_vol"], price_min: 0, price_max: 50,
  max_positions: 4, max_position_pct: 25, hold_days: 5, stop_loss_pct: 5, take_profit_pct: 10,
  max_drawdown_pct: 15, require_factors: false, commission_pct: 0.03, min_commission: 5, slippage_pct: 0.05,
};
const fields = {
  starting_cash: { label: "起始资金（元）", min: 1000, max: 10000000, step: 1000 },
  price_min: { label: "最低股价（元）", min: 0, max: 99999, step: 1 },
  price_max: { label: "最高股价（元）", min: 0.01, max: 100000, step: 1 },
  max_positions: { label: "最多同时持仓", min: 1, max: 20, step: 1 },
  max_position_pct: { label: "单股买入上限（%）", min: 5, max: 100, step: 1 },
  hold_days: { label: "持有交易日", min: 1, max: 60, step: 1 },
  stop_loss_pct: { label: "止损（%）", min: 0, max: 50, step: 1 },
  take_profit_pct: { label: "止盈（%）", min: 0, max: 100, step: 1 },
  max_drawdown_pct: { label: "停止新买入的回撤（%）", min: 0, max: 100, step: 1 },
  commission_pct: { label: "佣金（%）", min: 0, max: 1, step: 0.01 },
  min_commission: { label: "最低佣金（元/笔）", min: 0, max: 100, step: 1 },
  slippage_pct: { label: "单边滑点（%）", min: 0, max: 2, step: 0.01 },
};
const fieldKeys = Object.keys(fields) as (keyof typeof fields)[];
const money = new Intl.NumberFormat("zh-CN", { style: "currency", currency: "CNY" });
const number = new Intl.NumberFormat("zh-CN");

function pct(value: number | null) {
  return value === null ? "—" : `${value > 0 ? "+" : ""}${value.toFixed(2)}%`;
}

function clock(value: string | null) {
  return value?.replace("T", " ").slice(0, 19) || "—";
}

function SimConfigForm({ config, disabled, onSave }: {
  config?: StockSimConfig;
  disabled: boolean;
  onSave: (values: StockSimConfig) => Promise<void>;
}) {
  const initial = config || defaults;
  const [values, setValues] = useState(() => Object.fromEntries(fieldKeys.map((key) => [key, initial[key] ?? ""])));
  const [strategies, setStrategies] = useState(initial.strategies);
  const [factors, setFactors] = useState(initial.require_factors);
  const [error, setError] = useState<string>();

  async function save() {
    const parsed = Object.fromEntries(fieldKeys.map((key) => [key, values[key] === "" ? null : Number(values[key])]));
    const invalid = fieldKeys.find((key) => {
      const value = parsed[key];
      return value === null ? key !== "price_max"
        : !Number.isFinite(value) || value < fields[key].min || value > fields[key].max;
    });
    if (invalid) { setError(`请检查${fields[invalid].label}。`); return; }
    if (!strategies.length || (parsed.price_max !== null && parsed.price_max < Number(parsed.price_min))) {
      setError("至少选择一个策略，最高股价须大于或等于最低股价。");
      return;
    }
    setError(undefined);
    const next = { ...initial, ...parsed, strategies, require_factors: factors } as StockSimConfig;
    await onSave(next);
  }

  return <form onSubmit={(event) => { event.preventDefault(); void save(); }}>
    <Stack mt="xs" gap="sm">
      <MultiSelect label="策略信号" data={strategyOptions} value={strategies} disabled={disabled}
        onChange={(value) => setStrategies(value as StockSimStrategy[])} />
      <SimpleGrid cols={{ base: 2, sm: 3, md: 4 }} spacing="xs">
        {fieldKeys.map((key) => <NumberInput key={key} {...fields[key]} size="xs"
          value={values[key]} placeholder={key === "price_max" ? "不限" : undefined}
          allowDecimal={key !== "hold_days" && key !== "max_positions"}
          disabled={disabled || (key === "starting_cash" && !!config)}
          onChange={(value) => setValues((previous) => ({ ...previous, [key]: value }))} />)}
      </SimpleGrid>
      <Switch size="sm" checked={factors} disabled={disabled} onChange={(event) => setFactors(event.currentTarget.checked)}
        label="仅买入通过基本面、行业和大盘检查的候选" />
      <Text size="xs" c="dimmed">止盈、止损或回撤填 0 可关闭对应条件。建账时固定起始资金，后续保存的策略与风控参数在下一轮检查生效。</Text>
      {error ? <Alert color="red" py="xs">{error}</Alert> : null}
      <Group><Button type="submit" loading={disabled} size="sm">{config ? "保存策略配置" : "创建模拟账户"}</Button></Group>
    </Stack>
  </form>;
}

function Positions({ rows }: { rows: StockSimPosition[] }) {
  return <Paper className="stat-tile" p="sm">
    <Text size="sm" fw={600} mb="xs">当前持仓</Text>
    {rows.length ? <Table.ScrollContainer minWidth={600}><Table verticalSpacing={6} fz="xs">
      <Table.Thead><Table.Tr>{["股票", "股数", "均价 / 最新价", "浮动盈亏", "最新报价"].map((label) => <Table.Th key={label}>{label}</Table.Th>)}</Table.Tr></Table.Thead>
      <Table.Tbody>{rows.map((row) => <Table.Tr key={row.symbol}>
        <Table.Td>{row.name} · {row.code}{row.exit_reason ? <Text size="xs" c="orange">等待卖出 · {row.exit_reason}</Text> : null}</Table.Td>
        <Table.Td>{number.format(row.shares)}</Table.Td><Table.Td>{row.avg_cost.toFixed(3)} / {row.price.toFixed(2)}</Table.Td>
        <Table.Td>{money.format(row.pnl)}</Table.Td><Table.Td>{clock(row.marked_at)}</Table.Td>
      </Table.Tr>)}</Table.Tbody>
    </Table></Table.ScrollContainer> : <Text size="xs" c="dimmed">暂无持仓。</Text>}
  </Paper>;
}

function Trades({ rows, count }: { rows: StockSimTrade[]; count: number }) {
  return <Paper className="stat-tile" p="sm">
    <Group justify="space-between" mb="xs"><Text size="sm" fw={600}>阶段成交</Text>
      <Text size="xs" c="dimmed">{count > rows.length ? `显示最近 ${rows.length} 笔，共 ${count} 笔` : `${count} 笔`}</Text>
    </Group>
    {rows.length ? <Table.ScrollContainer minWidth={760}><Table verticalSpacing={6} fz="xs">
      <Table.Thead><Table.Tr>{["成交时间", "方向 / 股票", "股数 × 价格", "费用", "已实现盈亏", "触发依据"].map((label) => <Table.Th key={label}>{label}</Table.Th>)}</Table.Tr></Table.Thead>
      <Table.Tbody>{rows.map((row) => <Table.Tr key={row.id}>
        <Table.Td>{clock(row.filled_at)}<Text size="xs" c="dimmed">报价 {row.quoted_at.slice(11, 19)}</Text></Table.Td>
        <Table.Td>{row.side === "buy" ? "买入" : "卖出"} · {row.name} {row.code}</Table.Td>
        <Table.Td>{number.format(row.shares)} × {row.price.toFixed(2)}</Table.Td>
        <Table.Td>{money.format(row.fees)}</Table.Td><Table.Td>{row.realized === null ? "—" : money.format(row.realized)}</Table.Td>
        <Table.Td>{row.reason}{row.signal_day ? <Text size="xs" c="dimmed">{row.signal_day} 的收盘信号</Text> : null}</Table.Td>
      </Table.Tr>)}</Table.Tbody>
    </Table></Table.ScrollContainer> : <Text size="xs" c="dimmed">这个阶段还没有成交。</Text>}
  </Paper>;
}

export function StockSimulatorPanel() {
  const [period, setPeriod] = useState<StockSimPeriod>("30");
  const fetchView = useCallback((signal: AbortSignal) => api.stockSimulator(period, signal), [period]);
  const { data, loading, error, reload } = usePolling(fetchView);
  const [busy, setBusy] = useState<"config" | "run" | null>(null);
  const [failure, setFailure] = useState<string>();

  async function submit(action: "config" | "run", send: () => Promise<unknown>) {
    setBusy(action);
    setFailure(undefined);
    try {
      await send();
      await reload();
    } catch (err) {
      setFailure(err instanceof Error ? err.message : "模拟盘操作失败。");
    } finally {
      setBusy(null);
    }
  }

  if (loading) return <Loader size="sm" mt="lg" />;
  const account = data?.account;
  const latest = data?.account ? data.curve[data.curve.length - 1] : undefined;
  return <Paper className="glass" p="md"><Stack gap="sm">
    <Group justify="space-between">
      <div>
        <Text fw={700}>自动量化模拟盘</Text>
        <Text size="xs" c="dimmed">沪深主板 · 公开行情 · 虚拟资金</Text>
      </div>
      {account ? <Group gap="xs">
        <Badge color={account.running ? "teal" : "gray"}>{account.running ? "运行中" : "已暂停"}</Badge>
        <Button size="xs" variant={account.running ? "light" : "filled"} loading={busy === "run"} disabled={busy === "config"}
          onClick={() => void submit("run", () => api.setStockSimulatorRunning(!account.running))}>
          {account.running ? "暂停模拟" : "启动模拟"}
        </Button>
      </Group> : null}
    </Group>
    <Text size="xs" c="dimmed">交易日 09:35–10:00 检查一次入场，信号取上一交易日收盘候选。连续竞价期间约每分钟检查退出，买入当日不可卖出。服务器后台运行。</Text>
    {error || failure ? <Alert color="red" py="xs">{failure || error}</Alert> : null}
    {data?.account ? <Stack gap="sm">
      <Paper className="stat-tile" p="sm">
        <SimpleGrid cols={{ base: 2, sm: 4 }} spacing="xs">
          <div><Text size="xs" c="dimmed">模拟总资产</Text><Text fw={700}>{money.format(data.account.equity)}</Text></div>
          <div><Text size="xs" c="dimmed">可用资金</Text><Text fw={600}>{money.format(data.account.cash)}</Text></div>
          <div><Text size="xs" c="dimmed">持仓市值</Text><Text fw={600}>{money.format(data.account.market_value)}</Text></div>
          <div><Text size="xs" c="dimmed">建账以来收益</Text><Text fw={600}>{pct(data.account.return_pct)}</Text></div>
        </SimpleGrid>
        {data.account.message ? <Text size="xs" mt="xs">{data.account.message}</Text> : null}
        <Text size="xs" c="dimmed" mt={4}>最近检查 {clock(data.account.checked_at)}{data.account.entry_day ? ` · 最近入场检查 ${data.account.entry_day}` : ""} · 账户最大回撤 {data.account.max_drawdown_pct.toFixed(2)}%</Text>
      </Paper>
      <Paper className="stat-tile" p="sm">
        <Stack gap="xs">
          <Group justify="space-between"><Text fw={600} size="sm">阶段表现</Text>
            <SegmentedControl size="xs" value={period} onChange={(value) => setPeriod(value as StockSimPeriod)}
              data={[{ value: "7", label: "7 天" }, { value: "30", label: "30 天" }, { value: "90", label: "90 天" }, { value: "all", label: "全部" }]} />
          </Group>
          <SimpleGrid cols={{ base: 2, sm: 4 }} spacing="xs">
            <div><Text size="xs" c="dimmed">阶段收益</Text><Text fw={600}>{pct(data.period.return_pct)}</Text></div>
            <div><Text size="xs" c="dimmed">同期沪深 300</Text><Text fw={600}>{pct(data.period.benchmark_pct)}</Text></div>
            <div><Text size="xs" c="dimmed">阶段最大回撤</Text><Text fw={600}>{data.period.max_drawdown_pct == null ? "—" : `${data.period.max_drawdown_pct.toFixed(2)}%`}</Text></div>
            <div><Text size="xs" c="dimmed">已实现盈亏</Text><Text fw={600}>{money.format(data.period.realized)}</Text></div>
          </SimpleGrid>
          <EquityCurve points={data.curve} baseline={data.period.base_equity} />
          {data.curve.length < 2 ? <Text size="xs" c="dimmed">累计两个交易日的资产记录后显示曲线。</Text> : null}
          <Text size="xs" c="dimmed">阶段费用（含滑点）{money.format(data.period.fees)}{latest ? ` · ${latest.date} ${latest.final_mark ? "收盘估值" : "最近估值"}${latest.stale_positions ? `，${latest.stale_positions} 只沿用上次有效报价` : ""}` : ""}</Text>
        </Stack>
      </Paper>
      <Positions rows={data.positions} />
      <Trades rows={data.trades} count={data.period.trade_count} />
    </Stack> : null}
    {data ? <Paper className="stat-tile" p="sm"><details open={!account || undefined}>
      <summary style={{ cursor: "pointer" }}><Text span size="sm" fw={600}>{account ? "策略、仓位与费率配置" : "设置虚拟资金和策略"}</Text></summary>
      <SimConfigForm key={JSON.stringify(account?.config || null)} config={account?.config} disabled={busy !== null}
        onSave={(values) => submit("config", () => api.saveStockSimulator(values))} />
    </details></Paper> : null}
    <Text size="xs" c="dimmed">按公开买一、卖一和可见数量近似成交，费用另扣滑点和卖出税。停牌、缺报价或可见数量不足时可能跳过或只成交部分。账户估值按报价计，分红送转未单独入账。</Text>
  </Stack></Paper>;
}
