/* 個股頁：本益比河流圖 + 營收桑基圖 */
(async () => {
  const symbol = new URLSearchParams(location.search).get("symbol");
  const content = document.getElementById("content");
  if (!symbol) { content.innerHTML = '<div class="error">缺少股票代號</div>'; return; }
  document.title = symbol + " ｜ 股票追蹤";

  let d;
  try {
    d = await loadJSON("data/" + encodeURIComponent(symbol.toUpperCase()) + ".json");
  } catch (e) {
    content.innerHTML = '<div class="error">找不到 ' + symbol + ' 的資料</div>';
    return;
  }

  /* ---- 頁首 ---- */
  document.getElementById("symbol").textContent = d.symbol;
  document.getElementById("name").textContent = d.name;
  document.getElementById("price").textContent = "$" + fmtPrice(d.quote.price);
  const chg = d.quote.changePct;
  const chgEl = document.getElementById("change");
  chgEl.textContent = fmtPct(chg);
  chgEl.className = "change " + (chg >= 0 ? "up" : "down");
  document.getElementById("pe").textContent = fmtPE(d.quote.pe);
  const band = d.peBand;
  if (band && band.zoneLabel) {
    document.getElementById("zone").innerHTML =
      '<span class="zone ' + ZONE_CLASS[band.zoneIndex] + '">' + band.zoneLabel + "</span>";
  }

  const ZONE_COLORS = ["#16c784", "#7ac760", "#f5a623", "#f06e3c", "#ea3943"];

  /* ---- 財務體質 ---- */
  const h = d.health;
  if (h) {
    document.getElementById("healthPanel").hidden = false;
    document.getElementById("hSub").textContent = "資料至 " + h.asOf;
    const stats = document.getElementById("stats");

    const pp = (v) => (v == null ? "--" : (v >= 0 ? "+" : "") + v.toFixed(1) + "pp");
    const pct = (v) => (v == null ? "--" : (v >= 0 ? "+" : "") + v.toFixed(1) + "%");
    const ppCls = (v) => (v == null ? "" : v >= 0 ? "up" : "down");
    const hCur = h.currency || "USD";
    const CARDS = [
      { key: "roe", label: "ROE（近四季）", fmt: (v) => v.toFixed(1) + "%", unit: "%" },
      { key: "grossMargin", label: "毛利率（本季）", fmt: (v) => v.toFixed(1) + "%", unit: "%",
        delta: (c) => 'vs 上季 <b class="' + ppCls(c.qoq) + '">' + pp(c.qoq) +
                      '</b>　vs 去年 <b class="' + ppCls(c.yoy) + '">' + pp(c.yoy) + "</b>" },
      { key: "debtEquity", label: "D/E 負債權益比", fmt: (v) => v.toFixed(2), unit: "" },
      { key: "ocfNi", label: "營業現金流 ÷ 淨利", fmt: (v) => v.toFixed(2), unit: "" },
      { key: "revenueYoy", label: "營收年增率", fmt: pct, unit: " 億",
        delta: (c) => "本季營收 <b>" + fmtYi(c.latest, hCur) + "</b>" },
      { key: "fcf", label: "自由現金流（近四季）", fmt: (v) => fmtYi(v, hCur), unit: " 億",
        delta: (c) => "FCF 利潤率 <b>" + (c.margin == null ? "--" : c.margin.toFixed(1) + "%") + "</b>" },
      { key: "inventory", label: "存貨年增率", fmt: pct, unit: " 億",
        delta: (c) => "營收年增 <b>" + pct(c.revYoy) + "</b>（比較基準）" },
      { key: "shares", label: "股數變化（YoY）", fmt: pct, unit: " 億股" },
    ];

    for (const cfg of CARDS) {
      const c = h[cfg.key];
      const el = document.createElement("div");
      el.className = "stat";
      if (!c || c.na) {
        el.innerHTML = '<div class="label">' + cfg.label + '</div><div class="value">--</div>' +
          (c && c.na ? '<div class="delta">無存貨科目（非製造業）</div>' : "");
        stats.appendChild(el);
        continue;
      }
      el.innerHTML =
        '<div class="label">' + cfg.label + "</div>" +
        '<div class="value">' + cfg.fmt(c.value) + "</div>" +
        '<div class="delta">' + (cfg.delta ? cfg.delta(c) : "&nbsp;") + "</div>" +
        '<div class="spark"></div>' +
        '<span class="chip lv-' + c.level + '">' + c.status + "</span>";
      stats.appendChild(el);

      const trend = (c.trend || []).filter((t) => t.v != null);
      if (trend.length >= 2) {
        const spark = echarts.init(el.querySelector(".spark"));
        spark.setOption({
          grid: { left: 0, right: 0, top: 2, bottom: 2 },
          xAxis: { type: "category", data: trend.map((t) => t.q), show: false },
          yAxis: { type: "value", show: false, scale: true },
          tooltip: {
            backgroundColor: "#1a2030", borderColor: "#2a3345",
            textStyle: { color: CHART_TEXT, fontSize: 11 }, confine: true,
            formatter: (p) => p[0].name + "<br><b>" + p[0].value + cfg.unit + "</b>",
            trigger: "axis",
          },
          series: [{
            type: "bar", data: trend.map((t, i) => ({
              value: t.v,
              itemStyle: {
                color: i === trend.length - 1 ? "#4aa8ff" : "rgba(74,168,255,.35)",
                borderRadius: 2,
              },
            })),
            barCategoryGap: "25%",
          }],
        });
        window.addEventListener("resize", () => spark.resize());
      }
    }
  }

  /* ---- 本益比河流圖 ---- */
  if (band) {
    document.getElementById("peSub").textContent =
      "過去 5 年估值區間 " + band.multiples[0] + "x ～ " + band.multiples[band.multiples.length - 1] +
      "x ｜ 目前 " + fmtPE(band.currentPE) + "x（" + band.zoneLabel + "）";

    const { dates, price, ttm, multiples } = band;
    const bandVal = (k, i) => (ttm[i] != null && ttm[i] > 0 ? +(multiples[k] * ttm[i]).toFixed(2) : null);

    const series = [{
      name: multiples[0] + "x", type: "line", stack: "pe",
      data: dates.map((_, i) => bandVal(0, i)),
      lineStyle: { width: 1, color: "rgba(122,199,96,.5)", type: "dashed" },
      symbol: "none", emphasis: { disabled: true }, z: 1,
    }];
    for (let k = 1; k < multiples.length; k++) {
      series.push({
        name: multiples[k] + "x", type: "line", stack: "pe",
        data: dates.map((_, i) => {
          const a = bandVal(k, i), b = bandVal(k - 1, i);
          return a == null || b == null ? null : +(a - b).toFixed(2);
        }),
        lineStyle: { width: 1, color: "rgba(216,222,233,.25)", type: "dashed" },
        areaStyle: { color: ZONE_COLORS[k - 1], opacity: 0.14 },
        symbol: "none", emphasis: { disabled: true }, z: 1,
      });
    }
    series.push({
      name: "股價", type: "line",
      data: price.map((v) => +v.toFixed(2)),
      lineStyle: { width: 2, color: "#4aa8ff" },
      itemStyle: { color: "#4aa8ff" },
      symbol: "none", z: 5,
    });

    const peChart = echarts.init(document.getElementById("peChart"));
    peChart.setOption({
      textStyle: { fontFamily: CHART_FONT },
      grid: { left: 8, right: 14, top: 34, bottom: 40, containLabel: true },
      legend: {
        data: series.map((s) => s.name),
        textStyle: { color: CHART_MUTED, fontSize: 10 },
        itemWidth: 14, itemHeight: 8, top: 0, type: "scroll",
        pageIconColor: CHART_TEXT, pageTextStyle: { color: CHART_MUTED },
      },
      tooltip: {
        trigger: "axis",
        backgroundColor: "#1a2030", borderColor: "#2a3345",
        textStyle: { color: CHART_TEXT, fontSize: 12 },
        confine: true,
        formatter: (params) => {
          const i = params[0].dataIndex;
          let html = "<b>" + dates[i] + "</b><br>股價 <b>$" + fmtPrice(price[i]) + "</b>";
          if (ttm[i] != null && ttm[i] > 0) {
            html += "<br>本益比 <b>" + (price[i] / ttm[i]).toFixed(1) + "x</b><br>";
            html += multiples.map((m, k) =>
              '<span style="color:' + (k === 0 ? "#7ac760" : ZONE_COLORS[k - 1]) + '">' +
              m + "x → $" + fmtPrice(m * ttm[i]) + "</span>").join("<br>");
          }
          return html;
        },
      },
      xAxis: {
        type: "category", data: dates, boundaryGap: false,
        axisLine: { lineStyle: { color: "#2a3345" } },
        axisLabel: {
          color: CHART_MUTED, fontSize: 10,
          formatter: (v) => v.slice(0, 7).replace("-", "/"),
        },
      },
      yAxis: {
        type: "value", scale: true,
        splitLine: { lineStyle: { color: "rgba(42,51,69,.6)" } },
        axisLabel: { color: CHART_MUTED, fontSize: 10 },
      },
      dataZoom: [{ type: "inside" }],
      series,
    });
    window.addEventListener("resize", () => peChart.resize());
  } else {
    document.getElementById("peChart").innerHTML =
      '<div class="error">EPS 資料不足，無法繪製河流圖</div>';
  }

  /* ---- 營收桑基圖 ---- */
  const sk = d.sankey;
  const skNote = document.getElementById("skNote");
  if (sk) {
    const cur = sk.financialCurrency || "USD";
    document.getElementById("skSub").textContent =
      sk.quarter + " 財報（截至 " + sk.periodEnd + "）｜ 單位：億 " + cur;

    const TYPE_COLOR = { revenue: "#f5a623", profit: "#16c784", cost: "#ea3943" };
    const SEG_PALETTE = ["#f5a623", "#f7b955", "#e8890c", "#ffd166", "#f28e2b", "#d9822b", "#c9781f"];
    let segIdx = 0;
    const isSeg = new Set(sk.links.filter((l) => l.target === "總營收").map((l) => l.source));

    // 依財務流向固定欄位，讓「業外收入」出現在右側靠近淨利潤
    const DEPTHS = {
      "總營收": 1, "營收成本": 2, "毛利潤": 2,
      "營運費用": 3, "營業利益": 3,
      "研發費用": 4, "銷售與管理費用": 4, "其他營運費用": 4, "業外收入": 4,
      "稅務支出": 5, "其他支出": 5, "淨利潤": 5,
    };
    const dShift = sk.hasSegments ? 0 : 1;
    const nodes = sk.nodes.map((n) => ({
      name: n.name,
      depth: isSeg.has(n.name) ? 0 : (DEPTHS[n.name] != null ? DEPTHS[n.name] - dShift : undefined),
      itemStyle: { color: isSeg.has(n.name) ? SEG_PALETTE[segIdx++ % SEG_PALETTE.length] : TYPE_COLOR[n.type] },
      _type: n.type,
    }));
    const links = sk.links.map((l) => ({
      ...l,
      lineStyle: { color: "gradient", opacity: 0.3, curveness: 0.55 },
    }));

    const skChart = echarts.init(document.getElementById("sankeyChart"));
    skChart.setOption({
      textStyle: { fontFamily: CHART_FONT },
      tooltip: {
        backgroundColor: "#1a2030", borderColor: "#2a3345",
        textStyle: { color: CHART_TEXT, fontSize: 12 },
        confine: true,
        formatter: (p) => {
          if (p.dataType === "edge") {
            return segName(p.data.source) + " → " + segName(p.data.target) +
              "<br><b>" + fmtYi(p.data.value, cur) + "</b>";
          }
          return segName(p.name) + "<br><b>" + fmtYi(p.value, cur) + "</b>";
        },
      },
      series: [{
        type: "sankey",
        left: 6, right: 130, top: 14, bottom: 14,
        nodeWidth: 12, nodeGap: 14, nodeAlign: "left",
        emphasis: { focus: "adjacency" },
        data: nodes,
        links,
        label: {
          color: CHART_TEXT, fontSize: 11,
          formatter: (p) => {
            const t = p.data._type;
            const color = t === "cost" ? "#ff8890" : t === "profit" ? "#4fe0a6" : "#ffc75e";
            return segName(p.name) + "\n{v|" + fmtYi(p.value, "") + "}";
          },
          rich: { v: { color: CHART_MUTED, fontSize: 10, lineHeight: 16 } },
        },
        lineStyle: { color: "gradient" },
      }],
    });
    window.addEventListener("resize", () => skChart.resize());

    const notes = [];
    if (!sk.hasSegments) notes.push("此公司未於財報中提供可解析的季度營收分項，僅顯示損益表流向。");
    if (cur !== "USD") notes.push("財報幣別為 " + cur + "。");
    notes.push("資料來源：公司申報之財務報表，點擊節點或流帶可查看數字。");
    skNote.textContent = notes.join(" ");
  } else {
    document.getElementById("sankeyChart").innerHTML =
      '<div class="error">尚無本季損益資料</div>';
  }
})();
