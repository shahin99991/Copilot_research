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
        ↓ 新着あり
  GitHub Models API（gpt-4o-mini）で日本語サマリー生成
        ↓
  docs/updates/YYYY-MM-DD.md を自動コミット
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
