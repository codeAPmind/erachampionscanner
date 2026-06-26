"""
Era Champion Scanner — 报告生成模块
生成 Markdown 报告 + CSV 排名表
"""

import csv
import os
from datetime import datetime


DIMENSION_NAMES_CN = {
    "dominance": "行业龙头",
    "earnings_breakaway": "财报断层",
    "institutional": "机构共识",
    "narrative": "时代叙事",
    "cashflow": "现金流验证",
    "supply_constraint": "供需约束",
}

GRADE_EMOJI = {"S": "🏆", "A": "⭐", "B": "📊", "C": "📉"}


def generate_report(results: list, output_dir: str = ".") -> str:
    """
    生成完整的 Markdown 分析报告
    results: [{"ticker": ..., "composite": ..., "dimensions": ..., "signals": ...}, ...]
    """
    # 按总分降序排列
    results = sorted(results, key=lambda x: x["composite"]["total"], reverse=True)
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    lines = []
    lines.append(f"# 时代主角扫描报告")
    lines.append(f"")
    lines.append(f"生成时间: {now}")
    lines.append(f"")
    lines.append(f"扫描标的数: {len(results)}")
    lines.append("")

    # ---- 总排名表 ----
    lines.append("## 综合排名")
    lines.append("")
    lines.append("| 排名 | 股票 | 等级 | 总分 | 龙头 | 财报 | 机构 | 叙事 | 现金流 | 供需 | 信号 |")
    lines.append("|------|------|------|------|------|------|------|------|--------|------|------|")

    for i, r in enumerate(results, 1):
        t = r["ticker"]
        c = r["composite"]
        g = c["grade"]
        emoji = GRADE_EMOJI.get(g, "")
        bd = c["breakdown"]

        # 退化信号计数
        sig = r.get("signals", {})
        yellow_cnt = len(sig.get("yellow", []))
        red_cnt = len(sig.get("red", []))
        if red_cnt > 0:
            sig_str = f"🔴×{red_cnt}"
        elif yellow_cnt > 0:
            sig_str = f"🟡×{yellow_cnt}"
        else:
            sig_str = "✅"

        lines.append(
            f"| {i} | **{t}** | {emoji} {g} | {c['total']:.1f} "
            f"| {bd['dominance']['raw']:.0f} "
            f"| {bd['earnings_breakaway']['raw']:.0f} "
            f"| {bd['institutional']['raw']:.0f} "
            f"| {bd['narrative']['raw']:.0f} "
            f"| {bd['cashflow']['raw']:.0f} "
            f"| {bd['supply_constraint']['raw']:.0f} "
            f"| {sig_str} |"
        )

    lines.append("")

    # ---- 前5名目标价明细 ----
    lines.append("## 前5名分析师目标价明细（近90天）")
    lines.append("")
    for r in results[:5]:
        t = r["ticker"]
        pts = r.get("price_targets_raw", [])
        current = r.get("current_price", 0)
        lines.append(f"### {t}（当前价 ${current:.0f}）")
        lines.append("")
        if pts:
            lines.append("| 日期 | 机构 | 评级 | 目标价 | 前目标价 | 变化 |")
            lines.append("|------|------|------|--------|----------|------|")
            for p in pts:
                prior = f"${p['prior_target']:.0f}" if p["prior_target"] else "—"
                if p["prior_target"] and p["prior_target"] > 0:
                    chg = p["price_target"] - p["prior_target"]
                    chg_str = f"{'+' if chg >= 0 else ''}{chg:.0f}"
                else:
                    chg_str = "—"
                lines.append(
                    f"| {p['date']} | {p['firm']} | {p['grade']} "
                    f"| **${p['price_target']:.0f}** | {prior} | {chg_str} |"
                )
        else:
            lines.append("_近90天无带目标价的分析师评级记录_")
        lines.append("")

    # ---- S/A 级详细报告 ----
    top_tickers = [r for r in results if r["composite"]["grade"] in ("S", "A")]

    if top_tickers:
        lines.append("---")
        lines.append("")
        lines.append("## S/A 级标的详细分析")
        lines.append("")

        for r in top_tickers:
            t = r["ticker"]
            c = r["composite"]
            dims = r["dimensions"]
            sig = r.get("signals", {})

            lines.append(f"### {GRADE_EMOJI.get(c['grade'], '')} {t} — {c['grade']} 级（{c['total']:.1f} 分）")
            lines.append("")

            # 各维度详情
            for dim_key, dim_name in DIMENSION_NAMES_CN.items():
                dim_data = dims.get(dim_key, {})
                score = dim_data.get("score", 0)
                details = dim_data.get("details", {})

                bar_len = int(score / 5)
                bar = "█" * bar_len + "░" * (20 - bar_len)

                lines.append(f"**{dim_name}** [{score:.0f}/100] `{bar}`")
                lines.append("")

                if details:
                    for k, v in details.items():
                        lines.append(f"- {k}: {v}")
                    lines.append("")

            # 退化信号
            if sig.get("yellow") or sig.get("red"):
                lines.append("**退化信号:**")
                lines.append("")
                for s in sig.get("red", []):
                    lines.append(f"- 🔴 {s}")
                for s in sig.get("yellow", []):
                    lines.append(f"- 🟡 {s}")
                lines.append("")
            else:
                lines.append("**退化信号:** ✅ 无异常")
                lines.append("")

            lines.append("---")
            lines.append("")

    # ---- 退化信号汇总 ----
    lines.append("## 退化信号汇总")
    lines.append("")

    any_signal = False
    for r in results:
        sig = r.get("signals", {})
        reds = sig.get("red", [])
        yellows = sig.get("yellow", [])
        if reds or yellows:
            any_signal = True
            lines.append(f"### {r['ticker']}")
            for s in reds:
                lines.append(f"- 🔴 {s}")
            for s in yellows:
                lines.append(f"- 🟡 {s}")
            lines.append("")

    if not any_signal:
        lines.append("所有标的暂无退化信号。")
        lines.append("")

    # ---- 方法论说明 ----
    lines.append("---")
    lines.append("")
    lines.append("## 方法论")
    lines.append("")
    lines.append("本报告基于六维共振模型，加权评分公式：")
    lines.append("`总分 = 龙头×0.15 + 财报×0.25 + 机构×0.15 + 叙事×0.15 + 现金流×0.15 + 供需×0.15`")
    lines.append("")
    lines.append("数据源: Yahoo Finance + Financial Modeling Prep")
    lines.append("")
    lines.append("⚠️ 本报告仅供研究参考，不构成任何投资建议。")
    lines.append("")

    report = "\n".join(lines)

    # 写入文件
    report_path = os.path.join(output_dir, "era_champion_report.md")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report)

    return report_path


def generate_csv(results: list, output_dir: str = ".") -> str:
    """生成 CSV 排名表"""
    results = sorted(results, key=lambda x: x["composite"]["total"], reverse=True)
    csv_path = os.path.join(output_dir, "era_champion_ranking.csv")

    with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow([
            "Rank", "Ticker", "Grade", "Total",
            "Dominance", "Earnings", "Institutional",
            "Narrative", "Cashflow", "Supply",
            "Yellow_Signals", "Red_Signals"
        ])
        for i, r in enumerate(results, 1):
            c = r["composite"]
            bd = c["breakdown"]
            sig = r.get("signals", {})
            writer.writerow([
                i, r["ticker"], c["grade"], c["total"],
                bd["dominance"]["raw"],
                bd["earnings_breakaway"]["raw"],
                bd["institutional"]["raw"],
                bd["narrative"]["raw"],
                bd["cashflow"]["raw"],
                bd["supply_constraint"]["raw"],
                len(sig.get("yellow", [])),
                len(sig.get("red", [])),
            ])

    return csv_path
