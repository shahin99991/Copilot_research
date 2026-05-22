# GitHub Copilotで「アプデ情報の収集 -> Teams通知」を自動化した話（Power Automate連携）

## はじめに

GitHub Copilot活用コンテスト向けに、日々のアップデート情報を自動収集して Teams に通知する仕組みを紹介します。

やったことはシンプルで、次の3ステップです。

1. VS Code / GitHub Copilot / Microsoft系ブログの更新を収集
2. 要点を日本語でまとめ、日次レポートを生成
3. Teams に毎日自動通知（必要に応じて Power Automate を中継）

この仕組みで、情報収集の「見に行く運用」を「届く運用」に変えられました。

> [画像差し込み 01]
> 完成イメージ（Teams に更新内容が届いている画面）

## 先に結論: これはCopilot活用と言えるか

結論として、言えます。この記事での主役は Copilot です。

- 設計: 監視対象とデータ構造の分解を Copilot と対話しながら固めた
- 実装: Python での更新判定、Markdown解析、Adaptive Card整形を Copilot で高速実装
- 改善: 通知文面の粒度（できること/影響/要点）を Copilot で反復改善
- 保守: GitHub Actions の失敗パターン対策（Secret未設定、Webhook失敗）を Copilot で補強

Actions と Power Automate は「動かす基盤」で、
その中身の設計・実装・改善を加速したのが Copilot、という位置づけです。

---

## 何を自動化したか

今回の自動化対象は次です。

- 更新検知: VS Code release / GitHub Copilot changelog / 関連RSS
- レポート生成: `docs/updates/YYYY-MM-DD.md`
- Teams通知: Adaptive Card JSON を作って Webhook 送信
- 期間集計: 任意期間の backfill 通知

通知までの流れは次のとおりです。

1. GitHub Actions が毎日実行
2. `scripts/check_updates.py` で差分チェック
3. `scripts/build_teams_payload.py` で Teams 用 JSON 作成
4. Webhook で Teams へ送信

> [画像差し込み 02]
> 全体アーキテクチャ図（GitHub Actions -> Pythonスクリプト -> Teams / Power Automate）

---

## 構成（リポジトリ側）

主要ファイルはこの4つです。

- `scripts/check_updates.py`
  - 各ソースの更新確認
  - 差分があれば日次レポート生成
- `scripts/build_teams_payload.py`
  - 日次レポートを解析
  - Teams Adaptive Card JSON を生成
- `.github/workflows/daily-check.yml`
  - 定期実行（毎日）
  - payload作成 -> Teams通知
- `.github/workflows/teams-backfill-notify.yml`
  - 期間指定の再通知（手動実行）

---

## 実装ポイント

### 1. 更新を取りに行く（check_updates.py）

監視対象は次のように広めに持っています。

- VS Code 最新リリース（GitHub API）
- GitHub Copilot Changelog（RSS）
- VS Code Blog（AI/Copilot関連のみ）
- Microsoft 365 Blog / Power Platform Blog / Microsoft Blogs（キーワード絞り込み）

単にリンク列挙するだけではなく、更新がない日でも日次レポートを出すので「今日は差分なし」をチームで共有できます。

Copilot 活用ポイント:

- RSSごとのフィルタ条件をどう分けるか
- 重複URLをどう除外するか
- どの粒度で `stack` を推定するか

実際に使ったプロンプト例:

```text
check_updates.py に RSS監視を追加したい。
要件:
- feedごとに filter_keywords を持てる
- URL重複は除外
- stack 推定関数を用意
- 例外時は処理継続して WARN を出す
```

### 2. Teams向けに整形する（build_teams_payload.py）

日次レポートの Markdown を解析して、次の情報をカード化します。

- できるようになったこと
- 利用者への影響
- 変更の要点
- ソースURL

通知を読んだ人が「結局なにが変わったのか」を30秒で掴める形に寄せています。

Copilot 活用ポイント:

- Markdownから必要情報だけを安全に抽出するパーサ
- 文字数制限に合わせた要約とトリミング
- カード表示の階層（見出し/詳細）設計

実際に使ったプロンプト例:

```text
Teams Adaptive Card向けに、
"できるようになったこと / 利用者への影響 / 変更の要点" の3行を
日本語で安定生成する関数を作って。
入力欠落時はフォールバック文言を返し、URLは保持すること。
```

### 3. 定期実行する（daily-check.yml）

ワークフローは次の順で実行しています。

1. 依存ライブラリをインストール
2. 更新チェック実行
3. `docs/updates` と `state` をコミット
4. Teams payload を生成
5. `TEAMS_WEBHOOK_URL` が設定されていれば通知

