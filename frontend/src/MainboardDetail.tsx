import { useEffect, useMemo, useState } from "react";
import { Badge, Button, Group, Modal, Paper, SegmentedControl, SimpleGrid, Skeleton, Stack, Text } from "@mantine/core";
import { api } from "./api";
import type { MainboardDetail, MainboardPeriod } from "./types";

const PERIOD_OPTIONS: { value: MainboardPeriod; label: string }[] = [
  { value: "1m", label: "近1月" },
  { value: "3m", label: "近3月" },
  { value: "6m", label: "近6月" },
  { value: "ytd", label: "今年来" },
  { value: "1y", label: "近1年" },
];

const STOCK_COLOR = "#d4af37";
const INDEX_COLORS = ["#7eb6d4", "#b39ddb", "#9aa5a0"];

function fmt(n: number | null | undefined, digits = 2) {
  if (n === null || n === undefined || Number.isNaN(n)) return "—";
  return n.toFixed(digits);
}

function signedPct(value: number | null | undefined) {
  if (value === null || value === undefined) return "—";
  return `${value > 0 ? "+" : ""}${value.toFixed(2)}%`;
}

function tone(value: number | null | undefined) {
  if (value === null || value === undefined || value === 0) return "gray";
  return value > 0 ? "red" : "teal";
}

interface ChartLine {
  name: string;
  color: string;
  values: (number | null)[];
  dashed?: boolean;
  width?: number;
}

const W = 640;
const H = 220;
const PAD = { top: 12, right: 12, bottom: 22, left: 48 };

function TrendChart({
  dates,
  lines,
  format,
  baseline,
}: {
  dates: string[];
  lines: ChartLine[];
  format: (value: number) => string;
  baseline?: number;
}) {
  const [hover, setHover] = useState<number | null>(null);
  const values = lines.flatMap((line) => line.values.filter((v): v is number => v != null));
  if (dates.length < 2 || !values.length) {
    return <Text size="sm" c="dimmed">数据不足，画不出走势</Text>;
  }
  let min = Math.min(...values, baseline ?? Infinity);
  let max = Math.max(...values, baseline ?? -Infinity);
  if (max - min < 1e-9) {
    max += 1;
    min -= 1;
  }
  const span = max - min;
  min -= span * 0.06;
  max += span * 0.06;
  const innerW = W - PAD.left - PAD.right;
  const innerH = H - PAD.top - PAD.bottom;
  const x = (i: number) => PAD.left + (i / (dates.length - 1)) * innerW;
  const y = (v: number) => PAD.top + (1 - (v - min) / (max - min)) * innerH;

  const pathOf = (series: (number | null)[]) => {
    let d = "";
    let pen = false;
    series.forEach((v, i) => {
      if (v == null) {
        pen = false;
        return;
      }
      d += `${pen ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`;
      pen = true;
    });
    return d;
  };

  const ticks = [max - (max - min) * 0.06, (max + min) / 2, min + (max - min) * 0.06];
  const onMove = (event: React.PointerEvent<SVGSVGElement>) => {
    const rect = event.currentTarget.getBoundingClientRect();
    const px = ((event.clientX - rect.left) / rect.width) * W;
    const ratio = (px - PAD.left) / innerW;
    setHover(Math.max(0, Math.min(dates.length - 1, Math.round(ratio * (dates.length - 1)))));
  };

  return (
    <div>
      <svg
        viewBox={`0 0 ${W} ${H}`}
        width="100%"
        style={{ display: "block", touchAction: "pan-y" }}
        onPointerMove={onMove}
        onPointerDown={onMove}
        onPointerLeave={() => setHover(null)}
        role="img"
      >
        {ticks.map((tick) => (
          <g key={tick}>
            <line x1={PAD.left} x2={W - PAD.right} y1={y(tick)} y2={y(tick)} stroke="rgba(255,255,255,0.06)" />
            <text x={PAD.left - 6} y={y(tick) + 4} textAnchor="end" fontSize="11" fill="rgba(255,255,255,0.45)">
              {format(tick)}
            </text>
          </g>
        ))}
        {baseline != null ? (
          <line
            x1={PAD.left}
            x2={W - PAD.right}
            y1={y(baseline)}
            y2={y(baseline)}
            stroke="rgba(255,255,255,0.25)"
            strokeDasharray="3 4"
          />
        ) : null}
        {lines.map((line) => (
          <path
            key={line.name}
            d={pathOf(line.values)}
            fill="none"
            stroke={line.color}
            strokeWidth={line.width ?? 1.6}
            strokeDasharray={line.dashed ? "6 5" : undefined}
            strokeLinejoin="round"
            strokeLinecap="round"
          />
        ))}
        <text x={PAD.left} y={H - 4} fontSize="11" fill="rgba(255,255,255,0.45)">{dates[0]}</text>
        <text x={W - PAD.right} y={H - 4} textAnchor="end" fontSize="11" fill="rgba(255,255,255,0.45)">
          {dates[dates.length - 1]}
        </text>
        {hover != null ? (
          <g>
            <line x1={x(hover)} x2={x(hover)} y1={PAD.top} y2={H - PAD.bottom} stroke="rgba(255,255,255,0.3)" />
            {lines.map((line) => {
              const v = line.values[hover];
              return v == null ? null : <circle key={line.name} cx={x(hover)} cy={y(v)} r={3} fill={line.color} />;
            })}
          </g>
        ) : null}
      </svg>
      <Group gap="sm" mt={4} wrap="wrap">
        <Text size="xs" c="dimmed">{hover != null ? dates[hover] : "划过图表看每日读数"}</Text>
        {lines.map((line) => {
          const v = hover != null ? line.values[hover] : line.values[line.values.length - 1];
          return (
            <Group key={line.name} gap={4} wrap="nowrap">
              <span style={{ width: 10, height: 2, background: line.color, display: "inline-block" }} />
              <Text size="xs" c="dimmed">{line.name}</Text>
              <Text size="xs">{v == null ? "—" : format(v)}</Text>
            </Group>
          );
        })}
      </Group>
    </div>
  );
}

