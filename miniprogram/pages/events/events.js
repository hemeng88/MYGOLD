const api = require("../../utils/api");

Page({
  data: {
    events: [],
    error: "",
  },

  onShow() {
    this.load();
  },

  async load() {
    try {
      const events = await api.events();
      this.setData({
        events: (events || []).map((item) => ({
          ...item,
          triggered_at: String(item.triggered_at || "").replace("T", " "),
        })),
        error: "",
      });
    } catch (err) {
      this.setData({ error: err.message || "加载失败" });
    }
  },

  openUrl(e) {
    const url = e.currentTarget.dataset.url;
    if (!url) return;
    wx.setClipboardData({ data: url });
  },
});
