import { useState } from "react";
import { Alert, Badge, Button, Group, Loader, Paper, SimpleGrid, Stack, Text } from "@mantine/core";
import { api } from "./api";
import { usePolling } from "./usePolling";

export function SignalsPanel() {
  const { data, error, loading, reload } = usePolling(api.stockSignals);
  const [busy, setBusy] = useState(false);
  const [refreshError, setRefreshError] = useState<string | null>(null);
  const [analyzing, setAnalyzing] = useState(false);
  const analyze = async () => {
    setAnalyzing(true);
    setRefreshError(null);
    try {
      await api.analyzeStockSignals();
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
      await api.refreshStockSignals();
      await reload();
    } catch (err) {
      setRefreshError(err instanceof Error ? err.message : "扫描启动失败");
    } finally {
      setBusy(false);
    }
  };
  return (
    <Paper className="glass" p="md">
      <Group justify="space-between" mb="sm">
        <div>
          <Text fw={600}>全 A 股 · 策略观察</Text>
          <Text size="xs" c="dimmed">{data?.session || "读取中"} · 盘中每五分钟扫描，手动刷新间隔一分钟</Text>
        </div>
        <Button color="gold" variant="light" size="sm" loading={busy || data?.running} onClick={() => void refresh()}>扫描全部 A 股</Button>
      </Group>
      {error || refreshError ? <Alert color="red" mb="sm">{error || refreshError}<Button variant="subtle" size="compact-xs" onClick={() => void reload()}>重试</Button></Alert> : null}
      {loading && !data ? <Loader color="gold" size="sm" /> : null}
      {data ? (
        <Stack gap="sm">
          <Text size="xs" c="dimmed">{data.engine} · {data.source}</Text>
          <Group gap="xs">
            <Badge color={data.complete ? "teal" : "yellow"}>{data.complete ? "分页完整" : "尚未完成全市场覆盖"}</Badge>
            <Text size="xs">{data.running ? `正在扫描：已读取 ${data.progress} 只` : `已扫描 ${data.scanned} / ${data.expected || "待获取"} 只 · 命中 ${data.matched} 只`}</Text>
          </Group>
          <Text size="xs" c="dimmed">{Object.entries(data.boards).map(([board, count]) => `${board} ${count} 只`).join(" · ")}</Text>
          <Text size="xs" c="dimmed">抓取完成：{data.fetched_at?.replace("T", " ").slice(0, 19) || "等待首轮扫描"} · 市场最近交易日：{data.trade_date || "待核实"}</Text>
          <Alert color="yellow">
            <Text size="xs">以下为未回测规则生成的观察候选，不是买入指令。公开行情延迟未知，报价时刻只有时间、没有证券级日期，交易前需要核实。</Text>
            {data.stale && data.fetched_at ? <Text size="xs" mt={4}>数据已超过十分钟，仅供历史参考。</Text> : null}
            {!data.market_date_current && data.trade_date ? <Text size="xs" mt={4}>最近交易日不是今天，当前价格仅作收盘参考。</Text> : null}
          </Alert>
          {data.errors.map((message) => <Text key={message} size="xs" c="red">{message}</Text>)}
          <Paper className="stat-tile" p="sm">
            <Group justify="space-between" mb="xs">
              <Text fw={600} size="sm">DeepSeek 候选点评</Text>
              <Button size="compact-xs" variant="light" color="gold"
                loading={analyzing || data.ai?.status === "running"}
                disabled={!data.ai?.configured || data.running || !data.complete || data.stale || !data.market_date_current || !data.items.length}
                onClick={() => void analyze()}>分析本轮候选</Button>
            </Group>
            {!data.ai?.configured ? (
              <Text size="xs" c="dimmed">DeepSeek 尚未启用。请在服务器配置 API 密钥并重启，密钥无需填到网页或聊天中。</Text>
            ) : (
              <Stack gap={4}>
                <Text size="xs" c="dimmed">{data.ai.model} · 只分析本轮最多 20 只候选；仅使用公开行情，未接入新闻、财报或账户资料。</Text>
                <Text size="xs" c="dimmed">配置后有效扫描自动分析，会消耗 DeepSeek API 额度；手动分析至少间隔一分钟，页面轮询不重复调用。</Text>
                {data.ai.status === "running" ? <Text size="sm">DeepSeek 正在比较本轮候选…</Text> : null}
                {data.ai.error ? <Text size="xs" c={data.ai.status === "failed" ? "red" : "dimmed"}>{data.ai.error}</Text> : null}
                {data.ai.summary ? <Text size="sm">{data.ai.summary}</Text> : null}
                {data.ai.status === "ready" && data.ai.analyzed_at ? <Text size="xs" c="dimmed">分析完成：{data.ai.analyzed_at.replace("T", " ").slice(0, 19)} · 基于本页同一行情快照</Text> : null}
              </Stack>
            )}
          </Paper>
          <Paper className="stat-tile" p="sm">
            <Text fw={600} size="sm" mb={4}>筛选与价格规则</Text>
            {data.rules.map((rule) => <Text key={rule} size="xs" c="dimmed" mb={4}>{rule}</Text>)}
          </Paper>
          {!data.items.length && !data.running ? <Text size="sm" c="dimmed" ta="center" py="sm">{data.fetched_at ? "本轮没有符合全部规则的股票。" : "尚未取得可用行情，请启动扫描或稍后重试。"}</Text> : null}
          {data.items.map((item) => {
            const comment = data.ai?.items.find((row) => row.code === item.code);
            return (
            <Paper className="day-card" p="sm" key={item.code}>
              <Group justify="space-between" mb="xs">
                <div><Text fw={600}>{item.name}</Text><Text size="xs" c="dimmed">{item.code} · {item.board} · 报价时刻 {item.quote_time || "未知"}</Text></div>
                <div style={{ textAlign: "right" }}><Text fw={700} c="red">{item.price.toFixed(2)} · +{item.change_pct.toFixed(2)}%</Text><Badge size="xs" color="yellow">{item.status}</Badge></div>
              </Group>
              <SimpleGrid cols={{ base: 2, sm: 4 }} spacing="xs">
                <div><Text size="xs" c="dimmed">回踩观察区（元）</Text><Text size="sm">{item.watch_low.toFixed(2)}～{item.watch_high.toFixed(2)}</Text></div>
                <div><Text size="xs" c="dimmed">突破参考（当日高点）</Text><Text size="sm">{item.breakout_price.toFixed(2)}</Text></div>
                <div><Text size="xs" c="dimmed">失效参考（当日低点）</Text><Text size="sm">{item.invalidation_price.toFixed(2)}</Text></div>
                <div><Text size="xs" c="dimmed">成交额 / 换手率</Text><Text size="sm">{(item.amount / 100000000).toFixed(2)} 亿 / {item.turnover_pct.toFixed(2)}%</Text></div>
              </SimpleGrid>
              <Text size="xs" c="dimmed" mt="xs">{item.reason}</Text>
              {comment ? (
                <Stack gap={4} mt="xs">
                  <Group gap="xs"><Badge size="sm" color={comment.view === "优先观察" ? "teal" : "gray"}>AI · {comment.view}</Badge><Text size="xs">{comment.trigger}</Text></Group>
                  <Text size="sm">{comment.reason}</Text>
                  <Text size="xs" c="yellow">风险：{comment.risk}</Text>
                  <Text size="xs" c="dimmed">{comment.trigger === "回踩观察" ? `价格条件：回到 ${item.watch_low.toFixed(2)}～${item.watch_high.toFixed(2)} 元观察，跌破 ${item.invalidation_price.toFixed(2)} 元则本轮条件失效。` : comment.trigger === "突破观察" ? `价格条件：观察能否突破 ${item.breakout_price.toFixed(2)} 元；这是当日高点参考，不保证突破有效。` : "价格条件：等待，无新增买入触发条件。"}</Text>
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
