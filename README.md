# 股票追蹤網站

深色主題美股追蹤站：本益比河流圖 + 營收結構桑基圖，每日自動更新。

## 新增 / 刪除追蹤股票

改 `stocks.json` 一行就好，**不用動任何程式碼**：

```json
{ "stocks": ["AAPL", "TSLA", "GOOGL", "MU", "TSM", "NVDA", "AMD"] }
```

直接在 GitHub 網頁編輯這個檔案按 Commit，幾分鐘後 GitHub Actions
會自動抓新股票的資料並重新部署網站。刪除代號則會同步移除該股票頁面。

## 運作方式

- **每日 06:00（台北時間）**：GitHub Actions 排程執行 `scripts/update.py`
  - 股價、現價本益比：每天更新（Yahoo Finance）
  - 財報數據：查 SEC EDGAR 最新申報，偵測到新 10-Q/10-K 才重抓重算
  - 有變更就 commit，Cloudflare Pages 偵測到 push 自動重新部署
- **資料來源**：Yahoo Finance（yfinance，免金鑰）+ SEC EDGAR 官方 API（免費）

## 圖表說明

- **本益比河流圖**：過去 5 年每日本益比取 5%～95% 百分位，等距切 6 條估值線
  （倍數 × 當時已公布的近四季 EPS，含拆股調整、無前視偏差），疊上實際股價
- **營收桑基圖**：最新一季損益流向；營收分項解析自 SEC 財報 XBRL
  （TSM 為外國發行人，無季度分項，僅顯示損益表流向）

## 本機開發

```bash
pip install -r scripts/requirements.txt
python scripts/update.py          # 更新資料（FORCE=1 強制重抓財報）
python -m http.server -d site     # 本機預覽
```
