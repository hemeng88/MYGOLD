import { useState } from "react";
import { ActionIcon, Badge, Button, Group, NumberInput, Paper, SimpleGrid, Stack, Text, TextInput } from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { IconTrash } from "@tabler/icons-react";
import { api } from "./api";
import type { HoldingSummary } from "./types";

function fmt(n: number | null | undefined, digits = 2) {
  if (n === null || n === undefined || Number.isNaN(n)) return "—";
  return n.toFixed(digits);
}

function signed(value: number | null | undefined) {
  if (value === null || value === undefined) return "—";
  return `${value > 0 ? "+" : ""}${value.toFixed(2)}`;
}

function tone(value: number | null | undefined) {
  if (value === null || value === undefined || value === 0) return "gray";
  return value > 0 ? "red" : "teal";
}

function today() {
  const now = new Date();
  const month = String(now.getMonth() + 1).padStart(2, "0");
  const day = String(now.getDate()).padStart(2, "0");
  return `${now.getFullYear()}-${month}-${day}`;
}

export function HoldingsPanel({
  holdings,
  onChanged,
}: {
  holdings: HoldingSummary | null;
  onChanged: () => Promise<void>;
}) {
  const [grams, setGrams] = useState<number | string>("");
  const [buyPrice, setBuyPrice] = useState<number | string>("");
  const [boughtAt, setBoughtAt] = useState(today());
  const [note, setNote] = useState("");
  const [saving, setSaving] = useState(false);

  const submit = async () => {
    const nextGrams = Number(grams);
    const nextPrice = Number(buyPrice);
    if (!nextGrams || !nextPrice || !boughtAt) {
      notifications.show({ color: "red", title: "请补全", message: "克数、买入价和日期都要填" });
      return;
    }
    setSaving(true);
    try {
      await api.addLot({
        grams: nextGrams,
        buy_price: nextPrice,
        bought_at: boughtAt,
        note: note.trim() || undefined,
      });
      setGrams("");
      setBuyPrice("");
      setNote("");
      await onChanged();
      notifications.show({ color: "gold", title: "已记下", message: `${nextGrams} 克 · ${nextPrice.toFixed(2)} 元/克` });
    } catch (err) {
      notifications.show({ color: "red", title: "保存失败", message: err instanceof Error ? err.message : "请稍后重试" });
    } finally {
      setSaving(false);
    }
  };

  const remove = async (id: number) => {
    try {
      await api.deleteLot(id);
      await onChanged();
    } catch (err) {
      notifications.show({ color: "red", title: "删除失败", message: err instanceof Error ? err.message : "请稍后重试" });
    }
  };

  return (
    <Paper className="glass" p="lg">
      <Group justify="space-between" mb="md" wrap="wrap">
        <div>
          <Text fw={600}>我的持仓</Text>
          <Text size="xs" c="dimmed">
            手动记下仓储克数和买入价，用现价和 0.4% 卖出费率估算盈亏
          </Text>
        </div>
        {holdings?.avg_cost ? (
          <Badge variant="light" color="gold">
            保本卖出 {fmt(holdings.breakeven_sell)} · 还需 {fmt(holdings.needed_rise)} 元/克
          </Badge>
        ) : null}
      </Group>

      <SimpleGrid cols={{ base: 2, sm: 4 }} mb="md" spacing="sm">
        <Paper className="stat-tile" p="md">
          <Text size="xs" c="dimmed">总持仓</Text>
          <Text className="stat-value">{fmt(holdings?.total_grams, 4)} 克</Text>
        </Paper>
        <Paper className="stat-tile" p="md">
          <Text size="xs" c="dimmed">买入均价</Text>
          <Text className="stat-value">{fmt(holdings?.avg_cost)}</Text>
        </Paper>
        <Paper className="stat-tile" p="md">
          <Text size="xs" c="dimmed">现价市值</Text>
          <Text className="stat-value">{fmt(holdings?.market_value)}</Text>
        </Paper>
        <Paper className="stat-tile" p="md">
          <Text size="xs" c="dimmed">卖出到手盈亏</Text>
          <Text className="stat-value" c={tone(holdings?.net_if_sell_now)}>
            {signed(holdings?.net_if_sell_now)}
          </Text>
        </Paper>
      </SimpleGrid>

      <Group align="flex-end" gap="sm" mb="md" wrap="wrap">
        <NumberInput label="克数" placeholder="例如 2.5" min={0.0001} decimalScale={4} value={grams} onChange={setGrams} w={120} />
        <NumberInput label="买入价" placeholder="元/克" min={0.01} decimalScale={2} value={buyPrice} onChange={setBuyPrice} w={140} />
        <TextInput label="买入日期" type="date" value={boughtAt} onChange={(e) => setBoughtAt(e.currentTarget.value)} w={160} />
        <TextInput label="备注" placeholder="可选" value={note} onChange={(e) => setNote(e.currentTarget.value)} style={{ flex: 1, minWidth: 140 }} />
        <Button color="gold" loading={saving} onClick={submit}>
          记一笔
        </Button>
      </Group>

      <Stack gap={8}>
        {(holdings?.lots || []).length === 0 && (
          <Text ta="center" c="dimmed" py="sm">
            还没有持仓。按京东金融里的成交，把克数和买入价记下来即可。
          </Text>
        )}
        {(holdings?.lots || []).map((lot) => (
          <Paper key={lot.id} className="stat-tile" p="sm">
            <Group justify="space-between">
              <div>
                <Text fw={600}>
                  {fmt(lot.grams, 4)} 克 · {fmt(lot.buy_price)} 元/克
                </Text>
                <Text size="xs" c="dimmed">
                  {lot.bought_at} · 成本 {fmt(lot.cost)}
                  {lot.note ? ` · ${lot.note}` : ""}
                </Text>
              </div>
              <ActionIcon variant="subtle" color="gray" onClick={() => remove(lot.id)} aria-label="删除">
                <IconTrash size={16} />
              </ActionIcon>
            </Group>
          </Paper>
        ))}
      </Stack>
    </Paper>
  );
}
