"""건축물대장(법정동 전체)에서 지정한 도로의 건물 주소를 뽑아 주소록(.md)에 새 구역으로 추가한다.

사용법:  python add_area.py
  - 아래 AREAS 에 지역 설정을 추가하면 같은 방식으로 주소록에 붙는다.
  - 이미 주소록에 있는 구역(같은 제목)은 건너뛴다.
  - 추가 후 python fetch_elevators.py 를 실행하면 HTML에 반영된다.
"""
import json
import re
import time
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import date

import fetch_elevators as fe

AREAS = [{
    "title": "판교동 판교공원로 일대",
    "group": "판교공원로 일대",
    "sigunguCd": "41135",
    "bjdongCd": "10800",  # 판교동
    # 도로명 -> 포함할 건물번호(본번) 범위. None 이면 전부,
    # "edge" 이면 둘레 큰길: 나머지 도로 건물들이 이루는 영역에서 edge_buffer_m(기본 25m) 이내인 건물만
    "roads": {
        "판교공원로1길": None,
        "판교공원로2길": None,
        "판교공원로3길": None,
        "판교공원로4길": None,
        "판교공원로5길": None,
        "운중로": (227, 263),
    },
    "note": "판교공원로1~5길 전체와 그 앞 운중로 227~263번(양쪽)을 포함했다. 지도에 표기된 운중로267번길은 "
            "건축물대장·카카오 주소검색 모두에 해당 주소가 없어 제외했다.",
}, {
    "title": "운중동 운중로113·125번길 일대",
    "group": "운중로113·125번길 일대",
    "sigunguCd": "41135",
    "bjdongCd": "11500",  # 운중동
    "roads": {
        "운중로113번길": None,
        "운중로125번길": None,
        "운중로": (115, 135, "odd"),
        "산운로": (146, 146),
    },
    "note": "운중로113번길·125번길 전체, 블록 남쪽 운중로 115~135번(홀수), 북쪽 산운로 146을 포함했다. "
            "운중로137번길 건물은 도로 동쪽 바깥이라 제외했다.",
}, {
    "title": "운중동 운중로138번길 일대",
    "group": "운중로126·138번길 일대",
    "sigunguCd": "41135",
    "bjdongCd": "11500",  # 운중동
    "roads": {
        "운중로138번길": None,
        "운중로126번길": None,
        "운중로": (118, 136, "even"),
    },
    # 건축물대장 API에 없지만 지도에 있는 건물: (지번주소, 도로명주소)
    "extras": [
        ("경기도 성남시 분당구 운중동 935", "경기도 성남시 분당구 운중로138번길 10 (운중동, 운중동 행정복지센터)"),
    ],
    "note": "운중로138번길·126번길 전체와 블록 북쪽 운중로 118~136번(짝수)을 포함했다. 지도(OSM)에 '운중로138번길'로 "
            "표기된 가운데 골목의 5~12번은 실제 운중로126번길 주소다. 운중동 행정복지센터(운중동 935)는 건축물대장 "
            "API에 없어 수동으로 넣었다(대장 레코드 수 0).",
}, {
    "title": "정자동 느티로·내정로·백현로 단독주택 일대",
    "group": "정자동 단독주택 일대",
    "sigunguCd": "41135",
    "bjdongCd": "10300",  # 정자동
    "roads": {
        "황새울로108번길": None, "황새울로116번길": None, "황새울로132번길": None,
        "느티로51번길": None, "느티로63번길": None, "느티로69번길": None, "느티로77번길": None, "느티로87번길": None,
        "내정로107번길": None, "내정로113번길": None, "내정로119번길": None, "내정로129번길": None,
        "백현로144번길": None, "백현로150번길": None, "백현로156번길": None,
        "느티로": (65, 73, "odd"), "내정로": (111, 111), "백현로": (146, 156), "황새울로": (124, 124),
    },
    "note": "황새울로·백현로·내정로·느티로로 둘러싸인 단독주택 단지의 번길 15개 전체와, 큰길에 붙은 느티로 65~73(북쪽 홀수), "
            "백현로 146~156, 내정로 111, 황새울로 124(백현초등학교)를 포함했다. 이름이 같은 내정로7·11·17번길, "
            "황새울로12·18번길은 약 1km 남쪽이라 제외했다.",
}, {
    "title": "정자동 내정로7번길·불정로 일대",
    "group": "정자동 내정로7번길·불정로 일대",
    "sigunguCd": "41135",
    "bjdongCd": "10300",  # 정자동
    "roads": {
        "황새울로12번길": None, "황새울로18번길": None,
        "내정로7번길": None, "내정로11번길": None, "내정로17번길": None,
        "불정로65번길": None, "불정로71번길": None, "불정로77번길": None, "불정로87번길": None,
        "황새울로": (4, 4),
    },
    # 도로는 포함하되 지도 범위 밖인 주소 (내정로17번길이 북쪽으로 꺾여 이어지는 구간)
    "exclude": ["내정로17번길 2", "내정로17번길 4-7", "내정로17번길 4-9", "내정로17번길 4-11", "내정로17번길 8"],
    "note": "황새울로·내정로17번길·불정로87번길·불정로로 둘러싸인 블록의 번길 9개 전체와 분당중학교(황새울로 4)를 "
            "포함했다. 정자동 행정복지센터는 황새울로18번길 14로 대장에 있다. 북쪽 내정로 24(정든마을)·29(금곡프라자)는 "
            "범위 밖이라 제외했다.",
}, {
    "title": "서현동 서현로237번길·안골로 일대",
    "group": "서현동 서현로237번길·안골로 일대",
    "sigunguCd": "41135",
    "bjdongCd": "10500",  # 서현동
    "roads": {
        "서현로237번길": None, "서현로239번길": None, "서현로247번길": None, "서현로255번길": None, "서현로257번길": None,
        "새마을로1번길": None, "새마을로7번길": None, "안골로11번길": None,
        "서현로": (241, 251, "odd"), "새마을로": (5, 31), "안골로": (1, 25),
    },
    "exclude": ["안골로 24"],
    "note": "서현로237~257번길, 새마을로1·7번길, 안골로11번길 전체와 큰길의 서현로 241~251(북쪽), 새마을로 5~31, "
            "안골로 1~25를 포함했다. 화면 동쪽 밖인 안골로 24·27, 새마을로 35·37, 새마을로51번길, 안골로48번길은 제외했다.",
}, {
    "title": "수정구 창곡동 위례서일로1·3길 일대",
    "group": "위례 위례서일로1·3길 일대",
    "sigunguCd": "41131",  # 수정구
    "bjdongCd": "10800",   # 창곡동
    "roads": {
        "위례서일로1길": None, "위례서일로3길": None,
        "위례서로": (12, 34), "위례서일로": (2, 30), "위례광장로": (21, 45, "odd"),
    },
    "note": "위례서일로1·3길(남북 두 블록) 전체와 둘레의 위례서로 12~34(도로 동쪽), 위례서일로 2~30, 위례광장로 21~45 "
            "홀수(도로 서쪽)를 포함했다. 위례광장로 동쪽 건너편(푸르지오 4~6단지, 아이페리온 등)과 위례서일로 46은 제외했다.",
}, {
    "title": "서울 송파구 방이동 올림픽로32길 일대",
    "group": "방이동 올림픽로32길 일대",
    "sigunguCd": "11710",  # 서울 송파구
    "bjdongCd": "11100",   # 방이동
    "roads": {
        "올림픽로30길": None, "올림픽로32길": None, "올림픽로34길": None,
        "오금로11길": None, "오금로13길": None, "오금로15길": None, "오금로17길": None,
        "위례성대로2길": None, "백제고분로51길": None,
        # 둘레 큰길은 블록 쪽 면만 (모서리 건물 포함)
        "올림픽로": (336, 380, "even"), "오금로": (87, 153, "odd"),
        "백제고분로": (449, 497, "odd"), "위례성대로": (2, 18, "even"),
    },
    "note": "올림픽로·오금로·위례성대로·백제고분로로 둘러싸인 블록의 골목(올림픽로30·32·34길, 오금로11·13·15·17길, "
            "위례성대로2길, 백제고분로51길) 전체와, 둘레 큰길의 블록 쪽 면(올림픽로 336~380 짝수, 오금로 87~153 홀수, "
            "백제고분로 449~497 홀수, 위례성대로 2~18 짝수)을 포함했다. 오금로 남쪽(송파동)과 백제고분로 동쪽은 제외했다.",
}, {
    "title": "판교동 서판교로44·58·66번길 일대",
    "group": "판교동 서판교로44·58·66번길 일대",
    "sigunguCd": "41135",
    "bjdongCd": "10800",  # 판교동
    "roads": {"서판교로44번길": None, "서판교로58번길": None, "서판교로66번길": None},
    # 지도 화면 범위: 아래 44번길 홀수 줄 ~ 위 66번길 2~14 줄, 서판교로 ~ 동쪽 세로 골목
    "bbox": (37.3907, 37.3927, 127.0975, 127.0997),
    "note": "서판교로44·58·66번길 중 지도 화면 범위(아래쪽 44번길 1~17-11 홀수 줄부터 위쪽 66번길 2~14 줄까지, "
            "서판교로에서 동쪽 세로 골목까지)의 건물만 좌표로 골라 포함했다. 44번길 짝수·19번 이후, 66번길 3·5·7·9·13·15·19 "
            "계열은 화면 밖이라 제외했다.",
}, {
    "title": "야탑동 장미로·야탑로 사이 일대",
    "group": "야탑동 장미로·야탑로 일대",
    "sigunguCd": "41135",
    "bjdongCd": "10700",  # 야탑동
    "roads": None,  # 골목이 많아 도로 대신 좌표 범위로 선택
    "bbox": (37.4099, 37.4137, 127.1288, 127.1340),
    # 단지 중심 좌표가 범위 경계 바로 밖이지만 화면 안에 있는 아파트
    "extras": [("경기도 성남시 분당구 야탑동 391", "경기도 성남시 분당구 야탑로 125 (야탑동, 아이파크)")],
    "note": "성남대로(서)·장미로(북)·매화로(동)·야탑로(남) 사이, 지도 화면 범위 안의 야탑동 건물 전체를 좌표로 골라 포함했다. "
            "아이파크(야탑로 125)는 단지 중심 좌표가 범위 경계 밖이라 직접 추가했다.",
}, {
    "title": "야탑동 매화로·벌말로 사이 일대",
    "group": "야탑동 매화로·벌말로 일대",
    "sigunguCd": "41135",
    "bjdongCd": "10700",  # 야탑동
    "roads": None,
    "bbox": (37.4096, 37.4132, 127.1340, 127.1384),
    "note": "매화로(서)·장미로(북)·벌말로(동)·야탑로(남) 사이, 지도 화면 범위 안의 야탑동 건물 전체를 좌표로 골라 포함했다.",
}]

