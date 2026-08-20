const api = require("../../utils/api");

function today() {
  const now = new Date();
  const m = `${now.getMonth() + 1}`.padStart(2, "0");
  const d = `${now.getDate()}`.padStart(2, "0");
  return `${now.getFullYear()}-${m}-${d}`;
}

Page({
  data: {
    lots: [],
    grams: "",
    buyPrice: "",
    boughtAt: today(),
    note: "",
    saving: false,
    gramsText: "—",
    avgText: "—",
    valueText: "—",
    pnlText: "—",
    pnlClass: "muted",
    beText: "",
  },

  onShow() {
    this.refresh();
  },

  onGrams(e) { this.setData({ grams: e.detail.value }); },
  onPrice(e) { this.setData({ buyPrice: e.detail.value }); },
  onDate(e) { this.setData({ boughtAt: e.detail.value }); },
  onNote(e) { this.setData({ note: e.detail.value }); },

  async refresh() {
    try {
      const data = await api.holdings();
      const pnl = data.net_if_sell_now;
      this.setData({
        lots: data.lots || [],
        gramsText: api.fmt(data.total_grams, 4),
        avgText: api.fmt(data.avg_cost),
        valueText: api.fmt(data.market_value),
        pnlText: api.signed(pnl),
        pnlClass: pnl > 0 ? "up" : pnl < 0 ? "down" : "muted",
        beText: data.avg_cost
          ? `保本卖出 ${api.fmt(data.breakeven_sell)}，还需 ${api.fmt(data.needed_rise)} 元/克`
          : "",
      });
    } catch (err) {
      wx.showToast({ title: err.message || "加载失败", icon: "none" });
    }
  },

  async submit() {
    const grams = Number(this.data.grams);
    const buyPrice = Number(this.data.buyPrice);
    if (!grams || !buyPrice) {
      wx.showToast({ title: "请填写克数和买入价", icon: "none" });
      return;
    }
    this.setData({ saving: true });
    try {
      await api.addLot({
        grams,
        buy_price: buyPrice,
        bought_at: this.data.boughtAt,
        note: this.data.note || undefined,
      });
      this.setData({ grams: "", buyPrice: "", note: "" });
      await this.refresh();
      wx.showToast({ title: "已记下", icon: "success" });
    } catch (err) {
      wx.showToast({ title: err.message || "保存失败", icon: "none" });
    } finally {
      this.setData({ saving: false });
    }
  },

  async remove(e) {
    const id = e.currentTarget.dataset.id;
    try {
      await api.deleteLot(id);
      await this.refresh();
    } catch (err) {
      wx.showToast({ title: err.message || "删除失败", icon: "none" });
    }
  },
});
