#!/usr/bin/env python3
"""Build Teams Adaptive Card payloads from daily markdown reports."""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any


CARD_SCHEMA = "http://adaptivecards.io/schemas/adaptive-card.json"
MODELS_ENDPOINT = "https://models.inference.ai.azure.com/chat/completions"
MODELS_DEFAULT = "gpt-4o-mini"


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


def to_plain_bullets(lines: list[str]) -> list[str]:
    out: list[str] = []
    for line in lines:
        text = line.strip()
        if not text:
            continue
        if text.startswith("- "):
            out.append("・" + text[2:])
        else:
            out.append("・" + text)
    return out


def compact_text(text: str, max_len: int = 140) -> str:
    value = re.sub(r"\s+", " ", text or "").strip()
    if len(value) > max_len:
        return value[: max_len - 1].rstrip() + "…"
    return value


def has_japanese(text: str) -> bool:
    return bool(re.search(r"[\u3040-\u30ff\u3400-\u9fff]", text or ""))


def get_models_token() -> str:
    token = (
        os.getenv("GITHUB_MODELS_TOKEN", "").strip()
        or os.getenv("MODELS_TOKEN", "").strip()
        or os.getenv("GITHUB_TOKEN", "").strip()
    )
    return token


def extract_json_object(text: str) -> dict[str, Any] | None:
    candidate = text.strip()

    # Try direct parse first.
    try:
        parsed = json.loads(candidate)
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        pass

    # If wrapped in markdown code fences, strip and retry.
    if candidate.startswith("```"):
        candidate = re.sub(r"^```[a-zA-Z0-9_-]*\s*", "", candidate)
        candidate = re.sub(r"\s*```$", "", candidate)
        candidate = candidate.strip()
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            pass

    # Fallback: parse first JSON object region.
    start = candidate.find("{")
    end = candidate.rfind("}")
    if start != -1 and end != -1 and end > start:
        region = candidate[start : end + 1]
        try:
            parsed = json.loads(region)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            return None

    return None