ROAD_RE = re.compile(r"\S+구 (\S+) (지하)?(\d+)(?:-(\d+))?")  # 시·구 다음의 도로명과 건물번호


def dong_items(AREA):
    cache = fe.CACHE_DIR / f"dong_{AREA['sigunguCd']}_{AREA['bjdongCd']}.json"
    if cache.exists():
        return json.loads(cache.read_text(encoding="utf-8"))
    fe.CACHE_DIR.mkdir(exist_ok=True)
    items = fe.call_api(fe.load_key(), {"sigunguCd": AREA["sigunguCd"], "bjdongCd": AREA["bjdongCd"]})
    cache.write_text(json.dumps(items, ensure_ascii=False), encoding="utf-8")
    return items


def zip_code(kakao_key, addr):
    if not kakao_key:
        return ""
    req = urllib.request.Request(
        fe.KAKAO_URL + "?" + urllib.parse.urlencode({"query": addr}),
        headers={"Authorization": "KakaoAK " + kakao_key},
    )
    with urllib.request.urlopen(req, timeout=20) as r:
        docs = json.loads(r.read().decode("utf-8")).get("documents") or []
    time.sleep(0.05)
    road = docs[0].get("road_address") if docs else None
    return (road or {}).get("zone_no", "")


def _xy(ll):
    """위경도 → 대략적인 미터 좌표 (위도 37.5° 기준)"""
    return (ll[1] * 88300.0, ll[0] * 111000.0)


