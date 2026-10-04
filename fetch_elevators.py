"""주소록(.md)의 주소별 건축물대장 표제부를 조회해 엘리베이터 현황 HTML을 생성한다.

사용법:  python fetch_elevators.py
  - 인증키: 'Key_Open API.env' 의 DATA_GO_KR_KEY
  - 조회 결과는 cache/ 에 지번별로 저장되어 재실행 시 API를 다시 부르지 않는다
    (새로 조회하려면 cache/ 폴더를 지우고 실행).
  - 결과: elevator_data.json, 엘리베이터_현황.html, index.html(GitHub Pages용 동일본)
"""
import json
import re
import sys
import time
import urllib.parse
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path

BASE = Path(__file__).resolve().parent
SOURCE_MD = BASE / "백현동561_주변_전체주소록.md"
KEY_FILE = BASE / "Key_Open API.env"
TEMPLATE = BASE / "template.html"
CACHE_DIR = BASE / "cache"
OUT_JSON = BASE / "elevator_data.json"
OUT_HTML = BASE / "엘리베이터_현황.html"
OUT_INDEX = BASE / "index.html"  # GitHub Pages 진입 페이지 (내용 동일)

API_URL = "https://apis.data.go.kr/1613000/BldRgstHubService/getBrTitleInfo"
RECAP_URL = API_URL.replace("getBrTitleInfo", "getBrRecapTitleInfo")
KAKAO_URL = "https://dapi.kakao.com/v2/local/search/address.json"
CENTER_ADDR = "경기도 성남시 분당구 백현동 561"

ROW_RE = re.compile(
    r"^\|\s*(\d+)\s*\|\s*(.+?)\s*\|\s*(.+?)\s*\|\s*(\d*)\s*\|\s*(\d+)\s*\|\s*\[[^\]]+\]\(([^)]+)\)"
)
JIBUN_RE = re.compile(r"(산\s*)?(\d+)(?:-(\d+))?\s*$")
DONG_RE = re.compile(r"(\S+동)\s+(?:산\s*)?\d")
# 법정동 이름 -> (시군구코드, 법정동코드). 새 지역의 동을 추가할 때 여기에 넣는다.
DONG_CODES = {"백현동": ("41135", "11000"), "판교동": ("41135", "10800"), "운중동": ("41135", "11500"), "정자동": ("41135", "10300"), "서현동": ("41135", "10500"),
              "창곡동": ("41131", "10800")}  # 창곡동은 수정구(41131)
SECTION_RE = re.compile(r"^## (.+?) \((\d+)개\)")
SUMMARY_RE = re.compile(r"^\|\s*([^|]+?)\s*\|\s*(\d+)\s*\|\s*([^|]+?)\s*\|\s*$")


def load_key(name="DATA_GO_KR_KEY", required=True):
    for line in KEY_FILE.read_text(encoding="utf-8").splitlines():
        if line.strip().startswith(name + "="):
            return line.split("=", 1)[1].strip()
    if required:
        sys.exit(f"인증키({name})를 찾을 수 없습니다: {KEY_FILE}")
    return None


def parse_addresses():
    groups, rows, road = {}, [], None
    for line in SOURCE_MD.read_text(encoding="utf-8").splitlines():
        m = SUMMARY_RE.match(line)
        if m:
            groups[m.group(1)] = m.group(3)
            continue
        m = SECTION_RE.match(line)
        if m:
            road = m.group(1)
            continue
        m = ROW_RE.match(line)
        if m and road:
            # 지번주소 텍스트에서 동·본번·부번을 읽는다 (dorojuso 링크 코드는 실제 지번과 다를 때가 있음)
            jm, dm = JIBUN_RE.search(m.group(2)), DONG_RE.search(m.group(2))
            if not jm or not dm or dm.group(1) not in DONG_CODES:
                print(f"  건너뜀(지번 해석 불가 또는 DONG_CODES 미등록): {m.group(2)}")
                continue
            san, bun, ji = bool(jm.group(1)), int(jm.group(2)), int(jm.group(3) or 0)
            sigungu, bjdong = DONG_CODES[dm.group(1)]
            rows.append({
                "road": road,
                "group": groups.get(road, "기타"),
                "no": int(m.group(1)),
                "jibun": m.group(2),
                "doro": m.group(3),
                "zip": m.group(4),
                "entries": int(m.group(5)),
                "link": m.group(6),
                "sigunguCd": sigungu,
                "bjdongCd": bjdong,
                "platGbCd": "1" if san else "0",  # API: 대지=0, 산=1
                "bun": f"{bun:04d}",
                "ji": f"{ji:04d}",
            })
    return rows


