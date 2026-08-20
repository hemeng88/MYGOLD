function request(path, method, data) {
  const app = getApp();
  return new Promise((resolve, reject) => {
    wx.request({
      url: `${app.globalData.apiBase}${path}`,
      method: method || "GET",
      data,
      header: { "Content-Type": "application/json" },
      success(res) {
        if (res.statusCode >= 200 && res.statusCode < 300) {
          resolve(res.data);
          return;
        }
        const detail = (res.data && (res.data.detail || res.data.message)) || `请求失败 ${res.statusCode}`;
        reject(new Error(typeof detail === "string" ? detail : JSON.stringify(detail)));
      },
      fail(err) {
        reject(new Error(err.errMsg || "网络失败。真机请用 HTTPS，开发者工具可关闭合法域名校验。"));
      },
    });
  });
}

function fmt(n, digits) {
  if (n === null || n === undefined || Number.isNaN(n)) return "—";
  return Number(n).toFixed(digits == null ? 2 : digits);
}

function signed(n) {
  if (n === null || n === undefined) return "—";
  return `${n > 0 ? "+" : ""}${Number(n).toFixed(2)}`;
}

module.exports = {
  request,
  fmt,
  signed,
  latest: () => request("/api/quote/latest"),
  curve: (date) => request(date ? `/api/curve?date=${date}` : "/api/curve"),
  days: () => request("/api/days"),
  rules: () => request("/api/rules"),
  events: (date) => request(date ? `/api/events?date=${date}` : "/api/events"),
  holdings: () => request("/api/holdings"),
  addLot: (data) => request("/api/holdings/lots", "POST", data),
  deleteLot: (id) => request(`/api/holdings/lots/${id}`, "DELETE"),
};
