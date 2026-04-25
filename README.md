# Copilot Research

GitHub Copilot と VS Code の最新情報を自動収集・日本語まとめするリポジトリ。

## 仕組み

```
GitHub Actions（毎日 09:00 JST に自動実行）
  ↓
scripts/check_updates.py
  ├─ VS Code 最新リリース確認（GitHub API）
  ├─ GitHub Copilot Changelog（RSS）
  └─ VS Code Blog（RSS、AI/Copilot関連のみ）
    ↓
  差分あり: GitHub Models API（gpt-4o-mini）で日本語サマリー生成
  差分なし: 定型メッセージでサマリー生成
    ↓
  docs/updates/YYYY-MM-DD.md を毎日生成（差分0でも生成）
    ↓
  GitHub Actions が docs/updates/ と state/ を自動コミット
```

## ディレクトリ構成

```
Copilot_research/
├── .github/
│   └── workflows/
│       └── daily-check.yml     ← cron ジョブ本体
├── docs/
│   ├── updates/                ← 日次更新まとめ（自動生成）
│   │   └── 2026-03-08.md
│   └── releases/               ← VS Code リリースノート全文（自動生成）
│       └── v1.107.0.md
├── scripts/
│   ├── check_updates.py        ← 更新チェック本体
│   └── requirements.txt
├── state/
│   └── last-seen.json          ← 最後に確認した状態（自動更新）
└── README.md
```

## セットアップ

### 1. GITHUB_MODELS_TOKEN を設定する（オプション）

設定すると、日本語サマリーが AI によって自動生成されます。設定しなくても動作しますが、サマリーはスキップされます。

1. GitHub のプロフィール → **Settings → Developer settings → Personal access tokens**
2. Fine-grained token を作成、**Models (read)** 権限を付与
3. このリポジトリの **Settings → Secrets and variables → Actions** に `GITHUB_MODELS_TOKEN` として登録

### 2. GitHub Actions を有効化する

リポジトリの **Actions** タブから `Daily Copilot & VS Code Update Check` を選んで **Enable workflow**。

### 3. 手動で初回実行する

Actions タブ → `Daily Copilot & VS Code Update Check` → **Run workflow** を押すと即時確認できます。

## 監視対象

| ソース | 方法 | 頻度 |
|--------|------|------|
| VS Code 最新リリース | GitHub API | 毎日確認 |
| GitHub Copilot Changelog | RSS | 毎日確認 |
| VS Code Blog（Copilot/AI関連） | RSS + キーワードフィルタ | 毎日確認 |

## VS Code Agent との連携

`quita-agent` ワークスペースに `copilot-researcher.agent.md` エージェントがあります。
自動生成されたスタブに肉付けしたいときに呼び出してください。

```
【Copilot Researcherを選択】
「今日の更新まとめを詳しく解説して」
→ docs/updates/ の最新ファイルを読み、URLを開いて内容を補完してくれる
```

## 毎日の運用フロー（VS Code）

このワークスペースでは、毎朝の確認は次の手順で回せます。

1. Command Palette で `Tasks: Run Task` を実行
2. `Daily: Sync and check latest update` を実行
3. ターミナル出力の `Diff count` と `Article trigger` を確認
4. `Diff count: 0` なら、その日は終了
5. `Diff count: 1以上` なら `Daily: Open latest update report` で最新レポートを開く
6. チャットで「今日の更新を解説して」と依頼
7. 記事化したい場合のみ「記事化して」と明示指示する

### 記事化の判断ルール

- `Diff count = 0` : 記事化しない
- `Diff count >= 1` : 内容確認後に記事化するか判断

### 参考（ローカル実行コマンド）

VS Code タスクを使わずに確認する場合は、ワークスペース直下で次を実行します。

```bash
cd /home/shahin/quita-agent
./daily-check-local.sh
```

ghp_
AMgS7pOAmN5LzeVlHlNSdqvD3rVclz47yHSF
