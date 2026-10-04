"""한국승강기안전공단 승강기정보(승강기목록)를 받아 주소록 건물과 연결한다.

시군구 단위로 승강기 목록 전체를 받은 뒤, 승강기 소재지(도로명주소)가 건물 도로명주소와 같은 것을 붙인다.
건축물대장 승강기 수는 사용승인 당시 기준이라, 나중에 설치한 승강기는 이 자료로만 확인된다.

판정(row["liftNote"])
  later   : 대장 0대인데 운행중 승강기가 있고, 설치일이 사용승인보다 1년 넘게 늦음 → '있음' + '추후 설치'
  unrec   : 대장 0대(또는 대장 없음)인데 운행중 승강기가 준공 무렵부터 있음 → '있음' + '대장 누락'

  added   : 대장에도 있으나 사용승인 1년 이후 설치된 승강기가 있음 (증설)
  stopped : 등록은 있으나 운행중인 승강기가 없음 (운행중지·휴지·폐지)
  missing : 대장에는 있는데 같은 주소의 등록 승강기를 찾지 못함 (주소 표기 차이 가능)
"""
import json
import re
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import date, datetime

LIST_URL = "https://apis.data.go.kr/B553664/ElevatorInformationService/getElevatorListM"
PAGE = 500
MAX_AGE_DAYS = 30  # 캐시가 이보다 오래되면 다시 받는다
# 사람이 타는 엘리베이터가 아닌 종류
NON_PASSENGER = re.compile(r"에스컬레이터|무빙워크|휠체어리프트|자동차|덤웨이터|\(DW\)")


def fetch_all(key, sido, sigungu, cache_dir):
    cache = cache_dir / f"lifts_{sido}_{sigungu.replace(' ', '_')}.json"
    if cache.exists():
        age = (datetime.now() - datetime.fromtimestamp(cache.stat().st_mtime)).days
        if age < MAX_AGE_DAYS:
            return json.loads(cache.read_text(encoding="utf-8"))
    items, page = [], 1
    while True:
        q = {"serviceKey": key, "sido": sido, "sigungu": sigungu, "pageNo": page, "numOfRows": PAGE}
        for attempt in range(3):
            try:
                with urllib.request.urlopen(LIST_URL + "?" + urllib.parse.urlencode(q), timeout=60) as r:
                    root = ET.fromstring(r.read())
                break
            except Exception as e:
                if attempt == 2:
                    raise RuntimeError(f"승강기 API 호출 실패 {sigungu} p{page}: {e}")
                time.sleep(2 * (attempt + 1))
        code = (root.findtext(".//resultCode") or root.findtext(".//returnReasonCode") or "").strip()
        if code not in ("00", "000"):
            raise RuntimeError(f"승강기 API 오류 {sigungu}: {code} {root.findtext('.//resultMsg') or root.findtext('.//errMsg')}")
        got = [{c.tag: (c.text or "").strip() for c in it} for it in root.iter("item")]
        items.extend(got)
        total = int(root.findtext(".//totalCount") or 0)
        print(f"  승강기 {sigungu}: {len(items)}/{total}")
        if len(items) >= total or not got:
            break
        page += 1
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(items, ensure_ascii=False), encoding="utf-8")
    return items


def norm(addr):
    """'경기도 성남시 분당구 판교역로2번길 2 (백현동)' → '판교역로2번길2'"""
    a = re.sub(r"\s*\(.*\)\s*$", "", addr or "")
    a = re.sub(r"^\S+도\s+\S+시\s+\S+구\s+", "", a.strip())
    return re.sub(r"\s+", "", a)


def _d(v):
    v = (v or "").strip()
    return v.replace("-", ".") if re.match(r"\d{4}-\d{2}-\d{2}", v) else v


def attach(rows, key, cache_dir):
    areas = sorted({m.groups() for r in rows for m in [re.match(r"^(\S+도)\s+(\S+시\s+\S+구)\s", r["doro"])] if m})
    index = {}
    for sido, sigungu in areas:
        for it in fetch_all(key, sido, sigungu, cache_dir):
            index.setdefault(norm(it.get("address1")), []).append(it)

    stats = {"lifts": sum(len(v) for v in index.values()), "matched": 0, "later": 0, "unrec": 0, "added": 0, "stopped": 0, "missing": 0}
    for r in rows:
        found = [it for it in index.get(norm(r["doro"]), []) if not NON_PASSENGER.search(it.get("elvtrKindNm", ""))]
        r["lifts"] = [{
            "no": it.get("elevatorNo", ""), "kind": it.get("elvtrKindNm", ""), "stts": it.get("elvtrStts", ""),
            "inst": _d(it.get("installationDe")), "last": _d(it.get("lastInspctDe")),
            "result": it.get("lastResultNm", ""), "place": it.get("installationPlace", ""),
        } for it in found]
        active = [l for l in r["lifts"] if l["stts"] == "운행중"]
        r["liftActive"] = len(active)
        reg = (r.get("ride") or 0) + (r.get("emergency") or 0)
        years = [int(b["useAprDay"][:4]) for b in r.get("buildings", []) if b.get("useAprDay")]
        note = ""
        if r["lifts"]:
            stats["matched"] += 1
        inst_years = [int(l["inst"][:4]) for l in active if l["inst"][:4].isdigit()]
        if active and reg == 0:
            note = "later" if years and inst_years and min(inst_years) > min(years) + 1 else "unrec"
            r["statusReg"] = r["status"]  # 대장 기준 판정 보존
            r["status"] = "yes"
        elif r["lifts"] and not active:
            note = "stopped"
        elif reg > 0 and not r["lifts"]:
            note = "missing"
        elif years and any(y > min(years) + 1 for y in inst_years):
            note = "added"
        r["liftNote"] = note
        if note:
            stats[note] += 1
    return stats
