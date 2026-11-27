import { useEffect, useRef, useState } from "react";
import { Alert, Button, Group, NumberInput, Paper, SimpleGrid, Stack, Text } from "@mantine/core";
import { api } from "./api";
import type { StockPortfolioConfig, StockPortfolioResult, StockSignals } from "./types";
import { usePolling } from "./usePolling";

const fields = {
  starting_cash: { label: "起始资金（元）", min: 1000, max: 10000000, step: 1000 },
  max_positions: { label: "最多同时持仓", min: 1, max: 20, step: 1 },
  max_position_pct: { label: "单股买入上限（%）", min: 5, max: 100, step: 5 },
  commission_pct: { label: "佣金（%）", min: 0, max: 1, step: 0.01 },
  min_commission: { label: "每笔最低佣金（元）", min: 0, max: 100, step: 1 },
  slippage_pct: { label: "每边滑点（%）", min: 0, max: 2, step: 0.01 },
};
const keys = Object.keys(fields) as (keyof StockPortfolioConfig)[];
const defaults: StockPortfolioConfig = {
  starting_cash: 20000, max_positions: 4, max_position_pct: 25,
  commission_pct: 0.03, min_commission: 5, slippage_pct: 0.05,
};
const money = new Intl.NumberFormat("zh-CN", { style: "currency", currency: "CNY" });

function EquityCurve({ result }: { result: StockPortfolioResult }) {
  const canvas = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    const element = canvas.current;
    const ctx = element?.getContext("2d");
    if (!element || !ctx || result.curve.length < 2) return;
    const values = result.curve.map((row) => row.equity);
    const low = Math.min(result.starting_cash, ...values);
    const range = Math.max(1, Math.max(result.starting_cash, ...values) - low);
    const width = element.width, height = element.height, padding = 12;
    const y = (value: number) => height - padding - (value - low) / range * (height - 2 * padding);
    ctx.clearRect(0, 0, width, height);
    ctx.beginPath();
    ctx.strokeStyle = "#8491a2";
    ctx.setLineDash([8, 5]);
    ctx.moveTo(padding, y(result.starting_cash));
    ctx.lineTo(width - padding, y(result.starting_cash));
    ctx.stroke();
    ctx.beginPath();
    ctx.setLineDash([]);
    ctx.lineWidth = 3;
    ctx.strokeStyle = "#c89839";
    values.forEach((value, i) => {
      const x = padding + i * (width - 2 * padding) / (values.length - 1);
      if (i === 0) ctx.moveTo(x, y(value));
      else ctx.lineTo(x, y(value));
    });
    ctx.stroke();
  }, [result]);
  return <div>
    <Text size="xs" c="dimmed">每日模拟资产 · 虚线为起始资金</Text>
    <canvas ref={canvas} width={740} height={168} style={{ width: "100%", display: "block" }}
      role="img" aria-label={`从${money.format(result.starting_cash)}到${money.format(result.end_equity)}的模拟资产走势，最大回撤${result.max_drawdown_pct}%`} />
    <Group justify="space-between"><Text size="xs" c="dimmed">{result.start_date}</Text><Text size="xs" c="dimmed">{result.end_date}</Text></Group>
  </div>;
}

