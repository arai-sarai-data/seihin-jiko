"""製品事故検索：消費者庁「事故情報データバンク」の検索結果CSVを取得し、
買う前に製品名・メーカー名で探せるようにする。

取得方法：事故情報データバンクの検索画面と同じ「CSV出力」（1回1万件まで）を、
検索条件なし・登録日順で1万件ずつ順に書き出し、raw/jikojoho/ に保存する（コミットしない）。
アクセスは1回ずつ間隔を空け、7日以内に取得したCSVは再取得しない。
import/ に手で書き出したCSVを置いた場合は、それも取り込む（重複は事故情報IDで除く）。

利用条件：政府標準利用規約（第1.0版）／公共データ利用規約（PDL1.0）。
出典：消費者庁「事故情報データバンク」を加工して作成。"""
import csv
import io
import re
import secrets
import time
from collections import Counter, defaultdict

from lib import oc

IMPORT = oc.ROOT / "import"
SAVE = oc.RAW / "jikojoho"
SAVE.mkdir(parents=True, exist_ok=True)
SRC = "https://www.jikojoho.caa.go.jp/"
TOP = SRC + "ai-national/"
API = SRC + "web-server/national/index/"
PAGE = 10000            # CSV出力の上限
MAX_AGE = 7 * 86400     # この日数以内に取ったCSVは使い回す
SEARCH_MAX = 15000      # 検索用に載せる件数（新しい順）


def _post(path, body, tok, timeout=300):
    for i in range(4):
        oc._polite(API)
        try:
            r = oc._session.post(API + path, json=body, timeout=timeout,
                                 headers={"X-XSRF-TOKEN": tok, "Accept": "application/json, text/plain, */*",
                                          "Origin": SRC.rstrip("/"), "Referer": TOP + "accident/list"})
            if r.status_code == 200:
                return r
            oc.log("HTTP", r.status_code, path)
        except Exception as e:  # noqa: BLE001
            oc.log("通信エラー", e)
        time.sleep(15 * (i + 1))
    raise oc.DataError("事故情報データバンクから取得できませんでした: %s" % path)


def _token():
    oc._polite(TOP)
    try:
        oc._session.get(TOP, timeout=60)
    except Exception as e:  # noqa: BLE001
        oc.log("トップページ取得エラー", e)
    tok = oc._session.cookies.get("XSRF-TOKEN")
    if not tok:  # 画面側と同じ二重送信方式：クッキーとヘッダーに同じ値を入れる
        tok = secrets.token_hex(16)
        oc._session.cookies.set("XSRF-TOKEN", tok, domain="www.jikojoho.caa.go.jp", path="/")
    return tok


def _total(tok):
    r = _post("search.do", {"navigationId": 1, "searchParam": {}, "startPos": 0,
                            "sortField": "REGIST_DATE", "sortOrder": 1, "resultSize": 1}, tok, timeout=120)
    try:
        j = r.json()
    except ValueError:
        return None
    for k in ("totalCount", "total", "count", "hitCount", "resultCount"):
        v = j.get(k) if isinstance(j, dict) else None
        if isinstance(v, int):
            return v
    s = re.search(r'"(?:total\w*|\w*[Cc]ount)"\s*:\s*(\d{4,})', r.text)
    return int(s.group(1)) if s else None


