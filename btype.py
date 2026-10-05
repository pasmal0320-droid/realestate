"""건축물대장 층별개요로 건물 유형(단독주택·상가주택 등)과 층별 구성을 만든다.

유형(row["btype"])
  상가주택 : 주거 층과 상가(근린생활시설 등) 층이 함께 있음
  단독주택 : 주거 층만 있음 (단독·다가구·다중주택)
  공동주택 : 주용도가 공동주택(아파트·다세대·연립 등)
  상가     : 상가 층만 있음
  기타     : 업무·종교·교육·숙박 등
층별개요가 없으면 표제부의 주용도·기타용도로 판정한다 (row["btypeBy"] = "용도").
"""
import re

HOUSE = re.compile(r"단독주택|다가구|다중주택")
APT = re.compile(r"공동주택|아파트|다세대|연립|기숙사")
SHOP = re.compile(r"근린생활|음식점|소매|사무소|의원|치과|한의원|약국|학원|교습|미용|이용원|세탁|제과|휴게|판매|금융|중개|"
                  r"체육|노래|게임|당구|독서실|공방|사진|수리점|목욕|안마|마사지|탁구|볼링|골프연습|고시원")
SUPPORT = re.compile(r"계단실|기계실|물탱크|전기실|발전기|펌프실|승강기|옥탑|창고|주차장|대피|공용|복도|발코니")

FLOOR_LABEL = {"house": "주택", "apt": "공동주택", "shop": "상가", "other": "기타"}


def floor_kind(item):
    text = f"{item.get('mainPurpsCdNm', '')} {item.get('etcPurps', '')}"
    if SUPPORT.search(item.get("mainPurpsCdNm", "") + " " + item.get("etcPurps", "")) and not (HOUSE.search(text) or SHOP.search(text)):
        return "support"
    if (item.get("flrGbCdNm") or "").startswith("옥탑"):
        return "support"
    if HOUSE.search(text):
        return "house"
    if APT.search(text):
        return "apt"
    if SHOP.search(text):
        return "shop"
    return "other"


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def floor_rows(items):
    """층별개요 → 정렬된 층 목록 [{f, kind, use, etc, area}] (주건축물만, 같은 층은 합침)"""
    out = {}
    for it in items:
        if (it.get("mainAtchGbCdNm") or "") == "부속건축물":
            continue
        gb = it.get("flrGbCdNm") or ""
        try:
            no = int(float(it.get("flrNo") or 0))
        except ValueError:
            continue
        order = -no if gb == "지하" else (1000 + no if gb.startswith("옥탑") else no)
        label = f"B{no}" if gb == "지하" else (f"옥탑{no}" if gb.startswith("옥탑") else f"{no}F")
        kind = floor_kind(it)
        key = (order, kind)
        rec = out.setdefault(key, {"o": order, "f": label, "kind": kind, "uses": [], "area": 0.0})
        use = (it.get("mainPurpsCdNm") or "").strip()
        if use and use not in rec["uses"]:
            rec["uses"].append(use)
        rec["area"] += _num(it.get("area"))
    rows = sorted(out.values(), key=lambda r: (r["o"], r["kind"]))
    return [{"f": r["f"], "o": r["o"], "kind": r["kind"], "use": ", ".join(r["uses"][:3]), "area": round(r["area"], 1)} for r in rows]


def summary(floors):
    """'B1 상가 · 1F 상가 · 2~3F 주택' 형태 요약 (부대시설 제외, 연속된 같은 용도는 묶음)"""
    groups = []
    for fl in floors:
        if fl["kind"] == "support":
            continue
        k = FLOOR_LABEL[fl["kind"]]
        last = groups[-1]["last"] if groups else None
        consecutive = last is not None and (fl["o"] == last + 1 or (last == -1 and fl["o"] == 1))  # B1 다음은 1F
        if groups and groups[-1]["k"] == k and consecutive:
            groups[-1]["last"] = fl["o"]
            groups[-1]["to"] = fl["f"]
        elif groups and groups[-1]["last"] == fl["o"]:
            if k not in groups[-1]["k"]:
                groups[-1]["k"] += "+" + k  # 같은 층에 용도가 섞인 경우
        else:
            groups.append({"k": k, "from": fl["f"], "to": fl["f"], "last": fl["o"]})
    parts = []
    for g in groups:
        if g["from"] == g["to"]:
            span = g["from"]
        elif g["from"].endswith("F") and g["to"].endswith("F"):
            span = f"{g['from'][:-1]}~{g['to']}"  # 2F~3F → 2~3F
        else:
            span = f"{g['from']}~{g['to']}"  # B1~3F, B2~B1
        parts.append(f"{span} {g['k']}")
    return " · ".join(parts)


def classify(row, floor_items):
    """row 에 btype, btypeBy, floors, floorSummary 를 붙인다."""
    main = [b for b in row.get("buildings", []) if b.get("main") != "부속건축물"] or row.get("buildings", [])
    row["floors"], row["floorSummary"] = [], ""
    if not main:
        row["btype"], row["btypeBy"] = "대장 없음", ""
        return
    purposes = " ".join(b["purpose"] for b in main)
    etc = " ".join(b.get("etcPurpose", "") for b in main)
    if APT.search(purposes):
        row["btype"], row["btypeBy"] = "공동주택", "용도"
    floors = floor_rows(floor_items) if floor_items else []
    single = len(main) == 1
    if floors and single:  # 여러 동(아파트 단지 등)은 층별 요약을 만들지 않는다
        row["floors"] = [{k: f[k] for k in ("f", "kind", "use", "area")} for f in floors]
        row["floorSummary"] = summary(floors)
    if row.get("btype") == "공동주택":
        return
    kinds = {f["kind"] for f in floors if f["kind"] != "support"}
    if kinds:
        has_house, has_shop = "house" in kinds or "apt" in kinds, "shop" in kinds
        row["btypeBy"] = "층별"
        if has_house and has_shop:
            row["btype"] = "상가주택"
        elif has_house:
            row["btype"] = "단독주택" if "house" in kinds else "공동주택"
        elif has_shop:
            row["btype"] = "상가"
        else:
            row["btype"] = "기타"
        return
    # 층별개요가 없으면 주용도·기타용도로
    row["btypeBy"] = "용도"
    house = "단독주택" in purposes or HOUSE.search(etc)
    shop = "근린생활" in purposes or "근린생활" in etc
    if house and shop:
        row["btype"] = "상가주택"
    elif house:
        row["btype"] = "단독주택"
    elif "근린생활" in purposes:
        row["btype"] = "상가"
    else:
        row["btype"] = "기타"
