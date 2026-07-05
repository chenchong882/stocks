# -*- coding: utf-8 -*-
"""SEC EDGAR 資料抓取：EPS 歷史（本益比河流圖）與營收分項（桑基圖左半邊）。

免費、免金鑰，只需 User-Agent 帶聯絡方式。速率限制 10 req/s（此處遠低於）。
"""
import json
import re
import time
from datetime import date, datetime
from html import unescape

import requests

HEADERS = {"User-Agent": "Ivan Chen chenchong885@gmail.com"}
_session = requests.Session()
_session.headers.update(HEADERS)

_cik_map = None


def _get(url):
    for attempt in range(3):
        try:
            r = _session.get(url, timeout=60)
            if r.status_code == 200:
                return r
            if r.status_code == 404:
                return None
        except requests.RequestException:
            pass
        time.sleep(2 * (attempt + 1))
    raise RuntimeError("SEC request failed: %s" % url)


def get_cik(ticker):
    global _cik_map
    if _cik_map is None:
        data = _get("https://www.sec.gov/files/company_tickers.json").json()
        _cik_map = {v["ticker"].upper(): int(v["cik_str"]) for v in data.values()}
    return _cik_map.get(ticker.upper())


def get_submissions(cik):
    return _get("https://data.sec.gov/submissions/CIK%010d.json" % cik).json()


def list_financial_filings(subs, forms=("10-Q", "10-K")):
    """依申報日新到舊，列出財報申報：form, filed, accession, primaryDocument, reportDate。"""
    recent = subs["filings"]["recent"]
    out = []
    for i in range(len(recent["form"])):
        if recent["form"][i] in forms:
            out.append({
                "form": recent["form"][i],
                "filed": recent["filingDate"][i],
                "accession": recent["accessionNumber"][i],
                "primaryDocument": recent["primaryDocument"][i],
                "reportDate": recent["reportDate"][i],
            })
    return out


def get_companyfacts(cik):
    r = _get("https://data.sec.gov/api/xbrl/companyfacts/CIK%010d.json" % cik)
    return r.json() if r else None


def _parse_date(s):
    return datetime.strptime(s, "%Y-%m-%d").date()


def quarterly_eps(facts):
    """從 companyfacts 取稀釋 EPS，回傳 (quarters, years)，皆為 [{start, end, filed, val}]。

    同一期間在多份文件重複出現（次年比較期間、拆股後追溯調整），
    取最早申報值以符合「當時已知」原則（as-reported）。
    Q4 推導留給 compute（需先做拆股調整，否則同財年內混用不同股數基礎）。
    """
    gaap = facts.get("facts", {}).get("us-gaap", {})
    tag = gaap.get("EarningsPerShareDiluted") or gaap.get("EarningsPerShareBasic")
    if not tag:
        return [], []
    items = []
    for unit_vals in tag.get("units", {}).values():
        for f in unit_vals:
            if not f.get("start") or not f.get("end") or f.get("val") is None:
                continue
            items.append(f)

    quarters = {}  # end -> fact（季度期間，取最早 filed）
    years = {}     # (start,end) -> fact（年度期間）
    for f in items:
        start, end = _parse_date(f["start"]), _parse_date(f["end"])
        days = (end - start).days
        if 80 <= days <= 100:
            cur = quarters.get(end)
            if cur is None or f["filed"] < cur["filed"]:
                quarters[end] = f
        elif days >= 330:
            key = (start, end)
            cur = years.get(key)
            if cur is None or f["filed"] < cur["filed"]:
                years[key] = f

    q_out = sorted(({"start": q["start"], "end": q["end"],
                     "filed": q["filed"], "val": q["val"]}
                    for q in quarters.values()), key=lambda x: x["end"])
    y_out = sorted(({"start": y["start"], "end": y["end"],
                     "filed": y["filed"], "val": y["val"]}
                   for y in years.values()), key=lambda x: x["end"])
    return q_out, y_out


# ---------------------------------------------------------------------------
# 營收分項：解析 inline XBRL
# ---------------------------------------------------------------------------

REVENUE_TAGS = (
    "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
    "us-gaap:RevenueFromContractWithCustomerIncludingAssessedTax",
    "us-gaap:Revenues",
    "us-gaap:SegmentReportingInformationRevenue",
)
DIM_PRODUCT = "srt:ProductOrServiceAxis"
DIM_SEGMENT = "us-gaap:StatementBusinessSegmentsAxis"

_ctx_re = re.compile(
    r'<(?:xbrli:)?context[^>]*id="([^"]+)"[^>]*>(.*?)</(?:xbrli:)?context>', re.S)
