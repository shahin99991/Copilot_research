#!/usr/bin/env python3
"""
Microsoft AI / Copilot 更新チェッカー

監視対象:
  - VS Code の最新リリース（GitHub API）
  - GitHub Copilot Changelog（RSS）
  - VS Code Blog（RSS、Copilot/AI関連のみ）
    - Microsoft 365 Blog（RSS、Copilot/AI・アプリ更新）
    - Power Platform Blog（RSS、Copilot Studio/AI関連）
    - Microsoft Blogs（RSS、Copilot/AI関連）

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
MODELS_TOKEN = os.environ.get("GITHUB_MODELS_TOKEN", "") or os.environ.get("MODELS_TOKEN", "")
FEED_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

GH_HEADERS = {
    "Authorization": f"Bearer {GITHUB_TOKEN}",
    "Accept": "application/vnd.github+json",
}

FEED_HEADERS = {
    "User-Agent": FEED_USER_AGENT,
    "Accept": "application/rss+xml, application/xml, text/xml;q=0.9, */*;q=0.8",
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
    {
        "id": "microsoft_365_blog",
        "url": "https://www.microsoft.com/en-us/microsoft-365/blog/feed/",
        "name": "Microsoft 365 Blog",
        "filter_keywords": [
            "copilot",
            "ai",
            "agent",
            "microsoft 365",
            "word",
            "excel",
            "powerpoint",
            "outlook",
            "teams",
            "onedrive",
            "sharepoint",
        ],
    },
    {
        "id": "power_platform_blog",
        "url": "https://www.microsoft.com/en-us/power-platform/blog/feed/",
        "name": "Power Platform Blog",
        "filter_keywords": [
            "copilot studio",
            "copilot",
            "power platform",
            "power apps",
            "power automate",
            "power bi",
            "ai",
            "agent",
        ],
    },
    {
        "id": "microsoft_blogs",
        "url": "https://blogs.microsoft.com/feed/",
        "name": "Microsoft Blogs",
        "filter_keywords": [
            "copilot",
            "microsoft 365",
            "copilot studio",
            "power platform",
            "ai",
            "agent",
        ],
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


def is_truthy(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


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
        "stack": "VS Code",
        "title": f"VS Code {tag} リリース",
        "tag": tag,
        "url": data["html_url"],
        "body": (data.get("body") or "")[:1500],
        "published_at": data["published_at"],
    }


def infer_stack(title: str, summary: str, feed_name: str, url: str) -> str:
    text = f"{title} {summary} {feed_name} {url}".lower()

    if "copilot studio" in text or "power virtual agents" in text:
        return "Copilot Studio"
    if "microsoft 365 copilot" in text or "copilot for microsoft 365" in text:
        return "Microsoft 365 Copilot"
    if any(k in text for k in ["word", "excel", "powerpoint", "outlook", "teams", "sharepoint", "onedrive"]):
        return "Microsoft 365 Apps"
    if any(k in text for k in ["power platform", "power apps", "power automate", "power bi", "dataverse"]):
        return "Power Platform"
    if "vscode" in text or "visual studio code" in text:
        return "VS Code"
    if "github copilot" in text or "copilot" in text:
        return "Copilot"
    return "Microsoft AI / Copilot"


def fetch_feed(url: str) -> feedparser.FeedParserDict:
    resp = requests.get(url, headers=FEED_HEADERS, timeout=30)
    resp.raise_for_status()
    return feedparser.parse(resp.text)


def as_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return str(value)


def check_feeds(state: dict) -> list[dict]:
    """RSS フィードを確認して新着エントリを返す。"""
    new_entries = []
    feed_state = state.setdefault("feeds", {})
    seen_links: set[str] = set()

    for feed_config in FEEDS:
        feed_id = feed_config["id"]
        try:
            feed = fetch_feed(feed_config["url"])
        except Exception as e:
            print(f"[WARN] Feed parse error ({feed_id}): {e}", file=sys.stderr)
            continue

        last_seen_id = feed_state.get(feed_id)
        latest_id = None

        for entry in feed.entries[:15]:
            title = as_text(entry.get("title", ""))
            summary_text = as_text(entry.get("summary", ""))
            entry_link = as_text(entry.get("link", "")).strip()
            entry_id = as_text(entry.get("id", "")) or entry_link

            if latest_id is None:
                latest_id = entry_id  # 最新エントリのIDを記録

            if entry_id == last_seen_id:
                break  # ここまでは既読

            # キーワードフィルタ
            keywords = feed_config.get("filter_keywords", [])
            if keywords:
                text = f"{title} {summary_text}".lower()
                if not any(k in text for k in keywords):
                    continue

            if entry_link and entry_link in seen_links:
                continue

            new_entries.append({
                "type": "feed",
                "stack": infer_stack(
                    title,
                    summary_text,
                    feed_config["name"],
                    entry_link,
                ),
                "feed_name": feed_config["name"],
                "title": title or "（タイトルなし）",
                "url": entry_link,
                "summary": summary_text[:800],
                "published": as_text(entry.get("published", "")),
            })
            if entry_link:
                seen_links.add(entry_link)

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
        "以下のCopilot / VS Code / Microsoft 365 / Copilot Studio関連の最新情報を、"
        "日本語でエンジニア向けに要点を箇条書きでまとめてください。\n"
    ]
    for u in updates:
        if u["type"] == "vscode_release":
            lines.append(f"## [{u.get('stack','VS Code')}] {u['title']}\nURL: {u['url']}\n{u['body'][:600]}\n")
        else:
            lines.append(
                f"## [{u.get('stack','Microsoft AI / Copilot')}] {u['title']}\nSource: {u['feed_name']}\n"
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

    diff_count = len(updates)
    lines = [
        f"# Microsoft AI / Copilot 更新情報 ({today})\n",
        f"> 自動生成: {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}\n",
        "",
        "## 📌 実行ステータス\n",
        f"- 差分件数: {diff_count}",
        f"- 記事化トリガー: {'ON' if diff_count > 0 else 'OFF'}",
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

    if not updates:
        lines += [
            "- 本日の新規差分はありませんでした。",
            "- 定期チェックは正常に完了しています。",
            "",
        ]

    for u in updates:
        if u["type"] == "vscode_release":
            lines += [
                f"### 🚀 {u['title']}",
                f"- **スタック**: {u.get('stack', 'VS Code')}",
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
                f"- **スタック**: {u.get('stack', 'Microsoft AI / Copilot')}",
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
    require_ai = is_truthy(os.environ.get("REQUIRE_AI", ""))
    if require_ai and not MODELS_TOKEN:
        print(
            "[ERROR] REQUIRE_AI is enabled but GITHUB_MODELS_TOKEN/MODELS_TOKEN is not set.",
            file=sys.stderr,
        )
        sys.exit(1)

    state = load_state()
    updates: list[dict] = []

    # VS Code リリースチェック
    release = check_vscode_release(state)
    if release:
        updates.append(release)

    # RSS フィードチェック
    feed_updates = check_feeds(state)
    updates.extend(feed_updates)

    if updates:
        print(f"[INFO] {len(updates)} update(s) found.")

    # GitHub Models API で日本語サマリーを生成（トークンがある場合のみ）
    summary = None
    if updates:
        summary = generate_japanese_summary(updates)
        if require_ai and not summary:
            print(
                "[ERROR] REQUIRE_AI is enabled but AI summary generation failed.",
                file=sys.stderr,
            )
            sys.exit(1)
    else:
        summary = (
            "- 本日の定期実行では、前回チェック以降の新規差分は検知されませんでした。\n"
            "- 自動収集ワークフローは正常に完了しています。"
        )

    if summary and updates:
        print("[INFO] Japanese summary generated.")
    else:
        if updates:
            print("[INFO] Skipped LLM summary (no GITHUB_MODELS_TOKEN).")
        else:
            print("[INFO] No updates found. Daily report will still be generated.")

    # Markdown ファイルを生成
    create_update_doc(updates, summary)

    # state を保存
    save_state(state)

    # GitHub Actions の後続ステップに出力フラグを渡す
    output_file = os.environ.get("GITHUB_OUTPUT", "")
    if output_file:
        with open(output_file, "a") as f:
            f.write(f"has_updates={'true' if bool(updates) else 'false'}\n")
            f.write("has_report=true\n")


if __name__ == "__main__":
    main()
