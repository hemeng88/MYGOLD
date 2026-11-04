import { useCallback, useEffect, useState } from "react";
import {
  ActionIcon,
  Badge,
  Button,
  Group,
  Modal,
  NumberInput,
  Paper,
  SegmentedControl,
  SimpleGrid,
  Skeleton,
  Stack,
  Switch,
  Text,
  TextInput,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { IconPencil, IconPlus, IconTrash } from "@tabler/icons-react";
import { api } from "./api";
import type { CountdownItem, CountdownKind, CountdownPayload } from "./types";

const KINDS = [
  { value: "once", label: "单次日期" },
  { value: "monthly", label: "每月循环" },
];

function pad(n: number) {
  return String(n).padStart(2, "0");
}

function splitRemain(seconds: number) {
  const safe = Math.max(0, Math.floor(seconds));
  return {
    days: Math.floor(safe / 86400),
    hours: Math.floor((safe % 86400) / 3600),
    minutes: Math.floor((safe % 3600) / 60),
    seconds: safe % 60,
  };
}

function remainFrom(item: CountdownItem, nowMs: number) {
  if (item.status === "past") return 0;
  if (item.status === "today" && item.hour == null) return 0;
  return Math.max(0, item.next_ts * 1000 - nowMs) / 1000;
}

function RemainView({ seconds, compact }: { seconds: number; compact?: boolean }) {
  const parts = splitRemain(seconds);
  const cells = [
    { n: parts.days, u: "天" },
    { n: parts.hours, u: "时" },
    { n: parts.minutes, u: "分" },
    { n: parts.seconds, u: "秒" },
  ];
  return (
    <Group gap={compact ? 8 : 12} wrap="nowrap" justify="center">
      {cells.map((cell) => (
        <div key={cell.u} style={{ textAlign: "center", minWidth: compact ? 36 : 48 }}>
          <Text className={compact ? undefined : "stat-value"} fw={700} style={compact ? { fontSize: 22 } : undefined}>
            {cell.n}
          </Text>
          <Text size="xs" c="dimmed">{cell.u}</Text>
        </div>
      ))}
    </Group>
  );
}

function emptyDraft(): Draft {
  return { title: "", kind: "once", date: "", day: 15, useTime: false, time: "10:00" };
}

interface Draft {
  title: string;
  kind: CountdownKind;
  date: string;
  day: number | string;
  useTime: boolean;
  time: string;
}

function toDraft(item?: CountdownItem | null): Draft {
  if (!item) return emptyDraft();
  return {
    title: item.title,
    kind: item.kind,
    date: item.date || "",
    day: item.day ?? 15,
    useTime: item.hour != null,
    time: item.hour != null ? `${pad(item.hour)}:${pad(item.minute || 0)}` : "10:00",
  };
}

function toPayload(draft: Draft): CountdownPayload {
  const [hourText, minuteText] = draft.time.split(":");
  return {
    title: draft.title,
    kind: draft.kind,
    date: draft.kind === "once" ? draft.date || null : null,
    day: draft.kind === "monthly" ? Number(draft.day) : null,
    hour: draft.useTime ? Number(hourText) : null,
    minute: draft.useTime ? Number(minuteText) : null,
  };
}

export function MiscPanel() {
  const [items, setItems] = useState<CountdownItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [now, setNow] = useState(() => Date.now());
  const [editing, setEditing] = useState<CountdownItem | null | "new">(null);
  const [draft, setDraft] = useState<Draft>(emptyDraft());
  const [saving, setSaving] = useState(false);
  const [busyId, setBusyId] = useState<number | null>(null);

  const load = useCallback(async (signal?: AbortSignal) => {
    try {
      const next = await api.countdowns(signal);
      if (!signal?.aborted) {
        setItems(next);
        setError(null);
      }
    } catch (err) {
      if (!signal?.aborted) setError(err instanceof Error ? err.message : "读取失败");
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [load]);

  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, []);

  useEffect(() => {
    const onVisible = () => {
      if (document.visibilityState === "visible") void load();
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => document.removeEventListener("visibilitychange", onVisible);
  }, [load]);

  const openNew = () => {
    setDraft(emptyDraft());
    setEditing("new");
  };

  const openEdit = (item: CountdownItem) => {
    setDraft(toDraft(item));
    setEditing(item);
  };

  const onSave = async () => {
    setSaving(true);
    try {
      const payload = toPayload(draft);
      if (editing && editing !== "new") await api.updateCountdown(editing.id, payload);
      else await api.addCountdown(payload);
      setEditing(null);
      await load();
    } catch (err) {
      notifications.show({
        color: "red",
        title: "没存上",
        message: err instanceof Error ? err.message : "稍后重试",
      });
    } finally {
      setSaving(false);
    }
  };

  const onDelete = async (item: CountdownItem) => {
    if (!window.confirm(`删除「${item.title}」？`)) return;
    setBusyId(item.id);
    try {
      await api.deleteCountdown(item.id);
      await load();
    } catch (err) {
      notifications.show({
        color: "red",
        title: "没删掉",
        message: err instanceof Error ? err.message : "稍后重试",
      });
    } finally {
      setBusyId(null);
    }
  };

  const headline = items?.[0];

  return (
    <Paper className="glass" p="md">
      <Group justify="space-between" mb="sm" wrap="wrap" gap="sm" align="flex-end">
        <div style={{ minWidth: 0, flex: "1 1 180px" }}>
          <Text fw={600}>倒计时</Text>
          <Text size="xs" c="dimmed" mt={4}>
            单次日期倒数到那天，每月循环过了当天就翻下一轮。时刻可以不填。
          </Text>
        </div>
        <Button size="sm" color="gold" leftSection={<IconPlus size={14} />} onClick={openNew}>
          添加
        </Button>
      </Group>

      {error ? (
        <Group mb="sm" role="status">
          <Text size="sm" c="red">{error}</Text>
          <Button size="compact-xs" variant="subtle" onClick={() => void load()}>重试</Button>
        </Group>
      ) : null}

      {items === null && !error ? (
        <Stack gap="xs">
          {Array.from({ length: 2 }).map((_, index) => (
            <Skeleton key={index} height={88} radius="lg" />
          ))}
        </Stack>
      ) : null}

      {items && !items.length ? (
        <Text size="sm" c="dimmed">还没有倒计时。游戏发售、发工资都可以加进来。</Text>
      ) : null}

      {headline ? (
        <Paper className="stat-tile" p="md" mb="sm">
          <Group justify="space-between" wrap="wrap" gap={6}>
            <div>
              <Text fw={600}>{headline.title}</Text>
              <Text size="xs" c="dimmed">{headline.rule_label}</Text>
            </div>
            <Badge variant="light" color={headline.status === "past" ? "gray" : headline.status === "today" ? "gold" : "teal"}>
              {headline.status === "past" ? `已过 ${headline.elapsed_days ?? 0} 天` : headline.status === "today" ? "就是今天" : `下次 ${headline.next_date}`}
            </Badge>
          </Group>
          <div style={{ marginTop: 12 }}>
            {headline.status === "past" ? (
              <Text ta="center" c="dimmed">已经过去了</Text>
            ) : headline.status === "today" && headline.hour == null ? (
              <Text ta="center" className="stat-value">今天</Text>
            ) : (
              <RemainView seconds={remainFrom(headline, now)} />
            )}
          </div>
        </Paper>
      ) : null}

      <Stack gap={8}>
        {(items || []).map((item) => (
          <Paper key={item.id} className="day-card" p="sm" style={{ cursor: "default" }}>
            <Group justify="space-between" align="flex-start" wrap="nowrap" gap="sm">
              <div style={{ minWidth: 0, flex: 1 }}>
                <Group gap={6} wrap="wrap">
                  <Text fw={600}>{item.title}</Text>
                  <Badge size="sm" variant="light" color="gray">{item.kind === "monthly" ? "每月" : "单次"}</Badge>
                </Group>
                <Text size="xs" c="dimmed" mt={4}>{item.rule_label}</Text>
                {item.status === "past" ? (
                  <Text size="sm" mt={6} c="dimmed">已过 {item.elapsed_days ?? 0} 天</Text>
                ) : item.status === "today" && item.hour == null ? (
                  <Text size="sm" mt={6} c="var(--gold)">今天</Text>
                ) : (
                  <div style={{ marginTop: 8 }}>
                    <RemainView seconds={remainFrom(item, now)} compact />
                  </div>
                )}
              </div>
              <Group gap={4} wrap="nowrap">
                <ActionIcon variant="subtle" color="gray" aria-label={`编辑${item.title}`} onClick={() => openEdit(item)}>
                  <IconPencil size={16} />
                </ActionIcon>
                <ActionIcon
                  variant="subtle"
                  color="red"
                  aria-label={`删除${item.title}`}
                  loading={busyId === item.id}
                  onClick={() => void onDelete(item)}
                >
                  <IconTrash size={16} />
                </ActionIcon>
              </Group>
            </Group>
          </Paper>
        ))}
      </Stack>

      <Modal
        opened={editing !== null}
        onClose={() => setEditing(null)}
        title={editing && editing !== "new" ? `编辑 · ${editing.title}` : "添加倒计时"}
        centered
      >
        <Stack gap="sm">
          <TextInput
            label="名称"
            placeholder="发工资、某游戏发售"
            value={draft.title}
            onChange={(event) => setDraft((prev) => ({ ...prev, title: event.currentTarget.value }))}
            maxLength={40}
          />
          <SegmentedControl
            fullWidth
            data={KINDS}
            value={draft.kind}
            onChange={(value) => setDraft((prev) => ({ ...prev, kind: value as CountdownKind }))}
          />
          {draft.kind === "once" ? (
            <TextInput
              type="date"
              label="日期"
              value={draft.date}
              onChange={(event) => setDraft((prev) => ({ ...prev, date: event.currentTarget.value }))}
            />
          ) : (
            <NumberInput
              label="每月几号"
              min={1}
              max={31}
              clampBehavior="strict"
              value={draft.day}
              onChange={(value) => setDraft((prev) => ({ ...prev, day: value }))}
            />
          )}
          <Switch
            label="指定时刻"
            description="关掉就按整天算，当天之内都显示今天"
            checked={draft.useTime}
            onChange={(event) => setDraft((prev) => ({ ...prev, useTime: event.currentTarget.checked }))}
          />
          {draft.useTime ? (
            <TextInput
              type="time"
              label="时刻"
              value={draft.time}
              onChange={(event) => setDraft((prev) => ({ ...prev, time: event.currentTarget.value }))}
            />
          ) : null}
          <SimpleGrid cols={2} spacing="xs">
            <Button variant="default" onClick={() => setEditing(null)}>取消</Button>
            <Button color="gold" loading={saving} onClick={() => void onSave()}>保存</Button>
          </SimpleGrid>
        </Stack>
      </Modal>
    </Paper>
  );
}
