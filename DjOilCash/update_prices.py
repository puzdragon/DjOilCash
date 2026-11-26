"""
오피넷 가격 수집 스크립트
사용법:  python update_prices.py 오피넷인증키
결과:    prices.json (index.html이 읽음), opinet_ids.json (주유소 ↔ 오피넷 ID 매칭 캐시)

필요 패키지: pip install pyproj
"""
import json, sys, time, urllib.parse, urllib.request, difflib, os
from datetime import datetime, timezone, timedelta
from pyproj import Transformer

BASE = "https://www.opinet.co.kr/api/"
HERE = os.path.dirname(os.path.abspath(__file__))
# WGS84(위경도) → KATEC (오피넷 좌표계)
KATEC = ("+proj=tmerc +lat_0=38 +lon_0=128 +k=0.9999 +x_0=400000 +y_0=600000 "
         "+ellps=bessel +units=m +towgs84=-115.80,474.99,674.11,1.16,-2.31,-1.63,6.43 +no_defs")
to_katec = Transformer.from_crs("EPSG:4326", KATEC, always_xy=True)
PRODS = {"B027": "gasoline", "D047": "diesel", "K015": "lpg", "B034": "premium"}


def call(api, key, **params):
    params.update(code=key, out="json")  # 문서엔 certkey지만 실제로는 code만 동작
    url = BASE + api + "?" + urllib.parse.urlencode(params)
    for attempt in range(3):
        try:
            with urllib.request.urlopen(url, timeout=15) as r:
                return json.loads(r.read().decode("utf-8"))["RESULT"]["OIL"]
        except Exception as e:
            if attempt == 2:
                print("  ! 호출 실패:", api, e)
                return []
            time.sleep(1.5)


def norm(n):
    for t in ["(주)", "㈜", "주식회사", " ", "주유소", "충전소", "셀프", "self", "Self", "SELF"]:
        n = n.replace(t, "")
    return n


def find_id(st, key):
    """좌표 주변 300m에서 오피넷 주유소를 찾아 상호가 가장 비슷한 곳을 고름"""
    x, y = to_katec.transform(st["lng"], st["lat"])
    cands = {}
    for prod in (["K015"] if st["lpg"] else ["B027", "K015"]):
        for o in call("aroundAll.do", key, x=round(x, 1), y=round(y, 1),
                      radius=300, prodcd=prod, sort=2) or []:
            cands[o["UNI_ID"]] = o
    if not cands:
        return None, None
    def score(o):
        sim = difflib.SequenceMatcher(None, norm(st["name"]), norm(o["OS_NM"])).ratio()
        return sim - float(o.get("DISTANCE", 0)) / 1000
    best = max(cands.values(), key=score)
    return best["UNI_ID"], best["OS_NM"]


def main():
    if len(sys.argv) < 2:
        sys.exit("사용법: python update_prices.py 오피넷인증키")
    key = sys.argv[1]
    stations = json.load(open(os.path.join(HERE, "stations.json"), encoding="utf-8"))
    id_path = os.path.join(HERE, "opinet_ids.json")
    ids = json.load(open(id_path, encoding="utf-8")) if os.path.exists(id_path) else {}

    prices = {}
    for st in stations:
        sid = str(st["id"])
        if sid not in ids:
            uni, nm = find_id(st, key)
            ids[sid] = {"uni": uni, "opinet_name": nm}
            mark = "" if uni else "  (못 찾음)"
            print(f"매칭 {st['name']} → {nm}{mark}")
        uni = ids[sid]["uni"]
        if not uni:
            continue
        detail = call("detailById.do", key, id=uni)
        if not detail:
            continue
        d = detail[0]
        p = {"brand": d.get("POLL_DIV_CO") or d.get("POLL_DIV_CD"),
             "opinet_name": d.get("OS_NM"), "tel": d.get("TEL")}
        if p["tel"] in ("0", "", None):
            p.pop("tel")
        for op in d.get("OIL_PRICE", []):
            k = PRODS.get(op["PRODCD"])
            if k:
                p[k] = int(float(op["PRICE"]))
                dt, tm = op.get("TRADE_DT", ""), op.get("TRADE_TM", "")
                p["date"] = f"{dt[:4]}-{dt[4:6]}-{dt[6:8]} {tm[:2]}:{tm[2:4]}"
        prices[sid] = p
        time.sleep(0.2)

    if not prices:
        sys.exit("가격을 하나도 못 받았습니다 (키 또는 접속 차단 확인). prices.json은 그대로 둡니다.")
    json.dump(ids, open(id_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    out = {"updated": datetime.now(timezone(timedelta(hours=9))).strftime("%Y-%m-%d %H:%M"), "prices": prices}
    json.dump(out, open(os.path.join(HERE, "prices.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print(f"완료: {len(prices)}/{len(stations)}곳 가격 저장 → prices.json")
    missing = [s["name"] for s in stations if str(s["id"]) not in prices]
    if missing:
        print("가격 못 가져온 곳:", ", ".join(missing))
        print("→ opinet_ids.json에서 해당 번호의 uni 값을 직접 넣으면 됩니다.")


if __name__ == "__main__":
    main()
