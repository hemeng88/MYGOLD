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

function toNum(value: number | string) {
  const n = typeof value === "number" ? value : Number(String(value).replace(/,/g, ""));
  return Number.isFinite(n) ? n : null;
}

export function GoldConvert({ latest }: { latest: LatestQuote | null }) {
  const ounce = latest?.troy_ounce_grams || OZ;
  const zheshang = latest?.price ?? null;
  const london = latest?.london_usd ?? null;
  const fx = latest?.usdcny ?? null;

  const [priceSide, setPriceSide] = useState<"cnyg" | "usdoz">("cnyg");
  const [priceRaw, setPriceRaw] = useState<number | string>("");
  const [gramsRaw, setGramsRaw] = useState<number | string>(1);
  const [gramSide, setGramSide] = useState<"g" | "oz">("g");
  const [moneyRaw, setMoneyRaw] = useState<number | string>(10000);
  const [moneySide, setMoneySide] = useState<"cny" | "usd">("cny");

  const priceIn = toNum(priceRaw);
  const prices = useMemo(() => {
    if (!fx) return { cnyg: null, usdoz: null };
    if (priceIn == null || priceIn <= 0) {
      return { cnyg: zheshang, usdoz: zheshang ? (zheshang * ounce) / fx : london };
    }
    if (priceSide === "cnyg") {
      return { cnyg: priceIn, usdoz: (priceIn * ounce) / fx };
    }
    return { cnyg: (priceIn / ounce) * fx, usdoz: priceIn };
  }, [fx, london, ounce, priceIn, priceSide, zheshang]);

  const weightIn = toNum(gramsRaw) ?? 1;
  const grams = gramSide === "g" ? weightIn : weightIn * ounce;
  const ounces = grams / ounce;

  const moneyIn = toNum(moneyRaw) ?? 0;
  const moneyCny = !fx ? null : moneySide === "cny" ? moneyIn : moneyIn * fx;
  const moneyUsd = !fx ? null : moneySide === "usd" ? moneyIn : moneyIn / fx;

  return (
    <Paper className="glass" p="md">
      <Text fw={600}>浙商 ↔ 伦敦金</Text>
      <Text size="xs" c="dimmed" mt={4}>
        价格用实时{latest?.usdcny_source || "人民币"}汇率折：元/克 × {fmt(ounce, 4)} ÷ 汇率 = 美元/盎司。
        1 美元 = {fx == null ? "—" : fmt(fx, 4)} 元。
      </Text>

      <SimpleGrid cols={2} spacing="xs" mt="sm">
        <Paper className="stat-tile" p="xs">
          <Text size="xs" c="dimmed">
            浙商现价
          </Text>
          <Text fw={700} size="sm">
            {fmt(zheshang)} 元/克
          </Text>
        </Paper>
        <Paper className="stat-tile" p="xs">
          <Text size="xs" c="dimmed">
            伦敦现价折人民币
          </Text>
          <Text fw={700} size="sm">
            {fmt(latest?.london_cny_gram)} 元/克
          </Text>
          <Text size="xs" c={tone(latest?.premium_cny)}>
            {latest?.premium_cny == null ? "" : `浙商贵 ${signed(latest.premium_cny)}（${signed(latest.premium_pct, 2)}%）`}
          </Text>
        </Paper>
      </SimpleGrid>

      <Text size="xs" c="dimmed" fw={600} mt="md" mb={4}>
        价格换算（同一套汇率）
      </Text>
      <SimpleGrid cols={2} spacing="xs">
        <NumberInput
          size="xs"
          label="元 / 克"
          min={0}
          decimalScale={2}
          hideControls
          value={priceSide === "cnyg" ? priceRaw || zheshang || "" : prices.cnyg == null ? "" : Number(prices.cnyg.toFixed(2))}
          onChange={(value) => {
            setPriceSide("cnyg");
            setPriceRaw(value);
          }}
        />
        <NumberInput
          size="xs"
          label="美元 / 盎司"
          min={0}
          decimalScale={2}
          hideControls
          value={priceSide === "usdoz" ? priceRaw : prices.usdoz == null ? "" : Number(prices.usdoz.toFixed(2))}
          onChange={(value) => {
            setPriceSide("usdoz");
            setPriceRaw(value);
          }}
        />
      </SimpleGrid>
      {fx && prices.cnyg != null && prices.usdoz != null ? (
        <Text size="xs" c="dimmed" mt={6}>
          {fmt(prices.cnyg)} 元/克 = {fmt(prices.usdoz)} 美元/盎司。
          {zheshang != null ? ` 现在浙商 ${fmt(zheshang)}，差 ${signed(zheshang - prices.cnyg)} 元/克。` : ""}
          {london != null ? ` 现在伦敦 ${fmt(london)}，差 ${signed(london - prices.usdoz)} 美元/盎司。` : ""}
        </Text>
      ) : (
        <Text size="xs" c="dimmed" mt={6}>
          汇率还没有，先点一次采集。
        </Text>
      )}

      <Text size="xs" c="dimmed" fw={600} mt="md" mb={4}>
        重量
      </Text>
      <SimpleGrid cols={2} spacing="xs">
        <NumberInput
          size="xs"
          label="克"
          min={0}
          decimalScale={4}
          hideControls
          value={gramSide === "g" ? gramsRaw : Number(grams.toFixed(4))}
          onChange={(value) => {
            setGramSide("g");
            setGramsRaw(value);
          }}
        />
        <NumberInput
          size="xs"
          label="金衡盎司"
          min={0}
          decimalScale={4}
          hideControls
          value={gramSide === "oz" ? gramsRaw : Number(ounces.toFixed(4))}
          onChange={(value) => {
            setGramSide("oz");
            setGramsRaw(value);
          }}
        />
      </SimpleGrid>

      <Text size="xs" c="dimmed" fw={600} mt="md" mb={4}>
        人民币 ↔ 美元（只走汇率，不掺金价）
      </Text>
      <SimpleGrid cols={2} spacing="xs">
        <NumberInput
          size="xs"
          label="人民币"
          min={0}
          decimalScale={2}
          hideControls
          thousandSeparator
          prefix="¥"
          value={moneySide === "cny" ? moneyRaw : moneyCny == null ? "" : Number(moneyCny.toFixed(2))}
          onChange={(value) => {
            setMoneySide("cny");
            setMoneyRaw(value);
          }}
        />
        <NumberInput
          size="xs"
          label="美元"
          min={0}
          decimalScale={2}
          hideControls
          thousandSeparator
          prefix="$"
          value={moneySide === "usd" ? moneyRaw : moneyUsd == null ? "" : Number(moneyUsd.toFixed(2))}
          onChange={(value) => {
            setMoneySide("usd");
            setMoneyRaw(value);
          }}
        />
      </SimpleGrid>
      {moneyCny != null && moneyUsd != null && zheshang && london ? (
        <Text size="xs" c="dimmed" mt={6}>
          这笔钱按浙商大约能买 {fmt(moneyCny / zheshang, 3)} 克，按伦敦大约能买 {fmt(moneyUsd / london, 4)} 盎司。
        </Text>
      ) : null}
    </Paper>
  );
}
