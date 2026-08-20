const api = require("../../utils/api");
const { drawCurve } = require("../../utils/chart");

Page({
  data: {
    quote: {},
    rule: null,
    priceText: "—",
    changeText: "",
    changeClass: "muted",
    feeText: "",
    openText: "—",
    highText: "—",
    lowText: "—",
    pointText: "—",
    error: "",
  },

  onShow() {
    this.load();
  },

  async load() {
    wx.showNavigationBarLoading();
    try {
      const [quote, curve, rule] = await Promise.all([
        api.latest(),
        api.curve(),
        api.rules().catch(() => null),
      ]);
      const change = curve.summary && curve.summary.change_amt;
      this.setData({
        quote,
        rule,
        priceText: api.fmt(quote.price),
        changeText: `${api.signed(change)}  较昨日 ${api.fmt((curve.summary && curve.summary.prev_close) || quote.yesterday_price)}`,
        changeClass: change > 0 ? "up" : change < 0 ? "down" : "muted",
        feeText: rule ? `${(rule.sell_fee_rate * 100).toFixed(1)}%` : "",
        openText: api.fmt(curve.summary && curve.summary.open),
        highText: api.fmt(curve.summary && curve.summary.high),
        lowText: api.fmt(curve.summary && curve.summary.low),
        pointText: String((curve.summary && curve.summary.point_count) || 0),
        error: "",
      });
      const sampled = (curve.points || []).filter((_, i, arr) => i % Math.ceil(arr.length / 80) === 0 || i === (curve.points || []).length - 1);
      drawCurve("curve", sampled, this);
    } catch (err) {
      this.setData({ error: err.message || "加载失败" });
    } finally {
      wx.hideNavigationBarLoading();
    }
  },
});
