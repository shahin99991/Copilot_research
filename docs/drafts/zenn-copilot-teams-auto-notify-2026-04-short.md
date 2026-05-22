# GitHub Copilot活用で「アプデ収集 -> Teams通知」を自動化した実践（短縮版）

## はじめに

毎日の技術アップデート確認を、
「各自が見に行く運用」から「Teamsに自動で届く運用」へ変えました。

今回のポイントは、GitHub Actions や Power Automate を使ったこと自体ではなく、
**設計・実装・改善のサイクルを GitHub Copilot で高速化したこと**です。

> [画像1: Teamsに更新通知が届いた最終画面]

---

## 3行で要約

1. `check_updates.py` で VS Code / Copilot / Microsoft系の更新を自動収集
2. `build_teams_payload.py` で Markdown を Teams向けカードJSONに変換
3. `daily-check.yml` で毎日実行し、Teamsへ通知

---

## これは「Copilot活用」なのか？

結論: はい。

この取り組みで Copilot を使ったのは次の部分です。

- 設計: 監視対象、データ構造、通知粒度の決定
- 実装: Python の解析ロジック、整形ロジック、例外処理の下書き
- 改善: 通知文面とワークフロー失敗時の挙動を反復チューニング

GitHub Actions と Power Automate は実行基盤、
Copilot はその中身を短時間で作って改善するためのエンジン、という役割分担です。

---

## 構成（実ファイル）

- `scripts/check_updates.py`
  - 各ソースの更新確認、差分抽出、日次レポート生成
- `scripts/build_teams_payload.py`
  - 日次レポートを解析し、Adaptive Card JSONを作成
- `.github/workflows/daily-check.yml`
  - 毎日定期実行、payload作成、Teams送信
- `.github/workflows/teams-backfill-notify.yml`
  - 期間指定でまとめ通知

> [画像2: 全体アーキテクチャ図（Actions -> Python -> Teams）]

---

## Copilotの使いどころ（実例）

### 1. 収集ロジックの設計

使った指示の例:

```text
RSS監視を追加したい。
要件:
- feedごとに filter_keywords を持つ
- URL重複を除外する
- 例外時は処理継続して WARN を出す
```

効果:

- 監視対象追加時の実装スピードが上がる
- 既存ロジックとの整合を保ちやすい

### 2. Teams通知文面の品質改善

使った指示の例:

```text
"できるようになったこと / 利用者への影響 / 変更の要点" の3行で、
読みやすい日本語通知を生成する関数を作って。
入力欠落時はフォールバック文言を返すこと。
```

効果:

- 通知を見た人が30秒で要点把握できる
- 情報過多の日でも読み切れる

### 3. ワークフローの堅牢化

使った指示の例:

```text
Teams通知ステップを追加。
Secret未設定時はskip、送信失敗時はHTTPコードとレスポンスを出力してfail。
```

効果:

- 失敗時の原因切り分けが速い
- 日次運用の安定性が上がる

> [画像3: Copilotチャットで実装を詰めている画面]

---

## Power Automate連携（任意）

Webhook直送でも運用可能ですが、Power Automateを挟むと次が楽になります。

- 通知先の変更
- 条件分岐（重要更新のみ通知など）
- 承認フローや監査ログ

最小構成は次の3アクションです。

1. HTTPリクエスト受信
2. JSONパース
3. Teams投稿

> [画像4: Power Automate フロー全体]
> [画像5: Teams投稿アクション設定]

---

## ローカル検証（コピペ用）

```bash
cd /home/shahin/quita-agent
./daily-check-local.sh

cd Copilot_research
latest_file=$(ls -1 docs/updates/*.md | sort | tail -n 1)
python scripts/build_teams_payload.py daily \
  --report-file "$latest_file" \
  --require-ai \
  --output teams-payload.json

curl -sS -X POST \
  -H "Content-Type: application/json" \
  --data @teams-payload.json \
  "$TEAMS_WEBHOOK_URL"
```

> [画像6: daily-check.yml の成功ログ]

---

## 成果（ここは実測値を入れて公開）

公開前に次の2つを入れると、審査で伝わりやすくなります。

- 初版実装時間: 例）xx時間 -> xx時間
- 運用負荷: 例）毎朝確認 xx分 -> 通知確認 xx分

---

## まとめ

この取り組みは、
「Actions/Power Automateを使った自動化」だけではなく、
**Copilotで設計・実装・改善を回し続けた実践**です。

結果として、情報収集の定型作業を軽くし、
チームが意思決定と実装に集中できるようになりました。

---

## 公開前チェック

- 画像差し込み6枚を実スクリーンショットに置換
- Teams画面の機密情報をマスク
- 実測値2つを追記
- リポジトリ内ファイル名・Secrets名の表記を最終確認
