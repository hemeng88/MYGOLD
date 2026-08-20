import { Badge, Divider, Group, Modal, Paper, SimpleGrid, Stack, Text } from "@mantine/core";
import type { Advice, AdviceLevel } from "./types";

function fmt(n: number | null | undefined, digits = 2) {
  if (n === null || n === undefined || Number.isNaN(n)) return "—";
  return n.toFixed(digits);
}

function signed(value: number | null | undefined, digits = 2) {
  if (value === null || value === undefined) return "—";
  return `${value > 0 ? "+" : ""}${value.toFixed(digits)}`;
}

const STANCE: Record<string, { label: string; color: string }> = {
  accumulate: { label: "偏向买入", color: "teal" },
  hold: { label: "观望", color: "gray" },
  reduce: { label: "可分批止盈", color: "red" },
  wait: { label: "等回踩", color: "yellow" },
};

function LevelRow({ level, color }: { level: AdviceLevel; color: string }) {
  return (
    <Group justify="space-between" align="flex-start" gap="xs" wrap="nowrap">
      <div style={{ minWidth: 0 }}>
        <Group gap={6} wrap="nowrap">
          <Text fw={600} size="sm">
            {fmt(level.price)}
          </Text>
          {level.kind === "breakeven" ? (
            <Badge size="xs" variant="light" color="gold">
              保本
            </Badge>
          ) : null}
        </Group>
        <Text size="xs" c="dimmed" lineClamp={2}>
          {level.note}
        </Text>
      </div>
      <Text size="sm" fw={600} c={color} style={{ whiteSpace: "nowrap" }}>
        {signed(level.gap_pct)}%
      </Text>
    </Group>
  );
}

export function AdviceModal({
  advice,
  opened,
  onClose,
}: {
  advice: Advice | null;
  opened: boolean;
  onClose: () => void;
}) {
  const stance = advice?.stance ? STANCE[advice.stance] : null;

  return (
    <Modal
      opened={opened}
      onClose={onClose}
      title="买卖参考"
      centered
      radius="lg"
      size="md"
    >
      {!advice ? (
        <Text c="dimmed">正在计算…</Text>
      ) : !advice.ready ? (
        <Text c="dimmed">{advice.message || "暂时算不出来"}</Text>
      ) : (
        <Stack gap="md">
          <Group justify="space-between" align="flex-start" wrap="nowrap">
            <div>
              <Text className="eyebrow">现价</Text>
              <Text fw={700} size="xl">
                {fmt(advice.price)}
              </Text>
            </div>
            {stance ? (
              <Badge color={stance.color} variant="light" size="lg">
                {stance.label}
              </Badge>
            ) : null}
          </Group>

          <Text size="sm">{advice.headline}</Text>

          <SimpleGrid cols={3} spacing="xs">
            <Paper className="stat-tile" p="xs">
              <Text size="xs" c="dimmed">
                20 日均线
              </Text>
              <Text fw={600} size="sm">
                {fmt(advice.ma20)}
              </Text>
            </Paper>
            <Paper className="stat-tile" p="xs">
              <Text size="xs" c="dimmed">
                日波动 ATR
              </Text>
              <Text fw={600} size="sm">
                {fmt(advice.atr)}
              </Text>
            </Paper>
            <Paper className="stat-tile" p="xs">
              <Text size="xs" c="dimmed">
                偏离均线
              </Text>
              <Text fw={600} size="sm">
                {signed(advice.z_score, 1)} 个 ATR
              </Text>
            </Paper>
          </SimpleGrid>

          <div>
            <Text fw={600} size="sm" mb={6} c="teal.4">
              买入参考
            </Text>
            <Stack gap="xs">
              {advice.buy_levels.length ? (
                advice.buy_levels.map((level) => (
                  <LevelRow key={level.price} level={level} color="teal.4" />
                ))
              ) : (
                <Text size="xs" c="dimmed">
                  当前价已在区间下沿，没有更低的参考档位
                </Text>
              )}
            </Stack>
          </div>

          <Divider />

          <div>
            <Text fw={600} size="sm" mb={6} c="red.4">
              卖出参考
            </Text>
            <Stack gap="xs">
              {advice.sell_levels.length ? (
                advice.sell_levels.map((level) => (
                  <LevelRow key={level.price} level={level} color="red.4" />
                ))
              ) : (
                <Text size="xs" c="dimmed">
                  没有可用的卖出档位
                </Text>
              )}
            </Stack>
          </div>

          {advice.total_grams ? (
            <Paper className="stat-tile" p="sm">
              <Group justify="space-between">
                <Text size="xs" c="dimmed">
                  持仓 {fmt(advice.total_grams, 2)} 克 · 均价 {fmt(advice.avg_cost)}
                </Text>
                <Text size="xs" fw={600} c={(advice.net_if_sell_now ?? 0) >= 0 ? "red.4" : "teal.4"}>
                  现在全卖 {signed(advice.net_if_sell_now)}
                </Text>
              </Group>
            </Paper>
          ) : null}

          {advice.drivers.length ? (
            <div>
              <Text size="xs" c="dimmed" mb={6}>
                最近五天的盘面驱动
              </Text>
              <Group gap={6}>
                {advice.drivers.map((driver) => (
                  <Badge key={driver.tag} variant="light" size="sm">
                    {driver.tag} {driver.share_pct}%
                  </Badge>
                ))}
              </Group>
            </div>
          ) : null}

          <Stack gap={4}>
            {advice.notes.map((note) => (
              <Text key={note} size="xs" c="dimmed">
                {note}
              </Text>
            ))}
          </Stack>
        </Stack>
      )}
    </Modal>
  );
}
