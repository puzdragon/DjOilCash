"""
대전 온통대전 주유소 지도 데이터 만들기 (GitHub Actions에서 하루 2회 실행)

1) 대전시 '온통대전 신청 가맹점 목록' API(키 불필요)에서 이름에 주유소·충전소가 들어간 곳을 뽑는다.
   이 API에는 업종과 캐시백 여부 항목이 없어서, 이 곳들은 '미확인 후보'다.
2) 오피넷 반경 검색(aroundAll)으로 대전 전역 주유소의 위치와 휘발유·경유·LPG 가격을 받는다.
3) 오피넷 상세(detailById)의 주소로 1)의 후보와 맞춘다. 상세 정보는 data/opinet_detail_cache.json에 저장해
   다음 실행부터는 새로 생긴 곳만 호출한다.
4) stations.json(직접 확인한 캐시백 주유소)은 '확인됨'으로 표시한다.

결과: data/map.json (index.html이 읽음)
사용법: OPINET_API_KEY=키 python scripts/build_map.py
필요 패키지: pip install pyproj
"""
import difflib, json, os, re, sys, time, urllib.parse, urllib.request
from datetime import datetime, timedelta, timezone
from pyproj import Transformer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
KST = timezone(timedelta(hours=9))

ONTONG_URL = ("http://bigdata.daejeon.go.kr/openApi/6300000/getOtdjReqstMrhst/"
              "getOtdjReqstMrhstlist?pageNo={page}&numOfRows={rows}")
GAS_NAME = re.compile(r"주유소|충전소|LPG|lpg|오일뱅크|셀프주유")

OPINET = "https://www.opinet.co.kr/api/"
KATEC = ("+proj=tmerc +lat_0=38 +lon_0=128 +k=0.9999 +x_0=400000 +y_0=600000 "
         "+ellps=bessel +units=m +towgs84=-115.80,474.99,674.11,1.16,-2.31,-1.63,6.43 +no_defs")
to_katec = Transformer.from_crs("EPSG:4326", KATEC, always_xy=True)
from_katec = Transformer.from_crs(KATEC, "EPSG:4326", always_xy=True)
PRODS = {"B027": "gasoline", "D047": "diesel", "K015": "lpg"}
# 대전 전역을 덮는 범위 (위경도). 반경 5km 원을 7km 간격 격자로 깔면 빈틈이 없다.
BBOX = (127.24, 36.18, 127.57, 36.50)
GRID_STEP = 7000
RADIUS = 5000
MAX_DETAIL_CALLS = int(os.environ.get("MAX_DETAIL_CALLS", "200"))


# ---------- 온통대전 ----------
def ontong_candidates():
    rows, page, items = 10000, 1, []
    while True:
        body = get_json(ONTONG_URL.format(page=page, rows=rows))["response"]["body"]
        items += body["items"]
        if page * rows >= int(body["totalCnt"]):
            break
        page += 1
    return [i for i in items if GAS_NAME.search(i.get("mrhst_nm", ""))], len(items)


# ---------- 오피넷 ----------
def get_json(url):
    for attempt in range(3):
        try:
            with urllib.request.urlopen(url, timeout=60) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as e:
            if attempt == 2:
                raise
            print("  재시도:", e)
            time.sleep(3)


def opinet(api, key, **params):
    params.update(code=key, out="json")
    try:
        return get_json(OPINET + api + "?" + urllib.parse.urlencode(params))["RESULT"]["OIL"]
    except Exception as e:
        print("  ! 오피넷 호출 실패:", api, e)
        return []


def grid_points():
    x0, y0 = to_katec.transform(BBOX[0], BBOX[1])
    x1, y1 = to_katec.transform(BBOX[2], BBOX[3])
    pts, y = [], y0
    while y <= y1 + GRID_STEP / 2:
        x = x0
        while x <= x1 + GRID_STEP / 2:
            pts.append((round(x, 1), round(y, 1)))
            x += GRID_STEP
        y += GRID_STEP
    return pts


