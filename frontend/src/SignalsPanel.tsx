import { useCallback, useState } from "react";
import { Alert, Badge, Button, Group, Loader, SegmentedControl, Paper, SimpleGrid, Stack, Text } from "@mantine/core";
import { api } from "./api";
import { usePolling } from "./usePolling";
import { SignalSettingsPage } from "./SignalSettingsPage";

function percent(value: number | null | undefined) {
  return value == null ? "—" : `${value > 0 ? "+" : ""}${value.toFixed(2)}%`;
}

export function SignalsPanel() {
  const [mode, setMode] = useState<"intraday" | "close">("intraday");
  const [page, setPage] = useState<"results" | "settings">("results");
  const fetchSignals = useCallback((signal: AbortSignal) => api.stockSignals(signal, mode), [mode]);
  const { data: response, error, loading, reload } = usePolling(fetchSignals);
  const data = response && (response.mode || "intraday") === mode ? response : null;
  const [busy, setBusy] = useState(false);
  const [refreshError, setRefreshError] = useState<string | null>(null);
  const [analyzing, setAnalyzing] = useState(false);
  const [savingBoards, setSavingBoards] = useState(false);
  const saveBoards = async (boards: string[]) => {
    if (!boards.length) {
      setRefreshError("请至少选择一个参与选股的板块。");
      return;
    }
    setSavingBoards(true);
    setRefreshError(null);
    try {
      await api.saveStockBoards(boards);
      await reload();
    } catch (err) {
      setRefreshError(err instanceof Error ? err.message : "板块配置保存失败");
    } finally {
      setSavingBoards(false);
    }
  };
  const analyze = async () => {
    setAnalyzing(true);
    setRefreshError(null);
    try {
      await api.analyzeStockSignals(mode);
      await reload();
    } catch (err) {
      setRefreshError(err instanceof Error ? err.message : "AI 分析启动失败");
    } finally {
      setAnalyzing(false);
    }
  };
  const refresh = async () => {
    setBusy(true);
    setRefreshError(null);
    try {
      await api.refreshStockSignals(mode);
      await reload();
    } catch (err) {
      setRefreshError(err instanceof Error ? err.message : "扫描启动失败");
    } finally {
      setBusy(false);
    }
  };
  if (page === "settings" && data) {
    return <Paper className="glass" p="md"><SignalSettingsPage data={data} savingBoards={savingBoards} analyzing={analyzing} saveBoards={saveBoards} analyze={analyze} reload={reload} onBack={() => setPage("results")} />{refreshError ? <Alert color="red" mt="sm">{refreshError}</Alert> : null}</Paper>;
  }
  return (
    <Paper className="glass" p="md">
      <Group justify="space-between" mb="sm">
        <div>
          <Text fw={600}>全 A 股 · 策略观察</Text>
          <Text size="xs" c="dimmed">{mode === "close" ? `观察池基准日 ${data?.trade_date || "尚未生成"} · 供下一交易日参考` : `${data?.session || "读取中"} · ${data?.items.length ?? 0} 只候选`}</Text>
        </div>
        <Group gap="xs"><Button variant="subtle" size="sm" disabled={!data} onClick={() => setPage("settings")}>设置与说明</Button><Button color="gold" variant="light" size="sm" loading={busy || data?.running} disabled={mode === "close" && !data?.can_generate_close} onClick={() => void refresh()}>{mode === "close" ? "生成收盘观察池" : "刷新筛选"}</Button></Group>
      </Group>
      <SegmentedControl fullWidth mb="sm" value={mode} onChange={(value) => setMode(value as "intraday" | "close")} data={[{ value: "intraday", label: "盘中观察" }, { value: "close", label: "收盘选股" }]} />
      {mode === "close" ? <Text size="xs" c="dimmed" mb="sm">{data?.running ? "正在确认收盘数据并生成观察池…" : data?.can_generate_close ? "15:30后确认当日日线；生成后保留至下次成功更新。" : "交易日15:30后可生成；当前展示最近保存的观察池。"}</Text> : null}
      {data?.errors.map((message) => <Alert key={message} color="yellow" mb="sm">{message}</Alert>)}
      {mode !== "close" && data?.stale && data.fetched_at ? <Text size="xs" c="yellow" mb="sm">行情已过期，刷新后再查看。</Text> : null}
      {mode === "intraday" && data?.running ? <Text size="xs" c="dimmed" mb="sm">正在扫描与研究：已读取 {data.progress} 只…</Text> : null}
      {data?.ai?.status === "running" ? <Text size="xs" c="dimmed" mb="sm">AI 正在点评本轮候选…</Text> : null}
      {error || refreshError ? <Alert color="red" mb="sm">{error || refreshError}<Button variant="subtle" size="compact-xs" onClick={() => void reload()}>重试</Button></Alert> : null}
      {(loading || !data) && !error ? <Loader color="gold" size="sm" /> : null}
      {data ? (
        <Stack gap="sm">
          {!data.items.length && !data.running ? <Text size="sm" c="dimmed" ta="center" py="sm">{data.fetched_at ? "本轮没有技术候选。" : mode === "close" ? "尚无收盘观察池，请在交易日15:30后生成。" : "尚未取得可用行情，请启动扫描或稍后重试。"}</Text> : null}
          {data.items.map((item) => {
            const comment = data.ai?.items.find((row) => row.code === item.code);
            return (
            <Paper className="day-card" p="sm" key={item.code}>
              <Group justify="space-between" mb="xs">
                <div><Text fw={600}>{item.name}</Text><Text size="xs" c="dimmed">{item.code} · {item.board} · {mode === "close" ? `${data.trade_date} 收盘参考` : `报价时刻 ${item.quote_time || "未知"}`}</Text></div>
                <div style={{ textAlign: "right" }}><Text fw={700} c={item.change_pct >= 0 ? "red" : "teal"}>{item.price.toFixed(2)} · {percent(item.change_pct)}</Text><Badge size="xs" color="yellow">{item.status}</Badge></div>
              </Group>
              <SimpleGrid cols={{ base: 2, sm: 4 }} spacing="xs">
                <div><Text size="xs" c="dimmed">回踩观察区（元）</Text><Text size="sm">{item.watch_low.toFixed(2)}～{item.watch_high.toFixed(2)}</Text></div>
                <div><Text size="xs" c="dimmed">突破参考（{mode === "close" ? "基准日" : "当日"}高点）</Text><Text size="sm">{item.breakout_price.toFixed(2)}</Text></div>
                <div><Text size="xs" c="dimmed">失效参考（{mode === "close" ? "基准日" : "当日"}低点）</Text><Text size="sm">{item.invalidation_price.toFixed(2)}</Text></div>
                <div><Text size="xs" c="dimmed">成交额 / 换手率</Text><Text size="sm">{(item.amount / 100000000).toFixed(2)} 亿 / {item.turnover_pct.toFixed(2)}%</Text></div>
              </SimpleGrid>
              <Text size="xs" c="dimmed" mt="xs">{item.strategy_labels?.join(" / ") || item.reason}{item.historical_as_of ? ` · 信号日 ${item.historical_as_of}` : ""}</Text>
              {item.factors ? <Group gap={4} mt={4}><Badge size="xs" variant="light" color={item.factors.fundamentals.status === "pass" ? "teal" : "yellow"}>{item.factors.fundamentals.label}</Badge><Badge size="xs" variant="light" color={item.factors.industry.status === "pass" ? "teal" : "yellow"}>{item.factors.industry.name || "行业未知"} · {item.factors.industry.label}</Badge></Group> : null}
              <details style={{ marginTop: 8 }}><summary style={{ cursor: "pointer", fontSize: 12 }}>查看财报、行业与验证依据</summary>
              {item.historical_as_of ? <Text size="xs" c="dimmed" mt={4}>技术信号日 {item.historical_as_of} · 20日均价 {item.ma20?.toFixed(2)} · 60日均价 {item.ma60?.toFixed(2)} · 日收益波动率 {percent(item.vol20_pct)}</Text> : null}
              {item.factors ? (
                <Paper className="stat-tile" p="xs" mt="xs">
                  <Group gap="xs"><Badge size="xs" color={item.factors.fundamentals.status === "pass" ? "teal" : "yellow"}>{item.factors.fundamentals.label}</Badge><Badge size="xs" color={item.factors.industry.status === "pass" ? "teal" : "yellow"}>{item.factors.industry.name || "行业未知"} · {item.factors.industry.label}</Badge></Group>
                  <Text size="xs" mt={4}>报告期 {item.factors.fundamentals.report_date || "未知"} · 公告日 {item.factors.fundamentals.notice_date || "未知"}</Text>
                  <Text size="xs" mt={4}>营收同比 {percent(item.factors.fundamentals.revenue_yoy_pct)} · 归母净利润同比 {percent(item.factors.fundamentals.profit_yoy_pct)} · 加权ROE {percent(item.factors.fundamentals.roe_pct)}</Text>
                  <Text size="xs" c="dimmed" mt={4}>归母净利润 {item.factors.fundamentals.net_profit == null ? "—" : `${(item.factors.fundamentals.net_profit / 100000000).toFixed(2)} 亿元`}；财务指标为报告期累计值，ROE未经年化。{item.factors.fundamentals.reasons.join("；")}</Text>
                  <Text size="xs" mt={4}>行业当日涨跌 {percent(item.factors.industry.change_pct)} · 相对全A等权 {item.factors.industry.relative_pct == null ? "—" : `${item.factors.industry.relative_pct > 0 ? "+" : ""}${item.factors.industry.relative_pct.toFixed(2)} 个百分点`}</Text>
                  <Text size="xs" c="dimmed" mt={4}>{item.factors.industry.method}{item.factors.industry.sample_count != null ? ` · 同业有效报价 ${item.factors.industry.sample_count}/${item.factors.industry.member_count} 只 · 覆盖 ${item.factors.industry.coverage_pct?.toFixed(1)}%` : ""}</Text>
                  <Text size="xs" c="dimmed" mt={4}>{item.factors.industry.reason} · 行业行情时间 {item.factors.industry.as_of?.replace("T", " ") || "未知"}</Text>
                  {item.factors.blockers.length ? <Text size="xs" c="yellow" mt={4}>等待确认：{item.factors.blockers.join("；")}</Text> : null}
                  <Text size="xs" c="dimmed" mt={4}>{item.factors.fundamentals.source}；{item.factors.industry.source}</Text>
                </Paper>
              ) : null}
              {item.validation?.length ? <Text size="xs" c={item.priority_eligible ? "dimmed" : "yellow"} mt={4}>{item.validation.join(" · ")}{item.priority_eligible ? "" : "；AI 仅可等待或暂不考虑。"}</Text> : null}
              </details>
              {comment ? (
                <Stack gap={4} mt="xs">
                  <Group gap="xs"><Badge size="sm" color={comment.view === "优先观察" ? "teal" : "gray"}>AI · {comment.view}</Badge><Text size="xs">{comment.trigger}</Text></Group>
                  <Text size="sm">{comment.reason}</Text>
                  <Text size="xs" c="yellow">风险：{comment.risk}</Text>
                  <Text size="xs" c="dimmed">{comment.trigger === "回踩观察" ? `价格条件：回到 ${item.watch_low.toFixed(2)}～${item.watch_high.toFixed(2)} 元观察，跌破 ${item.invalidation_price.toFixed(2)} 元则本轮条件失效。` : comment.trigger === "突破观察" ? `价格条件：观察能否突破 ${item.breakout_price.toFixed(2)} 元；这是${mode === "close" ? "基准日" : "当日"}高点参考，不保证突破有效。` : "价格条件：等待，无新增买入触发条件。"}</Text>
                </Stack>
              ) : null}
            </Paper>
            );
          })}
        </Stack>
      ) : null}
    </Paper>
  );
}
