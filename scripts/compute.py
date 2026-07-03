# -*- coding: utf-8 -*-
"""計算：本益比河流圖（PE Band）與營收結構桑基圖。"""
from datetime import datetime

ZONE_LABELS = ["極度低估", "偏低", "合理", "偏高", "極度高估"]


def _split_factor_after(splits, date_str):
    """date_str 之後所有拆股比例的乘積（把歷史值換算成今日股數基礎）。"""
    f = 1.0
    for d, ratio in splits:
        if d > date_str and ratio > 0:
            f *= ratio
    return f


def pe_band(dates, closes, splits, eps_quarters, eps_years=None, num_lines=6):
    """本益比河流圖資料。

    dates/closes：日收盤（Yahoo 已做拆股調整）；splits：全部拆股；
    eps_quarters/eps_years：as-reported EPS（含 filed 申報日）。
    先把 EPS 換算到今日股數基礎、補推 Q4（全年 − 前三季），再逐日算
    「當時已知」的近四季 EPS（TTM）→ 每日 PE → 取 5%/95% 百分位切 6 條估值線。
    """
    if not dates or len(eps_quarters) < 4:
        return None

    def adjust(rows):
        return [{"start": q.get("start"), "end": q["end"], "filed": q["filed"],
                 "val": q["val"] / _split_factor_after(splits, q["filed"])}
                for q in rows]

    adj_q = adjust(eps_quarters)
    ends = {q["end"] for q in adj_q}
    # 補推 Q4：10-K 只申報全年 EPS，Q4 = 全年 − 已知的該財年前三季
    # （拆股調整後才能相減，否則同財年混用不同股數基礎會得到垃圾值）
    for y in adjust(eps_years or []):
        if y["end"] in ends:
            continue
        in_fy = [q for q in adj_q
                 if q.get("start") and y["start"] <= q["start"] and q["end"] < y["end"]]
        if len(in_fy) == 3:
            adj_q.append({"start": None, "end": y["end"], "filed": y["filed"],
                          "val": y["val"] - sum(q["val"] for q in in_fy)})
            ends.add(y["end"])

    adj_eps = sorted(adj_q, key=lambda q: q["filed"])

    price_adj, ttm_series, pe_series = [], [], []
    j = 0
    window = []  # 已公布的 adj EPS，按 filed 排序
    for i, d in enumerate(dates):
        while j < len(adj_eps) and adj_eps[j]["filed"] <= d:
            window.append(adj_eps[j]["val"])
            j += 1
        p = closes[i]  # Yahoo 已做拆股調整
        price_adj.append(round(p, 2))
        if len(window) >= 4:
            ttm = sum(window[-4:])
            ttm_series.append(round(ttm, 4))
            pe_series.append(round(p / ttm, 2) if ttm > 0 else None)
        else:
            ttm_series.append(None)
            pe_series.append(None)

    valid_pe = sorted(v for v in pe_series if v is not None and v > 0)
    if len(valid_pe) < 30:
        return None
    # 用 5%/95% 百分位數當上下緣：GAAP EPS 短暫趨近零時 PE 會飆到數千
    # （如 2023 年的 AMD），取絕對 min/max 會把整張圖壓扁到不可讀
    pe_min = valid_pe[int(len(valid_pe) * 0.05)]
    pe_max = valid_pe[min(int(len(valid_pe) * 0.95), len(valid_pe) - 1)]
    multiples = [round(pe_min + (pe_max - pe_min) * k / (num_lines - 1), 1)
                 for k in range(num_lines)]

    current_pe = None
    for v in reversed(pe_series):
        if v is not None:
            current_pe = v
            break
    zone_index = None
    if current_pe is not None:
        zone_index = 0
        for k in range(1, num_lines):
            if current_pe >= multiples[k]:
                zone_index = min(k, num_lines - 2)
    return {
        "dates": dates,
        "price": price_adj,
        "ttm": ttm_series,
        "multiples": multiples,
        "currentPE": current_pe,
        "zoneIndex": zone_index,
        "zoneLabel": ZONE_LABELS[zone_index] if zone_index is not None else None,
    }