def download():
    """全件を1万件ずつCSVで保存する。sortOrder=1（登録日の古い順）なので、前のページは増えても変わらない。"""
    fresh = [f for f in SAVE.glob("jikojoho_*.csv") if time.time() - f.stat().st_mtime < MAX_AGE]
    old = sorted(SAVE.glob("jikojoho_*.csv"))
    if old and len(fresh) == len(old):
        oc.log("保存済みCSVを使います", len(old), "ファイル")
        return
    tok = _token()
    total = _total(tok)
    oc.log("登録件数", total)
    pos, n = 0, 0
    while True:
        f = SAVE / ("jikojoho_%06d.csv" % pos)
        # 最後のページ以外は過去分なので、ファイルがあれば取り直さない
        last_full = f.exists() and total and pos + PAGE < total
        if not last_full:
            r = _post("searchForCsv.do", {"navigationId": 1, "searchParam": {}, "startPos": pos,
                                           "sortField": "REGIST_DATE", "sortOrder": 1, "resultSize": PAGE}, tok)
            oc.check("csv" in (r.headers.get("content-type") or "").lower(),
                     "CSVではない応答です: %s" % r.headers.get("content-type"))
            rows = r.content.count(b"\n") - 3
            if rows <= 0:
                break
            f.write_bytes(r.content)
            oc.log("保存", f.name, rows, "件")
            n += 1
            if rows < PAGE * 0.98:
                break
        pos += PAGE
        if total and pos >= total:
            break
        if pos > 2_000_000:
            raise oc.DataError("ページ送りが止まりません")
    oc.log("取得したファイル", n)


def read(f):
    t = f.read_bytes().decode("cp932", errors="replace")
    lines = t.splitlines()
    start = next((i for i, l in enumerate(lines[:10]) if l.startswith('"No"') or "事故情報ID" in l), None)
    oc.check(start is not None, "見出し行が見つかりません: %s" % f.name)
    return list(csv.DictReader(io.StringIO("\n".join(lines[start:]))))


def g(r, *keys):
    for k in keys:
        for c in r:
            if c and k in c:
                return (r[c] or "").strip()
    return ""


SERIOUS = ("死亡", "重症", "重傷", "1か月以上", "１か月以上", "１ヶ月以上", "1ヶ月以上")


