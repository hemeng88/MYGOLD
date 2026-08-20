function drawCurve(canvasId, points, component) {
  const ctx = wx.createCanvasContext(canvasId, component);
  const width = 340;
  const height = 200;
  ctx.clearRect(0, 0, width, height);
  if (!points || points.length < 2) {
    ctx.setFillStyle("#8c8170");
    ctx.setFontSize(12);
    ctx.fillText("暂无曲线", 140, 100);
    ctx.draw();
    return;
  }
  const prices = points.map((p) => p.p);
  const min = Math.min.apply(null, prices);
  const max = Math.max.apply(null, prices);
  const span = max - min || 1;
  const pad = 16;
  ctx.setStrokeStyle("rgba(212,175,55,0.2)");
  ctx.setLineWidth(1);
  ctx.beginPath();
  ctx.moveTo(0, height - 1);
  ctx.lineTo(width, height - 1);
  ctx.stroke();

  ctx.setStrokeStyle("#e0c25c");
  ctx.setLineWidth(2);
  ctx.beginPath();
  points.forEach((point, i) => {
    const x = pad + ((width - pad * 2) * i) / (points.length - 1);
    const y = height - pad - ((point.p - min) / span) * (height - pad * 2);
    if (i === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  });
  ctx.stroke();
  ctx.draw();
}

module.exports = { drawCurve };
