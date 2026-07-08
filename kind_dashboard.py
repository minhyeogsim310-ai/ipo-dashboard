# -*- coding: utf-8 -*-
"""
KIND 상장심사 현황 대시보드 생성기
- KIND에서 상장심사 데이터 수집
- HTML 대시보드 생성 (대시보드.html)
"""
import re
import time
import requests
from bs4 import BeautifulSoup
from datetime import datetime

BASE = "https://kind.krx.co.kr"
LIST_URL = BASE + "/listinvstg/listinvstgcom.do"
MAIN_URL = LIST_URL + "?method=searchListInvstgCorpMain"

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": MAIN_URL,
    "Content-Type": "application/x-www-form-urlencoded",
})

# 시장 아이콘 → 시장 구분 매핑
MARKET_MAP = {
    "icn_t_ko.gif": "코스닥",
    "icn_t_st.gif": "코스피",
    "icn_t_kn.gif": "코넥스",
}

# 심사결과 → 카테고리 매핑 (데이터 확인 후 정확하게 조정 필요)
STATUS_CATEGORY = {
    "청구서 접수": "진행중",
    "심사 진행": "진행중",
    "서류 심사": "진행중",
    "현장 심사": "진행중",
    "심사위원회": "진행중",
    "심사 완료": "승인",
    "심사 승인": "승인",
    "승인 완료": "승인",
    "상장 승인": "승인",
    "심사 철회": "철회",
    "청구 취하": "철회",
    "심사 취하": "철회",
    "상장 취소": "철회",
    "취하": "철회",
    "취소": "철회",
    "철회": "철회",
    "미승인": "미승인",
}


def get_status_category(status_text):
    s = " ".join(status_text.split())
    for key, cat in STATUS_CATEGORY.items():
        if key in s:
            return cat
    return "기타"


def fetch_page(from_date, to_date, page=1, page_size=200):
    params = [
        ("method", "searchListInvstgCorpSub"),
        ("forward", "listinvstgcom_sub"),
        ("currentPageSize", str(page_size)),
        ("pageIndex", str(page)),
        ("orderMode", "0"),
        ("orderStat", "D"),
        ("bizProcNo", ""),
        ("listClssCd", ""),
        ("comAbbrv", ""),
        ("listTypeArrStr", ""),
        ("invstgRsltArrStr", ""),
        ("seq", "0"),
        ("searchMode", ""),
        ("searchCodeType", ""),
        ("searchCorpName", ""),
        ("isurCd", ""),
        ("repIsuSrtCd", ""),
        ("marketType", "1"),
        ("marketType", "2"),
        ("searchCorpNameTmp", ""),
        ("listTypeArr", "01"),
        ("listTypeArr", "02"),
        ("listTypeArr", "03|04|05"),
        ("listTypeArr", "06"),
        ("listTypeArr", "07"),
        ("invstgRsltArr", "01"),
        ("invstgRsltArr", "02"),
        ("invstgRsltArr", "03"),
        ("invstgRsltArr", "04"),
        ("invstgRsltArr", "05"),
        ("invstgRsltArr", "08"),
        ("invstgRsltArr", "07"),
        ("invstgRsltArr", "06"),
        ("fromDate", from_date),
        ("toDate", to_date),
    ]
    r = session.post(LIST_URL, data=params, timeout=30)
    return r.content  # return raw bytes, decode in parse_rows