def _hull(pts):
    """볼록 껍질 (monotone chain), 반시계 방향"""
    pts = sorted(set(pts))
    if len(pts) < 3:
        return pts
    cross = lambda o, a, b: (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])
    lower, upper = [], []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return lower[:-1] + upper[:-1]


def _near_hull(p, hull, buf):
    """p 가 껍질 안이거나 경계에서 buf(m) 이내인지"""
    n = len(hull)
    inside = all((hull[(i + 1) % n][0] - hull[i][0]) * (p[1] - hull[i][1]) -
                 (hull[(i + 1) % n][1] - hull[i][1]) * (p[0] - hull[i][0]) >= 0 for i in range(n))
    if inside:
        return True
    for i in range(n):
        (ax, ay), (bx, by) = hull[i], hull[(i + 1) % n]
        dx, dy = bx - ax, by - ay
        t = max(0.0, min(1.0, ((p[0] - ax) * dx + (p[1] - ay) * dy) / ((dx * dx + dy * dy) or 1)))
        if ((p[0] - ax - t * dx) ** 2 + (p[1] - ay - t * dy) ** 2) ** 0.5 <= buf:
            return True
    return False


def main():
    for area in AREAS:
        if f"\n# {area['title']}\n" in fe.SOURCE_MD.read_text(encoding="utf-8"):
            print(f"이미 추가됨, 건너뜀: {area['title']}")
            continue
        add_area(area)


