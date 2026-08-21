import { useMemo } from "react";
import { Group, Text } from "@mantine/core";
import type { SessionExchange, SessionHour, SessionRange, SessionSnapshot } from "./types";

const REGION_COLOR: Record<string, string> = {
  asia: "#7eb6d4",
  emea: "#d4af37",
  americas: "#d24b3a",
};

function rangeLabel(range: SessionRange) {
  const end = range.end_min >= 1440 || (range.end === "00:00" && range.start_min > 0) ? "24:00" : range.end;
  return `${range.start}–${end}`;
}

function formatRanges(ranges: SessionRange[]) {
  if (!ranges.length) return "—";
  const sorted = [...ranges].sort((a, b) => a.start_min - b.start_min);
  const wraps = sorted.length >= 2 && sorted[0].start_min === 0 && sorted[sorted.length - 1].end_min >= 1440;
  if (wraps) {
    const morning = sorted[0];
    const overnight = sorted[sorted.length - 1];
    const mid = sorted.slice(1, -1).map(rangeLabel);
    return [...mid, `${overnight.start}–${morning.end}`].join(" / ");
  }
  return sorted.map(rangeLabel).join(" / ");
}

function openSortKey(exchange: SessionExchange) {
  const ranges = exchange.ranges;
  if (!ranges.length) return 9999;
  const wraps = ranges.some((range) => range.start_min === 0) && ranges.some((range) => range.end_min >= 1440);
  if (wraps) return Math.max(...ranges.map((range) => range.start_min));
  return Math.min(...ranges.map((range) => range.start_min));
}

function polar(cx: number, cy: number, r: number, minutes: number) {
  const rad = ((minutes / 1440) * 360 * Math.PI) / 180;
  return { x: cx + r * Math.sin(rad), y: cy - r * Math.cos(rad) };
}

function arcPath(cx: number, cy: number, r: number, startMin: number, endMin: number) {
  const start = polar(cx, cy, r, startMin);
  const sweep = (endMin - startMin + 1440) % 1440;
  const large = sweep > 720 ? 1 : 0;
  const end = polar(cx, cy, r, endMin);
  return `M ${start.x} ${start.y} A ${r} ${r} 0 ${large} 1 ${end.x} ${end.y}`;
}

