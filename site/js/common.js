/* 共用：資料載入與格式化 */
const ZONE_CLASS = ["zone-0", "zone-1", "zone-2", "zone-3", "zone-4"];

async function loadJSON(path) {
  const r = await fetch(path + "?v=" + Math.floor(Date.now() / 3600000));
  if (!r.ok) throw new Error(path + " " + r.status);
  return r.json();
}

function fmtPrice(v) {
  if (v == null) return "--";
  return v.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function fmtPct(v) {
  if (v == null) return "";
  return (v >= 0 ? "+" : "") + v.toFixed(2) + "%";
}

function fmtPE(v) {
  if (v == null) return "--";
  return v >= 1000 ? Math.round(v).toLocaleString() : v.toFixed(1);
}

/* 億為單位 */
function fmtYi(v, currency) {
  const yi = v / 1e8;
  const s = Math.abs(yi) >= 100 ? Math.round(yi).toLocaleString() : yi.toFixed(1);
  return s + " 億" + (currency && currency !== "USD" ? " " + currency : "");
}

/* 常見分項名稱中譯（找不到就保留英文） */
const SEG_ZH = {
  "Service": "服務", "Services": "服務",
  "Wearables, Home and Accessories": "穿戴裝置與配件",
  "Google Search & Other": "Google 搜尋及其他",
  "YouTube Advertising Revenue": "YouTube 廣告",
  "Google Network": "Google 聯播網",
  "Subscriptions, Platforms, And Devices Revenue": "訂閱、平台與裝置",
  "Google Cloud": "Google 雲端",
  "Other Operating Segment": "其他業務",
  "Automotive Sales": "汽車銷售",
  "Automotive Leasing": "汽車租賃",
  "Automotive Regulatory Credits": "碳權收入",
  "Services And Other": "服務及其他",
  "Energy Generation And Storage Sales": "能源與儲能銷售",
  "Energy Generation And Storage Leasing": "能源與儲能租賃",
  "Data Center": "資料中心", "Client": "客戶端", "Gaming": "遊戲", "Embedded": "嵌入式",
  "DRAM Products": "DRAM 產品", "NAND Products": "NAND 產品",
  "Other Product Sales": "其他產品",
  "Hyperscale": "超大規模資料中心",
  "AI Clouds, Industrial, & Enterprise": "AI 雲端、工業與企業",
  "Edge Computing": "邊緣運算",
  "Graphics Segment": "繪圖", "Compute & Networking Segment": "運算與網路",
  "其他營收": "其他營收",
};
function segName(n) { return SEG_ZH[n] || n; }

const CHART_FONT = '-apple-system, BlinkMacSystemFont, "PingFang TC", "Noto Sans TC", sans-serif';
const CHART_TEXT = "#d8dee9";
const CHART_MUTED = "#7a869c";
