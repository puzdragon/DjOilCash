"""대전시 '온통대전 신청 가맹점 목록' API에서 주유소·충전소 후보만 뽑아 저장한다.
API 응답에는 업종이나 캐시백 여부 항목이 없어서, 가맹점 이름으로 거른다.
"""
import json, os, re, sys, time, urllib.request

URL = ("http://bigdata.daejeon.go.kr/openApi/6300000/getOtdjReqstMrhst/"
       "getOtdjReqstMrhstlist?pageNo={page}&numOfRows={rows}")
ROWS = 10000
KEYWORDS = re.compile(r"주유소|충전소|오일뱅크|LPG|lpg|셀프주유|에너지|석유|가스")


def get(page):
    for attempt in range(3):
        try:
            with urllib.request.urlopen(URL.format(page=page, rows=ROWS), timeout=120) as r:
                return json.loads(r.read().decode("utf-8"))["response"]["body"]
        except Exception as e:
            if attempt == 2:
                raise
            print("재시도:", e)
            time.sleep(5)


def main(out):
    first = get(1)
    total = int(first["totalCnt"])
    items = list(first["items"])
    for page in range(2, (total + ROWS - 1) // ROWS + 1):
        items += get(page)["items"]
    hits = [i for i in items if KEYWORDS.search(i.get("mrhst_nm", ""))]
    json.dump({"total": total, "fetched": len(items), "fields": sorted(items[0].keys()) if items else [],
               "candidates": hits}, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"전체 {total} / 받음 {len(items)} / 후보 {len(hits)}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "ontong_candidates.json")