def scan_prices(key):
    """대전 전역 반경 검색 → {UNI_ID: {name, brand, x, y, prices}}"""
    found = {}
    for prod, field in PRODS.items():
        for x, y in grid_points():
            for o in opinet("aroundAll.do", key, x=x, y=y, radius=RADIUS, prodcd=prod, sort=2):
                s = found.setdefault(o["UNI_ID"], {"name": o["OS_NM"], "brand": o.get("POLL_DIV_CD"),
                                                   "x": float(o["GIS_X_COOR"]), "y": float(o["GIS_Y_COOR"]),
                                                   "prices": {}})
                price = int(float(o.get("PRICE") or 0))
                if price > 0:
                    s["prices"][field] = price
            time.sleep(0.1)
    return found


# ---------- 주소·이름 맞추기 ----------
def addr_keys(addr):
    a = re.sub(r"\(.*?\)", " ", addr or "")
    keys = set()
    m = re.search(r"([가-힣A-Za-z0-9]+(?:로|길))\s*(\d+(?:-\d+)?)", a)
    if m:
        keys.add("R:" + m.group(1) + m.group(2))
    m = re.search(r"([가-힣0-9]+(?:동|가|리))\s*(?:산\s*)?(\d+(?:-\d+)?)(?:\s|번지|$|,)", a)
    if m:
        keys.add("J:" + m.group(1) + m.group(2))
    return keys


def norm_name(n):
    n = n or ""
    for t in ["(주)", "㈜", "주식회사", "(유)", "유한회사", " ", "주유소", "충전소", "셀프", "Self", "SELF", "self"]:
        n = n.replace(t, "")
    return n


def gu_of(addr):
    m = re.search(r"(동구|중구|서구|유성구|대덕구)", addr or "")
    return m.group(1) if m else None