_member_re = re.compile(
    r'<(?:xbrldi:)?explicitMember[^>]*dimension="([^"]+)"[^>]*>\s*([^<\s]+)\s*<')
_start_re = re.compile(r'<(?:xbrli:)?startDate>([^<]+)<')
_end_re = re.compile(r'<(?:xbrli:)?endDate>([^<]+)<')
_fact_re = re.compile(r'<ix:nonFraction([^>]*)>(.*?)</ix:nonFraction>', re.S)
_attr_re = re.compile(r'(\w[\w:-]*)="([^"]*)"')
_tag_strip_re = re.compile(r'<[^>]+>')


def filing_dir_url(cik, accession):
    return "https://www.sec.gov/Archives/edgar/data/%d/%s" % (
        cik, accession.replace("-", ""))


_ixbrl_cache = {}  # accession -> facts（同一份文件在多個期間會重複用到）


def parse_ixbrl_revenue_facts(cik, filing):
    """從 inline XBRL 主文件解析帶維度的營收 facts。

    回傳 [{dim, member, start, end, val}]，僅含單一維度（產品線或業務分部）的營收。
    """
    if filing["accession"] in _ixbrl_cache:
        return _ixbrl_cache[filing["accession"]]
    url = "%s/%s" % (filing_dir_url(cik, filing["accession"]), filing["primaryDocument"])
    html = _get(url).text

    contexts = {}
    for cid, body in _ctx_re.findall(html):
        members = _member_re.findall(body)
        if not members:
            continue
        dims = {d: m for d, m in members}
        # ConsolidationItemsAxis=OperatingSegments 是分部報告的常見包裝維度，直通；
        # 其他成員（如 IntersegmentElimination）整個 context 剔除
        for axis in ("srt:ConsolidationItemsAxis", "us-gaap:ConsolidationItemsAxis"):
            if axis in dims:
                if not dims[axis].endswith("OperatingSegmentsMember"):
                    dims = None
                    break
                dims = {d: m for d, m in dims.items() if d != axis}
        if not dims:
            continue
        # 允許單維度，或「產品線 × 業務分部」雙維度（如 GOOGL 的搜尋/YouTube 標記法）
        if len(dims) > 2 or not set(dims).issubset({DIM_PRODUCT, DIM_SEGMENT}):
            continue
        if DIM_PRODUCT in dims:
            dim, member = DIM_PRODUCT, dims[DIM_PRODUCT]
        else:
            dim, member = DIM_SEGMENT, dims[DIM_SEGMENT]
        m_start, m_end = _start_re.search(body), _end_re.search(body)
        if not (m_start and m_end):
            continue
        contexts[cid] = {"dim": dim, "member": member, "allmembers": tuple(sorted(dims.values())),
                         "start": m_start.group(1), "end": m_end.group(1)}

    facts = []
    seen = set()
    for attr_str, content in _fact_re.findall(html):
        attrs = dict(_attr_re.findall(attr_str))
        if attrs.get("name") not in REVENUE_TAGS:
            continue
        ctx = contexts.get(attrs.get("contextRef"))
        if not ctx:
            continue
        text = _tag_strip_re.sub("", content).replace(",", "").replace(" ", "").strip()
        if not text or text in ("-", "—"):
            continue
        try:
            val = float(text) * (10 ** int(attrs.get("scale", 0)))
        except ValueError:
            continue
        if attrs.get("sign") == "-":
            val = -val
        key = (ctx["dim"], ctx["allmembers"], ctx["start"], ctx["end"])
        if key in seen:
            continue
        seen.add(key)
        facts.append({"dim": ctx["dim"], "member": ctx["member"],
                      "start": ctx["start"], "end": ctx["end"], "val": val})
    _ixbrl_cache[filing["accession"]] = facts
    return facts


_labels_cache = {}


def get_member_labels(cik, filing):
    """從 MetaLinks.json 取各 member 的人類可讀標籤。"""
    if filing["accession"] in _labels_cache:
        return _labels_cache[filing["accession"]]
    url = "%s/MetaLinks.json" % filing_dir_url(cik, filing["accession"])
    r = _get(url)
    labels = _labels_cache[filing["accession"]] = {}
    if not r:
        return labels
    try:
        meta = r.json()
        for inst in meta.get("instance", {}).values():
            for tag_name, info in inst.get("tag", {}).items():
                lang = info.get("lang", {})
                for lv in lang.values():
                    role = lv.get("role", {})
                    label = role.get("label") or role.get("terseLabel")
                    if label:
                        labels[tag_name.replace("_", ":")] = re.sub(
                            r"\s*\[Member\]\s*$", "", label).strip()
                        break
    except (ValueError, KeyError):
        pass
    return labels


