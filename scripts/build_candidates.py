"""
온통대전 신청 가맹점 API(대전시, 키 불필요)에서 주유소·충전소 후보만 뽑아 data/ontong_candidates.json 으로 저장.
오피넷을 부르지 않으므로 하루 호출 한도와 상관없이 언제든 돌릴 수 있다.
좌표는 없고, 지도(index.html)가 카카오 주소 검색으로 위치를 찾는다. 가격은 오피넷 갱신(build_map.py)에서 붙는다.
사용법: python scripts/build_candidates.py
"""
import json, os, re, sys
from datetime import datetime, timedelta, timezone
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
URL = ("http://bigdata.daejeon.go.kr/openApi/6300000/getOtdjReqstMrhst/"
       "getOtdjReqstMrhstlist?pageNo={page}&numOfRows={rows}")
GAS_NAME = re.compile(r"주유소|충전소|LPG|lpg|오일뱅크|셀프주유")


def get_json(url):
    for attempt in range(3):
        try:
            with urllib.request.urlopen(url, timeout=90) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as e:
            if attempt == 2:
                raise
            print("  재시도:", e)


def main():
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
        if not GAS_NAME.search(name) or (name, addr) in seen:
            continue
        seen.add((name, addr))
        out.append({"name": name, "addr": addr, "gu": i.get("se"), "dong": i.get("adstrd_nm")})
    if not out:
        sys.exit("후보를 하나도 못 받았습니다. 기존 파일은 그대로 둡니다.")
    out.sort(key=lambda c: (c["gu"] or "", c["name"]))
    counts = {}
    for c in out:
        counts[c["gu"]] = counts.get(c["gu"], 0) + 1
    result = {"updated": datetime.now(timezone(timedelta(hours=9))).strftime("%Y-%m-%d %H:%M"),
              "total_merchants": len(items), "counts": counts, "candidates": out}
    os.makedirs(os.path.join(ROOT, "data"), exist_ok=True)
    json.dump(result, open(os.path.join(ROOT, "data", "ontong_candidates.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print(f"가맹점 {len(items)}곳 중 주유소·충전소 후보 {len(out)}곳:", counts)


if __name__ == "__main__":
    main()
