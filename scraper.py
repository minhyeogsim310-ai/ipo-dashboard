# -*- coding: utf-8 -*-
"""
KIND 상장심사 현황 스크래퍼
- KIND에서 데이터 수집
- 이전 데이터(data/listings.json)와 비교
- 변경 시 index.html 재생성
"""
import re
import json
import time
import requests
from bs4 import BeautifulSoup
from datetime import datetime
from pathlib import Path

BASE     = "https://kind.krx.co.kr"
LIST_URL = BASE + "/listinvstg/listinvstgcom.do"
MAIN_URL = LIST_URL + "?method=searchListInvstgCorpMain"

ROOT      = Path(__file__).parent
DATA_FILE = ROOT / "data" / "listings.json"
HTML_FILE = ROOT / "index.html"

MARKET_MAP = {
    "icn_t_ko.gif": "코스닥",
    "icn_t_st.gif": "코스피",
    "icn_t_kn.gif": "코넥스",
}

STATUS_CATEGORY = {
    "청구서 접수": "진행중",
    "심사 진행":   "진행중",
    "서류 심사":   "진행중",
    "현장 심사":   "진행중",
    "심사위원회":  "진행중",
    "심사 완료":   "승인",
    "심사 승인":   "승인",
    "승인 완료":   "승인",
    "상장 승인":   "승인",
    "심사 철회":   "철회",
    "청구 취하":   "철회",
    "심사 취하":   "철회",
    "상장 취소":   "철회",
    "취하":        "철회",
    "취소":        "철회",
    "철회":        "철회",
    "미승인":      "미승인",
}


def get_category(status_text):
    s = " ".join(status_text.split())
    for key, cat in STATUS_CATEGORY.items():
        if key in s:
            return cat
    return "기타"


# ── 스크래핑 ────────────────────────────────────────────

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": MAIN_URL,
    "Content-Type": "application/x-www-form-urlencoded",
})


def fetch_page(from_date, to_date, page=1, page_size=200):
    params = [
        ("method", "searchListInvstgCorpSub"),
        ("forward", "listinvstgcom_sub"),
        ("currentPageSize", str(page_size)),
        ("pageIndex", str(page)),
        ("orderMode", "0"), ("orderStat", "D"),
        ("bizProcNo", ""), ("listClssCd", ""), ("comAbbrv", ""),
        ("listTypeArrStr", ""), ("invstgRsltArrStr", ""),
        ("seq", "0"), ("searchMode", ""), ("searchCodeType", ""),
        ("searchCorpName", ""), ("isurCd", ""), ("repIsuSrtCd", ""),
        ("marketType", "1"), ("marketType", "2"), ("searchCorpNameTmp", ""),
        ("listTypeArr", "01"), ("listTypeArr", "02"),
        ("listTypeArr", "03|04|05"), ("listTypeArr", "06"), ("listTypeArr", "07"),
        ("invstgRsltArr", "01"), ("invstgRsltArr", "02"), ("invstgRsltArr", "03"),
        ("invstgRsltArr", "04"), ("invstgRsltArr", "05"), ("invstgRsltArr", "08"),
        ("invstgRsltArr", "07"), ("invstgRsltArr", "06"),
        ("fromDate", from_date), ("toDate", to_date),
    ]
    r = session.post(LIST_URL, data=params, timeout=30)
    return r.content


def parse_rows(content):
    soup = BeautifulSoup(content, "html.parser", from_encoding="euc-kr")
    tbody = soup.find("tbody")
    if not tbody:
        return []

    rows = []
    for tr in tbody.find_all("tr"):
        tds = tr.find_all("td")
        if len(tds) < 5:
            continue

        first_td = tds[0]
        img = first_td.find("img")
        market = "코스닥"
        if img:
            src = img.get("src", "")
            for fname, mkt in MARKET_MAP.items():
                if fname in src:
                    market = mkt
                    break

        company     = first_td.get("title", "").strip() or first_td.get_text(strip=True)
        apply_date  = tds[2].get_text(strip=True)
        result_date = tds[3].get_text(strip=True)
        status_raw  = tds[4].get_text(strip=True)
        underwriter = tds[5].get_text(strip=True) if len(tds) > 5 else ""
        underwriter = re.sub(r'주식회사|㈜|\(주\)', '', underwriter).strip()

        rows.append({
            "회사명":      company,
            "시장":        market,
            "청구일":      apply_date,
            "결과확정일":  result_date,
            "심사결과":    status_raw,
            "분류":        get_category(status_raw),
            "상장주선인":  underwriter,
        })
    return rows


