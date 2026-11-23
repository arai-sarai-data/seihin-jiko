# 製品事故検索

買う前に、その製品で事故が起きていないか。国に集まった製品事故の情報を、製品名やメーカー名で探せます。

公開ページ：https://arai-sarai-data.github.io/seihin-jiko/

## 仕組み

- `fetch.py` が公式の公開データを取得・検証・集計し、`docs/data/` に JSON を書き出します。
- GitHub Actions（`.github/workflows/update.yml`）がデータを取り込んだときに実行し、GitHub Pages に公開します。
- 元データの形式が想定と違うときは **数字を推測で埋めずに停止** します（前回の正しいデータが表示され続けます）。停止した理由は Actions のログに `データ検証で停止しました` として出ます。

## 最初の設定（1回だけ）

1. このフォルダの中身を `arai-sarai-data/seihin-jiko` リポジトリ（Public）に置く。
2. Settings → Pages → Build and deployment の Source を **GitHub Actions** にする。
3. Settings → Actions → General → Workflow permissions を **Read and write permissions** にする。
4. Actions タブ → `update` → **Run workflow** で初回のデータ取得を実行する。

## 出典

- 出典：消費者庁「事故情報データバンク」(https://www.jikojoho.caa.go.jp/)を加工して作成（公共データ利用規約 PDL1.0）。本サイトは消費者庁が作成したものではありません。
- `fetch.py` は検索画面の「CSV出力」と同じ方法で1万件ずつCSVを取得し、`raw/jikojoho/` に保存します（7日以内の再取得はしません）。

各データの利用条件に従い、出典を明記して加工・公開しています（`docs/about.html`）。
