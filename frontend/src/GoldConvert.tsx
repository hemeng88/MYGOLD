import { useMemo, useState } from "react";
import { NumberInput, Paper, SimpleGrid, Text } from "@mantine/core";
import type { LatestQuote } from "./types";

const OZ = 31.1034768;

function fmt(n: number | null | undefined, digits = 2) {
  if (n === null || n === undefined || Number.isNaN(n)) return "—";
  return n.toFixed(digits);
}

function signed(value: number | null | undefined, digits = 2) {
  if (value === null || value === undefined) return "—";
  return `${value > 0 ? "+" : ""}${value.toFixed(digits)}`;
}

function tone(value: number | null | undefined) {
  if (value === null || value === undefined || value === 0) return "gray";
  return value > 0 ? "red" : "teal";
}

type Field = "grams" | "ounces" | "cny" | "usd";

export function GoldConvert({ latest }: { latest: LatestQuote | null }) {
  const [field, setField] = useState<Field>("grams");
  const [raw, setRaw] = useState<number | string>(1);
  const ounce = latest?.troy_ounce_grams || OZ;
  const zheshang = latest?.price ?? null;
  const london = latest?.london_usd ?? null;
  const fx = latest?.usdcny ?? null;

  const amount = Number(raw);
  const ready = Number.isFinite(amount) && amount > 0 && zheshang && london && fx;

  const values = useMemo(() => {
    if (!ready || !zheshang || !london || !fx) {
      return { grams: null, ounces: null, cny: null, usd: null };
    }
    let grams = amount;
    if (field === "ounces") grams = amount * ounce;
    if (field === "cny") grams = amount / zheshang;
    if (field === "usd") grams = (amount / london) * ounce;
    return {
      grams,
      ounces: grams / ounce,
      cny: grams * zheshang,
      usd: (grams / ounce) * london,
    };
  }, [amount, field, fx, london, ounce, ready, zheshang]);

  const set = (next: Field) => (value: number | string) => {
    setField(next);
    setRaw(value);
  };

  return (
    <Paper className="glass" p="md">
      <Text fw={600}>浙商 ↔ 伦敦金</Text>
      <Text size="xs" c="dimmed" mt={4}>
        用实时{latest?.usdcny_source || "人民币"}汇率换算。1 金衡盎司 = {fmt(ounce, 4)} 克。
      </Text>
      <SimpleGrid cols={2} spacing="xs" mt="sm">
        <Paper className="stat-tile" p="xs">
          <Text size="xs" c="dimmed">
            美元兑人民币
          </Text>
          <Text fw={700} size="sm">
            {fx == null ? "—" : fmt(fx, 4)}
          </Text>
          <Text size="xs" c={tone(latest?.usdcny_change_amt)}>
            {latest?.usdcny_change_amt == null ? "" : signed(latest.usdcny_change_amt, 4)}
          </Text>
        </Paper>
        <Paper className="stat-tile" p="xs">
          <Text size="xs" c="dimmed">
            伦敦折人民币
          </Text>
          <Text fw={700} size="sm">
            {fmt(latest?.london_cny_gram)} 元/克
          </Text>
          <Text size="xs" c={tone(latest?.premium_cny)}>
            {latest?.premium_cny == null
              ? "对不上价"
              : `浙商${signed(latest.premium_cny)}（${signed(latest.premium_pct, 2)}%）`}
          </Text>
        </Paper>
      </SimpleGrid>
      <SimpleGrid cols={2} spacing="xs" mt="sm">
        <NumberInput
          size="xs"
          label="浙商 · 克"
          min={0}
          decimalScale={4}
          hideControls
          value={field === "grams" ? raw : values.grams == null ? "" : Number(values.grams.toFixed(4))}
          onChange={set("grams")}
        />
        <NumberInput
          size="xs"
          label="伦敦 · 盎司"
          min={0}
          decimalScale={4}
          hideControls
          value={field === "ounces" ? raw : values.ounces == null ? "" : Number(values.ounces.toFixed(4))}
          onChange={set("ounces")}
        />
        <NumberInput
          size="xs"
          label="按浙商 · 人民币"
          min={0}
          decimalScale={2}
          hideControls
          thousandSeparator
          prefix="¥"
          value={field === "cny" ? raw : values.cny == null ? "" : Number(values.cny.toFixed(2))}
          onChange={set("cny")}
        />
        <NumberInput
          size="xs"
          label="按伦敦 · 美元"
          min={0}
          decimalScale={2}
          hideControls
          thousandSeparator
          prefix="$"
          value={field === "usd" ? raw : values.usd == null ? "" : Number(values.usd.toFixed(2))}
          onChange={set("usd")}
        />
      </SimpleGrid>
      {ready && values.cny != null && fx ? (
        <Text size="xs" c="dimmed" mt="sm">
          这 {fmt(values.grams, 4)} 克浙商约 {fmt(values.cny, 0)} 元；等量伦敦金约 {fmt(values.usd, 0)} 美元，按汇率合{" "}
          {fmt((values.usd || 0) * fx, 0)} 元。差的是积存金相对伦敦的溢价，不是手续费。
        </Text>
      ) : (
        <Text size="xs" c="dimmed" mt="sm">
          金价或汇率还没齐，先点一次采集。
        </Text>
      )}
    </Paper>
  );
}
