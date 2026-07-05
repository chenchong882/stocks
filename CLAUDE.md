# 股票追蹤網站 專案規範

本檔是這個專案「教訓與規則」的唯一存放處。以後被要求「記住／別再犯」的專案教訓，一律追加在這裡。

## 架構

- 本機：`~/Desktop/股票`；repo：`github.com/chenchong882/stocks`（public）
- 流程：Python 抓資料（yfinance 股價/損益表 + SEC EDGAR EPS/營收分項 XBRL 解析）→ 寫 `site/data/*.json` → 靜態前端（ECharts 深色主題）→ Cloudflare Pages（部署目錄 `site/`）
- 追蹤清單：根目錄 `stocks.json`，GitHub 網頁直接改即可增減股票，不用動程式

## 自動化

- GitHub Actions cron UTC 22:00（台北 06:00）自動更新；偵測到新 10-Q/10-K 才重抓財報；`stocks.json` 改動也會觸發
- 強制重抓：`FORCE=1 python scripts/update.py`

## Git 帳號

推送用 `chenchong882` 帳號——keychain / gh 預設帳號常是沒權限的 `Ivan-1999CODE`，一般 `git push` 會 403。可靠做法：

```
cd ~/Desktop/股票 && TOK=$(gh auth token --user chenchong882) && git push "https://chenchong882:${TOK}@github.com/chenchong882/stocks.git" HEAD:main
```

commit 用 `git -c user.name=chenchong882 -c user.email=chenchong885@gmail.com commit`。

## 技術地雷（都踩過、修過，別再犯）⚠️

- Yahoo 價格**已做拆股調整**，不可再除一次
- EPS 推 Q4 要**先拆股調整**再「全年 − 三季」
- PE band 用 5%/95% 百分位，不用 min/max（AMD 2023 GAAP EPS≈0 會讓 min/max 爆掉）
- SEC 分項解析要接受 `ConsolidationItemsAxis=OperatingSegments` 與「產品×分部」雙維度，並用覆蓋率選池
- TSM（外國發行人）無季度分項、財報幣別 TWD、EPS 走 yfinance fallback