def run():
    try:
        download()
    except oc.DataError as e:
        oc.log("ダウンロードできませんでした（保存済み・import/ のCSVで続行）:", e)
    files = sorted(SAVE.glob("jikojoho_*.csv")) + sorted(IMPORT.glob("*.csv"))
    oc.check(files, "CSVがありません（raw/jikojoho/ も import/ も空）")
    recs, seen = [], set()
    for f in files:
        for r in read(f):
            i = g(r, "事故情報ID")
            if not i or i in seen:
                continue
            seen.add(i)
            cats = g(r, "商品など分類")
            first = cats.split(",")[0].strip()
            recs.append({
                "id": i, "kind": g(r, "種別"), "date": g(r, "発生年月日"), "reg": g(r, "登録年月日"),
                "cat": first.split(" - ")[0].strip() or "（分類なし）",
                "sub": (first.split(" - ")[1].strip() if " - " in first else ""),
                "name": g(r, "商品など名称"), "maker": g(r, "事業者-事業者名１", "事業者名"),
                "what": g(r, "事故内容"), "harm": g(r, "傷病の程度"),
                "txt": re.sub(r"\s+", " ", g(r, "事故の概要")),
                "pref": g(r, "都道府県"), "src": g(r, "情報提供元")})
    oc.check(len(recs) >= 1000, "事故情報が少なすぎます(%d件)" % len(recs))
    oc.log("取り込み", len(recs), "件")
    serious = lambda h: any(w in h for w in SERIOUS)
    acc = [x for x in recs if x["kind"] == "事故情報"]
    yr = lambda s: (re.match(r"(\d{4})年", s) or [None, ""])[1]
    meth = ("消費者庁「事故情報データバンク」の全登録データ（%s件、%s取得）を集計。"
            "「事故情報」は実際に起きた事故、「危険情報」は事故には至らなかったが危険を感じた事例です。"
            "製品の欠陥と確認された事故だけでなく、使い方による事故や原因調査中のものも含みます。"
            "件数は販売台数や利用者数の多さにも左右されます。" % (format(len(recs), ","), oc.today()))

    def rank(rows, keyf, label):
        c = defaultdict(lambda: [0, 0])
        for x in rows:
            k = keyf(x)
            if k:
                c[k][0] += 1
                c[k][1] += serious(x["harm"])
        return sorted([{"k": k, "n": v[0], "serious": v[1]} for k, v in c.items()], key=lambda r: -r["n"])

    cols = lambda lab: [{"key": "k", "label": lab}, {"key": "n", "label": "事故件数", "type": "num", "bar": True},
                        {"key": "serious", "label": "うち死亡・重症など", "type": "num"}]
    R = []
    R.append({"id": "cat", "tab": "分類別", "title": "事故の多い製品分類", "desc": "実際に起きた事故（事故情報）を商品の大分類で数えたもの。",
              "rows": rank(acc, lambda x: x["cat"], "分類"), "method": meth, "share_label": "k", "share_value": "n", "columns": cols("分類")})
    R.append({"id": "sub", "tab": "品目別", "title": "事故の多い品目 トップ100", "desc": "中分類（例：電話機・電話機用品）ごとの事故件数。",
              "rows": rank(acc, lambda x: x["sub"] and "%s（%s）" % (x["sub"], x["cat"]), "品目")[:100],
              "method": meth, "share_label": "k", "share_value": "n", "columns": cols("品目")})
    sr = sorted(rank(acc, lambda x: x["sub"] and "%s（%s）" % (x["sub"], x["cat"]), "品目"), key=lambda r: -r["serious"])
    R.append({"id": "serious", "tab": "重い被害", "title": "死亡・重症などが多い品目 トップ100", "desc": "傷病の程度が死亡・重症（1か月以上）などの事故の件数順。",
              "rows": [r for r in sr if r["serious"] > 0][:100], "method": meth, "share_label": "k", "share_value": "serious", "columns": cols("品目")})
    R.append({"id": "what", "tab": "事故の種類", "title": "事故の種類（火災・転倒・やけど など）", "desc": "事故内容の区分ごとの件数。",
              "rows": rank(acc, lambda x: x["what"], "種類")[:50], "method": meth, "share_label": "k", "share_value": "n", "columns": cols("事故の種類")})
    yrows = sorted(rank(acc, lambda x: yr(x["date"]), "年"), key=lambda r: r["k"], reverse=True)
    R.append({"id": "year", "tab": "年別", "title": "発生年ごとの事故件数", "desc": "発生年が分かる事故だけを数えています。直近の年は登録が追いついていない分、少なく出ます。",
              "rows": [r for r in yrows if "1990" <= r["k"] <= oc.today()[:4]], "method": meth, "share_label": "k", "share_value": "n", "columns": cols("発生年")})

    key = lambda x: (x["reg"].replace("年", "-").replace("月", "-").replace("日", ""), x["id"])
    pick = sorted(acc, key=key, reverse=True)[:SEARCH_MAX]
    search = [{"n": x["name"] or x["sub"] or x["cat"], "s": x["date"],
               "a": " ".join(filter(None, [x["maker"], x["cat"], x["sub"], x["what"]])),
               "k": [["分類", " - ".join(filter(None, [x["cat"], x["sub"]]))], ["事故", x["what"] or "—"],
                     ["被害", x["harm"] or "—"], ["事業者", x["maker"] or "—"], ["概要", x["txt"][:80]]],
               "u": SRC} for x in pick]
    retrieved = oc.today()
    meta = {"data_period": "登録データ %s件（うち事故情報 %s件）／検索は新しい%s件" % (format(len(recs), ","), format(len(acc), ","), format(len(pick), ",")),
            "stats": [{"label": "登録された事故・危険情報", "value": len(recs), "unit": "件"},
                      {"label": "実際に起きた事故", "value": len(acc), "unit": "件"},
                      {"label": "うち死亡・重症など", "value": sum(serious(x["harm"]) for x in acc), "unit": "件"}],
            "sources": [{"name": "事故情報データバンク", "org": "消費者庁", "url": SRC,
                         "license": "公共データ利用規約（PDL1.0）。出典：消費者庁「事故情報データバンク」(%s)（%sに検索）を加工して作成。"
                                    "本サイトは消費者庁が作成したものではありません。" % (SRC, retrieved),
                         "retrieved": retrieved}]}
    oc.write(meta, R, search=search)


if __name__ == "__main__":
    oc.main(run)