export function PortfolioStudyPanel({ data }: { data: StockSignals }) {
  const [inputs, setInputs] = useState<Record<keyof StockPortfolioConfig, number | string>>(defaults);
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const { data: job, error: pollError, reload } = usePolling(api.stockPortfolioStatus);
  const canRun = data.complete && data.allowed_boards.includes("主板") && !!data.research?.sample_bands && !!data.research.split_date;
  const valid = keys.every((key) => {
    const value = inputs[key];
    return typeof value === "number" && value >= fields[key].min && value <= fields[key].max;
  }) && Number.isInteger(inputs.max_positions);
  const running = job?.status === "running";
  const result = job?.status === "complete" ? job.result : undefined;

  async function start() {
    if (!valid || !canRun || running || starting) return;
    setStarting(true);
    setError(null);
    try {
      await api.startStockPortfolio(data.mode || "intraday", inputs as StockPortfolioConfig);
      await reload();
    } catch (err) {
      setError(err instanceof Error ? err.message : "启动组合回测失败。");
    } finally {
      setStarting(false);
    }
  }

  return <Paper className="stat-tile" p="sm">
    <Stack gap="xs">
      <Text fw={600} size="sm">主板组合回测</Text>
      <Text size="xs" c="dimmed">当前抽样股票的历史技术信号，次日收盘尝试买入，持有五个交易日。按100股整手、资金和仓位扣减；卖出另计0.05%印花税。</Text>
      <form onSubmit={(event) => { event.preventDefault(); void start(); }}>
        <SimpleGrid cols={{ base: 2, sm: 3 }} spacing="xs">
          {keys.map((key) => <NumberInput key={key} size="xs" label={fields[key].label}
            min={fields[key].min} max={fields[key].max} step={fields[key].step} value={inputs[key]}
            allowDecimal={key !== "max_positions"} onChange={(value) => setInputs((current) => ({ ...current, [key]: value }))} />)}
        </SimpleGrid>
        <Group mt="xs"><Button type="submit" size="xs" disabled={!canRun || !valid} loading={starting || running}>运行组合回测</Button>
          <Text size="xs" c="dimmed">{running ? "正在补齐未复权行情并计算组合…" : canRun ? "使用当前选股范围 · 不调用 AI" : "先在包含主板的范围完成一次选股扫描"}</Text>
        </Group>
      </form>
      {error || pollError || (job?.status === "error" && job.error) ? <Alert color="red">{error || pollError || (job?.status === "error" && job.error)}</Alert> : null}
      {result && job?.status === "complete" ? <>
        <Text size="xs" c="dimmed">模拟起始 {money.format(result.starting_cash)} · 期末 {money.format(result.end_equity)} · {result.sessions} 个交易日 · 日线可用 {result.data_symbols}/{result.sample_size} 只主板样本</Text>
        <Text size="xs" c="dimmed">股价 {job.price_min}～{job.price_max ?? "不限"} 元 · 最多 {job.config.max_positions} 只 · 单股 {job.config.max_position_pct}% · 佣金 {job.config.commission_pct}%（最低 {job.config.min_commission} 元）· 单边滑点 {job.config.slippage_pct}%</Text>
        <SimpleGrid cols={{ base: 2, sm: 4 }} spacing="xs">
          <div><Text size="xs" c="dimmed">组合收益</Text><Text fw={600}>{result.return_pct.toFixed(2)}%</Text></div>
          <div><Text size="xs" c="dimmed">同期沪深300</Text><Text fw={600}>{result.benchmark_pct.toFixed(2)}%</Text></div>
          <div><Text size="xs" c="dimmed">最大回撤</Text><Text fw={600}>{result.max_drawdown_pct.toFixed(2)}%</Text></div>
          <div><Text size="xs" c="dimmed">已平仓交易胜率</Text><Text fw={600}>{result.win_pct == null ? "—" : `${result.win_pct.toFixed(2)}%`}</Text></div>
        </SimpleGrid>
        <EquityCurve result={result} />
        <Text size="xs">平仓 {result.closed_trades} 笔 · 期末持仓 {result.open_positions} 只 · 模拟总成本 {money.format(result.cost_total)}</Text>
        <Text size="xs" c="dimmed">买入无可用成交价 {result.skipped.no_buy_fill} 次 · 超出股价范围 {result.skipped.outside_price_range} 次 · 预算不足 {result.skipped.insufficient_budget} 次 · 持仓已满 {result.skipped.position_limit} 次 · 卖出延迟累计 {result.skipped.delayed_exit_days} 个持仓交易日</Text>
      </> : null}
      <Text size="xs" c="dimmed">缺有效日线时跳过买入或延后卖出；用单一成交价且同向涨跌近似封板。当前样本有历史选择偏差，未回放历日财报、行业和实际委托；期末未平仓按行情估值。</Text>
    </Stack>
  </Paper>;
}