export function SessionClock({
  data,
  clockMin,
  highlightId,
  compact,
  onHoverExchange,
  onLeave,
}: {
  data: SessionSnapshot;
  clockMin: number;
  highlightId: string | null;
  compact?: boolean;
  onHoverExchange: (exchange: SessionExchange | null) => void;
  onLeave: () => void;
}) {
  const size = compact ? 280 : 360;
  const cx = size / 2;
  const cy = size / 2;
  const outer = size / 2 - 18;
  const tip = polar(cx, cy, outer - 8, clockMin);
  const hours = data.hour_profile;
  const maxAbs = Math.max(...hours.map((row) => row.abs_pct || 0), 0.01);

  const rings = useMemo(
    () =>
      data.exchanges.map((exchange, index) => ({
        exchange,
        radius: outer - 28 - index * ((outer - 86) / Math.max(data.exchanges.length - 1, 1)),
      })),
    [data.exchanges, outer],
  );
  const schedule = useMemo(
    () =>
      data.exchanges
        .map((exchange, index) => ({ exchange, index }))
        .sort((a, b) => openSortKey(a.exchange) - openSortKey(b.exchange) || a.index - b.index),
    [data.exchanges],
  );

  return (
    <div className="session-clock">
      <svg
        viewBox={`0 0 ${size} ${size}`}
        width="100%"
        height={compact ? 260 : 340}
        role="img"
        aria-label="全球交易所交易时段"
        onMouseLeave={() => {
          onHoverExchange(null);
          onLeave();
        }}
      >
        <circle cx={cx} cy={cy} r={outer} fill="rgba(255,255,255,0.02)" stroke="rgba(212,175,55,0.18)" />
        {Array.from({ length: 24 }, (_, hour) => {
          const p = polar(cx, cy, outer - 2, hour * 60);
          const label = polar(cx, cy, outer + 10, hour * 60);
          return (
            <g key={hour}>
              <circle cx={p.x} cy={p.y} r={hour % 6 === 0 ? 2.2 : 1.1} fill="#c9b896" />
              {hour % 3 === 0 ? (
                <text x={label.x} y={label.y} textAnchor="middle" dominantBaseline="middle" className="clock-hour">
                  {hour === 0 ? "24" : String(hour).padStart(2, "0")}
                </text>
              ) : null}
            </g>
          );
        })}

        {hours.map((row: SessionHour) => {
          if (!row.abs_pct) return null;
          const inner = 22;
          const r = inner + (row.abs_pct / maxAbs) * 18;
          return (
            <path
              key={`vol-${row.hour}`}
              d={arcPath(cx, cy, r, row.hour * 60, row.hour * 60 + 60)}
              fill="none"
              stroke="rgba(212,175,55,0.35)"
              strokeWidth={3}
            />
          );
        })}

        {rings.map(({ exchange, radius }) => {
          const active = highlightId === exchange.id || (!highlightId && exchange.open);
          const color = REGION_COLOR[exchange.region] || "#8c8170";
          return (
            <g
              key={exchange.id}
              onMouseEnter={() => onHoverExchange(exchange)}
              style={{ cursor: "pointer" }}
            >
              <circle
                cx={cx}
                cy={cy}
                r={radius}
                fill="none"
                stroke="rgba(255,255,255,0.04)"
                strokeWidth={highlightId === exchange.id ? 5 : 3}
              />
              {exchange.ranges.map((range) => (
                <path
                  key={`${exchange.id}-${range.start_min}`}
                  d={arcPath(cx, cy, radius, range.start_min, range.end_min)}
                  fill="none"
                  stroke={color}
                  strokeWidth={highlightId === exchange.id ? 5 : exchange.open ? 3.2 : 2.2}
                  strokeOpacity={active ? 0.95 : 0.22}
                  strokeLinecap="round"
                />
              ))}
            </g>
          );
        })}

        <line x1={cx} y1={cy} x2={tip.x} y2={tip.y} stroke="#f6edd4" strokeWidth={1.6} />
        <circle cx={cx} cy={cy} r={4} fill="#f6edd4" />
        <text x={cx} y={cy + 22} textAnchor="middle" className="clock-center">
          {data.band_label}
        </text>
        <text x={cx} y={cy + 38} textAnchor="middle" className="clock-sub">
          {String(Math.floor(clockMin / 60)).padStart(2, "0")}:{String(clockMin % 60).padStart(2, "0")}
        </text>
      </svg>
      <Group gap={10} justify="center" mt={4}>
        <Text size="xs" c="#7eb6d4">
          亚太
        </Text>
        <Text size="xs" c="gold">
          欧非中东
        </Text>
        <Text size="xs" c="#d24b3a">
          美洲
        </Text>
      </Group>
      <Text size="xs" c="dimmed" ta="center" mt={4}>
        {data.open_count
          ? `当前 ${data.open_count} 家开盘：${data.open_names.slice(0, 4).join("、")}${data.open_names.length > 4 ? "…" : ""}`
          : "当前主要股票市场都未开盘"}
      </Text>
      <div className="session-schedule" onMouseLeave={onLeave}>
        <Text size="xs" c="dimmed" mb={6}>
          按北京时间开盘先后
        </Text>
        {schedule.map(({ exchange }) => {
          const color = REGION_COLOR[exchange.region] || "#8c8170";
          const on = highlightId === exchange.id;
          return (
            <div
              key={exchange.id}
              className={`session-row${exchange.open ? " is-open" : ""}${on ? " is-on" : ""}`}
              onMouseEnter={() => onHoverExchange(exchange)}
            >
              <span className="session-time">{formatRanges(exchange.ranges)}</span>
              <span className="session-name">
                <i className="session-dot" style={{ background: color }} />
                {exchange.name}
              </span>
              <span className="session-state">{exchange.open ? "开盘" : exchange.weekend ? "休市" : ""}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