def add_area(AREA):
    text = fe.SOURCE_MD.read_text(encoding="utf-8")

    found = {}  # (도로명주소, 지번) -> 대장 레코드 수
    for i in dong_items(AREA):
        doro = (i.get("newPlatPlc") or "").strip()
        m = ROAD_RE.search(doro)
        any_road = AREA["roads"] is None  # 도로 지정 없음: bbox 안의 모든 도로
        if not m or (not any_road and m.group(1) not in AREA["roads"]):
            continue
        rng, no = (None if any_road else AREA["roads"][m.group(1)]), int(m.group(3))
        if rng == "edge":  # 둘레 큰길: 아래에서 안쪽 블록에 붙은 건물만 남긴다
            rng = None
        elif rng and not rng[0] <= no <= rng[1]:
            continue
        if rng and len(rng) > 2 and (no % 2 == 1) != (rng[2] == "odd"):
            continue
        if re.sub(r"^\S+?(?:도|특별시|광역시) (?:\S+시 )?\S+구 ", "", fe.norm_addr(doro)) in AREA.get("exclude", []):
            continue
        jibun = re.sub(r"번지$", "", (i.get("platPlc") or "").strip())
        key = (doro, jibun)
        found[key] = found.get(key, 0) + 1
    if AREA.get("bbox"):  # (위도 최소, 위도 최대, 경도 최소, 경도 최대) 밖의 주소 제외
        la0, la1, lo0, lo1 = AREA["bbox"]
        kakao_key = fe.load_key("KAKAO_REST_KEY")
        for k in list(found):
            ll = fe.geocode(kakao_key, fe.norm_addr(k[0]))
            if not ll or not (la0 <= ll[0] <= la1 and lo0 <= ll[1] <= lo1):
                del found[k]
    edge_roads = {r for r, v in (AREA["roads"] or {}).items() if v == "edge"}
    if edge_roads:
        kakao_key = fe.load_key("KAKAO_REST_KEY")
        road_of = lambda k: ROAD_RE.search(k[0]).group(1)
        inner = [fe.geocode(kakao_key, fe.norm_addr(k[0])) for k in found if road_of(k) not in edge_roads]
        hull = _hull([_xy(ll) for ll in inner if ll])
        buf = AREA.get("edge_buffer_m", 25)
        for k in [k for k in found if road_of(k) in edge_roads]:
            ll = fe.geocode(kakao_key, fe.norm_addr(k[0]))
            if not ll or not _near_hull(_xy(ll), hull, buf):
                del found[k]
    for jibun, doro in AREA.get("extras", []):
        found.setdefault((doro, jibun), 0)

    def sort_key(k):
        m = ROAD_RE.search(k[0])
        order = list(AREA["roads"]) if AREA["roads"] else sorted({ROAD_RE.search(x[0]).group(1) for x in found})
        return (order.index(m.group(1)), int(m.group(3)), int(m.group(4) or 0))

    by_road = defaultdict(list)
    kakao_key = fe.load_key("KAKAO_REST_KEY", required=False)
    for key in sorted(found, key=sort_key):
        by_road[ROAD_RE.search(key[0]).group(1)].append((key, found[key], zip_code(kakao_key, fe.norm_addr(key[0]))))

    total = sum(len(v) for v in by_road.values())
    out = [
        "",
        f"# {AREA['title']}",
        "",
        f"수집일: {date.today().isoformat()}",
        "",
        "- 국토교통부 건축물대장 표제부(법정동 전체 조회)에서 아래 도로의 건물을 추렸다. 동일 도로명주소·지번은 합쳤고 대장 레코드 수를 기록했다.",
        f"- {AREA['note']}",
        "- 도로명주소가 없는 대장(부속시설 등)은 제외했다. 우편번호는 카카오 주소검색 기준이다.",
        "",
        "| 도로 | 중복 제거 주소 수 | 구분 |",
        "|---|---:|---|",
    ]
    out += [f"| {road} | {len(rows)} | {AREA['group']} |" for road, rows in by_road.items()]
    out += ["", f"전체: 중복 제거 {total}개 주소.", ""]
    for road, rows in by_road.items():
        out += [f"## {road} ({len(rows)}개)", "",
                "| 번호 | 지번주소 | 도로명주소 | 우편번호 | 대장 레코드 수 | 출처 |",
                "|---:|---|---|---|---:|---|"]
        for n, ((doro, jibun), cnt, zc) in enumerate(rows, 1):
            link = "https://map.kakao.com/link/search/" + urllib.parse.quote(fe.norm_addr(doro))
            out.append(f"| {n} | {jibun} | {doro} | {zc} | {cnt} | [카카오맵]({link}) |")
        out.append("")

    fe.SOURCE_MD.write_text(text.rstrip("\n") + "\n" + "\n".join(out), encoding="utf-8")
    print(f"{AREA['title']}: {total}개 주소 추가 -> {fe.SOURCE_MD.name}")
    for road, rows in by_road.items():
        print(f"  {road}: {len(rows)}")


if __name__ == "__main__":
    main()
