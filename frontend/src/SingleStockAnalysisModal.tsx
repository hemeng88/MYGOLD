import { useEffect, useState } from "react";
import { Alert, Badge, Button, Group, Modal, Paper, SimpleGrid, Stack, Text, TextInput } from "@mantine/core";
import { api } from "./api";
import type { SingleStockReview } from "./types";

function price(value: number) {
  return `${value.toFixed(2)} 元`;
}

export function SingleStockAnalysisModal({ opened, onClose }: { opened: boolean; onClose: () => void }) {
  const [code, setCode] = useState("");
  const [result, setResult] = useState<SingleStockReview | null>(null);
  const [busy, setBusy] = useState<"lookup" | "ai" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const match = result?.code === code.trim();
  const stock = match ? result : null;
  const snapshotId = stock?.snapshot_id;
  const running = stock?.ai.status === "running";
  const track = running || stock?.can_analyze;

  useEffect(() => {
    if (!opened || !track || !snapshotId || !stock?.code) return;
    const controller = new AbortController();
    const target = stock.code;
    let timer: number;
    const poll = async () => {
      try {
        const next = await api.singleStockStatus(target, snapshotId, controller.signal);
        if (controller.signal.aborted) return;
        setResult((current) => current?.snapshot_id === snapshotId ? next : current);
        if (next.ai.status === "running" || next.can_analyze) {
          timer = window.setTimeout(poll, next.ai.status === "running" ? 2200 : 20000);
        }
      } catch (err) {
        if (controller.signal.aborted) return;
        setError(err instanceof Error ? err.message : "读取 AI 分析状态失败。");
        setResult((current) => current?.snapshot_id === snapshotId
          ? { ...current, ai: { ...current.ai, status: "waiting" } } : current);
      }
    };
    timer = window.setTimeout(poll, running ? 1800 : 20000);
    return () => { controller.abort(); window.clearTimeout(timer); };
  }, [opened, running, snapshotId, stock?.code, track]);

  async function lookup() {
    const target = code.trim();
    if (!/^\d{6}$/.test(target) || busy) return;
    setBusy("lookup");
    setError(null);
    try {
      setResult(await api.singleStockPreview(target));
    } catch (err) {
      setResult(null);
      setError(err instanceof Error ? err.message : "股票查询失败。");
    } finally {
      setBusy(null);
    }
  }

  async function analyze() {
    if (!stock || busy || running) return;
    setBusy("ai");
    setError(null);
    try {
      setResult(await api.singleStockAnalysis(stock.code, stock.snapshot_id));
    } catch (err) {
      setError(err instanceof Error ? err.message : "AI 分析请求失败。");
    } finally {
      setBusy(null);
    }
  }

  const comment = stock?.ai.status === "ready" ? stock.ai.items.find((item) => item.code === stock.code) : undefined;
  const aiDecision = comment?.view === "优先观察" && stock?.decision === "符合条件，可考虑买入" ? "符合条件，可考虑买入"
    : comment?.view === "暂不考虑" || stock?.decision === "暂不买入" ? "暂不买入" : "等待确认";
  return (
    <Modal opened={opened} onClose={onClose} title="按代码分析 A 股" size="lg">
      <Stack gap="md">
        <form onSubmit={(event) => { event.preventDefault(); void lookup(); }}>
          <Group align="end" wrap="nowrap">
            <TextInput label="股票代码" placeholder="例如 000823" inputMode="numeric" maxLength={6} style={{ flex: 1 }}
              value={code} onChange={(event) => { setCode(event.currentTarget.value); setError(null); }} disabled={!!busy || running} />
            <Button type="submit" disabled={!/^\d{6}$/.test(code.trim()) || busy === "ai" || running} loading={busy === "lookup"}>
              {stock ? "刷新行情" : "查询"}
            </Button>
          </Group>
        </form>
        {error ? <Alert color="red">{error}</Alert> : null}
        {stock ? <>
          <Group justify="space-between" align="start">
            <div><Text fw={700}>{stock.name} · {stock.code}</Text><Text size="xs" c="dimmed">{stock.board} · {stock.session}</Text></div>
            <div style={{ textAlign: "right" }}>
              <Text fw={700}>{stock.price == null ? "暂无有效价格" : price(stock.price)}</Text>
              <Text size="xs" c="dimmed">{stock.price_source} · {stock.quote_at?.replace("T", " ") ?? stock.price_date ?? "日期未知"}</Text>
            </div>
          </Group>
          <Paper p="sm" withBorder>
            <Badge color={stock.decision === "符合条件，可考虑买入" ? "teal" : stock.decision === "暂不买入" ? "red" : "yellow"}>{stock.decision}</Badge>
            <Text size="sm" mt={6}>{stock.decision_reason}</Text>
            {stock.strategy_labels.length ? <Text size="xs" c="dimmed" mt={4}>技术形态 · {stock.strategy_labels.join("、")}</Text> : null}
            {stock.plan ? <>
              <SimpleGrid cols={{ base: 1, xs: 3 }} spacing="xs" mt="sm">
                <div><Text size="xs" c="dimmed">买入参考区</Text><Text fw={600}>{stock.plan.entry_low.toFixed(2)}–{price(stock.plan.entry_high)}</Text></div>
                <div><Text size="xs" c="dimmed">卖出目标参考</Text><Text fw={600}>{price(stock.plan.target)}</Text></div>
                <div><Text size="xs" c="dimmed">失效退出价</Text><Text fw={600}>{price(stock.plan.stop)}</Text></div>
              </SimpleGrid>
              <Text size="xs" c="dimmed" mt="xs">基准日 {stock.plan.as_of} · 目标空间/风险 {stock.plan.reward_risk.toFixed(2)} · 未扣交易费用</Text>
              <Text size="xs" c="dimmed" mt={4}>{stock.plan.method} 开盘跳空或停牌时需重新核实可成交价。</Text>
            </> : null}
          </Paper>
          <Group justify="space-between">
            <Text size="sm" fw={600}>AI 单股点评</Text>
            <Button variant="light" color="teal" onClick={() => void analyze()} loading={busy === "ai" || running}
              disabled={busy === "lookup" || !stock.ai.configured || !stock.can_analyze || !!comment}>分析这只股票</Button>
          </Group>
          {!stock.ai.configured ? <Text size="sm" c="dimmed">请到选股页的「设置与说明」配置 AI 模型。</Text> : null}
          {stock.ai.error && (stock.ai.status === "failed" || stock.ai.status === "waiting")
            ? <Text size="sm" c="dimmed">{stock.ai.error}</Text> : null}
          {stock.analysis_issue ? <Text size="sm" c="dimmed">{stock.analysis_issue}</Text> : null}
          {comment ? <Paper p="sm" withBorder>
            <Text size="sm" fw={600}>{aiDecision}</Text>
            <Text size="sm" mt={4}>{comment.reason}</Text>
            <Text size="sm" mt={4} c="dimmed">风险 · {comment.risk}</Text>
          </Paper> : null}
        </> : null}
      </Stack>
    </Modal>
  );
}
