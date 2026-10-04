"""국토교통부 단독/다가구 매매 실거래가를 받아 주소록 건물과 연결한다.

실거래 자료는 지번이 일부 가려져(예: '5**') 오므로 다음 기준으로 건물을 추정한다.
  1. 법정동이 같고, 본번이 가려진 지번의 첫 자리·자릿수와 맞는 건물
  2. 대지면적·연면적이 소수점까지 같은 건물 (신고 면적은 대개 건축물대장 값 그대로)
  3. 2에서 하나도 없으면 오차 1%(최소 1㎡)까지 허용하되, 후보가 한 곳일 때만 '추정'(approx)으로 연결
  4. 후보가 여럿이면 건축년도(사용승인 연도 ±1년)로 한 번 더 좁힘
그래도 여럿이면 후보 모두에 붙이고 'cand'(후보 수)를 기록한다. 해제된 거래는 제외한다.
"""
import json
import re
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import date

SH_URL = "https://apis.data.go.kr/1613000/RTMSDataSvcSHTrade/getRTMSDataSvcSHTrade"
YEARS = 10
REFRESH_MONTHS = 3  # 신고·해제가 늦게 반영되는 최근 몇 달은 매번 다시 받는다


def month_list(today, years=YEARS):
    y, m = today.year, today.month
    out = []
    for _ in range(years * 12):
        out.append(f"{y}{m:02d}")
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    return out


def fetch_month(key, lawd, ym, cache_dir, recent):
    cache = cache_dir / f"SH_{lawd}_{ym}.json"
    if cache.exists() and ym not in recent:
        return json.loads(cache.read_text(encoding="utf-8"))
    items, page = [], 1
    while True:
        q = {"serviceKey": key, "LAWD_CD": lawd, "DEAL_YMD": ym, "numOfRows": 1000, "pageNo": page}
        for attempt in range(3):
            try:
                with urllib.request.urlopen(SH_URL + "?" + urllib.parse.urlencode(q), timeout=30) as r:
                    root = ET.fromstring(r.read())
                break
            except Exception as e:  # 네트워크 오류·비XML 응답 재시도
                if attempt == 2:
                    raise RuntimeError(f"실거래 API 호출 실패 {lawd} {ym}: {e}")
                time.sleep(2 * (attempt + 1))
        code = (root.findtext(".//resultCode") or root.findtext(".//returnReasonCode") or "").strip()
        if code not in ("000", "00"):
            msg = root.findtext(".//resultMsg") or root.findtext(".//errMsg")
            raise RuntimeError(f"실거래 API 오류 {lawd} {ym}: {code} {msg}")
        got = [{c.tag: (c.text or "").strip() for c in it} for it in root.iter("item")]
        items.extend(got)
        total = int(root.findtext(".//totalCount") or 0)
        if len(items) >= total or not got:
            break
        page += 1
    cache.write_text(json.dumps(items, ensure_ascii=False), encoding="utf-8")
    time.sleep(0.05)
    return items


def _f(v):
    try:
        return float(str(v).replace(",", ""))
    except ValueError:
        return 0.0


def _near(a, b, exact):
    tol = 0.051 if exact else max(1.0, 0.01 * b)
    return a > 0 and b > 0 and abs(a - b) <= tol


def normalize(it):
    if (it.get("cdealType") or "").strip():  # 해제된 거래
        return None
    try:
        y, m, d = int(it["dealYear"]), int(it["dealMonth"]), int(it.get("dealDay") or 1)
    except (KeyError, ValueError):
        return None
    return {
        "date": f"{y}.{m:02d}.{d:02d}",
        "amount": int(_f(it.get("dealAmount"))),  # 만원
        "type": it.get("houseType", ""),
        "how": it.get("dealingGbn", ""),
        "plot": _f(it.get("plottageAr")),
        "floor": _f(it.get("totalFloorAr")),
        "year": int(_f(it.get("buildYear"))) or None,
        "dong": it.get("umdNm", ""),
        "mask": it.get("jibun", ""),
    }


def attach(rows, key, cache_dir, dong_codes, today=None):
    """rows 각각에 'deals'(최근순)를 붙이고 통계를 돌려준다."""
    today = today or date.today()
    cache_dir.mkdir(parents=True, exist_ok=True)
    months = month_list(today)
    recent = set(months[:REFRESH_MONTHS])

    # 건물 색인: (법정동, 본번 문자열)
    index = {}
    for r in rows:
        r["deals"] = []
        m = re.search(r"(\S+동)\s+(\d+)(?:-\d+)?$", r["jibun"])
        if not m or r.get("status") not in ("yes", "no"):
            continue
        r["_years"] = {int(b["useAprDay"][:4]) for b in r["buildings"] if b.get("useAprDay")}
        index.setdefault(m.group(1), []).append((m.group(2), r))

    lawds = sorted({dong_codes[d][0] for d in index if d in dong_codes})
    deals = []
    for lawd in lawds:
        for n, ym in enumerate(months, 1):
            deals += [x for x in map(normalize, fetch_month(key, lawd, ym, cache_dir, recent)) if x]
            if n % 30 == 0:
                print(f"  실거래 {lawd}: {n}/{len(months)}개월")

    stats = {"deals": 0, "matched": 0, "ambiguous": 0, "approx": 0}
    for d in deals:
        cands_all = index.get(d["dong"])
        if not cands_all:
            continue
        stats["deals"] += 1
        mask = d["mask"]
        first, width = mask[:1], len(mask)
        pool = [r for bun, r in cands_all if not first or (bun.startswith(first) and len(bun) == width)]
        approx = False
        for exact in (True, False):
            cands = [r for r in pool if _near(r.get("platArea", 0), d["plot"], exact) and (
                _near(r.get("totArea", 0), d["floor"], exact) or any(_near(b["totArea"], d["floor"], exact) for b in r["buildings"]))]
            if len(cands) > 1 and d["year"]:
                narrowed = [r for r in cands if any(abs(y - d["year"]) <= 1 for y in r["_years"])]
                cands = narrowed or cands
            if exact and cands:
                break
            if not exact:
                approx = True
                if len(cands) != 1:  # 오차 허용 단계에서는 후보가 하나일 때만 연결
                    cands = []
        if not cands:
            continue
        stats["matched"] += 1
        stats["ambiguous"] += len(cands) > 1
        stats["approx"] += approx
        rec = {k: d[k] for k in ("date", "amount", "type", "how", "plot", "floor", "year")}
        rec["cand"] = len(cands)
        rec["approx"] = approx
        for r in cands:
            r["deals"].append(rec)

    for r in rows:
        r.pop("_years", None)
        r["deals"].sort(key=lambda x: x["date"], reverse=True)
    stats["months"] = len(months)
    stats["range"] = f"{months[-1][:4]}.{months[-1][4:]}~{months[0][:4]}.{months[0][4:]}"
    return stats
