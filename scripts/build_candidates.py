"""
온통대전 신청 가맹점 API(대전시, 키 불필요)에서 주유소·충전소 후보만 뽑아 data/ontong_candidates.json 으로 저장.
오피넷을 부르지 않으므로 하루 호출 한도와 상관없이 언제든 돌릴 수 있다.
좌표는 없고, 지도(index.html)가 카카오 주소 검색으로 위치를 찾는다. 가격은 오피넷 갱신(build_map.py)에서 붙는다.
같이 대전사랑카드 고객센터가 공개한 '연매출 30억 초과(캐시백 제공 불가) 가맹점' 목록에서 주유소만 뽑아
data/cashback_excluded.json 으로 저장한다. 지도는 이 목록에 없는 온통대전 가맹 주유소를 캐시백 적립 주유소로 본다.
사용법: python scripts/build_candidates.py
"""
import json, os, re, sys
from datetime import datetime, timedelta, timezone
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
URL = ("http://bigdata.daejeon.go.kr/openApi/6300000/getOtdjReqstMrhst/"
       "getOtdjReqstMrhstlist?pageNo={page}&numOfRows={rows}")
GAS_NAME = re.compile(r"주유소|충전소|LPG|lpg|오일뱅크|셀프주유")
NOT_GAS = re.compile(r"수소|교통카드|전기차|충전기")  # 수소버스·교통카드 충전소 등은 주유소가 아님
# 매년 4월 1일 가맹점 매출 등급을 다시 매기며, 그 전날 날짜 폴더에 새 목록을 올린다(2026년: 20260331).
EXCL_URL = "https://cdn.nmcs.co.kr/zdata/merchant/{d}/daejeon_market_list.html"
KST = timezone(timedelta(hours=9))


def get_json(url):
    for attempt in range(3):
        try:
            with urllib.request.urlopen(url, timeout=90) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as e:
            if attempt == 2:
                raise
            print("  재시도:", e)


def fetch_excluded():
    """연매출 30억 초과(캐시백 불가) 가맹점 중 주유소·충전소. 못 받으면 None (기존 파일 유지)."""
    now = datetime.now(KST)
    dates = [f"{y}{md}" for y in (now.year, now.year - 1) for md in ("0331", "0401", "0330", "0329")]
    for d in dates:
        url = EXCL_URL.format(d=d)
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=60) as r:
                html = r.read().decode("utf-8")
        except Exception as e:
            print("  제외 목록 없음:", d, e)
            continue
        m = re.search(r"MERCHANT_DATA\s*=\s*(\[.*?\]);", html, re.S)
        if not m:
            print("  제외 목록 형식이 바뀜:", url)
            continue
        rows = json.loads(re.sub(r",\s*([\]}])", r"\1", m.group(1)))
        out, seen = [], set()
        for x in rows:
            name, addr, cat = (x.get("name") or "").strip(), re.sub(r"\s+", " ", x.get("address") or "").strip(), x.get("category") or ""
            if not (cat.startswith("주유소") or GAS_NAME.search(name)) or NOT_GAS.search(name) or (name, addr) in seen:
                continue
            seen.add((name, addr))
            gu = (addr.split(" ") + ["", ""])[1]
            out.append({"name": name, "addr": addr, "gu": gu, "category": cat})
        if not out:
            continue
        return {"updated": now.strftime("%Y-%m-%d %H:%M"), "base_date": f"{d[:4]}-04-01",
                "source": url, "all_excluded_merchants": len(rows), "count": len(out),
                "note": "연매출 30억 초과 가맹점은 대전사랑카드 캐시백 제공 불가 (대전사랑카드 고객센터 공지)",
                "stations": sorted(out, key=lambda c: (c["gu"], c["name"]))}
    return None


def main():
    excl = fetch_excluded()
    if excl:
        os.makedirs(os.path.join(ROOT, "data"), exist_ok=True)
        json.dump(excl, open(os.path.join(ROOT, "data", "cashback_excluded.json"), "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
        print(f"캐시백 불가(연매출 30억 초과) 주유소 {excl['count']}곳, 기준 {excl['base_date']}")
    else:
        print("::warning::캐시백 제외 목록을 받지 못했습니다. 기존 data/cashback_excluded.json 을 그대로 씁니다.")

    rows, page, items = 10000, 1, []
    while True:
        body = get_json(URL.format(page=page, rows=rows))["response"]["body"]
        items += body["items"]
        if page * rows >= int(body["totalCnt"]):
            break
        page += 1
    seen, out = set(), []
    for i in items:
        name, addr = (i.get("mrhst_nm") or "").strip(), (i.get("adres") or "").strip()
        if not GAS_NAME.search(name) or NOT_GAS.search(name) or (name, addr) in seen:
            continue
        seen.add((name, addr))
        out.append({"name": name, "addr": addr, "gu": i.get("se"), "dong": i.get("adstrd_nm")})
    if not out:
        sys.exit("후보를 하나도 못 받았습니다. 기존 파일은 그대로 둡니다.")
    out.sort(key=lambda c: (c["gu"] or "", c["name"]))
    counts = {}
    for c in out:
        counts[c["gu"]] = counts.get(c["gu"], 0) + 1
    result = {"updated": datetime.now(KST).strftime("%Y-%m-%d %H:%M"),
              "total_merchants": len(items), "counts": counts, "candidates": out}
    os.makedirs(os.path.join(ROOT, "data"), exist_ok=True)
    json.dump(result, open(os.path.join(ROOT, "data", "ontong_candidates.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print(f"가맹점 {len(items)}곳 중 주유소·충전소 후보 {len(out)}곳:", counts)


if __name__ == "__main__":
    main()
