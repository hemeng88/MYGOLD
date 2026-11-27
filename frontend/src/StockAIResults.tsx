import { useState } from "react";
import { Badge, Group, MultiSelect, Paper, SimpleGrid, Stack, Text } from "@mantine/core";
import type { StockAIComment, StockAIProfileResult } from "./types";

export function useAISelection(results: StockAIProfileResult[]) {
  const [choices, setChoices] = useState<string[] | null>(null);
  const available = results.filter((row) => row.configured);
  const ids = choices === null ? available.slice(0, 1).map((row) => row.profile_id)
    : choices.filter((id) => available.some((row) => row.profile_id === id));
  return {
    ids, setChoices, available,
    selected: ids.flatMap((id) => available.filter((row) => row.profile_id === id)),
  };
}

export function AIModelPicker({ models, value, onChange, disabled }: {
  models: StockAIProfileResult[];
  value: string[];
  onChange: (ids: string[]) => void;
  disabled?: boolean;
}) {
  if (!models.length) return <Text size="xs" c="dimmed">在页面上方的「AI 配置」添加 API Key 后即可分析。</Text>;
  return <MultiSelect size="xs" label="本次分析模型" placeholder="选择模型" disabled={disabled} searchable
    data={models.map((row) => ({ value: row.profile_id, label: `${row.name} · ${row.model}` }))}
    value={value} onChange={onChange} maxValues={32} />;
}

function dateLabel(value: string | null) {
  return value?.replace("T", " ").slice(0, 19) || "时间未知";
}

export function StockAIResults({ results, code, priceCondition }: {
  results: StockAIProfileResult[];
  code: string;
  priceCondition?: (trigger: StockAIComment["trigger"]) => string;
}) {
  const rows = results.flatMap((state) => {
    const item = (state.status === "ready" || state.status === "previous")
      ? state.items.find((comment) => comment.code === code) : undefined;
    const comment = state.card_reviews?.[code] ?? (item ? { ...item, previous: state.status === "previous",
      snapshot_at: state.snapshot_at, analyzed_at: state.analyzed_at, archived: state.archived } : undefined);
    const coversStock = state.reviewed_codes?.includes(code);
    const running = coversStock && state.status === "running";
    const error = coversStock && state.status === "failed" ? state.error : null;
    return comment || running || error ? [{ state, comment, running, error }] : [];
  });
  if (!rows.length) return null;
  return <SimpleGrid cols={{ base: 1, sm: Math.min(rows.length, 2) }} spacing="xs" mt="xs" aria-label="按模型查看股票点评">
    {rows.map(({ state, comment, running, error }) => <Paper key={state.profile_id} p="xs" className="stat-tile" withBorder>
      <Stack gap={4}>
        <Group gap="xs">
          <Text size="sm" fw={600}>{state.name}</Text><Text size="xs" c="dimmed">{state.model}</Text>
          {running ? <Badge size="xs" color="yellow">分析中</Badge> : null}
        </Group>
        {comment ? <>
          <Group gap="xs">
            <Badge size="xs" color={comment.view === "优先观察" ? "teal" : "gray"}>{comment.view}</Badge>
            <Text size="xs">{comment.trigger}</Text>
          </Group>
          <Text size="sm">{comment.reason}</Text>
          <Text size="xs" c="yellow">风险 · {comment.risk}</Text>
          {comment.previous ? <Text size="xs" c="dimmed">历史点评 · 行情 {dateLabel(comment.snapshot_at)}</Text>
            : <Text size="xs" c="dimmed">{priceCondition?.(comment.trigger) || `分析于 ${dateLabel(comment.analyzed_at)}`}</Text>}
          {comment.archived === false ? <Text size="xs" c="yellow">本次点评保存失败。</Text> : null}
        </> : null}
        {error ? <Text size="xs" c="red">{error}</Text> : null}
      </Stack>
    </Paper>)}
  </SimpleGrid>;
}