export function MainboardDetailModal({
  code,
  name,
  initialPeriod,
  onClose,
}: {
  code: string | null;
  name: string;
  initialPeriod: MainboardPeriod;
  onClose: () => void;
}) {
  const [period, setPeriod] = useState<MainboardPeriod>(initialPeriod);
  const [detail, setDetail] = useState<MainboardDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [revision, setRevision] = useState(0);

  useEffect(() => {
    if (code) setPeriod(initialPeriod);
  }, [code, initialPeriod]);

  useEffect(() => {
    if (!code) return;
    const controller = new AbortController();
    setError(null);
    api
      .mainboardDetail(code, period, controller.signal)
      .then((next) => {
        if (!controller.signal.aborted) setDetail(next);
      })
      .catch((err) => {
        if (!controller.signal.aborted) setError(err instanceof Error ? err.message : "读取失败");
      });
    return () => controller.abort();
  }, [code, period, revision]);

  const current = detail && detail.code === code && detail.period === period ? detail : null;

  const priceChart = useMemo(() => {
    if (!current) return null;
    const dates = current.series.map((p) => p.d);
    return {
      dates,
      lines: [
        { name: "收盘", color: STOCK_COLOR, values: current.series.map((p) => p.c), width: 2 },
        ...(current.avg != null
          ? [{ name: `${current.period_label}均价`, color: "rgba(255,255,255,0.55)", values: dates.map(() => current.avg), dashed: true }]
          : []),
      ],
    };
  }, [current]);

  const compareChart = useMemo(() => {
    if (!current || !current.series.length) return null;
    const dates = current.series.map((p) => p.d);
    const base = current.series[0].c;
    const lines: ChartLine[] = [
      { name: current.name, color: STOCK_COLOR, values: current.series.map((p) => (p.c / base - 1) * 100), width: 2 },
    ];
    current.indexes.forEach((index, i) => {
      if (!index.series.length) return;
      const byDate = new Map(index.series.map((p) => [p.d, p.c]));
      const first = index.series[0].c;
      let carry: number | null = null;
      // 指数和个股停牌日对不齐时沿用前一天，线不会断成一截一截
      const values = dates.map((d) => {
        const c = byDate.get(d);
        if (c != null) carry = (c / first - 1) * 100;
        return carry;
      });
      lines.push({ name: index.name, color: INDEX_COLORS[i % INDEX_COLORS.length], values });
    });
    return { dates, lines };
  }, [current]);

  return (
    <Modal opened={code !== null} onClose={onClose} title={`走势详情 · ${current?.name || name}`} size="lg" centered>
      <Stack gap="sm">
        <SegmentedControl
          fullWidth
          size="xs"
          data={PERIOD_OPTIONS}
          value={period}
          onChange={(value) => setPeriod(value as MainboardPeriod)}
        />
        {error ? (
          <Group role="status">
            <Text size="sm" c="red">{error}</Text>
            <Button size="compact-xs" variant="subtle" onClick={() => setRevision((n) => n + 1)}>重试</Button>
          </Group>
        ) : null}
        {!current && !error ? <Skeleton height={260} radius="md" /> : null}
        {current ? (
          <>
            <Group gap={6}>
              <Badge size="sm" variant="light" color="gray">{current.code}</Badge>
              <Text size="xs" c="dimmed">
                {current.window_start && current.window_end ? `${current.window_start} 至 ${current.window_end}` : ""}
              </Text>
            </Group>
            <SimpleGrid cols={{ base: 2, sm: 4 }} spacing="xs">
              <Paper className="stat-tile" p="xs">
                <Text size="xs" c="dimmed">现价 / 当日</Text>
                <Text fw={600} size="sm">
                  {fmt(current.last)} <Text span size="xs" c={tone(current.change_pct)}>{signedPct(current.change_pct)}</Text>
                </Text>
              </Paper>
              <Paper className="stat-tile" p="xs">
                <Text size="xs" c="dimmed">{current.period_label}涨跌</Text>
                <Text fw={600} size="sm" c={tone(current.period_change_pct)}>{signedPct(current.period_change_pct)}</Text>
              </Paper>
              <Paper className="stat-tile" p="xs">
                <Text size="xs" c="dimmed">{current.period_label}均价 / 偏离</Text>
                <Text fw={600} size="sm">
                  {fmt(current.avg)} <Text span size="xs" c={tone(current.vs_avg_pct)}>{signedPct(current.vs_avg_pct)}</Text>
                </Text>
              </Paper>
              <Paper className="stat-tile" p="xs">
                <Text size="xs" c="dimmed">区间最高 / 最低</Text>
                <Text fw={600} size="sm">{fmt(current.high)} / {fmt(current.low)}</Text>
              </Paper>
            </SimpleGrid>

            <Paper className="stat-tile" p="xs">
              <Text size="xs" c="dimmed" mb={4}>收盘价走势（虚线为区间均价，前复权）</Text>
              {priceChart ? <TrendChart dates={priceChart.dates} lines={priceChart.lines} format={(v) => v.toFixed(2)} /> : null}
            </Paper>

            <Paper className="stat-tile" p="xs">
              <Text size="xs" c="dimmed" mb={4}>同期涨跌对比（以区间首日为 0%）</Text>
              {compareChart ? (
                <TrendChart
                  dates={compareChart.dates}
                  lines={compareChart.lines}
                  baseline={0}
                  format={(v) => `${v > 0 ? "+" : ""}${v.toFixed(1)}%`}
                />
              ) : null}
              <SimpleGrid cols={{ base: 3 }} spacing="xs" mt="xs">
                {current.indexes.map((index) => (
                  <div key={index.symbol}>
                    <Text size="xs" c="dimmed">{index.name}</Text>
                    <Text size="sm" fw={600}>{fmt(index.last)}</Text>
                    <Text size="xs" c={tone(index.change_pct)}>{current.period_label} {signedPct(index.change_pct)}</Text>
                  </div>
                ))}
              </SimpleGrid>
            </Paper>

            <Paper className="stat-tile" p="xs">
              <Text size="xs" c="dimmed" mb={6}>各周期对照</Text>
              <Stack gap={4}>
                {current.periods.map((item) => (
                  <Group key={item.value} justify="space-between" wrap="nowrap">
                    <Text size="xs" fw={item.value === period ? 600 : 400}>{item.label}</Text>
                    <Text size="xs" c="dimmed">均价 {fmt(item.avg)}</Text>
                    <Text size="xs" c={tone(item.vs_avg_pct)}>偏离 {signedPct(item.vs_avg_pct)}</Text>
                    <Text size="xs" c={tone(item.change_pct)}>涨跌 {signedPct(item.change_pct)}</Text>
                  </Group>
                ))}
              </Stack>
            </Paper>
          </>
        ) : null}
      </Stack>
    </Modal>
  );
}
