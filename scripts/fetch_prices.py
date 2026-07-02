# -*- coding: utf-8 -*-
"""yfinance 資料抓取：股價歷史、即時報價、季度損益表、EPS 備援。"""
import math
import time

import yfinance as yf


def _retry(fn, attempts=3):
    last = None
    for i in range(attempts):
        try:
            return fn()
        except Exception as e:  # yfinance 偶發網路/限流錯誤
            last = e
            time.sleep(3 * (i + 1))
    raise last


def get_ticker(symbol):
    return yf.Ticker(symbol)


def get_price_history(t, period="5y"):
    """收盤價（Yahoo 已做拆股調整、未做股息調整）+ 全部拆股紀錄。

    注意：Yahoo 回傳的 Close 已是今日股數基礎，「不可」再除以拆股比例；
    拆股紀錄僅供把 as-reported EPS 換算到同一基礎。
    回傳 (dates[str], closes[float], splits[(date_str, ratio)])。
    """
    df = _retry(lambda: t.history(period=period, auto_adjust=False))
    df = df.dropna(subset=["Close"])
    dates = [d.strftime("%Y-%m-%d") for d in df.index]
    closes = [round(float(c), 4) for c in df["Close"]]
    splits = []
    try:
        s = t.splits
        for d, ratio in s.items():
            if ratio and not math.isnan(ratio):
                splits.append((d.strftime("%Y-%m-%d"), float(ratio)))
    except Exception:
        pass
    return dates, closes, splits


def get_quote(t):
    info = _retry(lambda: t.info)
    price = info.get("regularMarketPrice") or info.get("currentPrice")
    prev = info.get("regularMarketPreviousClose")
    change_pct = None
    if price and prev:
        change_pct = round((price - prev) / prev * 100, 2)
    return {
        "name": info.get("longName") or info.get("shortName"),
        "price": price,
        "changePct": change_pct,
        "currency": info.get("currency", "USD"),
        "financialCurrency": info.get("financialCurrency", "USD"),
        "marketCap": info.get("marketCap"),
        "trailingPE": info.get("trailingPE"),
    }


def quarterly_income(t):
    """最新一季損益表主要科目（原幣別）。回傳 (period_end_str, dict) 或 (None, None)。"""
    df = _retry(lambda: t.quarterly_income_stmt)
    if df is None or df.empty:
        return None, None
    col = df.columns[0]  # 最新一季
    # 最新一欄可能幾乎全空（僅少數科目先公布），改用第一個營收非空的欄位
    for c in df.columns:
        v = df[c].get("Total Revenue")
        if v is not None and not (isinstance(v, float) and math.isnan(v)):
            col = c
            break

    def g(row):
        try:
            v = df[col].get(row)
            if v is None or (isinstance(v, float) and math.isnan(v)):
                return None
            return float(v)
        except (KeyError, TypeError):
            return None

    income = {
        "revenue": g("Total Revenue"),
        "costOfRevenue": g("Cost Of Revenue"),
        "grossProfit": g("Gross Profit"),
        "rnd": g("Research And Development"),
        "sga": g("Selling General And Administration"),
        "operatingExpense": g("Operating Expense"),
        "operatingIncome": g("Operating Income"),
        "pretaxIncome": g("Pretax Income"),
        "tax": g("Tax Provision"),
        "netIncome": g("Net Income"),
    }
    if income["revenue"] is None or income["netIncome"] is None:
        return None, None
    return col.strftime("%Y-%m-%d"), income


def eps_history_fallback(t, limit=32):
    """SEC 無資料時（如 TSM 外國發行人）用 Yahoo 財報行事曆的實際 EPS。

    以發布日當作 filed（「當時已知」對齊用）。
    """
    df = _retry(lambda: t.get_earnings_dates(limit=limit))
    if df is None or df.empty:
        return []
    out = []
    for idx, row in df.iterrows():
        v = row.get("Reported EPS")
        if v is None or (isinstance(v, float) and math.isnan(v)):
            continue
        d = idx.strftime("%Y-%m-%d")
        out.append({"end": d, "filed": d, "val": float(v)})
    # 去重（同日多筆）並由舊到新
    seen, uniq = set(), []
    for r in sorted(out, key=lambda x: x["filed"]):
        if r["filed"] in seen:
            continue
        seen.add(r["filed"])
        uniq.append(r)
    return uniq
