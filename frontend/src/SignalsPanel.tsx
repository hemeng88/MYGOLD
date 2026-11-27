import { useCallback, useEffect, useState } from "react";
import { Alert, Badge, Button, Checkbox, Group, Loader, NumberInput, SegmentedControl, Paper, SimpleGrid, Stack, Text } from "@mantine/core";
import { api } from "./api";
import { usePolling } from "./usePolling";
import { SignalSettingsPage } from "./SignalSettingsPage";
import { SingleStockAnalysisModal } from "./SingleStockAnalysisModal";
import { liquidityBands } from "./liquidityBands";

function percent(value: number | null | undefined) {
  return value == null ? "—" : `${value > 0 ? "+" : ""}${value.toFixed(2)}%`;
}

export function SignalsPanel() {
  const [mode, setMode] = useState<"intraday" | "close">("intraday");
  const [page, setPage] = useState<"results" | "settings">("results");
  const [singleOpen, setSingleOpen] = useState(false);
  const fetchSignals = useCallback((signal: AbortSignal) => api.stockSignals(signal, mode), [mode]);
  const { data: response, error, loading, reload } = usePolling(fetchSignals);
  const data = response && (response.mode || "intraday") === mode ? response : null;
  const [priceMin, setPriceMin] = useState<string | number>(0);
  const [priceMax, setPriceMax] = useState<string | number>(50);
  const [savingPrices, setSavingPrices] = useState(false);
  useEffect(() => {
    if (data) { setPriceMin(data.price_min ?? 0); setPriceMax(data.price_max ?? ""); }
  }, [data?.price_min, data?.price_max]);
  const savePrices = async () => {
    setSavingPrices(true); setRefreshError(null);
    try {
      await api.saveStockPrices(Number(priceMin || 0), priceMax === "" ? null : Number(priceMax));
      await reload();
    } catch (err) { setRefreshError(err instanceof Error ? err.message : "股价区间保存失败"); }
    finally { setSavingPrices(false); }
  };
  const [busy, setBusy] = useState(false);
  const [refreshError, setRefreshError] = useState<string | null>(null);
  const [analyzing, setAnalyzing] = useState(false);
  const [savingBoards, setSavingBoards] = useState(false);
  const [selectedCodes, setSelectedCodes] = useState<string[]>([]);
  const availableCodes = data?.items.map((item) => item.code) ?? [];
  const checkedCodes = availableCodes.filter((code) => selectedCodes.includes(code));
  const reviewCodes = selectedCodes.length ? checkedCodes : availableCodes;
  const reviewed = data?.ai?.reviewed_codes ?? [];
  const sameReview = data?.ai?.status === "ready" && reviewed.length === reviewCodes.length
    && reviewCodes.every((code) => reviewed.includes(code));
  const analysisLabel = sameReview ? `这 ${reviewCodes.length} 只已分析`
    : selectedCodes.length ? `AI 分析所选 ${checkedCodes.length} 只` : `AI 分析全部 ${availableCodes.length} 只`;
  const canAnalyze = !!(data?.snapshot_id && data.ai?.configured && !sameReview
    && data.complete && !data.errors.length && reviewCodes.length
    && (mode === "close" ? data.close_ready : !data.stale && data.market_date_current));
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
    if (!canAnalyze || !data?.snapshot_id) return;
    setAnalyzing(true);
    setRefreshError(null);
    try {
      const result = await api.analyzeStockSignals(mode, data.snapshot_id, reviewCodes);
      if (result.ai.status !== "running" && result.ai.status !== "ready" && result.ai.error) {
        setRefreshError(result.ai.error);
      }
      await reload();
    } catch (err) {
      setRefreshError(err instanceof Error ? err.message : "AI 分析启动失败");
      await reload();
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
    return <Paper className="glass" p="md"><SignalSettingsPage data={data} savingBoards={savingBoards} analyzing={analyzing} canAnalyze={canAnalyze} analysisLabel={analysisLabel} saveBoards={saveBoards} analyze={analyze} reload={reload} onBack={() => setPage("results")} />{refreshError ? <Alert color="red" mt="sm">{refreshError}</Alert> : null}</Paper>;
  }
  return (
    <Paper className="glass" p="md">
      <SingleStockAnalysisModal opened={singleOpen} onClose={() => setSingleOpen(false)} />
      <Group justify="space-between" mb="sm">
        <div>
          <Text fw={600}>全 A 股 · 策略观察</Text>
          <Text size="xs" c="dimmed">{mode === "close" ? `观察池基准日 ${data?.trade_date || "尚未生成"} · 供下一交易日参考` : `${data?.session || "读取中"} · ${data?.items.length ?? 0} 只候选`}</Text>
        </div>
        <Group gap="xs">
          <Button size="sm" variant="light" color="gold" onClick={() => setSingleOpen(true)}>单股分析</Button>
          <Button size="sm" variant="light" color="teal" loading={analyzing || data?.ai?.status === "running"} disabled={!canAnalyze} onClick={() => void analyze()}>
            {analysisLabel}
          </Button>
          {selectedCodes.length > 0 ? <Button variant="subtle" size="sm" onClick={() => setSelectedCodes([])}>清除勾选</Button> : null}
          <Button variant="subtle" size="sm" disabled={!data} onClick={() => setPage("settings")}>设置与说明</Button>
          <Button color="gold" variant="light" size="sm" loading={busy || data?.running} disabled={mode === "close" && !data?.can_generate_close} onClick={() => void refresh()}>{mode === "close" ? "生成收盘观察池" : "刷新筛选"}</Button>
        </Group>
      </Group>
      <SegmentedControl fullWidth mb="sm" value={mode} onChange={(value) => { setSelectedCodes([]); setMode(value as "intraday" | "close"); }} data={[{ value: "intraday", label: "盘中观察" }, { value: "close", label: "收盘选股" }]} />
      <Group gap="xs" align="end" mb="sm">
        <NumberInput label="最低股价（元/股）" value={priceMin} onChange={setPriceMin} min={0} decimalScale={2} w={120} />
        <NumberInput label="最高股价（留空不限）" value={priceMax} onChange={setPriceMax} min={0.01} decimalScale={2} w={150} />
        <Button size="sm" variant="light" loading={savingPrices} onClick={() => void savePrices()}>保存价格范围</Button>
      </Group>
      {mode === "close" ? <Text size="xs" c="dimmed" mb="sm">{data?.running ? "正在确认收盘数据并生成观察池…" : data?.can_generate_close ? "15:30后确认当日日线；生成后保留至下次成功更新。" : "交易日15:30后可生成；当前展示最近保存的观察池。"}</Text> : null}
      {data?.errors.map((message) => <Alert key={message} color="yellow" mb="sm">{message}</Alert>)}
      {mode !== "close" && data?.stale && data.fetched_at ? <Text size="xs" c="yellow" mb="sm">行情已过期，刷新后再查看。</Text> : null}
      {mode === "intraday" && data?.running ? <Text size="xs" c="dimmed" mb="sm">正在扫描与研究：已读取 {data.progress} 只…</Text> : null}
      {data?.ai?.status === "running" ? <Text size="xs" c="dimmed" mb="sm">AI 正在点评已提交的候选…</Text> : null}
      {data?.ai?.status === "failed" ? <Text size="xs" c="red" mb="sm">{data.ai.error}</Text> : null}
      {data?.ai?.status === "ready" && data.ai.archived === false ? <Text size="xs" c="yellow" mb="sm">AI 点评已完成，但保存到数据库失败。</Text> : null}
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
                <Group gap="xs" wrap="nowrap">
                  <Checkbox size="xs" disabled={!data.ai?.configured} aria-label={`选择 ${item.name} 供 AI 分析`} checked={checkedCodes.includes(item.code)}
                    onChange={(event) => {
                      const checked = event.currentTarget.checked;
                      setSelectedCodes((codes) => checked ? [...codes.filter((code) => code !== item.code), item.code] : codes.filter((code) => code !== item.code));
                    }} />
                  <div><Text fw={600}>{item.name}</Text><Text size="xs" c="dimmed">{item.code} · {item.board} · {mode === "close" ? `${data.trade_date} 收盘参考` : `报价时刻 ${item.quote_time || "未知"}`}</Text></div>
                </Group>
                <div style={{ textAlign: "right" }}><Text fw={700} c={item.change_pct >= 0 ? "red" : "teal"}>{item.price.toFixed(2)} · {percent(item.change_pct)}</Text><Badge size="xs" color="yellow">{item.status}</Badge></div>
              </Group>
              <SimpleGrid cols={{ base: 2, sm: 4 }} spacing="xs">
                <div><Text size="xs" c="dimmed">回踩观察区（元）</Text><Text size="sm">{item.watch_low.toFixed(2)}～{item.watch_high.toFixed(2)}</Text></div>
                <div><Text size="xs" c="dimmed">突破参考（{mode === "close" ? "基准日" : "当日"}高点）</Text><Text size="sm">{item.breakout_price.toFixed(2)}</Text></div>
                <div><Text size="xs" c="dimmed">失效参考（{mode === "close" ? "基准日" : "当日"}低点）</Text><Text size="sm">{item.invalidation_price.toFixed(2)}</Text></div>
                <div><Text size="xs" c="dimmed">成交额 / 换手率</Text><Text size="sm">{(item.amount / 100000000).toFixed(2)} 亿 / {item.turnover_pct.toFixed(2)}%</Text></div>
              </SimpleGrid>
              <Text size="xs" c="dimmed" mt="xs">{item.liquidity_band ? `${liquidityBands[item.liquidity_band]} · ` : ""}{item.board === "主板" ? `100股参考金额 ${(item.price * 100).toFixed(0)} 元 · ` : ""}{item.strategy_labels?.join(" / ") || item.reason}{item.historical_as_of ? ` · 信号日 ${item.historical_as_of}` : ""}</Text>
              {item.factors ? <Group gap={4} mt={4}><Badge size="xs" variant="light" color={item.factors.fundamentals.status === "pass" ? "teal" : "yellow"}>{item.factors.fundamentals.label}</Badge><Badge size="xs" variant="light" color={item.factors.industry.status === "pass" ? "teal" : "yellow"}>{item.factors.industry.name || "行业未知"} · {item.factors.industry.label}</Badge></Group> : null}
              <details style={{ marginTop: 8 }}><summary style={{ cursor: "pointer", fontSize: 12 }}>查看财报、行业与验证依据</summary>
              {item.close_history ? <Stack gap={4} mt="xs">
                <Text size="xs" fw={600}>历史收盘归档 · 近 {data.history_context?.archive_days ?? 0} 次归档中入选 {item.close_history.appearances} 次 · 最近连续 {item.close_history.consecutive_archives} 个归档批次入选</Text>
                {!item.close_history.records.length ? <Text size="xs" c="dimmed">此前没有这只股票的收盘候选记录，AI仅使用本轮其他依据。</Text> : null}
                {item.close_history.records.map((row) => <Group key={row.trade_date} justify="space-between"><Text size="xs">{row.trade_date}</Text><Text size="xs">{row.price?.toFixed(2) ?? "—"} 元 · {percent(row.change_pct)}</Text><Text size="xs" c="dimmed">成交额 {row.amount == null ? "—" : `${(row.amount / 100000000).toFixed(2)}亿`} · 换手 {percent(row.turnover_pct)}</Text></Group>)}
                <Text size="xs" c="dimmed">仅为已保存的入选日期；连续归档不代表连续交易日，历史价格未经复权。</Text>
              </Stack> : null}
              {item.historical_as_of ? <Text size="xs" c="dimmed" mt={4}>技术信号日 {item.historical_as_of} · 信号收盘 {item.signal_close?.toFixed(2) ?? "—"} · 距20日均价 {percent(item.ma20_gap_pct)} · 日收益波动率 {percent(item.vol20_pct)}</Text> : null}
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
                  <Group gap="xs"><Badge size="sm" color={comment.view === "优先观察" ? "teal" : "gray"}>AI · {comment.view}{data.ai.status === "previous" ? "（上次分析）" : ""}</Badge><Text size="xs">{comment.trigger}</Text></Group>
                  <Text size="sm">{comment.reason}</Text>
                  <Text size="xs" c="yellow">风险：{comment.risk}</Text>
                  <Text size="xs" c="dimmed">{data.ai.status === "previous" ? `基于 ${data.ai.snapshot_at?.replace("T", " ").slice(0, 19) || "此前"} 的行情；点击AI按钮可重新分析。` : comment.trigger === "回踩观察" ? `价格条件：回到 ${item.watch_low.toFixed(2)}～${item.watch_high.toFixed(2)} 元观察，跌破 ${item.invalidation_price.toFixed(2)} 元则本轮条件失效。` : comment.trigger === "突破观察" ? `价格条件：观察能否突破 ${item.breakout_price.toFixed(2)} 元；这是${mode === "close" ? "基准日" : "当日"}高点参考，不保证突破有效。` : "价格条件：等待，无新增买入触发条件。"}</Text>
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