def call_api(key, params, retries=3, url_base=API_URL):
    q = dict(params, serviceKey=key, numOfRows=100, _type="json")
    items, page = [], 1
    while True:
        q["pageNo"] = page
        url = url_base + "?" + urllib.parse.urlencode(q)
        for attempt in range(retries):
            try:
                with urllib.request.urlopen(url, timeout=30) as r:
                    data = json.loads(r.read().decode("utf-8"))
                break
            except Exception as e:  # 네트워크 오류·비JSON 응답 재시도
                if attempt == retries - 1:
                    raise RuntimeError(f"API 호출 실패 {params}: {e}")
                time.sleep(2 * (attempt + 1))
        header = data["response"]["header"]
        if header["resultCode"] != "00":
            raise RuntimeError(f"API 오류 {header}")
        body = data["response"]["body"]
        got = (body.get("items") or {}).get("item") or []
        if isinstance(got, dict):
            got = [got]
        items.extend(got)
        if len(items) >= int(body.get("totalCount") or 0) or not got:
            return items
        page += 1


def fetch_lot(key, row, recap=False):
    """지번별 표제부(recap=True 이면 총괄표제부)를 조회한다. 결과는 cache/ 에 저장."""
    params = {k: row[k] for k in ("sigunguCd", "bjdongCd", "platGbCd", "bun", "ji")}
    name = ("recap_" if recap else "") + "{sigunguCd}_{bjdongCd}_{platGbCd}_{bun}_{ji}.json".format(**params)
    cache = CACHE_DIR / name
    if cache.exists():
        return json.loads(cache.read_text(encoding="utf-8"))
    items = call_api(key, params, url_base=RECAP_URL if recap else API_URL)
    cache.write_text(json.dumps(items, ensure_ascii=False), encoding="utf-8")
    time.sleep(0.1)
    return items


def geocode(kakao_key, *queries):
    """카카오 주소 검색으로 (위도, 경도)를 구한다. 결과는 cache/geo.json 에 누적 저장."""
    cache_file = CACHE_DIR / "geo.json"
    cache = json.loads(cache_file.read_text(encoding="utf-8")) if cache_file.exists() else {}
    for q in queries:
        if q in cache:
            if cache[q]:
                return cache[q]
            continue
        req = urllib.request.Request(
            KAKAO_URL + "?" + urllib.parse.urlencode({"query": q}),
            headers={"Authorization": "KakaoAK " + kakao_key},
        )
        with urllib.request.urlopen(req, timeout=20) as r:
            docs = json.loads(r.read().decode("utf-8")).get("documents") or []
        hit = None
        if docs:
            for d in (docs[0].get("road_address"), docs[0], docs[0].get("address")):
                if d and d.get("x") and d.get("y"):
                    hit = [round(float(d["y"]), 7), round(float(d["x"]), 7)]
                    break
        cache[q] = hit
        cache_file.write_text(json.dumps(cache, ensure_ascii=False, indent=0), encoding="utf-8")
        time.sleep(0.05)
        if hit:
            return hit
    return None


def norm_addr(s):
    s = re.sub(r"\s*\(.*\)\s*$", "", s or "")
    return re.sub(r"\s+", " ", s).strip()


def num(v):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return 0


