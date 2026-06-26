#!/usr/bin/env python3
"""
时代主角扫描器（Era Champion Scanner）
======================================
基于六维共振模型扫描市场，寻找正处于结构性变革中心的时代主角。

使用方法:
    python scanner.py                       # 扫描默认候选池
    python scanner.py --tickers NVDA MU TSLA  # 指定股票
    python scanner.py --fmp-key YOUR_KEY     # 指定 FMP API Key
    python scanner.py --output ./reports     # 指定输出目录

数据源: Yahoo Finance (免费) + FMP (会员)
"""

import argparse
import os
import sys
import json
from datetime import datetime

from config import FMP_API_KEY, WATCHLIST, DIMENSION_WEIGHTS, PROXY
from data_fetcher import FMPClient, fetch_all_data
from scoring import (
    score_dominance,
    score_earnings_breakaway,
    score_institutional,
    score_narrative,
    score_cashflow,
    score_supply_constraint,
    detect_degradation_signals,
    compute_composite,
)
from report import generate_report, generate_csv
from feishu_notifier import send_text, build_summary_message


def scan_single(ticker: str, themes: list, fmp: FMPClient) -> dict:
    """扫描单只股票"""
    # 1. 采集数据
    data = fetch_all_data(ticker, fmp, themes)

    # 2. 六维评分
    dimensions = {
        "dominance": score_dominance(data),
        "earnings_breakaway": score_earnings_breakaway(data),
        "institutional": score_institutional(data),
        "narrative": score_narrative(data),
        "cashflow": score_cashflow(data),
        "supply_constraint": score_supply_constraint(data),
    }

    # 3. 综合评分
    composite = compute_composite(dimensions, DIMENSION_WEIGHTS)

    # 4. 退化信号
    signals = detect_degradation_signals(data)

    return {
        "ticker": ticker,
        "themes": themes,
        "dimensions": dimensions,
        "composite": composite,
        "signals": signals,
        "current_price": data.get("yahoo", {}).get("current_price", 0),
        "price_targets_raw": data.get("price_targets_raw", []),
    }


def main():
    parser = argparse.ArgumentParser(description="时代主角扫描器 Era Champion Scanner")
    parser.add_argument("--tickers", nargs="+", help="指定股票代码列表（不指定则使用 config.py 中的 WATCHLIST）")
    parser.add_argument("--fmp-key", default=None, help="FMP API Key（不指定则使用 config.py 中的配置）")
    parser.add_argument("--output", default="./output", help="输出目录（默认 ./output）")
    parser.add_argument("--json", action="store_true", help="同时输出 JSON 格式的详细数据")
    parser.add_argument("--no-feishu", action="store_true", help="不发送飞书通知")
    args = parser.parse_args()

    # API Key
    api_key = args.fmp_key or FMP_API_KEY
    if api_key == "YOUR_FMP_API_KEY_HERE":
        print("⚠️  请在 config.py 中配置 FMP_API_KEY，或使用 --fmp-key 参数传入")
        print("   获取 API Key: https://financialmodelingprep.com/developer/docs/")
        sys.exit(1)

    fmp = FMPClient(api_key, proxy=PROXY)

    # 候选池
    if args.tickers:
        scan_list = {t: WATCHLIST.get(t, ["未分类"]) for t in args.tickers}
    else:
        scan_list = WATCHLIST

    # 输出目录
    os.makedirs(args.output, exist_ok=True)

    # 开始扫描
    print("=" * 60)
    print("🔭 时代主角扫描器 Era Champion Scanner")
    print(f"📅 {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"📋 待扫描: {len(scan_list)} 只股票")
    print("=" * 60)
    print()

    results = []
    for i, (ticker, themes) in enumerate(scan_list.items(), 1):
        print(f"[{i}/{len(scan_list)}] 扫描 {ticker} ({', '.join(themes)})")
        try:
            result = scan_single(ticker, themes, fmp)
            grade = result["composite"]["grade"]
            total = result["composite"]["total"]
            emoji = {"S": "🏆", "A": "⭐", "B": "📊", "C": "📉"}.get(grade, "")
            print(f"  → {emoji} {grade} 级 | 总分: {total:.1f}")

            # 打印退化信号
            sig = result["signals"]
            for s in sig.get("red", []):
                print(f"  🔴 {s}")
            for s in sig.get("yellow", []):
                print(f"  🟡 {s}")

            results.append(result)
        except Exception as e:
            print(f"  ❌ 扫描失败: {e}")
        print()

    if not results:
        print("没有有效结果，退出。")
        sys.exit(1)

    # 排序
    results.sort(key=lambda x: x["composite"]["total"], reverse=True)

    # 生成报告
    print("=" * 60)
    print("📝 生成报告...")

    report_path = generate_report(results, args.output)
    csv_path = generate_csv(results, args.output)

    print(f"  ✅ Markdown 报告: {report_path}")
    print(f"  ✅ CSV 排名表:    {csv_path}")

    if args.json:
        json_path = os.path.join(args.output, "era_champion_data.json")
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2, default=str)
        print(f"  ✅ JSON 详细数据: {json_path}")

    # 飞书通知
    if not args.no_feishu:
        print("  📨 发送飞书通知...")
        msg = build_summary_message(results, report_path)
        ok = send_text(msg)
        if ok:
            print("  ✅ 飞书通知已发送")
        else:
            print("  ⚠️  飞书通知发送失败（不影响本地报告）")

    # 打印摘要
    print()
    print("=" * 60)
    print("📊 扫描结果摘要")
    print("=" * 60)
    print()
    print(f"{'排名':<4} {'股票':<8} {'等级':<4} {'总分':<8} {'主题'}")
    print("-" * 60)

    for i, r in enumerate(results[:15], 1):
        c = r["composite"]
        emoji = {"S": "🏆", "A": "⭐", "B": "📊", "C": "📉"}.get(c["grade"], "")
        themes_str = ", ".join(r.get("themes", []))
        print(f"{i:<4} {r['ticker']:<8} {emoji}{c['grade']:<3} {c['total']:<8.1f} {themes_str}")

    s_count = sum(1 for r in results if r["composite"]["grade"] == "S")
    a_count = sum(1 for r in results if r["composite"]["grade"] == "A")
    print()
    print(f"🏆 S级: {s_count} 只 | ⭐ A级: {a_count} 只 | 共 {len(results)} 只")
    print()
    print("⚠️  本扫描仅供研究参考，不构成投资建议。")


if __name__ == "__main__":
    main()
