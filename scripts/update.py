# -*- coding: utf-8 -*-
"""每日更新入口。

- 股價 / 報價 / PE band：每次都更新（有新收盤價）
- 財報（EPS 歷史、桑基圖）：只在偵測到新申報（10-Q/10-K）時重抓 SEC
- 追蹤清單：stocks.json；移除的股票同步刪除 data 檔
"""
import json
import os
import sys
import traceback
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import compute
import fetch_prices as fp
import fetch_sec as sec

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT, "site", "data")
TPE = timezone(timedelta(hours=8))


def load_json(path):
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return None


def save_json(path, obj):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))


def latest_sec_filing(symbol):
    cik = sec.get_cik(symbol)
    if not cik:
        return None, None, None
    subs = sec.get_submissions(cik)
    forms = ("10-Q", "10-K") if sec.list_financial_filings(subs) else ("20-F",)
    filings = sec.list_financial_filings(subs, forms)
    if not filings:
        return cik, None, None
    return cik, filings[0], filings


def build_financials(symbol, cik, filing, filings, ticker, income, period_end):
    """重抓財報：EPS 歷史（SEC 優先）與營收分項。"""
    eps_quarters, eps_years, segments = [], [], []
    if cik and filing and filing["form"] in ("10-Q", "10-K"):
        facts = sec.get_companyfacts(cik)
        if facts:
            eps_quarters, eps_years = sec.quarterly_eps(facts)
        # 分項期間需與損益表同一季，否則桑基圖左右對不上。
        # 非月底結帳的公司（AAPL 3/28、NVDA 4/26…）yfinance 會標成月底，容忍 ±7 天
        same_quarter = False
        if income and period_end and filing.get("reportDate"):
            d1 = datetime.strptime(filing["reportDate"], "%Y-%m-%d")
            d2 = datetime.strptime(period_end, "%Y-%m-%d")
            same_quarter = abs((d1 - d2).days) <= 7
        if same_quarter:
            prev_10q = None
            if filing["form"] == "10-K":
                prev_10q = next((f for f in filings[1:] if f["form"] == "10-Q"), None)
            try:
                segments = sec.extract_segments(cik, filing, filing["reportDate"],
                                                income.get("revenue"), prev_10q)
            except Exception:
                print("  segments 解析失敗（退回無分項）: %s" % symbol)
                traceback.print_exc()
    if not eps_quarters:
        eps_quarters = fp.eps_history_fallback(ticker)
    return eps_quarters, eps_years, segments


def update_symbol(symbol, prev):
    t = fp.get_ticker(symbol)
    quote = fp.get_quote(t)
    dates, closes, splits = fp.get_price_history(t)
    period_end, income = fp.quarterly_income(t)

    cik, filing, filings = latest_sec_filing(symbol)
    prev_filing = (prev or {}).get("latestFiling") or {}
    need_refresh = (
        prev is None
        or os.environ.get("FORCE") == "1"
        or not prev.get("epsQuarters")
        or (filing or {}).get("accession") != prev_filing.get("accession")
        or (prev.get("sankey") or {}).get("periodEnd") != period_end
    )

    if need_refresh:
        print("  重抓財報（%s）" % ((filing or {}).get("form", "yfinance")))
        eps_quarters, eps_years, segments = build_financials(
            symbol, cik, filing, filings, t, income, period_end)
    else:
        eps_quarters = prev["epsQuarters"]
        eps_years = prev.get("epsYears") or []
        segments = (prev.get("sankey") or {}).get("segmentsRaw") or []

    band = compute.pe_band(dates, closes, splits, eps_quarters, eps_years)

    sankey = None
    if income:
        sk = compute.build_sankey(income, segments, quote["financialCurrency"])
        if sk:
            sankey = {
                "quarter": compute.quarter_label(period_end),
                "periodEnd": period_end,
                "segmentsRaw": segments,
                **sk,
            }

    price = quote["price"]
    pe = None
    if band and band["ttm"] and band["ttm"][-1] and band["ttm"][-1] > 0 and price:
        pe = round(price / band["ttm"][-1], 2)

    return {
        "symbol": symbol,
        "name": quote["name"] or symbol,
        "currency": quote["currency"],
        "updated": datetime.now(TPE).strftime("%Y-%m-%d %H:%M"),
        "latestFiling": {k: filing[k] for k in ("form", "filed", "accession", "reportDate")} if filing else None,
        "quote": {"price": price, "changePct": quote["changePct"],
                  "pe": pe or quote["trailingPE"], "marketCap": quote["marketCap"]},
        "epsQuarters": eps_quarters,
        "epsYears": eps_years,
        "peBand": band,
        "sankey": sankey,
    }


def main():
    with open(os.path.join(ROOT, "stocks.json"), encoding="utf-8") as f:
        symbols = [s.upper() for s in json.load(f)["stocks"]]
    os.makedirs(DATA_DIR, exist_ok=True)

    summary, failed = [], []
    for symbol in symbols:
        path = os.path.join(DATA_DIR, "%s.json" % symbol)
        prev = load_json(path)
        print("== %s ==" % symbol)
        try:
            data = update_symbol(symbol, prev)
            save_json(path, data)
        except Exception:
            traceback.print_exc()
            failed.append(symbol)
            data = prev  # 抓取失敗沿用舊資料，避免網站開天窗
            if data is None:
                continue
        summary.append({
            "symbol": data["symbol"], "name": data["name"],
            "price": data["quote"]["price"], "changePct": data["quote"]["changePct"],
            "pe": data["quote"]["pe"], "currency": data["currency"],
            "zoneLabel": (data.get("peBand") or {}).get("zoneLabel"),
            "quarter": (data.get("sankey") or {}).get("quarter"),
        })

    save_json(os.path.join(DATA_DIR, "summary.json"), {
        "updated": datetime.now(TPE).strftime("%Y-%m-%d %H:%M"),
        "stocks": summary,
    })

    # 清除已移除股票的資料檔
    keep = {"%s.json" % s for s in symbols} | {"summary.json"}
    for fn in os.listdir(DATA_DIR):
        if fn.endswith(".json") and fn not in keep:
            os.remove(os.path.join(DATA_DIR, fn))
            print("移除 %s" % fn)

    if failed:
        print("失敗：%s" % ", ".join(failed))
        if len(failed) == len(symbols):
            sys.exit(1)  # 全滅才視為失敗，部分失敗仍部署舊資料
    print("完成，共 %d 檔" % len(summary))


if __name__ == "__main__":
    main()
