import { Alert, Badge, Button, Group, MultiSelect, Paper, SimpleGrid, Stack, Table, Text } from "@mantine/core";
import { PortfolioStudyPanel } from "./PortfolioStudyPanel";
import { liquidityBands } from "./liquidityBands";
import type { LiquidityBand, StockSignals } from "./types";

function percent(value: number | null | undefined) {
  return value == null ? "—" : `${value > 0 ? "+" : ""}${value.toFixed(2)}%`;
}

interface Props {
  data: StockSignals;
  savingBoards: boolean;
  saveBoards: (boards: string[]) => Promise<void>;
  onBack: () => void;
}

export function SignalSettingsPage({ data, savingBoards, saveBoards, onBack }: Props) {
  const comparison = data.research?.holding_comparison;
  return <Stack gap="sm">
    <Group justify="space-between"><Text fw={600}>选股设置与研究依据</Text><Button variant="subtle" size="sm" onClick={onBack}>返回股票结果</Button></Group>
    <Paper className="stat-tile" p="sm">
      <Text size="sm" fw={600}>两种使用方式</Text>
      <Text size="xs" mt={4}>盘中观察：采用上一完整交易日日线，配合本轮行情，每两分钟自动安排扫描，正在扫描时不重复启动。</Text>
      <Text size="xs" mt={4}>收盘选股：交易日15:30后可手动生成，服务器工作日16:00自动归档，17:00重试未成功范围。当日基准日线及足够的个股日线到齐后生成，缺日线的股票退出当日候选。</Text>
      <Text size="xs" mt={4}>收盘池中的价格、财报和行业状态固定在生成时，次日请切换盘中模式确认；这里不承诺下一交易日成交价格，也不会自动下单或推送。</Text>
    </Paper>
    <PortfolioStudyPanel data={data} />
    {data.parameter_evaluation ? <Paper className="stat-tile" p="sm">
      <Text size="sm" fw={600}>参数滚动评估 · {data.adaptive_applied ? "本轮已采用通过验证的过滤参数" : "本轮采用原规则"}</Text>
      <Text size="xs" mt={4}>已取得 {data.parameter_evaluation.history_days ?? 0} 根基准日线；真实新增归档 {data.parameter_evaluation.forward_days}/{data.parameter_evaluation.required_forward_days} 个日期。{data.parameter_evaluation.reason}</Text>
      <Text size="xs" c="dimmed" mt={4}>{data.parameter_evaluation.note}</Text>
      {data.parameter_evaluation.strategies.map((row) => <Paper key={row.key} className="stat-tile" p="xs" mt="xs">
        <Text size="xs" fw={600}>{row.label} · 已比较 {row.tested_variants} 套小范围参数 · {row.passed ? "本轮验证门槛通过" : "证据不足"}</Text>
        <Text size="xs" mt={4}>训练区选出的候选：{row.selected.parameter.max_extension == null ? "不另限均线乖离" : `高于20日均价不超过${row.selected.parameter.max_extension * 100}%`} · {row.selected.parameter.require_index_up ? "要求沪深300趋势向上" : "不加指数趋势限制"}</Text>
        <Text size="xs" c="dimmed" mt={4}>验证区 {row.selected.validation.trades} 次 / 平均净收益 {percent(row.selected.validation.avg_net_pct)}；后段核验区 {row.selected.holdout.trades} 次 / 平均净收益 {percent(row.selected.holdout.avg_net_pct)}</Text>
      </Paper>)}
    </Paper> : null}
    <Paper className="stat-tile" p="sm">
      <Text size="sm" fw={600}>每日收盘归档 · AI历史依据</Text>
      <Text size="xs" mt={4}>成功生成的收盘候选按日期长期保存；同一天重新生成更新同一份，不重复累加。AI读取本轮基准日前、相同板块范围近20次归档统计，以及每股最近5条入选记录，比较此前的行情、财报和行业状态；卡片详情可查看近20次归档中的全部入选记录。</Text>
      <Text size="xs" mt={4}>本轮历史参考：{data.history_context?.archive_days ?? 0} 次归档 · {data.history_context?.status === "unavailable" ? "读取失败" : data.history_context?.archive_days ? "已提供给AI" : "等待积累"}</Text>
      {data.history_context?.dates.length ? <Text size="xs" c="dimmed" mt={4}>已读取日期：{data.history_context.dates.join("、")}</Text> : null}
      <Text size="xs" c="dimmed" mt={4}>{data.history_context?.note || "历史记录不会凭空补齐；服务器未运行、采集失败或当天未入选的股票可能没有记录。"}</Text>
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
          {data.research ? (
            <Paper className="stat-tile" p="sm">
              <Text fw={600} size="sm" mb={4}>策略对照 · 样本外验证</Text>
              <Text size="xs" c="dimmed" mb="xs">本轮行情有效 {data.eligible ?? "—"} 只；抽取日线样本 {data.research.sample_requested} 只，可用 {data.research.sample_usable} 只，历史不足 {data.research.history_insufficient} 只，获取失败 {data.research.history_failed} 个请求。历史验证范围不是全部 A 股。</Text>
              {data.research.sample_bands ? <Group gap="xs" mb="xs">
                {(Object.keys(liquidityBands) as LiquidityBand[]).map((band) =>
                  <Badge key={band} variant="light">{liquidityBands[band]} · 样本 {data.research?.sample_bands?.[band] ?? 0} / 入选 {data.research?.candidate_bands?.[band] ?? 0}</Badge>)}
              </Group> : null}
              {data.mode === "close" && !!data.research.close_pending ? <Text size="xs" c="dimmed" mb="xs">当日缺日线 {data.research.close_pending} 只。</Text> : null}
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
          {comparison ? (
            <Paper className="stat-tile" p="sm">
              <Text fw={600} size="sm">同一批信号的持有期对照</Text>
              <Text size="xs" c="dimmed" mt={4}>回放当前样本的历史技术信号，次日收盘模拟入场，统一扣除设定成本。同股按最长持有期去重。缺后续行情跳过 {comparison.missing_windows} 个信号。</Text>
              <Table.ScrollContainer minWidth={380} mt="xs"><Table withRowBorders>
                <Table.Thead><Table.Tr><Table.Th>持有期</Table.Th><Table.Th>事件数</Table.Th><Table.Th>净盈利占比</Table.Th><Table.Th>平均净收益</Table.Th><Table.Th>最差单笔</Table.Th></Table.Tr></Table.Thead>
                <Table.Tbody>{comparison.periods.map((period) => (
                  <Table.Tr key={period.hold_days}>
                    <Table.Td>{period.hold_days} 日</Table.Td><Table.Td>{period.trades}</Table.Td>
                    <Table.Td>{period.win_pct == null ? "—" : `${period.win_pct.toFixed(1)}%`}</Table.Td>
                    <Table.Td>{percent(period.avg_net_pct)}</Table.Td><Table.Td>{percent(period.worst_trade_pct)}</Table.Td>
                  </Table.Tr>
                ))}</Table.Tbody>
              </Table></Table.ScrollContainer>
              <Text size="xs" c="dimmed" mt={4}>使用复权日线模拟收盘成交。涨跌停、实际委托和最低收费暂未纳入对照。</Text>
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