バックフィル用に、期間指定の通知ワークフローも分けています。

Copilot 活用ポイント:

- Secret未設定時の安全な分岐
- 通知失敗時にHTTPコードとレスポンスを残す処理
- 毎日運用を想定した最小のトラブルシュート文言

実際に使ったプロンプト例:

```text
GitHub Actionsで Teams Webhook 通知を追加したい。
Secret未設定時は fail ではなく skip。
送信時はHTTPコードを検証し、失敗時にレスポンス本文を表示する run ステップを書いて。
```

---

## Power Automate連携（任意）

この仕組みは Teams Incoming Webhook へ直接送る構成でも動きますが、
Power Automate を挟むと次のメリットがあります。

- 通知先チャネルの切り替えがGUIでできる
- 条件分岐や承認フローをあとから追加しやすい
- 送信失敗時の再試行や監査ログを取りやすい

Power Automate 側は以下のような流れにしておくと扱いやすいです。

1. HTTPリクエスト受信
2. JSONパース
3. Teamsにメッセージ投稿（またはカード投稿）

> [画像差し込み 03]
> Power Automate フロー全体（トリガー〜Teams投稿）

> [画像差し込み 04]
> JSON パース設定画面

> [画像差し込み 05]
> Teams投稿アクション設定画面

---

## ローカル検証コマンド

```bash
cd /home/shahin/quita-agent

# 日次チェックをローカルで実行
./daily-check-local.sh

# 最新レポートから Teams payload を作成
cd Copilot_research
latest_file=$(ls -1 docs/updates/*.md | sort | tail -n 1)
python scripts/build_teams_payload.py daily \
  --report-file "$latest_file" \
  --require-ai \
  --output teams-payload.json
```

Webhook疎通確認は次のようにできます。

```bash
curl -sS -X POST \
  -H "Content-Type: application/json" \
  --data @teams-payload.json \
  "$TEAMS_WEBHOOK_URL"
```

> [画像差し込み 06]
> GitHub Actions の成功画面（daily-check.yml 実行結果）

> [画像差し込み 07]
> Teams に実際に届いた通知（最終形）

---

## Copilot活用の実例（ここが本題）

この記事が「Actions紹介」だけに見えないよう、
Copilot を使った実作業を3レイヤーで明示します。

### レイヤー1: 設計

- 収集対象の定義（どのRSSを追うか、何を除外するか）
- 更新の分類軸（stack/source/impact）の決定

### レイヤー2: 実装

- `check_updates.py` の feed処理と state管理
- `build_teams_payload.py` のレポート解析とカード整形
- `.github/workflows/daily-check.yml` の通知フロー

### レイヤー3: 改善

- 通知文面の読みやすさ調整
- 失敗時の挙動（skip / fail）の切り分け
- backfill 通知の追加

実務上の効果:

- 実装の初速が上がる（下書き作成が速い）
- 仕様変更に追従しやすい（プロンプトで差分修正しやすい）
- ドキュメント化が楽（実装意図を文章に落とし込みやすい）

補足:
公開時には、あなたの実測値を1〜2個だけ入れると説得力が上がります。
例: 「初版実装にかかった時間」「通知文面の試行回数」「運用開始までの日数」

---

## つまずいた点と対策

### 1. 更新が多い日のカード可読性

情報を詰め込みすぎると読まれないので、
「できるようになったこと / 影響 / 要点」の3行に寄せました。

### 2. モデルトークン未設定時の失敗

`--require-ai` を有効にしている場合、
`GITHUB_MODELS_TOKEN` または `MODELS_TOKEN` が無いと失敗します。
Secrets の必須化で対処しました。

### 3. Teams通知の運用設計

Webhook直送は簡単ですが、運用要件が増えると管理が辛くなるので、
Power Automate を中継にすると拡張しやすいです。

---

## まとめ

「情報収集の定型作業」を自動化すると、
チームは最新情報の確認よりも、意思決定や実装に時間を使えるようになります。

今回の構成は次の点が気に入っています。

- 差分がない日も含めて運用が安定する
- Teams通知でチーム全員の認知を揃えられる
- Power Automate を挟めば運用拡張しやすい

同じ悩みを持つチームの参考になればうれしいです。

---

## 公開前チェック（自分用）

- `[画像差し込み xx]` を実画像に置き換えた
- Teams のスクショは機密情報をマスクした
- リポジトリ名やURLに誤りがない
- Secrets名（`TEAMS_WEBHOOK_URL` など）に誤記がない
