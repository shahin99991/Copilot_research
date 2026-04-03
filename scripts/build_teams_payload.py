#!/usr/bin/env python3
"""Build Teams Adaptive Card payloads from daily markdown reports."""

from __future__ import annotations

import argparse
import html
import json
import re
from dataclasses import dataclass
from pathlib import Path


CARD_SCHEMA = "http://adaptivecards.io/schemas/adaptive-card.json"


@dataclass
class ReportSummary:
    date_name: str
    file_name: str
    diff_count: int
    updates: list[dict[str, str]]
    ai_summary_lines: list[str]


def read_report(path: Path) -> ReportSummary:
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()

    date_name = path.stem
    diff_count = parse_diff_count(lines)
    updates = parse_updates(lines)
    ai_summary_lines = parse_ai_summary_lines(lines)

    return ReportSummary(
        date_name=date_name,
        file_name=path.name,
        diff_count=diff_count,
        updates=updates,
        ai_summary_lines=ai_summary_lines,
    )


def parse_diff_count(lines: list[str]) -> int:
    for line in lines:
        match = re.match(r"^- 差分件数:\s*(\d+)", line.strip())
        if match:
            return int(match.group(1))

    # Fallback: count URL bullets under update sections.
    return sum(1 for line in lines if line.strip().startswith("- **URL**:"))


def parse_updates(lines: list[str]) -> list[dict[str, str]]:
    updates: list[dict[str, str]] = []
    current: dict[str, str] | None = None
    in_code_block = False

    for raw_line in lines:
        line = raw_line.strip()

        if line.startswith("### "):
            if current:
                updates.append(finalize_update(current))
            current = {
                "title": clean_heading(line[4:].strip()),
                "source": "",
                "url": "",
                "detail": "",
                "detail_lines": [],
            }
            continue

        if not current:
            continue

        if line.startswith("```"):
            in_code_block = not in_code_block
            continue

        if in_code_block:
            continue

        if line.startswith("- **ソース**:"):
            current["source"] = line.split(":", 1)[1].strip()
            continue

        if line.startswith("- **URL**:"):
            current["url"] = extract_url(line)
            continue

        if line.startswith("- **公開日**:") or line.startswith("- **リリースノート全文**:"):
            continue

        if line.startswith("<details>") or line.startswith("</details>"):
            continue

        if line.startswith("## "):
            continue

        cleaned = clean_detail_line(line)
        if cleaned:
            detail_lines = current.setdefault("detail_lines", [])
            detail_lines.append(cleaned)

    if current:
        updates.append(finalize_update(current))

    return updates


def finalize_update(update: dict[str, str]) -> dict[str, str]:
    detail_lines = update.get("detail_lines", [])
    unique_lines: list[str] = []
    for line in detail_lines:
        if line not in unique_lines:
            unique_lines.append(line)

    detail = " ".join(unique_lines)
    detail = re.sub(r"\s+", " ", detail).strip()

    return {
        "title": update.get("title", ""),
        "source": update.get("source", ""),
        "url": update.get("url", ""),
        "detail": detail,
    }


def clean_detail_line(line: str) -> str:
    if not line:
        return ""

    cleaned = re.sub(r"<[^>]+>", " ", line)
    cleaned = html.unescape(cleaned)
    cleaned = cleaned.strip()
    cleaned = re.sub(r"\s+", " ", cleaned)

    lowered = cleaned.lower()
    if not cleaned:
        return ""
    if cleaned.startswith("http://") or cleaned.startswith("https://"):
        return ""
    if lowered.startswith("the post ") or "appeared first on" in lowered:
        return ""
    if cleaned.startswith("[") and "](" in cleaned:
        return ""
    return cleaned


def parse_ai_summary_lines(lines: list[str]) -> list[str]:
    in_section = False
    extracted: list[str] = []

    for raw_line in lines:
        line = raw_line.strip()

        if line == "## 🤖 AIによる日本語まとめ":
            in_section = True
            continue

        if in_section and line.startswith("## "):
            break

        if in_section and line:
            cleaned = re.sub(r"<[^>]+>", "", line).strip()
            if cleaned:
                extracted.append(cleaned)

    return extracted


def clean_heading(title: str) -> str:
    # Remove common emoji prefixes used in report headings.
    for prefix in ("🚀 ", "📰 ", "✨ ", "🔧 ", "📣 "):
        if title.startswith(prefix):
            return title[len(prefix):].strip()
    return title


