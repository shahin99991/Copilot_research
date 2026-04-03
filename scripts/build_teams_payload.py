#!/usr/bin/env python3
"""Build Teams Adaptive Card payloads from daily markdown reports."""

from __future__ import annotations

import argparse
import json
import os
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

    for raw_line in lines:
        line = raw_line.strip()

        if line.startswith("### "):
            if current:
                updates.append(current)
            current = {
                "title": clean_heading(line[4:].strip()),
                "source": "",
                "url": "",
            }
            continue

        if not current:
            continue

        if line.startswith("- **ソース**:"):
            current["source"] = line.split(":", 1)[1].strip()
            continue

        if line.startswith("- **URL**:"):
            current["url"] = extract_url(line)
            continue

    if current:
        updates.append(current)

    return updates


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


def build_daily_change_lines(report: ReportSummary, max_items: int = 6) -> list[str]:
    if report.diff_count == 0:
        return ["- 本日の更新差分はありませんでした。"]

    ai_lines = normalize_bullets(report.ai_summary_lines, max_items=max_items)
    if ai_lines:
        return ai_lines

    lines: list[str] = []
    for item in report.updates[:max_items]:
        title = item.get("title", "（タイトルなし）")
        source = item.get("source", "")

        if source:
            sentence = f"- {source}で「{title}」が公開されました。"
        else:
            sentence = f"- 「{title}」が公開されました。"

        lines.append(sentence)

    if not lines:
        return ["- 変更内容の抽出に失敗しました。次回の自動収集で再試行します。"]

    return lines


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


def build_backfill_lines(reports: list[ReportSummary]) -> list[str]:
    lines: list[str] = []

    for report in reports:
        if report.diff_count == 0:
            lines.append(f"- {report.date_name} は差分 0 件でした。更新はありません。")
            continue

        ai_lines = normalize_bullets(report.ai_summary_lines, max_items=2)
        if ai_lines:
            sentence = ai_lines[0][2:].strip()
            lines.append(
                f"- {report.date_name} は差分 {report.diff_count} 件。{sentence}"
            )
            if len(ai_lines) > 1:
                lines.append(f"  補足: {ai_lines[1][2:].strip()}")
            continue

        titles = [u.get("title", "") for u in report.updates if u.get("title")]
        if titles:
            top = " / ".join(titles[:2])
            lines.append(
                f"- {report.date_name} は差分 {report.diff_count} 件。主な変更: {top}"
            )
        else:
            lines.append(
                f"- {report.date_name} は差分 {report.diff_count} 件。主な変更の抽出に失敗しました。"
            )

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