def invoke_models(payload: dict[str, Any], token: str, timeout: int = 50) -> str | None:
    req = urllib.request.Request(
        MODELS_ENDPOINT,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as res:
            body = res.read().decode("utf-8")
    except (urllib.error.URLError, TimeoutError, ValueError):
        return None

    try:
        decoded = json.loads(body)
        return decoded["choices"][0]["message"]["content"]
    except Exception:
        return None


def parse_insights_from_content(content: str, max_updates: int) -> dict[int, dict[str, str]]:
    data = extract_json_object(content)
    if not data:
        return {}

    items = data.get("items", [])
    if not isinstance(items, list):
        return {}

    result: dict[int, dict[str, str]] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        idx = item.get("index")
        if not isinstance(idx, int):
            continue
        if idx < 0 or idx >= max_updates:
            continue

        title_ja = compact_text(str(item.get("title_ja", "")), max_len=60)
        capability = compact_text(str(item.get("capability", "")), max_len=90)
        impact = compact_text(str(item.get("impact", "")), max_len=90)
        point = compact_text(str(item.get("point", "")), max_len=110)

        if not title_ja and not capability and not impact and not point:
            continue

        # Keep Japanese readability in Teams even when model drifts.
        if title_ja and not has_japanese(title_ja):
            title_ja = ""
        if capability and not has_japanese(capability):
            capability = "新機能や改善を利用できるようになりました。"
        if impact and not has_japanese(impact):
            impact = "利用者の作業効率や使いやすさに良い影響があります。"
        if point and not has_japanese(point):
            point = ""

        result[idx] = {
            "title_ja": title_ja,
            "capability": capability,
            "impact": impact,
            "point": point,
        }

    return result


def build_insight_payload(input_items: list[dict[str, str]], single_mode: bool = False) -> dict[str, Any]:
    scope = "1件" if single_mode else "複数件"
    return {
        "model": os.getenv("GITHUB_MODELS_MODEL", MODELS_DEFAULT),
        "temperature": 0.2,
        "max_tokens": 1400,
        "messages": [
            {
                "role": "system",
                "content": (
                    "あなたはGitHub CopilotとVS Code更新を日本語で要約する技術ライターです。"
                    "入力ごとに『何ができるようになったか』と『利用者への影響』を短く具体的に書いてください。"
                    "不明な点は断定せず、控えめに表現してください。"
                    "必ずJSONのみを返してください。"
                ),
            },
            {
                "role": "user",
                "content": (
                    f"次のupdates配列({scope})を読んで、各indexについて日本語の説明を作成してください。\n"
                    "出力形式は次のJSONだけにしてください:\n"
                    "{\"items\":[{\"index\":0,\"title_ja\":\"...\",\"capability\":\"...\",\"impact\":\"...\",\"point\":\"...\"}]}\n"
                    "制約:\n"
                    "- title_ja: 更新名の日本語見出し(最大50文字)\n"
                    "- capability: 何ができるようになったか(最大80文字)\n"
                    "- impact: 誰にどんな影響があるか(最大80文字)\n"
                    "- point: 補足要点(最大100文字、任意)\n"
                    "- すべて日本語で出力\n"
                    "- 主要な製品用語は英語表記を残してよい"
                    " (例: Research / Plan / Code, cloud agent, Auto model selection, native session logs)\n"
                    "- URLは含めない\n"
                    f"updates={json.dumps(input_items, ensure_ascii=False)}"
                ),
            },
        ],
    }


def call_models_for_update_insights(
    updates: list[dict[str, str]],
    *,
    retries: int = 2,
) -> dict[int, dict[str, str]]:
    token = get_models_token()
    if not token or not updates:
        return {}

    input_items = []
    for idx, update in enumerate(updates):
        input_items.append(
            {
                "index": idx,
                "title": compact_text(update.get("title", ""), max_len=180),
                "source": compact_text(update.get("source", ""), max_len=80),
                "detail": compact_text(update.get("detail", ""), max_len=500),
            }
        )

    result: dict[int, dict[str, str]] = {}

    # Batch call first.
    payload = build_insight_payload(input_items)
    for attempt in range(retries + 1):
        content = invoke_models(payload, token)
        if content:
            result.update(parse_insights_from_content(content, max_updates=len(updates)))
        if len(result) == len(updates):
            return result
        if attempt < retries:
            time.sleep(1.0 + attempt)

    # Retry missing entries one by one to increase robustness.
    missing = [idx for idx in range(len(updates)) if idx not in result]
    for idx in missing:
        single_item = [
            {
                "index": 0,
                "title": compact_text(updates[idx].get("title", ""), max_len=180),
                "source": compact_text(updates[idx].get("source", ""), max_len=80),
                "detail": compact_text(updates[idx].get("detail", ""), max_len=500),
            }
        ]
        single_payload = build_insight_payload(single_item, single_mode=True)

        parsed_single: dict[str, str] | None = None
        for attempt in range(retries + 1):
            content = invoke_models(single_payload, token)
            if content:
                one = parse_insights_from_content(content, max_updates=1)
                if 0 in one:
                    parsed_single = one[0]
                    break
            if attempt < retries:
                time.sleep(0.8 + attempt)

        if parsed_single:
            result[idx] = parsed_single

    return result


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


def infer_title_ja(title: str, detail: str) -> str:
    if has_japanese(title):
        return title

    corpus = f"{title} {detail}".lower()
    if "cloud agent" in corpus and "research, plan, and code" in corpus:
        return "Copilot cloud agent (Research / Plan / Code) の拡張"
    if "student" in corpus and "now available" in corpus:
        return "Copilot Student向け GPT-5.4 mini 提供"
    if "github mobile" in corpus and "session logs" in corpus:
        return "GitHub Mobile の Copilot tab / native session logs 改善"
    if "github mobile" in corpus and "agent assignment" in corpus:
        return "GitHub Mobile の Assign an Agent 改善"
    if ("vscode" in corpus or "vs code" in corpus) and (
        "release" in corpus or "リリース" in corpus
    ):
        return "VS Code 新バージョン公開"
    return "主要な機能更新"


def infer_capability(title: str, detail: str) -> str:
    corpus = f"{title} {detail}".lower()

    if "cloud agent" in corpus and "research, plan, and code" in corpus:
        return "Copilot cloud agentで Research / Plan / Code を広い場面で進められるようになりました。"
    if "no longer limited to pull-request workflows" in corpus:
        return "Pull Request workflows 以外でも cloud agent を使えるようになりました。"
    if "is now available" in corpus or "now available" in corpus:
        feature = re.split(r"(?i)\s+is now available|\s+now available", title)[0].strip()
        if feature:
            return f"{feature} が利用可能になりました。"
        return "新機能が利用可能になりました。"
    if "agent assignment" in corpus and "issue" in corpus:
        return "Issue 画面から Assign an Agent を素早く実行できるようになりました。"
    if "refreshed copilot tab" in corpus or "native session logs" in corpus:
        return "GitHub Mobileで Copilot tab / native session logs が使いやすくなりました。"
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


def infer_impact(title: str, detail: str, source: str) -> str:
    corpus = f"{title} {detail} {source}".lower()

    if "student" in corpus or "education" in corpus:
        return "学習ユーザーが新しいモデルや機能を使って学習を進めやすくなります。"
    if "mobile" in corpus:
        return "外出先でも agent 作業の継続や進捗確認がしやすくなります。"
    if "cloud agent" in corpus or "agent" in corpus:
        return "実装作業の自動化範囲が広がり、開発スピード向上が見込めます。"
    if "vscode" in corpus or "vs code" in corpus:
        return "開発環境を最新化することで日常開発の安定性と効率が向上します。"
    return "利用者の作業効率や使いやすさに良い影響があります。"


def retain_key_terms(text: str, title: str, detail: str) -> str:
    base = compact_text(text, max_len=120)
    corpus = f"{title} {detail}".lower()

    # Keep official wording for cloud agent update.
    if "cloud agent" in corpus and "research, plan, and code" in corpus:
        if "research" not in base.lower() and "plan" not in base.lower() and "code" not in base.lower():
            base = base.rstrip("。") + " (Research / Plan / Code)"

    # Keep official wording for student auto model selection update.
    if "auto model selection" in corpus and "gpt-5.4 mini" in corpus:
        if "auto model selection" not in base.lower():
            base = base.rstrip("。") + " (Auto model selection)"

    # Keep official wording for mobile session logs update.
    if "native session logs" in corpus:
        if "native session logs" not in base.lower():
            base = base.rstrip("。") + " (native session logs)"

    return base


def format_update_lines(update: dict[str, str], ai_insight: dict[str, str] | None = None) -> list[str]:
    title = update.get("title", "（タイトルなし）").strip()
    source = update.get("source", "").strip()
    detail = update.get("detail", "").strip()

    ai_title = ""
    heading_title = infer_title_ja(title, detail)
    if ai_insight:
        ai_title = compact_text(ai_insight.get("title_ja", ""), max_len=60)
        if ai_title and has_japanese(ai_title):
            heading_title = ai_title

    heading = f"・{heading_title}"
    if source:
        heading = f"・{heading_title} ({source})"

    lines = [heading]

    ai_capability = ""
    ai_impact = ""
    ai_point = ""
    if ai_insight:
        ai_capability = compact_text(ai_insight.get("capability", ""), max_len=90)
        ai_impact = compact_text(ai_insight.get("impact", ""), max_len=90)
        ai_point = compact_text(ai_insight.get("point", ""), max_len=110)

    if ai_capability:
        ai_capability = retain_key_terms(ai_capability, title, detail)

    if ai_capability:
        lines.append(f"できるようになったこと: {ai_capability}")
    else:
        lines.append(f"できるようになったこと: {retain_key_terms(infer_capability(title, detail), title, detail)}")

    if ai_impact:
        lines.append(f"利用者への影響: {ai_impact}")
    else:
        lines.append(f"利用者への影響: {infer_impact(title, detail, source)}")

    summary = summarize_detail_text(detail)
    if ai_point:
        lines.append(f"変更の要点: {ai_point}")
    elif summary and ai_insight is None and has_japanese(summary):
        lines.append(f"変更の要点: {summary}")

    return lines


def build_daily_change_lines(
    report: ReportSummary,
    max_items: int = 6,
    *,
    require_ai: bool = False,
) -> list[str]:
    if report.diff_count == 0:
        return ["・本日の更新差分はありませんでした。"]

    lines: list[str] = []
    day_updates = report.updates[:max_items]
    ai_insights = call_models_for_update_insights(day_updates)
    if require_ai and len(ai_insights) < len(day_updates):
        missing = [str(i + 1) for i in range(len(day_updates)) if i not in ai_insights]
        raise RuntimeError(
            "AI insight generation failed for update index: " + ",".join(missing)
        )
    for idx, item in enumerate(day_updates):
        lines.extend(format_update_lines(item, ai_insight=ai_insights.get(idx)))

    if lines:
        return lines

    ai_lines = normalize_bullets(report.ai_summary_lines, max_items=max_items)
    if ai_lines:
        return to_plain_bullets(ai_lines)

    return ["・変更内容の抽出に失敗しました。次回の自動収集で再試行します。"]


def build_daily_card(report: ReportSummary, *, require_ai: bool = False) -> dict:
    status = "更新あり" if report.diff_count > 0 else "差分なし"
    summary = f"ステータス: {status}\n差分件数: {report.diff_count}"
    detail_lines = build_daily_change_lines(report, require_ai=require_ai)

    body = [
        {
            "type": "TextBlock",
            "size": "Medium",
            "weight": "Bolder",
            "text": "Copilot / VS Code 定期チェック結果",
        },
        {"type": "TextBlock", "wrap": True, "text": summary},
        {"type": "TextBlock", "weight": "Bolder", "text": "変更内容"},
    ]
    for line in detail_lines:
        body.append({"type": "TextBlock", "wrap": True, "text": line})

    return {
        "$schema": CARD_SCHEMA,
        "type": "AdaptiveCard",
        "version": "1.4",
        "body": body,
    }


def list_reports_between(updates_dir: Path, from_date: str, to_date: str) -> list[Path]:
    matched: list[Path] = []
    for path in sorted(updates_dir.glob("*.md")):
        date_name = path.stem
        if from_date <= date_name <= to_date:
            matched.append(path)
    return matched


def build_backfill_lines(
    reports: list[ReportSummary],
    *,
    require_ai: bool = False,
) -> list[str]:
    lines: list[str] = []

    for report in reports:
        if report.diff_count == 0:
            lines.append(f"【{report.date_name}】差分 0 件。更新はありません。")
            continue

        lines.append(f"【{report.date_name}】差分 {report.diff_count} 件")

        if report.updates:
            day_updates = report.updates
            ai_insights = call_models_for_update_insights(day_updates)
            if require_ai and len(ai_insights) < len(day_updates):
                missing = [str(i + 1) for i in range(len(day_updates)) if i not in ai_insights]
                raise RuntimeError(
                    f"AI insight generation failed for {report.date_name} update index: "
                    + ",".join(missing)
                )
            for idx, update in enumerate(day_updates):
                formatted = format_update_lines(update, ai_insight=ai_insights.get(idx))
                lines.extend(formatted)
            continue

        ai_lines = normalize_bullets(report.ai_summary_lines, max_items=2)
        if ai_lines:
            lines.extend(to_plain_bullets(ai_lines))
            continue

        lines.append("・主な変更の抽出に失敗しました。")

    if not lines:
        lines = ["・対象期間のレポートファイルは見つかりませんでした。"]

    return lines


def build_backfill_card(
    reports: list[ReportSummary],
    from_date: str,
    to_date: str,
    *,
    require_ai: bool = False,
) -> dict:
    summary = f"期間: {from_date} 〜 {to_date}\n対象日数: {len(reports)}"
    detail_lines = build_backfill_lines(reports, require_ai=require_ai)

    body = [
        {
            "type": "TextBlock",
            "size": "Medium",
            "weight": "Bolder",
            "text": "Copilot / VS Code 期間サマリー通知",
        },
        {"type": "TextBlock", "wrap": True, "text": summary},
        {"type": "TextBlock", "weight": "Bolder", "text": "変更内容"},
    ]
    for line in detail_lines:
        body.append({"type": "TextBlock", "wrap": True, "text": line})

    return {
        "$schema": CARD_SCHEMA,
        "type": "AdaptiveCard",
        "version": "1.4",
        "body": body,
    }


def cmd_daily(args: argparse.Namespace) -> None:
    report_file = Path(args.report_file)
    report = read_report(report_file)
    card = build_daily_card(report, require_ai=args.require_ai)
    Path(args.output).write_text(json.dumps(card, ensure_ascii=False), encoding="utf-8")


def cmd_backfill(args: argparse.Namespace) -> None:
    updates_dir = Path(args.updates_dir)
    files = list_reports_between(updates_dir, args.from_date, args.to_date)
    reports = [read_report(path) for path in files]
    card = build_backfill_card(reports, args.from_date, args.to_date, require_ai=args.require_ai)
    Path(args.output).write_text(json.dumps(card, ensure_ascii=False), encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build Teams payload JSON files.")
    sub = parser.add_subparsers(dest="mode", required=True)

    daily = sub.add_parser("daily", help="Build payload for daily report notification")
    daily.add_argument("--report-file", required=True, help="Path to daily report markdown")
    daily.add_argument("--output", required=True, help="Output JSON file path")
    daily.add_argument(
        "--require-ai",
        action="store_true",
        help="Fail if AI interpretation cannot be generated for updates.",
    )
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
    backfill.add_argument(
        "--require-ai",
        action="store_true",
        help="Fail if AI interpretation cannot be generated for updates.",
    )
    backfill.set_defaults(func=cmd_backfill)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()