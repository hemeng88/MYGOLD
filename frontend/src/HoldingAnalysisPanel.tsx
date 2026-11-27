import { useEffect, useState } from "react";
import { Alert, Badge, Button, Group, Paper, SimpleGrid, Skeleton, Stack, Text } from "@mantine/core";
import { api } from "./api";
import { AIModelPicker, StockAIResults, useAISelection } from "./StockAIResults";
import type { HoldingAnalysis, HoldingPriceReference } from "./types";

const money = new Intl.NumberFormat("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const sharesFormat = new Intl.NumberFormat("zh-CN", { maximumFractionDigits: 4 });
const signalLabel = { stop_hit: "触及止损参考", target_hit: "触及止盈参考", between: "未触及参考线", reference: "价格参考" };

function signed(value: number, format: Intl.NumberFormat) {
  return (value > 0 ? "+" : "") + format.format(value);
}

function Pnl({ reference }: { reference: HoldingPriceReference | null }) {
  if (!reference) return <Text size="xs" c="dimmed">暂无盈亏估算</Text>;
  return <Text size="xs" c={reference.pnl > 0 ? "red" : reference.pnl < 0 ? "teal" : "dimmed"}>
    {signed(reference.pnl, money)} 元 · {signed(reference.pnl_pct, money)}%
  </Text>;
}

export function HoldingAnalysisPanel({ code, shares, costPrice, edit }: {
  code: string;
  shares: number | null | undefined;
  costPrice: number | null | undefined;
  edit: () => void;
}) {
  const [result, setResult] = useState<HoldingAnalysis | null>(null);
  const [revision, setRevision] = useState(0);
  const [loading, setLoading] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const valid = (shares ?? 0) > 0 && (costPrice ?? 0) > 0;
  const models = useAISelection(result?.ai_results ?? []);
  const running = result?.ai_results.some((model) => model.status === "running") ?? false;
  const selectedRunning = models.selected.some((model) => model.status === "running");
  const pending = models.selected.filter((model) => model.status !== "ready" || !model.items.some((item) => item.code === result?.code));
  const snapshotId = result?.snapshot_id;
  const track = running || result?.can_analyze;

  useEffect(() => {
    setResult(null);
    setError("");
    if (!valid) return;
    const controller = new AbortController();
    setLoading(true);
    api.holdingPreview(code, controller.signal).then((preview) => {
      if (!controller.signal.aborted) setResult(preview);
    }).catch((err) => {
      if (!controller.signal.aborted) setError(err instanceof Error ? err.message : "持仓分析获取失败。");
    }).finally(() => {
      if (!controller.signal.aborted) setLoading(false);
    });
    return () => controller.abort();
  }, [code, shares, costPrice, revision, valid]);

  useEffect(() => {
    if (!snapshotId || !track) return;
    const controller = new AbortController();
    let timer: number;
    const poll = async () => {
      try {
        const next = await api.holdingAnalysisStatus(code, snapshotId, controller.signal);
        if (controller.signal.aborted) return;
        setResult((current) => current?.snapshot_id === snapshotId ? next : current);
        const active = next.ai_results.some((model) => model.status === "running");
        if (active || next.can_analyze) timer = window.setTimeout(poll, active ? 2200 : 18000);
      } catch (err) {
        if (controller.signal.aborted) return;
        setError(err instanceof Error ? err.message : "读取 AI 复核状态失败，请刷新价位。");
        setResult((current) => current?.snapshot_id === snapshotId ? null : current);
      }
    };
    timer = window.setTimeout(poll, running ? 1800 : 18000);
    return () => { controller.abort(); window.clearTimeout(timer); };
  }, [code, snapshotId, running, track]);

  async function analyze() {
    if (!result?.can_analyze || !pending.length || submitting || selectedRunning) return;
    setSubmitting(true);
    setError("");
    try {
      const next = await api.analyzeHolding(code, result.snapshot_id, pending.map((model) => model.profile_id));
      setResult((current) => current?.snapshot_id === next.snapshot_id ? next : current);
      const failures = next.ai_results.filter((model) => model.request_error).map((model) => `${model.name} · ${model.request_error}`);
      if (failures.length) setError(failures.join("；"));
    } catch (err) {
      setError(err instanceof Error ? err.message : "AI 复核提交失败。");
    } finally {
      setSubmitting(false);
    }
  }

  return <Paper className="stat-tile" p="sm" withBorder>
    <Stack gap="xs">
      <Group justify="space-between">
        <Text fw={700} size="sm">持仓止盈止损</Text>
        {valid ? <Button variant="subtle" size="compact-xs" onClick={() => setRevision((value) => value + 1)}
          disabled={submitting || running} loading={loading}>刷新参考价</Button>
          : <Button variant="light" size="compact-xs" onClick={edit}>填写持仓</Button>}
      </Group>
      {!valid ? <Text size="xs" c="dimmed">保存这只股票的股数和成本价后，即可查看退出参考。</Text> : null}
      {error ? <Alert color="red" py="xs">{error}</Alert> : null}
      {valid && loading ? <Skeleton height={72} /> : null}
      {valid && result ? <>
        <Group gap="xs">
          <Badge color={result.signal === "stop_hit" ? "orange" : result.signal === "target_hit" ? "teal" : "gray"}>
            {signalLabel[result.signal]}
          </Badge>
          <Text size="xs">{result.signal_note}</Text>
        </Group>
        <SimpleGrid cols={{ base: 2, sm: 4 }} spacing="xs">
          <div><Text size="xs" c="dimmed">已记录持仓 / 成本</Text><Text size="sm" fw={600}>{sharesFormat.format(result.shares)} 股</Text>
            <Text size="xs">{sharesFormat.format(result.cost_price)} 元/股</Text></div>
          <div><Text size="xs" c="dimmed">{result.current ? "报价 / 浮动盈亏" : "参考价格 / 浮动盈亏"}</Text>
            <Text size="sm" fw={600}>{result.price === null ? "—" : money.format(result.price) + " 元"}</Text><Pnl reference={result.pnl} /></div>
          <div><Text size="xs" c="dimmed">止损参考</Text><Text size="sm" fw={600}>{money.format(result.plan.stop.price)} 元</Text><Pnl reference={result.plan.stop} /></div>
          <div><Text size="xs" c="dimmed">止盈参考</Text><Text size="sm" fw={600}>{money.format(result.plan.take_profit.price)} 元</Text><Pnl reference={result.plan.take_profit} /></div>
        </SimpleGrid>
        <Text size="xs" c="dimmed">{result.price_source || "行情未取得"} · {result.quote_at?.replace("T", " ").slice(0, 19) || result.price_date || "日期未知"} · 盈亏未扣交易费用</Text>
        {result.visible_buy_shares !== null && result.visible_buy_shares < result.shares ? <Text size="xs" c="yellow">
          {result.visible_buy_shares === 0 ? "当前报价无可见买盘。" : `买一可见 ${sharesFormat.format(result.visible_buy_shares)} 股，少于记录的持仓。`}
        </Text> : null}
        <details>
          <summary style={{ cursor: "pointer" }}><Text span size="xs">查看价格依据</Text></summary>
          <Text size="xs" c="dimmed" mt={4}>成本基线为止损 {result.plan.cost_loss_pct}%、止盈 {result.plan.cost_profit_pct}%。{result.plan.atr14 === null
            ? "本次缺少对齐的完整日线，采用成本基线。"
            : `止损线还参考近 20 日最高收盘价减 ${result.plan.atr_multiple} 倍 ATR，止盈线还参考近 20 日高点及与止损线的波动距离。ATR(14) 为 ${result.plan.atr14.toFixed(3)} 元，日线截至 ${result.basis_date}。`}</Text>
          <Text size="xs" c="dimmed" mt={4}>持仓按填报值计算，可卖股数以券商为准。触及价位时，实际成交还取决于买盘和交易状态。</Text>
        </details>
        <Group align="end" gap="xs">
          <div style={{ flex: "1 1 190px" }}><AIModelPicker models={models.available} value={models.ids} onChange={models.setChoices} disabled={submitting} /></div>
          {models.available.length ? <Button variant="light" size="xs" loading={submitting || selectedRunning}
            disabled={!result.can_analyze || !pending.length} onClick={() => void analyze()}>
            {models.ids.length && !pending.length ? "所选模型已复核" : `AI 复核 · ${pending.length} 个模型`}
          </Button> : null}
        </Group>
        {models.available.length ? <Text size="xs" c="dimmed">点击复核会向所选模型提供这只股票的股数、成本和分析依据。</Text> : null}
        {result.analysis_issue ? <Text size="xs" c="yellow">{result.analysis_issue}</Text> : null}
        <StockAIResults results={result.ai_results} code={result.code} />
      </> : null}
    </Stack>
  </Paper>;
}
