"""製品事故検索：消費者庁・国民生活センター「事故情報データバンクシステム」の検索結果CSVを、
買う前に製品名・メーカー名で探せるようにする。

事故情報データバンクには一括ダウンロードの仕組みがなく、検索画面には自動取得を想定した案内もないため、
画面から人が書き出したCSV（検索結果のCSV出力機能）を import/ フォルダに置く方式にしている。"""
import re
from collections import Counter, defaultdict
from pathlib import Path

from lib import oc

IMPORT = oc.ROOT / "import"
SRC = "https://www.jikojoho.caa.go.jp/"


def pick(df, *cands, required=True):
    for keys in cands:
        c = oc.col(df, *keys, required=False)
        if c:
            return c
    if required:
        raise oc.DataError("列が見つかりません: %s / 実際の列: %s" % (cands, list(df.columns)[:40]))
    return None


def run():
    files = sorted(IMPORT.glob("*.csv"))
    oc.check(files, "import/ にCSVがありません（事故情報データバンクの検索結果CSVを置いてください）")
    recs, seen = [], set()
    for f in files:
        df = oc.read_csv(f.read_bytes())
        c_id = pick(df, ("事故情報",), ("番号",), ("ID",), required=False)
        c_date = pick(df, ("発生", "年月"), ("発生", "日"), ("登録",), required=False)
        c_cat = pick(df, ("商品", "分類"), ("分類",), ("カテゴリ",))
        c_name = pick(df, ("商品", "名"), ("品名",), ("製品",), required=False)
        c_maker = pick(df, ("事業者",), ("メーカー",), ("製造",), required=False)
        c_harm = pick(df, ("危害",), ("被害",), ("程度",), required=False)
        c_txt = pick(df, ("概要",), ("内容",), ("状況",), required=False)
        for r in df.to_dict("records"):
            key = r[c_id] if c_id else (r.get(c_date, ""), r.get(c_name, ""), r.get(c_txt, "")[:60])
            if key in seen:
                continue
            seen.add(key)
            recs.append({"id": str(r[c_id]) if c_id else "", "date": str(r.get(c_date, "")) if c_date else "",
                         "cat": str(r[c_cat]).strip(), "name": str(r.get(c_name, "")).strip() if c_name else "",
                         "maker": str(r.get(c_maker, "")).strip() if c_maker else "",
                         "harm": str(r.get(c_harm, "")).strip() if c_harm else "",
                         "txt": re.sub(r"\s+", " ", str(r.get(c_txt, "")))[:240] if c_txt else ""})
    oc.check(len(recs) >= 100, "事故情報が少なすぎます(%d件)" % len(recs))
    serious = lambda h: any(w in h for w in ("死亡", "重症", "重傷", "中等症", "1か月以上", "１か月以上"))
    cat = defaultdict(lambda: [0, 0])
    for x in recs:
        c = cat[x["cat"] or "（分類なし）"]
        c[0] += 1; c[1] += serious(x["harm"])
    crow = sorted([{"cat": k, "n": v[0], "serious": v[1]} for k, v in cat.items()], key=lambda x: -x["n"])
    meth = ("事故情報データバンクシステムの検索結果CSV（取り込んだ%d件）を集計しました。登録された事故情報は、"
            "製品の欠陥が原因と確認されたものだけではなく、使い方による事故や原因調査中のものも含みます。"
            "件数は販売台数の多さにも左右されます。" % len(recs))
    R = [{"id": "cat", "tab": "分類別", "title": "事故の多い製品の分類", "desc": "取り込んだ事故情報を商品分類ごとに数えたもの。",
          "rows": crow, "method": meth, "share_label": "cat", "share_value": "n",
          "columns": [{"key": "cat", "label": "分類"}, {"key": "n", "label": "件数", "type": "num", "bar": True},
                      {"key": "serious", "label": "うち重い被害", "type": "num"}]}]
    srow = sorted(crow, key=lambda x: -x["serious"])
    R.append({"id": "serious", "tab": "重い被害", "title": "重い被害（死亡・重症など）が多い分類", "desc": "危害の程度が死亡・重症などの事故の件数。",
              "rows": srow, "method": meth, "share_label": "cat", "share_value": "serious", "columns": R[0]["columns"]})
    search = [{"n": (x["name"] or x["cat"]), "s": x["date"], "a": x["maker"] + " " + x["cat"] + " " + x["txt"],
               "k": [["分類", x["cat"]], ["危害", x["harm"] or "—"], ["概要", x["txt"][:120]]]} for x in recs]
    meta = {"data_period": "取り込んだCSV：%d件" % len(recs),
            "stats": [{"label": "取り込んだ事故情報", "value": len(recs), "unit": "件"},
                      {"label": "重い被害のあった事故", "value": sum(serious(x["harm"]) for x in recs), "unit": "件"}],
            "sources": [{"name": "事故情報データバンクシステム", "org": "消費者庁・独立行政法人国民生活センター", "url": SRC,
                         "license": "検索結果を出典を明記して加工", "retrieved": oc.today()}]}
    oc.write(meta, R, search=search)


if __name__ == "__main__":
    oc.main(run)
