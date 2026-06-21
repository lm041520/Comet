"""评测结果输出：① 数值指标报告（Markdown 表）② 明细（JSON，逐条召回/抽取细节）。

results 结构：{section: {row: {metric: value}}}（每节一张表）。
details 结构：{section: [明细 dict, ...]}。
"""
import json
from datetime import datetime
from pathlib import Path

_RESULTS_DIR = Path(__file__).parent / "results"


def _ts() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def _table(section: str, rows: dict) -> str:
    if not rows:
        return f"### {section}\n\n（无数据）\n"
    metric_names = list(next(iter(rows.values())).keys())
    lines = [f"### {section}", ""]
    lines.append("| 配置 | " + " | ".join(metric_names) + " |")
    lines.append("|" + "---|" * (len(metric_names) + 1))
    for row, m in rows.items():
        lines.append(f"| {row} | " + " | ".join(str(m.get(k, "")) for k in metric_names) + " |")
    lines.append("")
    return "\n".join(lines)


def write_report(results: dict, setup_stats: dict | None = None) -> Path:
    _RESULTS_DIR.mkdir(exist_ok=True)
    ts = _ts()
    lines = [
        f"# Comet 评测报告 {ts}",
        "",
        "> 小规模自建 gold 集的离线自测，非大规模 benchmark。",
        "> 记忆/抽取名称匹配口径：归一化 + 包含（更完整或更具体的名视为命中，如「日本京都」命中「京都」），通用自指「用户」仅精确匹配。RAG 文档按文件名精确匹配。",
        "",
    ]
    if setup_stats:
        lines += [f"评测数据：语料 {setup_stats.get('docs', 0)} 篇、对话 {setup_stats.get('dialogues', 0)} 段。", ""]
    for section, rows in results.items():
        lines.append(_table(section, rows))
    path = _RESULTS_DIR / f"report-{ts}.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def write_details(details: dict) -> Path:
    _RESULTS_DIR.mkdir(exist_ok=True)
    path = _RESULTS_DIR / f"details-{_ts()}.json"
    path.write_text(json.dumps(details, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def print_summary(results: dict) -> None:
    """控制台打印指标摘要。"""
    for section, rows in results.items():
        print(f"\n=== {section} ===")
        if not rows:
            print("（无数据）")
            continue
        metric_names = list(next(iter(rows.values())).keys())
        print("行".ljust(14) + "".join(m.ljust(12) for m in metric_names))
        for row, m in rows.items():
            print(row.ljust(14) + "".join(f"{m.get(k, ''):<12}" for k in metric_names))