def parse_rows(html):
    soup = BeautifulSoup(html, "html.parser", from_encoding="euc-kr")
    tbody = soup.find("tbody")
    if not tbody:
        return []

    rows = []
    for tr in tbody.find_all("tr"):
        tds = tr.find_all("td")
        if len(tds) < 5:
            continue

        # 시장 구분 (아이콘 이미지 파일명으로 판별)
        first_td = tds[0]
        img = first_td.find("img")
        market = "코스닥"
        if img:
            src = img.get("src", "")
            for fname, mkt in MARKET_MAP.items():
                if fname in src:
                    market = mkt
                    break

        company = first_td.get("title", "").strip() or first_td.get_text(strip=True)
        listing_type = tds[1].get_text(strip=True)
        apply_date = tds[2].get_text(strip=True)
        result_date = tds[3].get_text(strip=True)
        status_raw = tds[4].get_text(strip=True)
        underwriter = tds[5].get_text(strip=True) if len(tds) > 5 else ""

        # 상장주선인 정리 (주식회사, (주) 제거)
        underwriter = re.sub(r'주식회사|㈜|\(주\)', '', underwriter).strip()

        rows.append({
            "회사명": company,
            "시장": market,
            "상장유형": listing_type,
            "청구일": apply_date,
            "결과확정일": result_date,
            "심사결과_원문": status_raw,
            "심사결과_분류": get_status_category(status_raw),
            "상장주선인": underwriter,
        })

    return rows


def scrape(from_date="20260101", to_date="20261231"):
    print("KIND 세션 수립 중...")
    session.get(MAIN_URL, timeout=30)

    all_rows = []
    page = 1
    while True:
        print(f"  페이지 {page} 수집 중...")
        html = fetch_page(from_date, to_date, page=page, page_size=200)
        rows = parse_rows(html)
        if not rows:
            break
        all_rows.extend(rows)
        # 한 페이지에 200개 미만이면 마지막 페이지
        if len(rows) < 200:
            break
        page += 1
        time.sleep(0.5)

    print(f"총 {len(all_rows)}건 수집 완료")
    return all_rows