def _quarter_label(period_end):
    d = datetime.strptime(period_end, "%Y-%m-%d")
    return "%d Q%d" % (d.year, (d.month - 1) // 3 + 1)


def build_sankey(income, segments, financial_currency):
    """組裝桑基圖節點與連線。

    左：營收分項 → 總營收；右：總營收 → 營收成本｜毛利潤 → 營運費用（研發/銷管）｜
    營業利益 →（＋業外收入）→ 稅務支出｜其他支出｜淨利潤。
    節點 type：revenue（暖色）/ profit（綠）/ cost（紅）。
    """
    rev = income.get("revenue")
    net = income.get("netIncome")
    if not rev or net is None:
        return None

    nodes, links = [], []
    node_set = set()

    def add_node(name, ntype):
        if name not in node_set:
            node_set.add(name)
            nodes.append({"name": name, "type": ntype})

    def add_link(src, dst, val):
        if val is not None and val > 0:
            links.append({"source": src, "target": dst, "value": round(val)})

    add_node("總營收", "revenue")
    has_segments = bool(segments) and len(segments) >= 2
    if has_segments:
        for s in segments:
            add_node(s["name"], "revenue")
            add_link(s["name"], "總營收", s["value"])

    gross = income.get("grossProfit")
    cost = income.get("costOfRevenue")
    if gross is None and cost is not None:
        gross = rev - cost
    if cost is None and gross is not None:
        cost = rev - gross

    op = income.get("operatingIncome")
    if gross is not None and cost is not None and gross > 0:
        add_node("營收成本", "cost")
        add_node("毛利潤", "profit")
        add_link("總營收", "營收成本", cost)
        add_link("總營收", "毛利潤", gross)
        profit_src = "毛利潤"
        if op is not None and 0 < op < gross:
            opex = gross - op
            add_node("營運費用", "cost")
            add_link("毛利潤", "營運費用", opex)
            rnd, sga = income.get("rnd"), income.get("sga")
            detail = 0
            if rnd and rnd > 0:
                add_node("研發費用", "cost")
                add_link("營運費用", "研發費用", rnd)
                detail += rnd
            if sga and sga > 0:
                add_node("銷售與管理費用", "cost")
                add_link("營運費用", "銷售與管理費用", sga)
                detail += sga
            rest = opex - detail
            if rest > opex * 0.02:
                add_node("其他營運費用", "cost")
                add_link("營運費用", "其他營運費用", rest)
            add_node("營業利益", "profit")
            add_link("毛利潤", "營業利益", op)
            profit_src = "營業利益"
    else:
        # 沒有毛利結構（少數金融/特殊公司）：總營收直接對淨利與費用
        op = None
        profit_src = "總營收"

    # 稅與業外：profit_src（營業利益或毛利潤）流向 淨利潤 + 稅務 + 其他
    pretax = income.get("pretaxIncome")
    tax = income.get("tax")
    base = op if op is not None else (gross if profit_src == "毛利潤" else rev)
    if net > 0 and base is not None and base > 0:
        add_node("淨利潤", "profit")
        non_op = (pretax - base) if pretax is not None else 0.0  # 業外損益（利息、投資等）
        if non_op > net * 0.005:
            add_node("業外收入", "revenue")
            add_link("業外收入", "淨利潤", min(non_op, net))
        else:
            non_op = 0.0
        add_link(profit_src, "淨利潤", max(net - non_op, 0))
        if tax and tax > 0:
            add_node("稅務支出", "cost")
            add_link(profit_src, "稅務支出", tax)
        other_out = base + non_op - (tax if tax and tax > 0 else 0) - net
        if other_out > base * 0.01:
            add_node("其他支出", "cost")
            add_link(profit_src, "其他支出", other_out)

    if len(links) < 2:
        return None
    return {
        "nodes": nodes,
        "links": links,
        "hasSegments": has_segments,
        "netIncome": net,
        "financialCurrency": financial_currency,
    }


def quarter_label(period_end):
    return _quarter_label(period_end)


# ---------------------------------------------------------------------------
# 財務體質：ROE、毛利率趨勢、D/E、營業現金流/淨利
# ---------------------------------------------------------------------------

def _trend(rows, fn):
    out = []
    for r in rows:
        v = fn(r)
        out.append({"q": _quarter_label(r["end"]), "v": round(v, 2) if v is not None else None})
    return out


def _yoy_entry(rows, months=12):
    """找去年同期（約 12 個月前）那一季。"""
    if not rows:
        return None
    last = datetime.strptime(rows[-1]["end"], "%Y-%m-%d")
    for r in rows[:-1]:
        d = datetime.strptime(r["end"], "%Y-%m-%d")
        if abs((last - d).days - 365) <= 40:
            return r
    return None


def build_health(rows):
    """組裝財務體質卡片資料。rows 為 health_series 輸出（依季底排序）。

    每張卡：value（頭條值）、trend（各季 sparkline）、status（判讀文字）、
    level（good/mid/bad/neutral，前端上色用）。全為比率，無幣別問題。
    """
    if len(rows) < 2:
        return None
    last = rows[-1]
    health = {"asOf": last["end"]}

    # ROE：頭條用近四季淨利 ÷ 平均股東權益；sparkline 為單季 ROE
    roe_val = None
    ni4 = [r["netIncome"] for r in rows[-4:] if r["netIncome"] is not None]
    eqs = [r["equity"] for r in rows[-4:] if r["equity"] is not None]
    if len(ni4) == 4 and eqs:
        avg_eq = sum(eqs) / len(eqs)
        if avg_eq > 0:
            roe_val = round(sum(ni4) / avg_eq * 100, 1)
    def roe_q(r):
        if r["netIncome"] is None or not r["equity"] or r["equity"] <= 0:
            return None
        return r["netIncome"] / r["equity"] * 100
    if roe_val is not None:
        if roe_val >= 15:
            st, lv = "良好", "good"
        elif roe_val >= 8:
            st, lv = "普通", "mid"
        elif roe_val >= 0:
            st, lv = "偏低", "bad"
        else:
            st, lv = "虧損", "bad"
        health["roe"] = {"value": roe_val, "trend": _trend(rows, roe_q),
                         "status": st, "level": lv, "note": "近四季，僅 %d 季資料" % len(ni4) if len(ni4) < 4 else "近四季"}

    # 毛利率：頭條為最新一季，附 vs 上季 / vs 去年同期（百分點）
    def gm(r):
        if r["grossProfit"] is None or not r["revenue"]:
            return None
        return r["grossProfit"] / r["revenue"] * 100
    gm_now = gm(last)
    if gm_now is not None:
        gm_prev = gm(rows[-2])
        yoy_row = _yoy_entry(rows)
        gm_yoy = gm(yoy_row) if yoy_row else None
        qoq = round(gm_now - gm_prev, 1) if gm_prev is not None else None
        yoy = round(gm_now - gm_yoy, 1) if gm_yoy is not None else None
        if qoq is None:
            st, lv = "—", "neutral"
        elif qoq > 0.3:
            st, lv = "較上季上升", "good"
        elif qoq < -0.3:
            st, lv = "較上季下滑", "bad"
        else:
            st, lv = "大致持平", "neutral"
        health["grossMargin"] = {"value": round(gm_now, 1), "qoq": qoq, "yoy": yoy,
                                 "trend": _trend(rows, gm), "status": st, "level": lv}

    # D/E：有息負債 ÷ 股東權益
    def de(r):
        if r["totalDebt"] is None or not r["equity"] or r["equity"] <= 0:
            return None
        return r["totalDebt"] / r["equity"]
    de_now = de(last)
    if de_now is not None:
        if de_now < 0.5:
            st, lv = "低槓桿", "good"
        elif de_now < 1.5:
            st, lv = "適中", "mid"
        else:
            st, lv = "偏高", "bad"
        health["debtEquity"] = {"value": round(de_now, 2), "trend": _trend(rows, de),
                                "status": st, "level": lv}

    # 營業現金流 ÷ 淨利：頭條用近四季合計（單季波動大）
    ocf4 = [r["ocf"] for r in rows[-4:] if r["ocf"] is not None]
    ni4v = [r["netIncome"] for r in rows[-4:] if r["ocf"] is not None and r["netIncome"] is not None]
    def ocf_ni(r):
        if r["ocf"] is None or not r["netIncome"] or r["netIncome"] <= 0:
            return None
        return r["ocf"] / r["netIncome"]
    if ocf4 and ni4v and sum(ni4v) > 0:
        ratio = round(sum(ocf4) / sum(ni4v), 2)
        if ratio >= 1:
            st, lv = "現金紮實", "good"
        elif ratio >= 0.7:
            st, lv = "尚可", "mid"
        else:
            st, lv = "含金量偏低", "bad"
        health["ocfNi"] = {"value": ratio, "trend": _trend(rows, ocf_ni),
                           "status": st, "level": lv,
                           "note": "近四季" if len(ocf4) >= 4 else "近 %d 季" % len(ocf4)}

    # --- 第二排 ---

    def yoy_pct(now, ago):
        if now is None or not ago or ago <= 0:
            return None
        return round((now / ago - 1) * 100, 1)

    yoy_row = _yoy_entry(rows)

    # 營收 YoY：頭條為最新一季年增率，sparkline 為各季營收（億）
    rev_yoy = yoy_pct(last["revenue"], (yoy_row or {}).get("revenue"))
    if rev_yoy is not None:
        if rev_yoy >= 20:
            st, lv = "高速成長", "good"
        elif rev_yoy >= 5:
            st, lv = "穩健成長", "good"
        elif rev_yoy >= 0:
            st, lv = "低速成長", "mid"
        else:
            st, lv = "營收衰退", "bad"
        health["revenueYoy"] = {
            "value": rev_yoy, "latest": last["revenue"],
            "trend": _trend(rows, lambda r: r["revenue"] / 1e8 if r["revenue"] else None),
            "status": st, "level": lv}

    # 自由現金流：頭條為近四季合計，附 FCF 利潤率
    fcf4 = [r["fcf"] for r in rows[-4:] if r["fcf"] is not None]
    rev4 = [r["revenue"] for r in rows[-4:] if r["fcf"] is not None and r["revenue"]]
    if fcf4:
        fcf_ttm = sum(fcf4)
        margin = round(fcf_ttm / sum(rev4) * 100, 1) if rev4 else None
        if fcf_ttm <= 0:
            st, lv = "現金流出", "bad"
        elif margin is not None and margin >= 15:
            st, lv = "現金充沛", "good"
        elif margin is not None and margin >= 5:
            st, lv = "正常", "mid"
        else:
            st, lv = "偏薄", "mid"
        health["fcf"] = {
            "value": fcf_ttm, "margin": margin,
            "trend": _trend(rows, lambda r: r["fcf"] / 1e8 if r["fcf"] is not None else None),
            "status": st, "level": lv,
            "note": "近四季" if len(fcf4) >= 4 else "近 %d 季" % len(fcf4)}

    # 存貨 vs 營收增速：存貨增速明顯超過營收＝下游砍單的領先訊號
    inv_yoy = yoy_pct(last["inventory"], (yoy_row or {}).get("inventory"))
    if inv_yoy is not None and rev_yoy is not None:
        gap = inv_yoy - rev_yoy
        if gap > 15:
            st, lv = "庫存堆積", "bad"
        elif gap > 0:
            st, lv = "略高於營收", "mid"
        else:
            st, lv = "庫存健康", "good"
        health["inventory"] = {
            "value": inv_yoy, "revYoy": rev_yoy,
            "trend": _trend(rows, lambda r: r["inventory"] / 1e8 if r["inventory"] is not None else None),
            "status": st, "level": lv}
    elif last.get("inventory") is None:
        health["inventory"] = {"na": True}  # 無存貨科目（服務業）

    # 股數變化：負＝回購，正＝稀釋
    sh_yoy = yoy_pct(last["dilutedShares"], (yoy_row or {}).get("dilutedShares"))
    if sh_yoy is not None:
        if sh_yoy <= -0.5:
            st, lv = "回購中", "good"
        elif sh_yoy < 1:
            st, lv = "穩定", "neutral"
        elif sh_yoy < 3:
            st, lv = "輕微稀釋", "mid"
        else:
            st, lv = "明顯稀釋", "bad"
        health["shares"] = {
            "value": sh_yoy,
            "trend": _trend(rows, lambda r: r["dilutedShares"] / 1e8 if r["dilutedShares"] else None),
            "status": st, "level": lv}

    return health if len(health) > 1 else None
