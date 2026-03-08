#!/usr/bin/env python3
"""
GitHub Copilot / VS Code 更新チェッカー

監視対象:
  - VS Code の最新リリース（GitHub API）
  - GitHub Copilot Changelog（RSS）
  - VS Code Blog（RSS、Copilot/AI関連のみ）

変更検知時: docs/updates/YYYY-MM-DD.md を生成して GitHub Actions でコミット
"""

import os
import json
import sys
import requests
import feedparser
from datetime import datetime, timezone
from pathlib import Path

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
MODELS_TOKEN = os.environ.get("GITHUB_MODELS_TOKEN", "") or os.environ.get("MODELS_TOKEN", GITHUB_TOKEN)

GH_HEADERS = {
    "Authorization": f"Bearer {GITHUB_TOKEN}",
    "Accept": "application/vnd.github+json",
}

STATE_FILE = Path("state/last-seen.json")
UPDATES_DIR = Path("docs/updates")
RELEASES_DIR = Path("docs/releases")

# 監視するRSSフィード
FEEDS = [
    {
        "id": "github_copilot_changelog",
        "url": "https://github.blog/changelog/label/copilot/feed/",
        "name": "GitHub Copilot Changelog",
        "filter_keywords": [],  # このフィードは全件対象
    },
    {
        "id": "vscode_blog",
        "url": "https://code.visualstudio.com/feed.xml",
        "name": "VS Code Blog",
        "filter_keywords": ["copilot", "agent", "ai", "model", "llm", "chat", "skill"],
    },
]


# ─────────────────────────────────────────────
# State 管理
# ─────────────────────────────────────────────

def load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return {"vscode_release": None, "feeds": {}}


def save_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(
        json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8"
    )


# ─────────────────────────────────────────────
# 更新チェック
# ─────────────────────────────────────────────

def check_vscode_release(state: dict) -> dict | None:
    """VS Code 最新リリースを GitHub API で確認する。"""
    try:
        resp = requests.get(
            "https://api.github.com/repos/microsoft/vscode/releases/latest",
            headers=GH_HEADERS,
            timeout=30,
        )
        resp.raise_for_status()
    except Exception as e:
        print(f"[WARN] VS Code release check failed: {e}", file=sys.stderr)
        return None

    data = resp.json()
    tag = data["tag_name"]

    if state.get("vscode_release") == tag:
        return None  # 変化なし

    print(f"[INFO] New VS Code release detected: {tag}")
    state["vscode_release"] = tag

    # リリースノート全文を docs/releases/ に保存
    release_path = RELEASES_DIR / f"{tag}.md"
    RELEASES_DIR.mkdir(parents=True, exist_ok=True)
    if not release_path.exists():
        release_body = data.get("body", "") or ""
        release_path.write_text(
            f"# VS Code {tag} リリースノート\n\n"
            f"- **公開日**: {data['published_at']}\n"
            f"- **URL**: {data['html_url']}\n\n"
            f"## 原文（英語）\n\n{release_body}\n",
            encoding="utf-8",
        )

    return {
        "type": "vscode_release",
        "title": f"VS Code {tag} リリース",
        "tag": tag,
        "url": data["html_url"],
        "body": (data.get("body") or "")[:1500],
        "published_at": data["published_at"],
    }


def check_feeds(state: dict) -> list[dict]:
    """RSS フィードを確認して新着エントリを返す。"""
    new_entries = []
    feed_state = state.setdefault("feeds", {})

    for feed_config in FEEDS:
        feed_id = feed_config["id"]
        try:
            feed = feedparser.parse(feed_config["url"])
        except Exception as e:
            print(f"[WARN] Feed parse error ({feed_id}): {e}", file=sys.stderr)
            continue

        last_seen_id = feed_state.get(feed_id)
        latest_id = None

        for entry in feed.entries[:15]:
            entry_id = entry.get("id") or entry.get("link", "")

            if latest_id is None:
                latest_id = entry_id  # 最新エントリのIDを記録

            if entry_id == last_seen_id:
                break  # ここまでは既読

            # キーワードフィルタ
            keywords = feed_config.get("filter_keywords", [])
            if keywords:
                text = (
                    entry.get("title", "") + " " + entry.get("summary", "")
                ).lower()
                if not any(k in text for k in keywords):
                    continue

            new_entries.append({
                "type": "feed",
                "feed_name": feed_config["name"],
                "title": entry.get("title", "（タイトルなし）"),
                "url": entry.get("link", ""),
                "summary": (entry.get("summary") or "")[:800],
                "published": entry.get("published", ""),
            })

        if latest_id:
            feed_state[feed_id] = latest_id

    return new_entries