def summarize(row, items):
    target = norm_addr(row["doro"])
    matched = [i for i in items if norm_addr(i.get("newPlatPlc")) == target]
    match = "도로명 일치"
    if not matched:
        matched, match = items, "지번 기준"
    if not matched:
        return {"status": "unknown", "match": "대장 없음", "buildings": []}

    buildings = []
    for i in matched:
        buildings.append({
            "name": (i.get("bldNm") or "").strip(),
            "dong": (i.get("dongNm") or "").strip(),
            "main": i.get("mainAtchGbCdNm") or "",
            "kind": i.get("regstrKindCdNm") or "",
            "purpose": (i.get("mainPurpsCdNm") or "").strip(),
            "etcPurpose": (i.get("etcPurps") or "").strip(),
            "floors": num(i.get("grndFlrCnt")),
            "basement": num(i.get("ugrndFlrCnt")),
            "ride": num(i.get("rideUseElvtCnt")),
            "emergency": num(i.get("emgenUseElvtCnt")),
            "households": num(i.get("hhldCnt")) + num(i.get("fmlyCnt")) + num(i.get("hoCnt")),
            "platArea": float(i.get("platArea") or 0),
            "totArea": float(i.get("totArea") or 0),
            "useAprDay": (i.get("useAprDay") or "").strip(),
        })
    ride = sum(b["ride"] for b in buildings)
    emg = sum(b["emergency"] for b in buildings)
    main = [b for b in buildings if b["main"] != "부속건축물"] or buildings
    return {
        "status": "yes" if ride + emg > 0 else "no",
        "match": match,
        "ride": ride,
        "emergency": emg,
        "maxFloors": max(b["floors"] for b in main),
        "maxBasement": max(b["basement"] for b in main),
        # 대지면적은 같은 필지의 동마다 반복 기재되므로 최댓값, 연면적은 동별 합계
        "platArea": round(max(b["platArea"] for b in buildings), 2),
        "totArea": round(sum(b["totArea"] for b in buildings), 2),
        "buildings": buildings,
    }


def main():
    key = load_key()
    rows = parse_addresses()
    if not rows:
        sys.exit("주소를 읽지 못했습니다.")
    CACHE_DIR.mkdir(exist_ok=True)
    print(f"주소 {len(rows)}건 조회 시작")
    errors = 0
    for n, row in enumerate(rows, 1):
        try:
            row.update(summarize(row, fetch_lot(key, row)))
            # 집합건물(아파트 등)은 동별 표제부에 대지면적이 없어 총괄표제부에서 보충
            if row["status"] in ("yes", "no") and not row["platArea"]:
                recap = fetch_lot(key, row, recap=True)
                row["platArea"] = round(max([float(i.get("platArea") or 0) for i in recap] or [0]), 2)
        except RuntimeError as e:
            errors += 1
            row.update({"status": "error", "match": str(e)[:200], "buildings": []})
        if n % 25 == 0 or n == len(rows):
            print(f"  {n}/{len(rows)}")
    for row in rows:
        for k in ("sigunguCd", "bjdongCd", "platGbCd", "bun", "ji"):
            row.pop(k)

    center = None
    kakao_key = load_key("KAKAO_REST_KEY", required=False)
    if kakao_key:
        print("좌표 조회(카카오)")
        try:
            center = geocode(kakao_key, CENTER_ADDR)
            for row in rows:
                row["latlng"] = geocode(kakao_key, norm_addr(row["doro"]), row["jibun"])
            print(f"  좌표 확보 {sum(bool(r['latlng']) for r in rows)}/{len(rows)}")
        except urllib.error.HTTPError as e:
            print(f"  카카오 API 오류 {e.code}: {e.read().decode('utf-8', 'replace')[:200]} -> 지도 없이 생성")
    else:
        print("KAKAO_REST_KEY 없음 -> 지도 없이 생성")

    payload = {"generated": date.today().isoformat(), "source": "국토교통부 건축HUB 건축물대장정보 서비스(표제부)",
               "center": center, "rows": rows}
    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    data = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
    html = TEMPLATE.read_text(encoding="utf-8").replace("/*__DATA__*/null", data)
    OUT_HTML.write_text(html, encoding="utf-8")
    OUT_INDEX.write_text(html, encoding="utf-8")

    count = {s: sum(r["status"] == s for r in rows) for s in ("yes", "no", "unknown", "error")}
    print(f"완료: 있음 {count['yes']} / 없음 {count['no']} / 대장없음 {count['unknown']} / 오류 {count['error']}")
    print(f"-> {OUT_HTML.name}, {OUT_INDEX.name}")


if __name__ == "__main__":
    main()