def main():
    key = os.environ.get("OPINET_API_KEY") or (sys.argv[1] if len(sys.argv) > 1 else "")
    if not key:
        sys.exit("OPINET_API_KEY 환경변수(또는 첫 번째 인자)에 오피넷 인증키를 넣어 주세요.")
    os.makedirs(DATA, exist_ok=True)

    cands, ontong_total = ontong_candidates()
    print(f"온통대전 가맹점 {ontong_total}곳 중 주유소·충전소 후보 {len(cands)}곳")

    scanned = scan_prices(key)
    print(f"오피넷 반경 검색으로 {len(scanned)}곳 위치·가격 확인")
    if not scanned:
        sys.exit("오피넷에서 가격을 하나도 못 받았습니다. 키를 확인하세요. 기존 데이터는 그대로 둡니다.")

    cache_path = os.path.join(DATA, "opinet_detail_cache.json")
    cache = json.load(open(cache_path, encoding="utf-8")) if os.path.exists(cache_path) else {}
    calls = 0
    for uni in scanned:
        if uni in cache or calls >= MAX_DETAIL_CALLS:
            continue
        d = opinet("detailById.do", key, id=uni)
        calls += 1
        if d:
            d = d[0]
            cache[uni] = {"name": d.get("OS_NM"), "new_adr": d.get("NEW_ADR"), "van_adr": d.get("VAN_ADR"),
                          "tel": d.get("TEL") if d.get("TEL") not in ("0", "") else None,
                          "lpg_yn": d.get("LPG_YN")}
        time.sleep(0.1)
    json.dump(cache, open(cache_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1, sort_keys=True)
    pending = [u for u in scanned if u not in cache]
    print(f"상세 조회 {calls}회, 아직 상세 미조회 {len(pending)}곳")

    # 오피넷 주유소 중 대전 소재만, 주소 키로 색인
    by_key, daejeon = {}, {}
    for uni, s in scanned.items():
        c = cache.get(uni)
        if not c or not (c.get("new_adr") or c.get("van_adr") or "").startswith("대전"):
            continue
        daejeon[uni] = s
        for k in addr_keys(c.get("new_adr")) | addr_keys(c.get("van_adr")):
            by_key.setdefault(k, set()).add(uni)

    def match(name, addr, gu):
        hits = set()
        for k in addr_keys(addr):
            hits |= by_key.get(k, set())
        if len(hits) == 1:
            return hits.pop()
        pool = hits or {u for u in daejeon if gu_of(cache[u].get("new_adr") or cache[u].get("van_adr")) == gu}
        best, best_sim = None, 0
        for u in pool:
            sim = difflib.SequenceMatcher(None, norm_name(name), norm_name(daejeon[u]["name"])).ratio()
            if sim > best_sim:
                best, best_sim = u, sim
        return best if best and (hits or best_sim >= 0.8) else None

    out = {}

    def add(uni, status, name, ontong_name=None, addr=None, gu=None, fallback=None):
        if uni and uni in daejeon:
            s, c = daejeon[uni], cache[uni]
            lng, lat = from_katec.transform(s["x"], s["y"])
            rec = out.setdefault(uni, {
                "id": uni, "name": name, "opinet_name": s["name"], "ontong_name": ontong_name,
                "addr": (c.get("new_adr") or c.get("van_adr") or addr or "").strip(),
                "gu": gu_of(c.get("new_adr") or c.get("van_adr")) or gu,
                "lat": round(lat, 6), "lng": round(lng, 6),
                "lpg": c.get("lpg_yn") in ("Y", "C") or "lpg" in s["prices"] and len(s["prices"]) == 1,
                "brand": s["brand"], "tel": c.get("tel"), "prices": s["prices"], "status": status})
            if status == "verified":
                rec["status"], rec["name"] = "verified", name
            if ontong_name and not rec.get("ontong_name"):
                rec["ontong_name"] = ontong_name
        elif fallback:
            out.setdefault(fallback["id"], fallback)

    # 직접 확인한 캐시백 주유소
    verified = json.load(open(os.path.join(ROOT, "stations.json"), encoding="utf-8"))
    ids_path = os.path.join(ROOT, "opinet_ids.json")
    ids = json.load(open(ids_path, encoding="utf-8")) if os.path.exists(ids_path) else {}
    for st in verified:
        uni = (ids.get(str(st["id"])) or {}).get("uni") or match(st["name"], st["addr"], st["gu"])
        add(uni, "verified", st["name"], addr=st["addr"], gu=st["gu"],
            fallback={"id": f"v{st['id']}", "name": st["name"], "addr": st["addr"], "gu": st["gu"],
                      "lat": st["lat"], "lng": st["lng"], "lpg": st["lpg"], "prices": {}, "status": "verified"})

    # 온통대전 API 후보
    unmatched = []
    for c in cands:
        uni = match(c["mrhst_nm"], c["adres"], c["se"])
        if uni:
            add(uni, "candidate", daejeon[uni]["name"], ontong_name=c["mrhst_nm"].strip(), gu=c["se"])
        else:
            unmatched.append({"name": c["mrhst_nm"].strip(), "addr": c["adres"], "gu": c["se"]})

    stations = sorted(out.values(), key=lambda s: (s["gu"] or "", s["name"]))
    result = {
        "updated": datetime.now(KST).strftime("%Y-%m-%d %H:%M"),
        "counts": {"verified": sum(s["status"] == "verified" for s in stations),
                   "candidate": sum(s["status"] == "candidate" for s in stations),
                   "ontong_candidates": len(cands), "unmatched": len(unmatched),
                   "detail_pending": len(pending)},
        "stations": stations,
        "unmatched": unmatched,
    }
    json.dump(result, open(os.path.join(DATA, "map.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("완료:", json.dumps(result["counts"], ensure_ascii=False))


if __name__ == "__main__":
    main()