def scrape(year=None):
    y = year or datetime.now().year
    from_date = f"{y}0101"
    to_date   = datetime.now().strftime("%Y%m%d")

    print(f"KIND 세션 수립 ({from_date} ~ {to_date})")
    session.get(MAIN_URL, timeout=30)

    all_rows, page = [], 1
    while True:
        print(f"  페이지 {page} 수집 중...")
        content = fetch_page(from_date, to_date, page=page)
        rows    = parse_rows(content)
        if not rows:
            break
        all_rows.extend(rows)
        if len(rows) < 200:
            break
        page += 1
        time.sleep(0.5)

    print(f"총 {len(all_rows)}건 수집")
    return all_rows


# ── 변경 감지 ────────────────────────────────────────────

def load_previous():
    if DATA_FILE.exists():
        return json.loads(DATA_FILE.read_text(encoding="utf-8"))
    return []


def save_current(rows):
    DATA_FILE.parent.mkdir(exist_ok=True)
    DATA_FILE.write_text(
        json.dumps(rows, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )


def detect_changes(old, new):
    """변경사항 감지 — 새 종목 추가 or 심사결과 변경"""
    old_map = {r["회사명"]: r for r in old}
    new_map = {r["회사명"]: r for r in new}

    added   = [r for name, r in new_map.items() if name not in old_map]
    removed = [r for name, r in old_map.items() if name not in new_map]
    changed = [
        {"before": old_map[name], "after": r}
        for name, r in new_map.items()
        if name in old_map and old_map[name]["심사결과"] != r["심사결과"]
    ]
    return added, removed, changed


# ── HTML 생성 ────────────────────────────────────────────

def build_html(rows):
    today_str = datetime.now().strftime("%Y.%m.%d")
    now_str   = datetime.now().strftime("%Y-%m-%d %H:%M")
    year      = datetime.now().year

    total      = len(rows)
    approved   = sum(1 for r in rows if r["분류"] == "승인")
    in_prog    = sum(1 for r in rows if r["분류"] == "진행중")
    withdrawn  = sum(1 for r in rows if r["분류"] == "철회")

    pct_ok  = round(approved  / total * 100, 1) if total else 0
    pct_pr  = round(in_prog   / total * 100, 1) if total else 0
    pct_out = round(withdrawn / total * 100, 1) if total else 0

    CAT_CSS = {
        "승인":  ("row-ok",   "sts-ok",   "심사 승인"),
        "진행중":("row-prog", "sts-prog", "청구서 접수"),
        "철회":  ("row-out",  "sts-out",  "심사 철회"),
    }

    tbody_html = ""
    for i, r in enumerate(rows, 1):
        cat = r["분류"]
        row_cls, sts_cls, sts_label = CAT_CSS.get(cat, ("", "sts-other", r["심사결과"]))
        # 원문이 "상장 승인"이면 그대로 표기
        if r["심사결과"] in ("상장 승인", "심사 승인"):
            sts_label = r["심사결과"]
        elif r["심사결과"] in ("심사 철회",):
            sts_label = "심사 철회"

        mkt_cls = "mkt-kosdaq" if r["시장"] == "코스닥" else "mkt-kospi" if r["시장"] == "코스피" else "mkt-konex"
        rd = r["결과확정일"] if r["결과확정일"] else "—"
        rd_cls = "" if r["결과확정일"] else " empty"

        tbody_html += f"""    <tr class="{row_cls}" data-cat="{cat}" data-mkt="{r['시장']}">
      <td class="td-no">{i}</td>
      <td class="td-name">{r['회사명']}</td>
      <td><span class="mkt {mkt_cls}">{r['시장']}</span></td>
      <td class="td-date">{r['청구일']}</td>
      <td class="td-date{rd_cls}">{rd}</td>
      <td><span class="sts {sts_cls}">{sts_label}</span></td>
      <td class="td-uw">{r['상장주선인']}</td>
    </tr>\n"""

    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{year} IPO 상장심사 현황</title>
<style>
*,*::before,*::after{{box-sizing:border-box;margin:0;padding:0}}
:root{{
  --bg:#0C1220;--surface:#111B2D;--border:#1D2E45;--border2:#243650;
  --tx1:#E8EFF6;--tx2:#8AAAC4;--tx3:#4D6880;
  --green:#10B981;--green-dim:#0A2A1E;--green-mid:#0F4030;
  --blue:#3B82F6;--blue-dim:#0A1628;--blue-mid:#0D2248;
  --red:#EF4444;--red-dim:#1F0B0B;--red-mid:#3D1212;
  --font:'Apple SD Gothic Neo','Malgun Gothic','Noto Sans KR',system-ui,sans-serif;
}}
html{{font-size:14px}}
body{{font-family:var(--font);background:var(--bg);color:var(--tx1);min-height:100vh}}
.hd{{display:flex;align-items:flex-end;justify-content:space-between;padding:22px 32px 18px;border-bottom:1px solid var(--border)}}
.hd-eyebrow{{font-size:10px;letter-spacing:.12em;text-transform:uppercase;color:var(--tx3);margin-bottom:5px}}
.hd-title{{font-size:22px;font-weight:700;letter-spacing:-.01em}}
.hd-title em{{font-style:normal;color:var(--blue)}}
.hd-right{{text-align:right}}
.hd-right-label{{font-size:10px;letter-spacing:.1em;color:var(--tx3);margin-bottom:3px}}
.hd-right-val{{font-size:13px;color:var(--tx2);font-variant-numeric:tabular-nums}}
.kpi-bar{{display:grid;grid-template-columns:repeat(4,1fr);border-bottom:1px solid var(--border)}}
.kpi{{padding:20px 28px 18px;border-right:1px solid var(--border);display:flex;flex-direction:column;gap:6px}}
.kpi:last-child{{border-right:none}}
.kpi-label{{font-size:10px;letter-spacing:.1em;text-transform:uppercase;color:var(--tx3)}}
.kpi-num{{font-size:40px;font-weight:700;line-height:1;font-variant-numeric:tabular-nums;letter-spacing:-.02em}}
.kpi-unit{{font-size:16px;font-weight:400;margin-left:2px}}
.kpi-sub{{font-size:11px;color:var(--tx3);font-variant-numeric:tabular-nums}}
.kpi-track{{height:2px;background:var(--border);border-radius:1px;margin-top:4px;overflow:hidden}}
.kpi-fill{{height:100%;border-radius:1px}}
.kpi-total .kpi-num{{color:var(--tx1)}}.kpi-total .kpi-fill{{background:var(--border2)}}
.kpi-ok .kpi-num{{color:var(--green)}}.kpi-ok .kpi-fill{{background:var(--green)}}
.kpi-prog .kpi-num{{color:var(--blue)}}.kpi-prog .kpi-fill{{background:var(--blue)}}
.kpi-out .kpi-num{{color:var(--red)}}.kpi-out .kpi-fill{{background:var(--red)}}
.toolbar{{display:flex;align-items:center;gap:10px;padding:10px 32px;border-bottom:1px solid var(--border)}}
.toolbar label{{font-size:10px;letter-spacing:.1em;text-transform:uppercase;color:var(--tx3);flex-shrink:0}}
.toolbar input,.toolbar select{{background:var(--surface);border:1px solid var(--border2);color:var(--tx1);padding:6px 12px;border-radius:3px;font-size:12px;font-family:var(--font);outline:none}}
.toolbar input{{width:200px}}.toolbar input::placeholder{{color:var(--tx3)}}
.toolbar select{{cursor:pointer}}
.toolbar input:focus,.toolbar select:focus{{border-color:var(--blue)}}
.toolbar-count{{margin-left:auto;font-size:11px;color:var(--tx3);font-variant-numeric:tabular-nums;flex-shrink:0}}
.toolbar-count strong{{color:var(--blue);font-weight:600}}
.tbl-wrap{{overflow-x:auto}}
table{{width:100%;border-collapse:collapse;font-size:12.5px}}
thead th{{padding:10px 14px;text-align:left;font-size:10px;font-weight:600;letter-spacing:.08em;text-transform:uppercase;color:var(--tx3);background:var(--bg);border-bottom:1px solid var(--border);white-space:nowrap}}
.th-c{{text-align:center}}
tbody tr{{border-bottom:1px solid var(--border);transition:background .1s}}
tbody tr:hover{{background:var(--surface)}}
tbody td{{padding:9px 14px;color:var(--tx2);vertical-align:middle}}
tbody tr td:first-child{{padding-left:4px;position:relative}}
tbody tr.row-ok td:first-child::before,tbody tr.row-prog td:first-child::before,tbody tr.row-out td:first-child::before{{content:'';position:absolute;left:0;top:0;bottom:0;width:2px}}
tbody tr.row-ok td:first-child::before{{background:var(--green)}}
tbody tr.row-prog td:first-child::before{{background:var(--blue)}}
tbody tr.row-out td:first-child::before{{background:var(--red)}}
.td-no{{text-align:center;color:var(--tx3);font-size:11px;font-variant-numeric:tabular-nums;width:44px}}
.td-name{{font-weight:600;color:var(--tx1);white-space:nowrap}}
.td-date{{font-variant-numeric:tabular-nums;white-space:nowrap;font-size:12px}}
.td-date.empty{{color:var(--tx3)}}
.td-uw{{color:var(--tx3);font-size:11.5px}}
.mkt{{display:inline-flex;align-items:center;padding:1px 7px;border-radius:2px;font-size:10px;font-weight:700;letter-spacing:.04em;white-space:nowrap}}
.mkt-kosdaq{{background:#0E2040;color:#5BA4F5}}.mkt-kospi{{background:#0A2018;color:#34D399}}.mkt-konex{{background:#1A100A;color:#F59E0B}}
.sts{{display:inline-flex;align-items:center;gap:5px;padding:3px 10px;border-radius:12px;font-size:11px;font-weight:600;white-space:nowrap}}
.sts::before{{content:'';width:5px;height:5px;border-radius:50%;flex-shrink:0}}
.sts-ok{{background:var(--green-dim);color:var(--green);border:1px solid var(--green-mid)}}.sts-ok::before{{background:var(--green)}}
.sts-prog{{background:var(--blue-dim);color:var(--blue);border:1px solid var(--blue-mid)}}.sts-prog::before{{background:var(--blue)}}
.sts-out{{background:var(--red-dim);color:var(--red);border:1px solid var(--red-mid)}}.sts-out::before{{background:var(--red)}}
.no-result{{text-align:center;padding:48px;color:var(--tx3);font-size:13px;display:none}}
.ft{{padding:10px 32px;font-size:10px;color:var(--tx3);letter-spacing:.04em;border-top:1px solid var(--border)}}
</style>
</head>
<body>
<div class="hd">
  <div>
    <div class="hd-eyebrow">KRX KIND · 상장예비심사</div>
    <h1 class="hd-title">{year} IPO <em>상장심사</em> 현황</h1>
  </div>
  <div class="hd-right">
    <div class="hd-right-label">기준일</div>
    <div class="hd-right-val">{today_str}</div>
  </div>
</div>
<div class="kpi-bar">
  <div class="kpi kpi-total">
    <div class="kpi-label">예비심사 청구건수</div>
    <div class="kpi-num">{total}<span class="kpi-unit">건</span></div>
    <div class="kpi-sub">{year}년 1월 ~ 현재</div>
    <div class="kpi-track"><div class="kpi-fill" style="width:100%"></div></div>
  </div>
  <div class="kpi kpi-ok">
    <div class="kpi-label">심사 승인</div>
    <div class="kpi-num">{approved}<span class="kpi-unit">건</span></div>
    <div class="kpi-sub">전체의 {pct_ok}%</div>
    <div class="kpi-track"><div class="kpi-fill" style="width:{pct_ok}%"></div></div>
  </div>
  <div class="kpi kpi-prog">
    <div class="kpi-label">심사 진행중</div>
    <div class="kpi-num">{in_prog}<span class="kpi-unit">건</span></div>
    <div class="kpi-sub">전체의 {pct_pr}%</div>
    <div class="kpi-track"><div class="kpi-fill" style="width:{pct_pr}%"></div></div>
  </div>
  <div class="kpi kpi-out">
    <div class="kpi-label">심사 철회</div>
    <div class="kpi-num">{withdrawn}<span class="kpi-unit">건</span></div>
    <div class="kpi-sub">전체의 {pct_out}%</div>
    <div class="kpi-track"><div class="kpi-fill" style="width:{pct_out}%"></div></div>
  </div>
</div>
<div class="toolbar">
  <label>검색</label>
  <input type="text" id="q" placeholder="회사명, 상장주선인...">
  <select id="mkt-f">
    <option value="">전체 시장</option>
    <option value="코스닥">코스닥</option>
    <option value="코스피">코스피</option>
  </select>
  <select id="sts-f">
    <option value="">전체 결과</option>
    <option value="승인">심사 승인</option>
    <option value="진행중">심사 진행중</option>
    <option value="철회">심사 철회</option>
  </select>
  <span class="toolbar-count">표시 <strong id="cnt">{total}</strong> / {total}건</span>
</div>
<div class="tbl-wrap">
  <table>
    <thead>
      <tr>
        <th class="th-c">No</th><th>회사명</th><th>시장</th>
        <th>청구일</th><th>결과확정일</th><th>심사결과</th><th>상장주선인</th>
      </tr>
    </thead>
    <tbody id="tbody">
{tbody_html}    </tbody>
  </table>
  <div class="no-result" id="no-result">검색 결과가 없습니다.</div>
</div>
<div class="ft">출처: 한국거래소 KIND &nbsp;·&nbsp; 수집일시: {now_str} (KST)</div>
<script>
const rows=Array.from(document.querySelectorAll('#tbody tr'));
const cntEl=document.getElementById('cnt');
const noRes=document.getElementById('no-result');
const total={total};
function filter(){{
  const q=document.getElementById('q').value.toLowerCase();
  const mkt=document.getElementById('mkt-f').value;
  const sts=document.getElementById('sts-f').value;
  let n=0;
  rows.forEach(tr=>{{
    const ok=(!q||tr.querySelector('.td-name').textContent.toLowerCase().includes(q)||tr.querySelector('.td-uw').textContent.toLowerCase().includes(q))&&(!mkt||tr.dataset.mkt===mkt)&&(!sts||tr.dataset.cat===sts);
    tr.style.display=ok?'':'none';
    if(ok)n++;
  }});
  cntEl.textContent=n;
  noRes.style.display=n===0?'block':'none';
}}
document.getElementById('q').addEventListener('input',filter);
document.getElementById('mkt-f').addEventListener('change',filter);
document.getElementById('sts-f').addEventListener('change',filter);
</script>
</body>
</html>"""


# ── 메인 ────────────────────────────────────────────────

def main():
    new_rows = scrape()
    old_rows = load_previous()

    added, removed, changed = detect_changes(old_rows, new_rows)

    if added or removed or changed:
        print(f"\n변경 감지:")
        for r in added:
            print(f"  [신규] {r['회사명']} ({r['시장']}) - {r['심사결과']}")
        for r in removed:
            print(f"  [삭제] {r['회사명']}")
        for c in changed:
            print(f"  [변경] {c['before']['회사명']}: {c['before']['심사결과']} → {c['after']['심사결과']}")

        save_current(new_rows)
        html = build_html(new_rows)
        HTML_FILE.write_text(html, encoding="utf-8")
        print(f"\nindex.html 업데이트 완료 ({len(new_rows)}건)")
        print("CHANGED=true")  # GitHub Actions에서 감지용
    else:
        print("\n변경사항 없음 — 업데이트 스킵")
        print("CHANGED=false")


if __name__ == "__main__":
    main()