# ─────────────────────────────────────────────
# GitHub Models API で日本語サマリー生成
# ─────────────────────────────────────────────

def generate_japanese_summary(updates: list[dict]) -> str | None:
    """GitHub Models API（gpt-4o-mini）で日本語サマリーを生成する。"""
    if not MODELS_TOKEN:
        return None

    lines = [
        "以下のGitHub CopilotおよびVS Codeの最新情報を、"
        "日本語でエンジニア向けに要点を箇条書きでまとめてください。\n"
    ]
    for u in updates:
        if u["type"] == "vscode_release":
            lines.append(f"## {u['title']}\nURL: {u['url']}\n{u['body'][:600]}\n")
        else:
            lines.append(
                f"## {u['title']}\nSource: {u['feed_name']}\n"
                f"URL: {u['url']}\n{u['summary'][:400]}\n"
            )
    lines.append("\n**日本語まとめ（箇条書き）:**")

    payload = {
        "model": "gpt-4o-mini",
        "messages": [
            {
                "role": "system",
                "content": (
                    "あなたはGitHub CopilotとVS Codeの最新情報を"
                    "日本語でまとめる技術ライターです。"
                    "専門用語は英語のまま、説明は日本語で書いてください。"
                ),
            },
            {"role": "user", "content": "\n".join(lines)},
        ],
        "max_tokens": 1200,
        "temperature": 0.3,
    }

    try:
        resp = requests.post(
            "https://models.inference.ai.azure.com/chat/completions",
            headers={
                "Authorization": f"Bearer {MODELS_TOKEN}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=60,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]
    except Exception as e:
        print(f"[WARN] GitHub Models API error: {e}", file=sys.stderr)
        return None


# ─────────────────────────────────────────────
# Markdown ドキュメント生成
# ─────────────────────────────────────────────

def create_update_doc(updates: list[dict], summary: str | None) -> Path:
    """更新情報を Markdown ファイルに書き出す。"""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    filepath = UPDATES_DIR / f"{today}.md"
    UPDATES_DIR.mkdir(parents=True, exist_ok=True)

    lines = [
        f"# GitHub Copilot / VS Code 更新情報 ({today})\n",
        f"> 自動生成: {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}\n",
        "",
    ]

    if summary:
        lines += [
            "## 🤖 AIによる日本語まとめ\n",
            summary,
            "",
            "---",
            "",
        ]

    lines += ["## 📋 検知した更新\n"]

    for u in updates:
        if u["type"] == "vscode_release":
            lines += [
                f"### 🚀 {u['title']}",
                f"- **URL**: [{u['url']}]({u['url']})",
                f"- **公開日**: {u['published_at']}",
                f"- **リリースノート全文**: [docs/releases/{u['tag']}.md](../releases/{u['tag']}.md)",
                "",
                "<details><summary>リリースノート抜粋</summary>",
                "",
                f"```\n{u['body'][:600]}\n```",
                "",
                "</details>",
                "",
            ]
        else:
            lines += [
                f"### 📰 {u['title']}",
                f"- **ソース**: {u['feed_name']}",
                f"- **URL**: [{u['url']}]({u['url']})",
                f"- **公開日**: {u['published']}",
                "",
                f"{u['summary'][:400]}",
                "",
            ]

    filepath.write_text("\n".join(lines), encoding="utf-8")
    print(f"[INFO] Created: {filepath}")
    return filepath


# ─────────────────────────────────────────────
# メイン
# ─────────────────────────────────────────────

def main():
    state = load_state()
    updates: list[dict] = []

    # VS Code リリースチェック
    release = check_vscode_release(state)
    if release:
        updates.append(release)

    # RSS フィードチェック
    feed_updates = check_feeds(state)
    updates.extend(feed_updates)

    if not updates:
        print("[INFO] No updates found. Nothing to do.")
        save_state(state)
        return

    print(f"[INFO] {len(updates)} update(s) found.")

    # GitHub Models API で日本語サマリーを生成（トークンがある場合のみ）
    summary = generate_japanese_summary(updates)
    if summary:
        print("[INFO] Japanese summary generated.")
    else:
        print("[INFO] Skipped LLM summary (no GITHUB_MODELS_TOKEN).")

    # Markdown ファイルを生成
    create_update_doc(updates, summary)

    # state を保存
    save_state(state)

    # GitHub Actions の後続ステップに「更新あり」フラグを渡す
    output_file = os.environ.get("GITHUB_OUTPUT", "")
    if output_file:
        with open(output_file, "a") as f:
            f.write("has_updates=true\n")


if __name__ == "__main__":
    main()
