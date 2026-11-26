import { Alert, Badge, Button, Group, MultiSelect, Paper, SimpleGrid, Stack, Text } from "@mantine/core";
import { DeepSeekSettingsPanel } from "./DeepSeekSettingsPanel";
import type { StockSignals } from "./types";

function percent(value: number | null | undefined) {
  return value == null ? "—" : `${value > 0 ? "+" : ""}${value.toFixed(2)}%`;
}

interface Props {
  data: StockSignals;
  savingBoards: boolean;
  analyzing: boolean;
  saveBoards: (boards: string[]) => Promise<void>;
  analyze: () => Promise<void>;
  reload: () => Promise<void>;
  onBack: () => void;
}

export function SignalSettingsPage({ data, savingBoards, analyzing, saveBoards, analyze, reload, onBack }: Props) {
  return <Stack gap="sm">
    <Group justify="space-between"><Text fw={600}>选股设置与研究依据</Text><Button variant="subtle" size="sm" onClick={onBack}>返回股票结果</Button></Group>
    <Paper className="stat-tile" p="sm">
      <Text size="sm" fw={600}>两种使用方式</Text>
      <Text size="xs" mt={4}>盘中观察：采用上一完整交易日日线，配合本轮行情，每五分钟扫描。</Text>
      <Text size="xs" mt={4}>收盘选股：交易日15:30后确认当日日线，生成并保存下一交易日观察池；第二天打开仍显示原有名单。日线未更新时保留上一份，不自动用旧日线代替。</Text>
      <Text size="xs" mt={4}>收盘池中的价格、财报和行业状态固定在生成时，次日请切换盘中模式确认；这里不承诺下一交易日成交价格，也不会自动下单或推送。</Text>
    </Paper>
          <Paper className="stat-tile" p="sm">
            <MultiSelect
              label="参与选股板块"
              description="默认仅主板。更改后自动按账号保存，并重新生成该范围的候选与研究结果。"
              data={["主板", "创业板", "科创板", "北交所"]}
              value={data.allowed_boards || ["主板"]}
              onChange={(boards) => void saveBoards(boards)}
              disabled={savingBoards}
              clearable={false}
              aria-label="参与选股板块"
            />
            <Text size="xs" c="dimmed" mt={4}>{savingBoards ? "正在保存板块配置…" : `当前选股范围：${(data.allowed_boards || ["主板"]).join("、")}；未选板块不进入日线样本、历史验证或 AI 候选。`}</Text>
          </Paper>
          <Text size="xs" c="dimmed">{data.engine} · {data.source}</Text>
          <Group gap="xs">
            <Badge color={data.complete ? "teal" : "yellow"}>{data.complete ? "分页完整" : "尚未完成全市场覆盖"}</Badge>
            <Text size="xs">{data.running ? `正在扫描与研究：已读取 ${data.progress} 只` : `已扫描 ${data.scanned} / ${data.expected || "待获取"} 只 · 展示 ${data.items.length} 只候选`}</Text>
          </Group>
          <Text size="xs" c="dimmed">全市场报价覆盖（不代表全部参与选股）：{Object.entries(data.boards).map(([board, count]) => `${board} ${count} 只`).join(" · ")}</Text>
          <Text size="xs" c="dimmed">抓取完成：{data.fetched_at?.replace("T", " ").slice(0, 19) || "等待首轮扫描"} · 市场最近交易日：{data.trade_date || "待核实"}</Text>
          <Alert color="yellow">
            <Text size="xs">以下候选由三套待验证假设产生。历史研究仅覆盖当前抽取的样本，存在选择偏差；公开行情延迟未知，报价日期未逐只验证。</Text>
            {data.mode !== "close" && data.stale && data.fetched_at ? <Text size="xs" mt={4}>数据已超过十分钟，仅供历史参考。</Text> : null}
            {!data.market_date_current && data.trade_date ? <Text size="xs" mt={4}>最近交易日不是今天，价格仅作历史参考。</Text> : null}
          </Alert>
          {data.errors.map((message) => <Text key={message} size="xs" c="red">{message}</Text>)}
          {data.factor_context ? (
            <Paper className="stat-tile" p="sm">
              <Group justify="space-between" mb="xs"><Text fw={600} size="sm">大盘环境与多因子检查</Text><Badge color={data.factor_context.market.status === "favorable" ? "teal" : "yellow"}>{data.factor_context.market.label}</Badge></Group>
              <SimpleGrid cols={{ base: 2, sm: 3 }} spacing="xs">
                <div><Text size="xs" c="dimmed">全A有效报价上涨占比</Text><Text size="sm">{percent(data.factor_context.market.advance_pct)}</Text><Text size="xs" c="dimmed">共 {data.factor_context.market.stock_count} 只</Text></div>
                <div><Text size="xs" c="dimmed">全A有效报价等权涨跌</Text><Text size="sm">{percent(data.factor_context.market.mean_change_pct)}</Text></div>
                <div><Text size="xs" c="dimmed">沪深300最近完整收盘</Text><Text size="sm">{data.factor_context.market.index_close?.toFixed(2) ?? "—"}</Text><Text size="xs" c="dimmed">{data.factor_context.market.index_as_of || "待核实"} · 20/60日均价 {data.factor_context.market.ma20?.toFixed(2) ?? "—"} / {data.factor_context.market.ma60?.toFixed(2) ?? "—"}</Text></div>
              </SimpleGrid>
              <Text size="xs" c="dimmed" mt="xs">{data.factor_context.market.reason}</Text>
              <Text size="xs" mt={4}>检查 {data.factor_context.checked} 只技术候选 · 新增因子通过 {data.factor_context.passed} 只 · 同时通过历史证据与新增因子 {data.factor_context.priority_count} 只</Text>
              <Text size="xs" c="dimmed" mt={4}>{data.factor_context.note}</Text>
              <Text size="xs" c="dimmed" mt={4}>{data.factor_context.market.source}；公开行情延迟与个股报价日期仍需核实。</Text>
            </Paper>
          ) : null}
          <Paper className="stat-tile" p="sm">
            <Group justify="space-between" mb="xs">
              <Text fw={600} size="sm">AI 候选点评</Text>
              <DeepSeekSettingsPanel onChanged={reload} />
              <Button size="compact-xs" variant="light" color="gold"
                loading={analyzing || data.ai?.status === "running"}
                disabled={!data.ai?.configured || data.running || !data.complete || !data.items.length || !!data.errors.length || (data.mode === "close" ? !data.close_ready : data.stale || !data.market_date_current)}
                onClick={() => void analyze()}>分析本轮候选</Button>
            </Group>
            {!data.ai?.configured ? (
              <Text size="xs" c="dimmed">AI 分析尚未启用。点击“配置 AI 模型”选择服务商、填写 Key 并保存即可使用。</Text>
            ) : (
              <Stack gap={4}>
                <Text size="xs" c="dimmed">{data.ai.provider_label || "AI"} · {data.ai.model} · 比较最多20只候选、历史研究、已披露财报指标、行业当日强弱和大盘环境；未接入新闻、完整财报或账户资料。</Text>
                <Text size="xs" c="dimmed">配置后有效扫描自动分析，会消耗对应服务商的 API 额度；手动分析至少间隔一分钟，页面轮询不重复调用。</Text>
                {data.ai.status === "running" ? <Text size="sm">AI 正在比较本轮候选…</Text> : null}
                {data.ai.error ? <Text size="xs" c={data.ai.status === "failed" ? "red" : "dimmed"}>{data.ai.error}</Text> : null}
                {data.ai.summary ? <Text size="sm">{data.ai.summary}</Text> : null}
                {data.ai.status === "ready" && data.ai.analyzed_at ? <Text size="xs" c="dimmed">分析完成：{data.ai.analyzed_at.replace("T", " ").slice(0, 19)} · 基于本页同一行情快照</Text> : null}
              </Stack>
            )}
          </Paper>
          {data.research ? (
            <Paper className="stat-tile" p="sm">
              <Text fw={600} size="sm" mb={4}>策略对照 · 样本外验证</Text>
              <Text size="xs" c="dimmed" mb="xs">本轮行情有效 {data.eligible ?? "—"} 只；抽取日线样本 {data.research.sample_requested} 只，可用 {data.research.sample_usable} 只，历史不足 {data.research.history_insufficient} 只，获取失败 {data.research.history_failed} 个请求。历史验证范围不是全部 A 股。</Text>
              <Text size="xs" c="dimmed" mb="xs">历史区间 {data.research.history_start || "—"}～{data.research.history_end || "—"} · 样本外从 {data.research.split_date || "待取得足够历史"} 开始</Text>
              {!data.research.benchmark_available ? <Text size="xs" c="yellow" mb="xs">沪深 300 基准缺失，本轮不产生新的技术候选。</Text> : null}
              <Stack gap="xs">
                {data.research.strategies.map((strategy) => (
                  <Paper key={strategy.key} p="sm" className="stat-tile">
                    <Group justify="space-between" mb={4}><Text size="sm" fw={600}>{strategy.label} · 当前命中 {strategy.current_matches}</Text><Badge size="xs" color="yellow">{strategy.status}</Badge></Group>
                    <Text size="xs" c="dimmed" mb="xs">{strategy.rule}</Text>
                    <SimpleGrid cols={{ base: 2, sm: 4 }} spacing="xs">
                      <div><Text size="xs" c="dimmed">研究区间 · 平均净事件收益</Text><Text size="sm">{percent(strategy.train.avg_net_pct)}</Text><Text size="xs" c="dimmed">{strategy.train.trades} 个事件</Text></div>
                      <div><Text size="xs" c="dimmed">样本外 · 平均净事件收益</Text><Text size="sm">{percent(strategy.test.avg_net_pct)}</Text><Text size="xs" c="dimmed">{strategy.test.trades} 个事件 · 正收益占比 {strategy.test.win_pct == null ? "—" : `${strategy.test.win_pct.toFixed(1)}%`}</Text></div>
                      <div><Text size="xs" c="dimmed">样本外 · 双倍交易成本</Text><Text size="sm">{percent(strategy.test.double_cost_pct)}</Text><Text size="xs" c="dimmed">最差单次 {percent(strategy.test.worst_trade_pct)}</Text></div>
                      <div><Text size="xs" c="dimmed">样本外 · 相对沪深 300</Text><Text size="sm">{percent(strategy.test.avg_excess_pct)}</Text><Text size="xs" c="dimmed">{strategy.test.benchmark_trades} 个可比事件</Text></div>
                    </SimpleGrid>
                  </Paper>
                ))}
              </Stack>
              <Text size="xs" fw={600} mt="sm" mb={4}>验证口径与限制</Text>
              {data.research.assumptions.map((text) => <Text key={text} size="xs" c="dimmed" mb={4}>{text}</Text>)}
            </Paper>
          ) : null}
          {data.paper ? (
            <Paper className="stat-tile" p="sm">
              <Text fw={600} size="sm" mb={4}>前向模拟跟踪</Text>
              <Text size="sm">已记录 {data.paper.recorded} 个策略事件 · 完成 {data.paper.completed} · 待观察 {data.paper.pending}</Text>
              <Text size="xs" mt={4}>已完成事件的平均净收益：{percent(data.paper.avg_net_pct)}</Text>
              <Text size="xs" c="dimmed" mt={4}>{data.paper.note}</Text>
            </Paper>
          ) : null}
          <Paper className="stat-tile" p="sm">
            <Text fw={600} size="sm" mb={4}>筛选与价格规则</Text>
            {data.rules.map((rule) => <Text key={rule} size="xs" c="dimmed" mb={4}>{rule}</Text>)}
          </Paper>
  </Stack>;
}