def extract_url(line: str) -> str:
    markdown_match = re.search(r"\[[^\]]+\]\((https?://[^)]+)\)", line)
    if markdown_match:
        return markdown_match.group(1)

    plain_match = re.search(r"(https?://\S+)", line)
    if plain_match:
        return plain_match.group(1)

    return ""


def normalize_bullets(lines: list[str], max_items: int) -> list[str]:
    normalized: list[str] = []

    for line in lines:
        clean = line.strip()
        if not clean or clean == "---":
            continue

        if clean.startswith("- "):
            normalized.append(clean)
        else:
            normalized.append(f"- {clean}")

        if len(normalized) >= max_items:
            break

    return normalized


def summarize_detail_text(text: str, max_len: int = 120) -> str:
    if not text:
        return ""

    normalized = re.sub(r"\s+", " ", text).strip()
    if not normalized:
        return ""

    candidates = re.split(r"(?<=[。.!?])\s+", normalized)
    for candidate in candidates:
        sentence = candidate.strip()
        if not sentence:
            continue
        lowered = sentence.lower()
        if lowered.startswith("the post "):
            continue
        if "appeared first on" in lowered:
            continue
        if len(sentence) > max_len:
            return sentence[: max_len - 1].rstrip() + "…"
        return sentence

    if len(normalized) > max_len:
        return normalized[: max_len - 1].rstrip() + "…"
    return normalized


def infer_capability(title: str, detail: str) -> str:
    corpus = f"{title} {detail}".lower()

    if "cloud agent" in corpus and "research, plan, and code" in corpus:
        return "Copilot cloud agentで調査・計画・実装までを広い場面で進められるようになりました。"
    if "no longer limited to pull-request workflows" in corpus:
        return "Pull Request以外のワークフローでもエージェントを使えるようになりました。"
    if "is now available" in corpus or "now available" in corpus:
        feature = re.split(r"(?i)\s+is now available|\s+now available", title)[0].strip()
        if feature:
            return f"{feature} が利用可能になりました。"
        return "新機能が利用可能になりました。"
    if "agent assignment" in corpus and "issue" in corpus:
        return "Issue画面からエージェントを素早く割り当てられるようになりました。"
    if "refreshed copilot tab" in corpus or "native session logs" in corpus:
        return "GitHub MobileでCopilotタブとセッションログが使いやすくなりました。"
    if ("vscode" in corpus or "vs code" in corpus) and (
        "release" in corpus or "リリース" in corpus
    ):
        return "VS Codeの新バージョンが公開され、最新の改善を利用できます。"
    if "support" in corpus or "supported" in corpus:
        return "新しい対象への対応が追加され、使える範囲が広がりました。"
    if "faster" in corpus or "improved" in corpus or "refresh" in corpus:
        return "操作性や処理速度が改善されました。"
    if detail:
        return "機能改善が公開されました。"
    return "新機能または改善が追加されました。"


def format_update_lines(update: dict[str, str]) -> list[str]:
    title = update.get("title", "（タイトルなし）").strip()
    source = update.get("source", "").strip()
    detail = update.get("detail", "").strip()

    heading = f"- {title}"
    if source:
        heading = f"- {title} ({source})"

    lines = [heading]
    lines.append(f"  できるようになったこと: {infer_capability(title, detail)}")

    summary = summarize_detail_text(detail)
    if summary:
        lines.append(f"  変更の要点: {summary}")

    return lines


def build_daily_change_lines(report: ReportSummary, max_items: int = 6) -> list[str]:
    if report.diff_count == 0:
        return ["- 本日の更新差分はありませんでした。"]

    lines: list[str] = []
    for item in report.updates[:max_items]:
        lines.extend(format_update_lines(item))

    if lines:
        return lines

    ai_lines = normalize_bullets(report.ai_summary_lines, max_items=max_items)
    if ai_lines:
        return ai_lines

    return ["- 変更内容の抽出に失敗しました。次回の自動収集で再試行します。"]