def _label_from_member(member):
    name = member.split(":")[-1]
    name = re.sub(r"Member$", "", name)
    name = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", name)
    return name


def _is_subtotal(value, others, tol=0.003):
    """value 是否約等於 others 中某子集合（≥2 項）之和 → 視為小計，剔除。

    容差需極小：小計理應精確等於成分之和（僅剩四捨五入誤差），
    容差太鬆會把巧合相近的獨立分項誤判成小計。
    """
    from itertools import combinations
    cands = [v for v in others if 0 < v < value * (1 + tol)]
    for r in range(2, min(len(cands), 6) + 1):
        for combo in combinations(cands, r):
            s = sum(combo)
            if abs(s - value) <= tol * value:
                return True
    return False


def _remove_subtotals(rows):
    """剔除小計項（如 GOOGL「Google Services」= 搜尋+YouTube+聯播網+訂閱）。"""
    members = sorted(rows.items(), key=lambda kv: -kv[1])
    kept, removed = [], set()
    for i, (m, v) in enumerate(members):
        others = [v2 for j, (m2, v2) in enumerate(members)
                  if j != i and m2 not in removed]
        if v > 0 and _is_subtotal(v, others):
            removed.add(m)
        else:
            kept.append((m, v))
    return kept


def extract_segments(cik, filing, quarter_end, total_revenue, prev_10q=None,
                     annual=False):
    """取目標期間的營收分項 [{name, value}]，驗證加總後回傳；失敗回傳 []。

    filing 為 10-Q 時直接取 3 個月期間 facts；為 10-K 時以 全年 − 前三季YTD 推得 Q4；
    annual=True 時直接取 10-K 的全年期間 facts（桑基圖年度檢視用）。
    """
    facts = parse_ixbrl_revenue_facts(cik, filing)
    labels = get_member_labels(cik, filing)

    def pick(fact_list, dim, end_date, min_days, max_days):
        rows = {}
        for f in fact_list:
            if f["dim"] != dim or f["end"] != end_date:
                continue
            days = (_parse_date(f["end"]) - _parse_date(f["start"])).days
            if not (min_days <= days <= max_days):
                continue
            rows[f["member"]] = rows.get(f["member"], 0) + f["val"]
        return rows

    ytd_facts = None

    def rows_for(dim):
        if annual:
            return pick(facts, dim, quarter_end, 330, 380)
        if filing["form"].startswith("10-Q") or filing["form"] in ("6-K",):
            return pick(facts, dim, quarter_end, 80, 100)
        # 10-K：全年 − 前三季 YTD（YTD 值在前一份 10-Q）
        nonlocal ytd_facts
        fy_rows = pick(facts, dim, quarter_end, 330, 380)
        if not fy_rows or not prev_10q:
            return {}
        if ytd_facts is None:
            ytd_facts = parse_ixbrl_revenue_facts(cik, prev_10q)
        ytd_rows = pick(ytd_facts, dim, prev_10q["reportDate"], 240, 290)
        if not ytd_rows:
            return {}
        return {m: fy_rows[m] - ytd_rows[m] for m in fy_rows if m in ytd_rows}

    product_rows = rows_for(DIM_PRODUCT)
    segment_rows = rows_for(DIM_SEGMENT)
    merged = dict(segment_rows)
    merged.update(product_rows)  # 同名時以產品線值為準

    # 三個候選池：合併（產品線+分部，靠小計剔除去重）、純產品線、純分部。
    # 有實際總營收時以「覆蓋率最接近 1」挑選（防止正交分解重複計算，
    # 如 AAPL 的產品線 × 地理區同時入池會加總成兩倍）；同分取分項較多者。
    best, best_score = None, None
    for rows in (merged, product_rows, segment_rows):
        if len(rows) < 2:
            continue
        kept = _remove_subtotals(rows)
        kept = [(m, v) for m, v in kept if v > 0]
        if len(kept) < 2:
            continue
        seg_sum = sum(v for _, v in kept)
        if total_revenue:
            coverage = seg_sum / total_revenue
            if coverage > 1.02 or coverage < 0.5:
                continue
            score = (round(coverage, 2), len(kept))
        else:
            if best is not None:
                continue  # 無總營收可驗證時，僅接受第一個非空池
            score = (0, len(kept))
        if best_score is None or score > best_score:
            best, best_score = kept, score

    if not best:
        return []
    segments = [{"name": unescape(labels.get(m, _label_from_member(m))), "value": v}
                for m, v in best]
    seg_sum = sum(s["value"] for s in segments)
    if total_revenue and seg_sum < total_revenue * 0.98:
        segments.append({"name": "其他營收", "value": total_revenue - seg_sum})
    segments.sort(key=lambda s: -s["value"])
    return segments