def build_dashboard(rows, output_path):
    today_str = datetime.now().strftime("%Y.%m.%d")
    year = datetime.now().year

    # KPI 계산
    total = len(rows)
    approved = sum(1 for r in rows if r["심사결과_분류"] == "승인")
    in_progress = sum(1 for r in rows if r["심사결과_분류"] == "진행중")
    withdrawn = sum(1 for r in rows if r["심사결과_분류"] == "철회")

    # 상태별 스타일
    STATUS_STYLE = {
        "승인": ("status-approved", "심사 승인"),
        "진행중": ("status-progress", "심사 진행중"),
        "철회": ("status-withdrawn", "심사 철회"),
        "미승인": ("status-rejected", "미승인"),
        "기타": ("status-other", "기타"),
    }

    # 테이블 행 생성
    table_rows = ""
    for i, r in enumerate(rows, 1):
        cat = r["심사결과_분류"]
        css_cls, label = STATUS_STYLE.get(cat, ("status-other", r["심사결과_원문"]))
        mkt_cls = "badge-kosdaq" if r["시장"] == "코스닥" else "badge-kospi" if r["시장"] == "코스피" else "badge-konex"
        result_date = r["결과확정일"] if r["결과확정일"] else "—"
        table_rows += f"""
        <tr>
            <td class="col-no">{i}</td>
            <td class="col-name">{r['회사명']}</td>
            <td><span class="badge {mkt_cls}">{r['시장']}</span></td>
            <td class="col-date">{r['청구일']}</td>
            <td class="col-date">{result_date}</td>
            <td><span class="status-badge {css_cls}">{label}</span></td>
            <td class="col-underwriter">{r['상장주선인']}</td>
        </tr>"""

    html = f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{year} IPO 상장심사 현황</title>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{
    font-family: 'Malgun Gothic', 'Apple SD Gothic Neo', sans-serif;
    background: #0f1a2e;
    color: #e0e8f0;
    min-height: 100vh;
    padding: 0;
  }}

  /* 헤더 */
  .header {{
    background: #0f1a2e;
    border-bottom: 1px solid #1e3a5f;
    padding: 20px 32px 16px;
    display: flex;
    align-items: flex-end;
    justify-content: space-between;
  }}
  .header-brand {{
    font-size: 11px;
    color: #7fa8c9;
    letter-spacing: 1px;
    margin-bottom: 6px;
  }}
  .header-title {{
    font-size: 28px;
    font-weight: 700;
    color: #ffffff;
  }}
  .header-title span {{
    color: #4db8ff;
  }}
  .header-date {{
    text-align: right;
    font-size: 11px;
    color: #7fa8c9;
  }}
  .header-date-val {{
    font-size: 13px;
    color: #b0cde6;
    margin-top: 2px;
  }}

  /* KPI 카드 */
  .kpi-row {{
    display: flex;
    gap: 0;
    border-bottom: 1px solid #1e3a5f;
  }}
  .kpi-card {{
    flex: 1;
    padding: 20px 28px;
    border-right: 1px solid #1e3a5f;
    position: relative;
  }}
  .kpi-card:last-child {{ border-right: none; }}
  .kpi-label {{
    font-size: 11px;
    color: #7fa8c9;
    letter-spacing: 0.5px;
    margin-bottom: 10px;
  }}
  .kpi-value {{
    font-size: 36px;
    font-weight: 700;
    line-height: 1;
  }}
  .kpi-unit {{
    font-size: 14px;
    font-weight: 400;
    margin-left: 2px;
  }}
  .kpi-total   .kpi-value {{ color: #e0e8f0; }}
  .kpi-approved .kpi-value {{ color: #3dd68c; }}
  .kpi-progress .kpi-value {{ color: #4db8ff; }}
  .kpi-withdrawn .kpi-value {{ color: #ff6b6b; }}

  /* 필터/검색 바 */
  .toolbar {{
    background: #0d1829;
    padding: 12px 32px;
    display: flex;
    align-items: center;
    gap: 12px;
    border-bottom: 1px solid #1e3a5f;
  }}
  .toolbar input {{
    background: #1a2d47;
    border: 1px solid #2a4a6e;
    color: #e0e8f0;
    padding: 7px 14px;
    border-radius: 4px;
    font-size: 13px;
    width: 220px;
    outline: none;
  }}
  .toolbar input::placeholder {{ color: #5a7a9a; }}
  .toolbar select {{
    background: #1a2d47;
    border: 1px solid #2a4a6e;
    color: #e0e8f0;
    padding: 7px 12px;
    border-radius: 4px;
    font-size: 13px;
    outline: none;
    cursor: pointer;
  }}
  .toolbar-label {{
    font-size: 12px;
    color: #7fa8c9;
  }}
  .count-label {{
    margin-left: auto;
    font-size: 12px;
    color: #7fa8c9;
  }}
  #filtered-count {{ color: #4db8ff; font-weight: 600; }}

  /* 테이블 */
  .table-wrap {{
    overflow-x: auto;
    padding: 0 32px 32px;
  }}
  table {{
    width: 100%;
    border-collapse: collapse;
    font-size: 13px;
    margin-top: 0;
  }}
  thead tr {{
    background: #0d1829;
    border-bottom: 2px solid #1e3a5f;
  }}
  thead th {{
    padding: 12px 14px;
    text-align: left;
    font-size: 11px;
    font-weight: 600;
    color: #7fa8c9;
    letter-spacing: 0.5px;
    white-space: nowrap;
  }}
  .col-no {{ width: 50px; text-align: center; }}
  .col-date {{ width: 100px; white-space: nowrap; }}
  tbody tr {{
    border-bottom: 1px solid #1a2d47;
    transition: background 0.15s;
  }}
  tbody tr:hover {{ background: #162236; }}
  tbody td {{
    padding: 10px 14px;
    vertical-align: middle;
    color: #c8dae8;
  }}
  tbody td.col-no {{ text-align: center; color: #5a7a9a; font-size: 12px; }}
  tbody td.col-name {{ font-weight: 600; color: #e0e8f0; }}
  tbody td.col-underwriter {{ font-size: 12px; color: #9ab8d0; }}

  /* 뱃지 */
  .badge {{
    display: inline-block;
    padding: 2px 8px;
    border-radius: 3px;
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 0.5px;
  }}
  .badge-kosdaq {{ background: #1a3a5f; color: #4db8ff; }}
  .badge-kospi  {{ background: #1a3f2e; color: #3dd68c; }}
  .badge-konex  {{ background: #3a2a1a; color: #f0a040; }}

  .status-badge {{
    display: inline-block;
    padding: 3px 10px;
    border-radius: 12px;
    font-size: 11px;
    font-weight: 600;
    white-space: nowrap;
  }}
  .status-approved  {{ background: #0d3320; color: #3dd68c; border: 1px solid #2a7a50; }}
  .status-progress  {{ background: #0a2540; color: #4db8ff; border: 1px solid #1a4a80; }}
  .status-withdrawn {{ background: #3a1515; color: #ff6b6b; border: 1px solid #7a2a2a; }}
  .status-rejected  {{ background: #3a2010; color: #ff9940; border: 1px solid #7a4a10; }}
  .status-other     {{ background: #2a2a2a; color: #9ab8d0; border: 1px solid #4a4a4a; }}

  /* 범례 */
  .legend {{
    padding: 10px 32px;
    background: #0d1829;
    border-bottom: 1px solid #1e3a5f;
    display: flex;
    gap: 20px;
    font-size: 11px;
    color: #7fa8c9;
    align-items: center;
  }}
  .legend-item {{ display: flex; align-items: center; gap: 6px; }}

  .no-data {{ text-align: center; padding: 60px; color: #5a7a9a; }}

  /* 수집 정보 */
  .footer {{
    text-align: right;
    padding: 10px 32px;
    font-size: 11px;
    color: #3a5a7a;
  }}
</style>
</head>
<body>

<!-- 헤더 -->
<div class="header">
  <div>
    <div class="header-brand">삼성투자연구소 · IPO PIPELINE</div>
    <div class="header-title">{year} IPO <span>상장심사</span> 현황</div>
  </div>
  <div class="header-date">
    <div>기준일</div>
    <div class="header-date-val">{today_str}</div>
  </div>
</div>

<!-- KPI 카드 -->
<div class="kpi-row">
  <div class="kpi-card kpi-total">
    <div class="kpi-label">전체 현황</div>
    <div class="kpi-value">{total}<span class="kpi-unit">건</span></div>
  </div>
  <div class="kpi-card kpi-approved">
    <div class="kpi-label">심사 승인</div>
    <div class="kpi-value">{approved}<span class="kpi-unit">건</span></div>
  </div>
  <div class="kpi-card kpi-progress">
    <div class="kpi-label">심사 진행중</div>
    <div class="kpi-value">{in_progress}<span class="kpi-unit">건</span></div>
  </div>
  <div class="kpi-card kpi-withdrawn">
    <div class="kpi-label">심사 철회</div>
    <div class="kpi-value">{withdrawn}<span class="kpi-unit">건</span></div>
  </div>
</div>

<!-- 범례 -->
<div class="legend">
  <span>● 심사결과 구분:</span>
  <span class="legend-item"><span class="status-badge status-approved" style="padding:1px 7px;font-size:10px;">심사 승인</span></span>
  <span class="legend-item"><span class="status-badge status-progress" style="padding:1px 7px;font-size:10px;">심사 진행중</span></span>
  <span class="legend-item"><span class="status-badge status-withdrawn" style="padding:1px 7px;font-size:10px;">심사 철회</span></span>
</div>

<!-- 툴바 -->
<div class="toolbar">
  <span class="toolbar-label">검색</span>
  <input type="text" id="search-input" placeholder="회사명, 상장주선인 검색...">
  <select id="market-filter">
    <option value="">전체 시장</option>
    <option value="코스닥">코스닥</option>
    <option value="코스피">코스피</option>
    <option value="코넥스">코넥스</option>
  </select>
  <select id="status-filter">
    <option value="">전체 심사결과</option>
    <option value="진행중">심사 진행중</option>
    <option value="승인">심사 승인</option>
    <option value="철회">심사 철회</option>
  </select>
  <span class="count-label">표시: <span id="filtered-count">{total}</span>건</span>
</div>

<!-- 테이블 -->
<div class="table-wrap">
  <table id="main-table">
    <thead>
      <tr>
        <th class="col-no">번호</th>
        <th>회사명</th>
        <th>시장</th>
        <th>청구일</th>
        <th>결과확정일</th>
        <th>심사결과</th>
        <th>상장주선인</th>
      </tr>
    </thead>
    <tbody id="table-body">
      {table_rows}
    </tbody>
  </table>
  <div id="no-data" class="no-data" style="display:none;">검색 결과가 없습니다.</div>
</div>

<div class="footer">출처: 한국거래소 KIND · 수집일시: {datetime.now().strftime('%Y-%m-%d %H:%M')}</div>

<script>
const rows = document.querySelectorAll('#table-body tr');
const countEl = document.getElementById('filtered-count');
const noData = document.getElementById('no-data');

function applyFilter() {{
  const q = document.getElementById('search-input').value.toLowerCase();
  const mkt = document.getElementById('market-filter').value;
  const sts = document.getElementById('status-filter').value;
  let visible = 0;
  rows.forEach(tr => {{
    const name = tr.querySelector('.col-name')?.textContent.toLowerCase() || '';
    const underwriter = tr.querySelector('.col-underwriter')?.textContent.toLowerCase() || '';
    const badge = tr.querySelector('.badge')?.textContent || '';
    const statusBadge = tr.querySelector('.status-badge')?.dataset?.cat || '';
    const statusText = tr.querySelector('.status-badge')?.textContent || '';

    const matchQ = !q || name.includes(q) || underwriter.includes(q);
    const matchMkt = !mkt || badge === mkt;
    const matchSts = !sts || tr.dataset.cat === sts;

    if (matchQ && matchMkt && matchSts) {{
      tr.style.display = '';
      visible++;
    }} else {{
      tr.style.display = 'none';
    }}
  }});
  countEl.textContent = visible;
  noData.style.display = visible === 0 ? 'block' : 'none';
}}

// data-cat 속성 설정 (필터용)
rows.forEach(tr => {{
  const s = tr.querySelector('.status-badge');
  if (s) {{
    if (s.classList.contains('status-approved')) tr.dataset.cat = '승인';
    else if (s.classList.contains('status-progress')) tr.dataset.cat = '진행중';
    else if (s.classList.contains('status-withdrawn')) tr.dataset.cat = '철회';
    else tr.dataset.cat = '기타';
  }}
}});

document.getElementById('search-input').addEventListener('input', applyFilter);
document.getElementById('market-filter').addEventListener('change', applyFilter);
document.getElementById('status-filter').addEventListener('change', applyFilter);
</script>
</body>
</html>"""

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"대시보드 저장: {output_path}")


def main():
    from_date = "20260101"
    to_date = datetime.now().strftime("%Y%m%d")
    out = r"C:\Users\YSChae\Desktop\심민혁\인바이츠벤처 제안서\공모주 시장 현황\IPO_상장심사_현황.html"

    rows = scrape(from_date, to_date)

    # 심사결과 원문 목록 출력 (STATUS_MAP 확인용)
    print("\n=== 심사결과 원문 목록 ===")
    from collections import Counter
    status_counts = Counter(r["심사결과_원문"] for r in rows)
    for k, v in status_counts.most_common():
        cat = get_status_category(k)
        print(f"  [{cat:6s}] {k!r}: {v}건")

    build_dashboard(rows, out)
    print(f"\n총 {len(rows)}건")
    print(f"  승인: {sum(1 for r in rows if r['심사결과_분류']=='승인')}건")
    print(f"  진행중: {sum(1 for r in rows if r['심사결과_분류']=='진행중')}건")
    print(f"  철회: {sum(1 for r in rows if r['심사결과_분류']=='철회')}건")


if __name__ == "__main__":
    main()
