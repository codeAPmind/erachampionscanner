"""
Era Champion Scanner — 飞书通知模块
"""

import json
import os
import sys
import requests

# 从环境变量读取，也可在 config.py 里写死
FEISHU_WEBHOOK = os.environ.get("FEISHU_BOT_WEBHOOK", "")

MAX_MSG_CHARS = 12000  # 飞书单条文本上限约 30KB，保守截断


def send_text(text: str, webhook: str = FEISHU_WEBHOOK) -> bool:
    """发送纯文本消息到飞书群机器人"""
    if len(text) > MAX_MSG_CHARS:
        text = text[:MAX_MSG_CHARS] + "\n\n…（内容过长已截断，完整报告见 output/ 目录）"

    payload = {"msg_type": "text", "content": {"text": text}}
    try:
        resp = requests.post(
            webhook,
            headers={"Content-Type": "application/json; charset=utf-8"},
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            timeout=15,
        )
        resp.raise_for_status()
        result = resp.json()
        if result.get("code", 0) != 0:
            print(f"  [飞书] 发送失败: {result}", file=sys.stderr)
            return False
        return True
    except Exception as e:
        print(f"  [飞书] 请求异常: {e}", file=sys.stderr)
        return False


def build_summary_message(results: list, report_path: str) -> str:
    """把扫描结果构建成飞书消息文本"""
    from datetime import datetime

    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = [
        f"🔭 时代主角扫描报告  {now}",
        f"扫描标的: {len(results)} 只",
        "=" * 40,
    ]

    # 排名表（前15）
    lines.append(f"{'排名':<4} {'股票':<8} {'级':<3} {'分':<6} 主题")
    lines.append("-" * 40)
    grade_emoji = {"S": "🏆", "A": "⭐", "B": "📊", "C": "📉"}
    for i, r in enumerate(results[:15], 1):
        c = r["composite"]
        em = grade_emoji.get(c["grade"], "")
        themes = ", ".join(r.get("themes", []))
        lines.append(f"{i:<4} {r['ticker']:<8} {em}{c['grade']:<2} {c['total']:<6.1f} {themes}")

    # 等级统计
    s_cnt = sum(1 for r in results if r["composite"]["grade"] == "S")
    a_cnt = sum(1 for r in results if r["composite"]["grade"] == "A")
    lines.append("")
    lines.append(f"🏆 S级 {s_cnt} 只  ⭐ A级 {a_cnt} 只  共 {len(results)} 只")

    # 退化信号汇总
    has_signal = False
    sig_lines = ["", "【退化信号】"]
    for r in results:
        sig = r.get("signals", {})
        reds = sig.get("red", [])
        yellows = sig.get("yellow", [])
        if reds or yellows:
            has_signal = True
            sig_lines.append(f"{r['ticker']}:")
            for s in reds:
                sig_lines.append(f"  🔴 {s}")
            for s in yellows:
                sig_lines.append(f"  🟡 {s}")
    if has_signal:
        lines.extend(sig_lines)

    lines.append("")
    lines.append(f"📄 完整报告: {report_path}")
    lines.append("⚠️ 仅供研究参考，不构成投资建议。")

    return "\n".join(lines)