def build_daily_card(report: ReportSummary) -> dict:
    status = "更新あり" if report.diff_count > 0 else "差分なし"
    summary = f"ステータス: {status}\n差分件数: {report.diff_count}"
    details = "\n".join(build_daily_change_lines(report))

    return {
        "$schema": CARD_SCHEMA,
        "type": "AdaptiveCard",
        "version": "1.4",
        "body": [
            {
                "type": "TextBlock",
                "size": "Medium",
                "weight": "Bolder",
                "text": "Copilot / VS Code 定期チェック結果",
            },
            {"type": "TextBlock", "wrap": True, "text": summary},
            {"type": "TextBlock", "wrap": True, "text": "変更内容:\n" + details},
        ],
    }


def list_reports_between(updates_dir: Path, from_date: str, to_date: str) -> list[Path]:
    matched: list[Path] = []
    for path in sorted(updates_dir.glob("*.md")):
        date_name = path.stem
        if from_date <= date_name <= to_date:
            matched.append(path)
    return matched


def build_backfill_lines(reports: list[ReportSummary], max_items_per_day: int = 3) -> list[str]:
    lines: list[str] = []

    for report in reports:
        if report.diff_count == 0:
            lines.append(f"- {report.date_name} は差分 0 件でした。更新はありません。")
            continue

        lines.append(f"- {report.date_name} は差分 {report.diff_count} 件です。")

        if report.updates:
            day_updates = report.updates[:max_items_per_day]
            for update in day_updates:
                formatted = format_update_lines(update)
                for idx, line in enumerate(formatted):
                    if idx == 0:
                        lines.append("  ・" + line[2:])
                    else:
                        lines.append("    " + line.strip())

            remaining = report.diff_count - len(day_updates)
            if remaining > 0:
                lines.append(f"  ・ほか {remaining} 件の更新があります。")
            continue

        ai_lines = normalize_bullets(report.ai_summary_lines, max_items=2)
        if ai_lines:
            for bullet in ai_lines:
                text = bullet[2:].strip() if bullet.startswith("- ") else bullet
                lines.append(f"  ・{text}")
            continue

        lines.append("  ・主な変更の抽出に失敗しました。")

    if not lines:
        lines = ["- 対象期間のレポートファイルは見つかりませんでした。"]

    return lines


def build_backfill_card(
    reports: list[ReportSummary],
    from_date: str,
    to_date: str,
) -> dict:
    summary = f"期間: {from_date} 〜 {to_date}\n対象日数: {len(reports)}"
    details = "\n".join(build_backfill_lines(reports))

    return {
        "$schema": CARD_SCHEMA,
        "type": "AdaptiveCard",
        "version": "1.4",
        "body": [
            {
                "type": "TextBlock",
                "size": "Medium",
                "weight": "Bolder",
                "text": "Copilot / VS Code 期間サマリー通知",
            },
            {"type": "TextBlock", "wrap": True, "text": summary},
            {"type": "TextBlock", "wrap": True, "text": "変更内容:\n" + details},
        ],
    }


def cmd_daily(args: argparse.Namespace) -> None:
    report_file = Path(args.report_file)
    report = read_report(report_file)
    card = build_daily_card(report)
    Path(args.output).write_text(json.dumps(card, ensure_ascii=False), encoding="utf-8")


def cmd_backfill(args: argparse.Namespace) -> None:
    updates_dir = Path(args.updates_dir)
    files = list_reports_between(updates_dir, args.from_date, args.to_date)
    reports = [read_report(path) for path in files]
    card = build_backfill_card(reports, args.from_date, args.to_date)
    Path(args.output).write_text(json.dumps(card, ensure_ascii=False), encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build Teams payload JSON files.")
    sub = parser.add_subparsers(dest="mode", required=True)

    daily = sub.add_parser("daily", help="Build payload for daily report notification")
    daily.add_argument("--report-file", required=True, help="Path to daily report markdown")
    daily.add_argument("--output", required=True, help="Output JSON file path")
    daily.set_defaults(func=cmd_daily)

    backfill = sub.add_parser("backfill", help="Build payload for range summary notification")
    backfill.add_argument("--from-date", required=True, help="Start date YYYY-MM-DD")
    backfill.add_argument("--to-date", required=True, help="End date YYYY-MM-DD")
    backfill.add_argument(
        "--updates-dir",
        default="docs/updates",
        help="Directory containing daily report markdown files",
    )
    backfill.add_argument("--output", required=True, help="Output JSON file path")
    backfill.set_defaults(func=cmd_backfill)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()