import { useCallback, useEffect, useMemo, useState } from "react";
import ReactECharts from "echarts-for-react";
import { api } from "./api";
import type { CurveResponse, DaySummary, LatestQuote } from "./types";

function fmt(n: number | null | undefined, digits = 2) {
  if (n === null || n === undefined || Number.isNaN(n)) return "—";
  return n.toFixed(digits);
}

function changeClass(value: number | null | undefined) {
  if (value === null || value === undefined || value === 0) return "flat";
  return value > 0 ? "up" : "down";
}

function signed(value: number | null | undefined) {
  if (value === null || value === undefined) return "—";
  const prefix = value > 0 ? "+" : "";
  return `${prefix}${value.toFixed(2)}`;
}

export default function App() {
  const [days, setDays] = useState<DaySummary[]>([]);
  const [selectedDate, setSelectedDate] = useState<string>("");
  const [compareDate, setCompareDate] = useState<string>("");
  const [curve, setCurve] = useState<CurveResponse | null>(null);
  const [compareCurve, setCompareCurve] = useState<CurveResponse | null>(null);
  const [latest, setLatest] = useState<LatestQuote | null>(null);
  const [loading, setLoading] = useState(true);
  const [collecting, setCollecting] = useState(false);
  const [error, setError] = useState("");
  const [status, setStatus] = useState("正在读取已归档曲线…");

  const loadAll = useCallback(async (date?: string) => {
    setError("");
    const [dayList, latestQuote] = await Promise.all([
      api.days(),
      api.latest().catch(() => null),
    ]);
    setDays(dayList);
    setLatest(latestQuote);
    const nextDate = date || dayList[0]?.date || latestQuote?.trade_date || "";
    setSelectedDate(nextDate);
    if (nextDate) {
      setCurve(await api.curve(nextDate));
    }
    setStatus(latestQuote?.collected_at ? `最近采集 ${latestQuote.collected_at.replace("T", " ")}` : "等待首次采集");
  }, []);

  useEffect(() => {
    loadAll()
      .catch((err: Error) => setError(err.message))
      .finally(() => setLoading(false));
  }, [loadAll]);

  useEffect(() => {
    if (!compareDate) {
      setCompareCurve(null);
      return;
    }
    api.curve(compareDate).then(setCompareCurve).catch((err: Error) => setError(err.message));
  }, [compareDate]);

  const onSelectDay = async (date: string) => {
    setSelectedDate(date);
    setCurve(await api.curve(date));
  };

  const onCollect = async () => {
    setCollecting(true);
    setError("");
    try {
      const result = await api.collect();
      setStatus(result.message);
      await loadAll(selectedDate || result.tick?.trade_date);
    } catch (err) {
      setError(err instanceof Error ? err.message : "采集失败");
    } finally {
      setCollecting(false);
    }
  };

  const summary = curve?.summary;
  const displayPrice = selectedDate === latest?.trade_date ? latest?.price ?? summary?.close : summary?.close;
  const displayChange = summary?.change_amt ?? latest?.change_amt;
  const displayRate = summary?.change_rate;

  const option = useMemo(() => {
    const series = [
      {
        name: selectedDate || "当日",
        type: "line",
        showSymbol: false,
        smooth: 0.15,
        data: (curve?.points || []).map((p) => [p.time, p.p]),
        lineStyle: { width: 2.2, color: "#d4af37" },
        areaStyle: {
          color: {
            type: "linear",
            x: 0,
            y: 0,
            x2: 0,
            y2: 1,
            colorStops: [
              { offset: 0, color: "rgba(212,175,55,0.28)" },
              { offset: 1, color: "rgba(212,175,55,0.02)" },
            ],
          },
        },
      },
    ];

    if (compareCurve) {
      series.push({
        name: compareDate,
        type: "line",
        showSymbol: false,
        smooth: 0.15,
        data: compareCurve.points.map((p) => [p.time, p.p]),
        lineStyle: { width: 1.6, color: "#8cb4d4" },
        areaStyle: {
          color: {
            type: "linear",
            x: 0,
            y: 0,
            x2: 0,
            y2: 1,
            colorStops: [
              { offset: 0, color: "rgba(140,180,212,0.16)" },
              { offset: 1, color: "rgba(140,180,212,0.01)" },
            ],
          },
        },
      });
    }

    return {
      backgroundColor: "transparent",
      tooltip: {
        trigger: "axis",
        backgroundColor: "#1b160f",
        borderColor: "rgba(212,175,55,0.25)",
        textStyle: { color: "#f4ead6" },
      },
      legend: {
        show: Boolean(compareCurve),
        top: 0,
        textStyle: { color: "#c9b896" },
      },
      grid: { left: 48, right: 18, top: compareCurve ? 36 : 18, bottom: 36 },
      xAxis: {
        type: "category",
        boundaryGap: false,
        axisLine: { lineStyle: { color: "rgba(212,175,55,0.2)" } },
        axisLabel: { color: "#8c8170" },
        splitLine: { show: false },
      },
      yAxis: {
        type: "value",
        scale: true,
        axisLabel: { color: "#8c8170" },
        splitLine: { lineStyle: { color: "rgba(212,175,55,0.08)" } },
      },
      series,
    };
  }, [compareCurve, compareDate, curve, selectedDate]);

  return (
    <div className="app">
      <header className="topbar">
        <div>
          <div className="brand-mark">FOR THE DAYS THAT MATTER</div>
          <h1 className="brand-title">MYGOLD</h1>
          <p className="brand-sub">浙商积存金每日价格曲线档案 · 今天看见昨天，以后也能看见今天</p>
        </div>
        <div className="top-actions">
          <div className="status">{status}</div>
          <button className="ghost-btn" onClick={() => loadAll(selectedDate)} disabled={loading}>
            刷新
          </button>
          <button className="gold-btn" onClick={onCollect} disabled={collecting}>
            {collecting ? "采集中…" : "立即采集"}
          </button>
        </div>
      </header>

      {error ? <div className="error">{error}</div> : null}

      <div className="layout">
        <aside className="panel sidebar">
          <h2>历史交易日</h2>
          <div className="day-list">
            {days.length === 0 && <div className="empty">还没有归档日期</div>}
            {days.map((day) => (
              <button
                key={day.date}
                className={`day-item ${day.date === selectedDate ? "active" : ""}`}
                onClick={() => onSelectDay(day.date)}
              >
                <span className="date">{day.date}</span>
                <span className="meta">
                  <span>{fmt(day.close)}</span>
                  <span className={`change ${changeClass(day.change_amt)}`}>{signed(day.change_amt)}</span>
                </span>
              </button>
            ))}
          </div>
        </aside>

        <section className="main">
          <div className="panel hero">
            <div className="hero-kicker">{selectedDate || "今日"} · 元 / 克</div>
            <div className="price-row">
              <div className="price">{fmt(displayPrice)}</div>
              <div className={`change ${changeClass(displayChange)}`}>
                <div className="change-main">
                  {signed(displayChange)}{" "}
                  {displayRate === null || displayRate === undefined ? "" : `(${signed(displayRate)}%)`}
                </div>
                <div className="change-sub">较昨日收盘 {fmt(summary?.prev_close ?? latest?.yesterday_price)}</div>
              </div>
            </div>
            <div className="stats">
              <div className="stat">
                <span>开盘</span>
                <strong>{fmt(summary?.open)}</strong>
              </div>
              <div className="stat">
                <span>最高</span>
                <strong>{fmt(summary?.high)}</strong>
              </div>
              <div className="stat">
                <span>最低</span>
                <strong>{fmt(summary?.low)}</strong>
              </div>
              <div className="stat">
                <span>点数</span>
                <strong>{summary?.point_count ?? 0}</strong>
              </div>
            </div>
          </div>

          <div className="panel chart-panel">
            <div className="chart-head">
              <h2>当日价格曲线</h2>
              <label className="compare">
                叠加对比
                <select value={compareDate} onChange={(e) => setCompareDate(e.target.value)}>
                  <option value="">不对比</option>
                  {days
                    .filter((d) => d.date !== selectedDate)
                    .map((d) => (
                      <option key={d.date} value={d.date}>
                        {d.date}
                      </option>
                    ))}
                </select>
              </label>
            </div>
            {curve && curve.points.length > 0 ? (
              <ReactECharts option={option} style={{ height: 420 }} notMerge />
            ) : (
              <div className="empty">{loading ? "加载中…" : "这一天还没有曲线，先点右上角采集一次。"}</div>
            )}
            <p className="hero-note">
              数据来自京东金融浙商积存金报价，并归档当日走势。请保持后端运行，跨天后即可回看历史曲线。
            </p>
          </div>
        </section>
      </div>
    </div>
  );
}
