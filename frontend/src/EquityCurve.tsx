import { useEffect, useRef } from "react";
import { Group, Text } from "@mantine/core";

const money = new Intl.NumberFormat("zh-CN", { style: "currency", currency: "CNY" });

export function EquityCurve({ points, baseline }: {
  points: { date: string; equity: number }[];
  baseline: number;
}) {
  const canvas = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    const element = canvas.current;
    const ctx = element?.getContext("2d");
    if (!element || !ctx || points.length < 2) return;
    const values = points.map((row) => row.equity);
    const low = Math.min(baseline, ...values);
    const range = Math.max(1, Math.max(baseline, ...values) - low);
    const width = element.width, height = element.height, padding = 12;
    const y = (value: number) => height - padding - (value - low) / range * (height - 2 * padding);
    ctx.clearRect(0, 0, width, height);
    ctx.beginPath();
    ctx.lineWidth = 1;
    ctx.strokeStyle = "#8491a2";
    ctx.setLineDash([8, 5]);
    ctx.moveTo(padding, y(baseline));
    ctx.lineTo(width - padding, y(baseline));
    ctx.stroke();
    ctx.beginPath();
    ctx.setLineDash([]);
    ctx.lineWidth = 3;
    ctx.strokeStyle = "#c89839";
    values.forEach((value, index) => {
      const x = padding + index * (width - 2 * padding) / (values.length - 1);
      if (index === 0) ctx.moveTo(x, y(value));
      else ctx.lineTo(x, y(value));
    });
    ctx.stroke();
  }, [points, baseline]);
  if (points.length < 2) return null;
  const last = points[points.length - 1];
  return <div>
    <Text size="xs" c="dimmed">每日模拟资产 · 虚线为阶段起始资金</Text>
    <canvas ref={canvas} width={740} height={168} style={{ width: "100%", display: "block" }}
      role="img" aria-label={`模拟资产走势，阶段起始资金 ${money.format(baseline)}，最新资产 ${money.format(last.equity)}`} />
    <Group justify="space-between"><Text size="xs" c="dimmed">{points[0].date}</Text><Text size="xs" c="dimmed">{last.date}</Text></Group>
  </div>;
}
