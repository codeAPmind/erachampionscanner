"""
Era Champion Scanner — 六维评分引擎
"""

import numpy as np
from config import THEME_HEAT


def _clamp(val: float, lo: float = 0, hi: float = 100) -> float:
    return max(lo, min(hi, val))


def _safe_div(a, b, default=0):
    try:
        a, b = float(a or 0), float(b or 0)
        return a / b if b != 0 else default
    except (TypeError, ValueError):
        return default


# ── 高增长豁免检测 ─────────────────────────────────────────────
# 条件：收入 YoY >200% + 量价齐升（1年涨幅>30% 且成交量趋势>10%）
# 满足时现金流维度改用"增长质量"替代 FCF，并挂叙事风险黄灯。
def _check_high_growth_exempt(data: dict) -> tuple:
    """
    返回 (is_exempt: bool, rev_growth: float)
    """
    income_q = data.get("income_q", [])
    yahoo = data.get("yahoo", {})

    rev_growth = 0.0
    if len(income_q) >= 5:
        curr = float(income_q[0].get("revenue", 0))
        yago = float(income_q[4].get("revenue", 0))
        rev_growth = _pct_change(curr, yago)

    return_1y    = yahoo.get("return_1y", 0) or 0
    volume_trend = yahoo.get("volume_trend", 0) or 0
    price_vol_rising = return_1y > 30 and volume_trend > 10

    is_exempt = rev_growth > 200 and price_vol_rising
    return is_exempt, rev_growth


def _pct_change(new, old, default=0):
    try:
        new, old = float(new or 0), float(old or 0)
        return ((new - old) / abs(old)) * 100 if old != 0 else default
    except (TypeError, ValueError):
        return default


# ============================================================
# 维度 1：行业龙头地位
# ============================================================
def score_dominance(data: dict, peer_data: dict = None) -> dict:
    """
    评估龙头地位。
    peer_data: {ticker: {"market_cap": ..., "revenue": ...}} 行业内同行数据
    如果没有同行数据，基于自身绝对指标打分。
    """
    details = {}
    scores = []

    # 市值排名（如有同行数据）
    mkt_cap = data["yahoo"].get("market_cap", 0)
    if peer_data and len(peer_data) > 1:
        caps = sorted(peer_data.values(), key=lambda x: x.get("market_cap", 0), reverse=True)
        rank = next((i + 1 for i, p in enumerate(caps) if p.get("ticker") == data["ticker"]), len(caps))
        cap_score = _clamp(100 - (rank - 1) * 20)  # Top1=100, Top2=80, ...
        details["market_cap_rank"] = rank
    else:
        # 无同行数据时，用市值绝对值打分（>500B=100, >100B=80, >50B=60, ...）
        if mkt_cap >= 500e9:
            cap_score = 100
        elif mkt_cap >= 100e9:
            cap_score = 80
        elif mkt_cap >= 50e9:
            cap_score = 60
        elif mkt_cap >= 10e9:
            cap_score = 40
        else:
            cap_score = 20
        details["market_cap"] = f"${mkt_cap / 1e9:.1f}B"
    scores.append(("market_cap_rank", cap_score, 0.30))

    # 收入规模
    income_q = data.get("income_q", [])
    latest_rev = float(income_q[0].get("revenue", 0)) if income_q else 0
    if latest_rev >= 30e9:
        rev_score = 100
    elif latest_rev >= 10e9:
        rev_score = 80
    elif latest_rev >= 5e9:
        rev_score = 60
    elif latest_rev >= 1e9:
        rev_score = 40
    else:
        rev_score = 20
    scores.append(("revenue_scale", rev_score, 0.30))
    details["latest_quarterly_revenue"] = f"${latest_rev / 1e9:.2f}B"

    # 毛利率 vs 行业
    latest_gm = 0
    if income_q:
        rev = float(income_q[0].get("revenue", 0))
        cogs = float(income_q[0].get("costOfRevenue", 0))
        latest_gm = ((rev - cogs) / rev * 100) if rev > 0 else 0
    gm_score = _clamp(latest_gm * 1.2)  # 83%+ = 100
    scores.append(("gross_margin", gm_score, 0.20))
    details["gross_margin"] = f"{latest_gm:.1f}%"

    # 收入增速 vs 行业（简化：用自身 YoY 增速作为份额扩张代理）
    rev_growth = 0
    if len(income_q) >= 5:
        curr = float(income_q[0].get("revenue", 0))
        yago = float(income_q[4].get("revenue", 0))
        rev_growth = _pct_change(curr, yago)
    growth_score = _clamp(min(rev_growth, 200) / 2)  # 200%+ = 100
    scores.append(("revenue_growth_yoy", growth_score, 0.20))
    details["revenue_growth_yoy"] = f"{rev_growth:.1f}%"

    total = sum(s * w for _, s, w in scores)
    return {"score": round(total, 1), "details": details}


# ============================================================
# 维度 2：财报断层
# ============================================================
def score_earnings_breakaway(data: dict) -> dict:
    details = {}
    scores = []

    income_q = data.get("income_q", [])
    surprises = data.get("surprises", [])

    # 收入 YoY 增速
    rev_growth = 0
    if len(income_q) >= 5:
        curr = float(income_q[0].get("revenue", 0))
        yago = float(income_q[4].get("revenue", 0))
        rev_growth = _pct_change(curr, yago)
    rg_score = _clamp(min(rev_growth, 400) / 4)  # 400%+ = 100
    scores.append(("revenue_growth", rg_score, 0.20))
    details["revenue_growth_yoy"] = f"{rev_growth:.1f}%"

    # EPS 超预期幅度（stable/earnings 字段名：epsActual / epsEstimated）
    eps_surprise_pct = 0
    if surprises:
        latest = surprises[0]
        actual = float(latest.get("epsActual") or latest.get("actualEarningResult") or 0)
        estimated = float(latest.get("epsEstimated") or latest.get("estimatedEarning") or 0)
        if estimated != 0:
            eps_surprise_pct = ((actual - estimated) / abs(estimated)) * 100
    surprise_score = _clamp(min(abs(eps_surprise_pct), 50) * 2)  # 50%+ = 100
    if eps_surprise_pct < 0:
        surprise_score = max(0, 30 - abs(eps_surprise_pct))
    scores.append(("eps_surprise", surprise_score, 0.25))
    details["eps_surprise_pct"] = f"{eps_surprise_pct:.1f}%"

    # 毛利率绝对值
    gm = 0
    if income_q:
        rev = float(income_q[0].get("revenue", 0))
        cogs = float(income_q[0].get("costOfRevenue", 0))
        gm = ((rev - cogs) / rev * 100) if rev > 0 else 0
    gm_score = _clamp(gm / 0.8)  # 80%+ = 100
    scores.append(("gross_margin_abs", gm_score, 0.15))
    details["gross_margin"] = f"{gm:.1f}%"

    # 毛利率 YoY 变化
    gm_change = 0
    if len(income_q) >= 5:
        rev_old = float(income_q[4].get("revenue", 0))
        cogs_old = float(income_q[4].get("costOfRevenue", 0))
        gm_old = ((rev_old - cogs_old) / rev_old * 100) if rev_old > 0 else 0
        gm_change = gm - gm_old
    gm_chg_score = _clamp(50 + gm_change * 2)  # ±25pp 映射到 0-100
    scores.append(("gross_margin_change", gm_chg_score, 0.15))
    details["gross_margin_yoy_change"] = f"{gm_change:+.1f}pp"

    # 连续超预期季度数
    consecutive_beats = 0
    for s in surprises[:8]:
        actual = float(s.get("epsActual") or s.get("actualEarningResult") or 0)
        estimated = float(s.get("epsEstimated") or s.get("estimatedEarning") or 0)
        if actual > estimated:
            consecutive_beats += 1
        else:
            break
    beat_score = _clamp(consecutive_beats / 4 * 100)  # 4 季连续 = 满分
    scores.append(("consecutive_beats", beat_score, 0.25))
    details["consecutive_beats"] = consecutive_beats

    total = sum(s * w for _, s, w in scores)
    return {"score": round(total, 1), "details": details}


# ============================================================
# 维度 3：机构共识力度
# ============================================================
def score_institutional(data: dict) -> dict:
    details = {}
    scores = []

    yahoo = data.get("yahoo", {})
    grades = data.get("grades", [])
    pt = data.get("pt_consensus", {})

    # 分析师覆盖数量
    analyst_count = yahoo.get("analyst_count", 0)
    ac_score = _clamp(analyst_count / 30 * 100)  # 30+ = 满分
    scores.append(("analyst_count", ac_score, 0.15))
    details["analyst_count"] = analyst_count

    # 买入评级占比
    buy_pct = 0
    if grades:
        recent_90d = grades[:20]  # 取最近 20 条
        buys = sum(1 for g in recent_90d if g.get("newGrade", "").lower() in
                   ["buy", "strong buy", "outperform", "overweight", "positive"])
        buy_pct = (buys / len(recent_90d) * 100) if recent_90d else 0
    buy_score = _clamp(buy_pct / 0.8)  # 80%+ = 满分
    scores.append(("buy_rating_pct", buy_score, 0.20))
    details["buy_rating_pct"] = f"{buy_pct:.0f}%"

    # 目标价 vs 现价上行空间（优先近期分析师数据）
    current_price = yahoo.get("current_price", 0)
    ptd = yahoo.get("price_targets_dated", {})
    # 优先级：近期加权 median > FMP consensus > Yahoo mean
    target_consensus = float(
        ptd.get("wmedian") or
        pt.get("targetConsensus") or pt.get("targetMedian") or
        yahoo.get("target_mean") or 0
    )
    upside = _pct_change(target_consensus, current_price) if current_price > 0 else 0
    upside_score = _clamp(upside / 0.3)  # 30%+ = 满分
    scores.append(("target_upside", upside_score, 0.25))
    src = ptd.get("coverage_label", f"{ptd.get('count','?')}家") if ptd.get("wmedian") else "FMP"
    details["target_consensus"] = f"${target_consensus:.0f}({src})"
    details["current_price"] = f"${current_price:.0f}"
    details["upside_pct"] = f"{upside:.1f}%"

    # 目标价近期上调次数
    upgrades_90d = 0
    if grades:
        for g in grades[:30]:
            action = g.get("action", "").lower()
            if action in ["upgrade", "reiterated"] or "raise" in action:
                upgrades_90d += 1
    upgrade_score = _clamp(upgrades_90d / 10 * 100)  # 10次+ = 满分
    scores.append(("recent_upgrades", upgrade_score, 0.20))
    details["recent_upgrades"] = upgrades_90d

    # 机构持仓占比
    inst_pct = yahoo.get("institutional_pct", 0) or 0
    inst_score = _clamp(inst_pct * 100 / 0.8)  # 80%+ = 满分
    scores.append(("institutional_pct", inst_score, 0.20))
    details["institutional_pct"] = f"{inst_pct * 100:.1f}%"

    total = sum(s * w for _, s, w in scores)
    return {"score": round(total, 1), "details": details}


# ============================================================
# 维度 4：时代叙事
# ============================================================
def score_narrative(data: dict) -> dict:
    details = {}
    scores = []

    themes = data.get("themes", [])
    yahoo = data.get("yahoo", {})

    # 主题热度匹配
    if themes:
        max_heat = max(THEME_HEAT.get(t, 1) for t in themes)
        avg_heat = np.mean([THEME_HEAT.get(t, 1) for t in themes])
    else:
        max_heat, avg_heat = 1, 1
    theme_score = _clamp(max_heat * 10)  # 10/10 = 满分
    scores.append(("theme_heat", theme_score, 0.40))
    details["themes"] = themes
    details["max_theme_heat"] = f"{max_heat}/10"

    # 近 1 年股价涨幅
    ret_1y = yahoo.get("return_1y", 0)
    # 100%+ = 80分，200%+ = 90分，300%+ = 满分（避免给纯投机股过高分）
    if ret_1y >= 300:
        ret_score = 100
    elif ret_1y >= 100:
        ret_score = 70 + (ret_1y - 100) / 200 * 30
    elif ret_1y >= 50:
        ret_score = 50 + (ret_1y - 50) / 50 * 20
    elif ret_1y >= 0:
        ret_score = ret_1y
    else:
        ret_score = max(0, 20 + ret_1y / 5)  # 负收益扣分
    scores.append(("return_1y", _clamp(ret_score), 0.30))
    details["return_1y"] = f"{ret_1y:.1f}%"

    # 成交量趋势
    vol_trend = yahoo.get("volume_trend", 0)
    if vol_trend >= 100:
        vol_score = 100
    elif vol_trend >= 50:
        vol_score = 70 + (vol_trend - 50) / 50 * 30
    elif vol_trend >= 0:
        vol_score = 40 + vol_trend / 50 * 30
    else:
        vol_score = max(0, 40 + vol_trend / 100 * 40)
    scores.append(("volume_trend", _clamp(vol_score), 0.30))
    details["volume_trend_6m"] = f"{vol_trend:+.1f}%"

    total = sum(s * w for _, s, w in scores)
    return {"score": round(total, 1), "details": details}


# ============================================================
# 维度 5：现金流验证
# ============================================================
def score_cashflow(data: dict) -> dict:
    details = {}
    scores = []

    cf_q = data.get("cashflow_q", [])
    income_q = data.get("income_q", [])

    if not cf_q:
        return {"score": 0, "details": {"error": "无现金流数据"}}

    latest_cf = cf_q[0]
    fcf = float(latest_cf.get("freeCashFlow", 0))
    ocf = float(latest_cf.get("operatingCashFlow", 0))
    net_income = float(income_q[0].get("netIncome", 0)) if income_q else 0
    revenue = float(income_q[0].get("revenue", 0)) if income_q else 0

    # ── 高增长豁免模式 ──────────────────────────────────────────
    is_exempt, rev_growth = _check_high_growth_exempt(data)
    if is_exempt:
        # 用"增长质量"替代 FCF，共 4 个子项
        # 1. 收入增速动能（>200%=满分）
        growth_score = _clamp(min(rev_growth, 500) / 5)
        scores.append(("revenue_momentum", growth_score, 0.35))
        details["revenue_growth_yoy"] = f"{rev_growth:.1f}%"

        # 2. 毛利率（高毛利=未来 FCF 潜力）
        gm = 0
        if income_q:
            rev = float(income_q[0].get("revenue", 0))
            cogs = float(income_q[0].get("costOfRevenue", 0))
            gm = ((rev - cogs) / rev * 100) if rev > 0 else 0
        gm_score = _clamp(gm / 0.7 * 100)  # 70%+ 毛利率 = 满分
        scores.append(("gross_margin_quality", gm_score, 0.30))
        details["gross_margin"] = f"{gm:.1f}%"

        # 3. 收入加速度（最近一季增速 vs 上一季）
        accel_score = 50
        if len(income_q) >= 9:
            g_curr = _pct_change(float(income_q[0].get("revenue", 0)),
                                 float(income_q[4].get("revenue", 0)))
            g_prev = _pct_change(float(income_q[1].get("revenue", 0)),
                                 float(income_q[5].get("revenue", 0)))
            if g_curr > g_prev:
                accel_score = _clamp(50 + (g_curr - g_prev) / 2)
            else:
                accel_score = max(20, 50 - (g_prev - g_curr) / 2)
        scores.append(("growth_acceleration", accel_score, 0.20))

        # 4. 现金储备可持续性（现金 / 季度净亏损 = 季度数）
        cash = 0
        burn = abs(min(net_income, 0))  # 亏损额作为 burn rate 代理
        if cf_q:
            balance_q = data.get("balance_q", [])
            cash = float(balance_q[0].get("cashAndCashEquivalents", 0)) if balance_q else 0
        runway_qtrs = _safe_div(cash, burn) if burn > 0 else 8  # 默认8季
        runway_score = _clamp(min(runway_qtrs, 8) / 8 * 100)
        scores.append(("cash_runway", runway_score, 0.15))
        details["cash_runway_quarters"] = f"{runway_qtrs:.1f}季" if burn > 0 else "盈利/无需评估"
        details["fcf"] = f"${fcf / 1e9:.2f}B（豁免模式）"
        details["exempt_mode"] = "⚡ 高增长豁免：收入增速>200%+量价齐升，用增长质量替代FCF"

        total = sum(s * w for _, s, w in scores)
        return {"score": round(total, 1), "details": details, "high_growth_exempt": True}

    # ── 常规 FCF 模式 ───────────────────────────────────────────
    fcf_positive = fcf > 0
    fcf_pos_score = 100 if fcf_positive else 0
    scores.append(("fcf_positive", fcf_pos_score, 0.30))
    details["fcf"] = f"${fcf / 1e9:.2f}B"

    fcf_ni_ratio = _safe_div(fcf, net_income) if net_income > 0 else 0
    fcf_ni_score = _clamp(fcf_ni_ratio / 0.7 * 100) if fcf_ni_ratio > 0 else 0
    scores.append(("fcf_to_net_income", fcf_ni_score, 0.30))
    details["fcf_to_net_income"] = f"{fcf_ni_ratio:.2f}"

    fcf_growth = 0
    if len(cf_q) >= 5:
        fcf_old = float(cf_q[4].get("freeCashFlow", 0))
        fcf_growth = _pct_change(fcf, fcf_old)
    fcf_g_score = _clamp(50 + min(fcf_growth, 200) / 4) if fcf_growth > 0 else max(0, 30 + fcf_growth / 10)
    scores.append(("fcf_growth", fcf_g_score, 0.20))
    details["fcf_growth_yoy"] = f"{fcf_growth:.1f}%"

    ocf_rev = _safe_div(ocf, revenue) * 100
    ocf_score = _clamp(ocf_rev / 0.2)
    scores.append(("ocf_to_revenue", ocf_score, 0.20))
    details["ocf_to_revenue"] = f"{ocf_rev:.1f}%"

    total = sum(s * w for _, s, w in scores)

    if not fcf_positive:
        total = min(total, 30)
        details["cap_warning"] = "FCF为负，此维度上限30"

    return {"score": round(total, 1), "details": details}


# ============================================================
# 维度 6：供需约束验证
# ============================================================
def score_supply_constraint(data: dict) -> dict:
    details = {}
    scores = []

    income_q = data.get("income_q", [])
    balance_q = data.get("balance_q", [])
    cf_q = data.get("cashflow_q", [])
    ratios = data.get("ratios", [])

    # 库存周转天数趋势
    dio_score = 50  # 默认中性
    if len(ratios) >= 5:
        dio_curr = float(ratios[0].get("daysOfInventoryOutstanding", 0) or 0)
        dio_prev = float(ratios[4].get("daysOfInventoryOutstanding", 0) or 0)
        if dio_prev > 0:
            dio_change = _pct_change(dio_curr, dio_prev)
            # 下降 = 好信号
            dio_score = _clamp(70 - dio_change)  # 下降越多分越高
            details["inventory_days_change"] = f"{dio_change:+.1f}%"
        details["inventory_days_current"] = f"{dio_curr:.0f}"
    scores.append(("inventory_turnover", dio_score, 0.30))

    # 应收账款周转天数趋势
    dso_score = 50
    if len(ratios) >= 5:
        dso_curr = float(ratios[0].get("daysOfSalesOutstanding", 0) or 0)
        dso_prev = float(ratios[4].get("daysOfSalesOutstanding", 0) or 0)
        if dso_prev > 0:
            dso_change = _pct_change(dso_curr, dso_prev)
            dso_score = _clamp(70 - dso_change)
            details["receivable_days_change"] = f"{dso_change:+.1f}%"
        details["receivable_days_current"] = f"{dso_curr:.0f}"
    scores.append(("receivable_turnover", dso_score, 0.20))

    # 资本支出 / 收入比率（上升 = 扩产信号）
    capex_score = 50
    if cf_q and income_q:
        capex = abs(float(cf_q[0].get("capitalExpenditure", 0)))
        rev = float(income_q[0].get("revenue", 0))
        capex_ratio = _safe_div(capex, rev) * 100
        # 资本密集型行业 capex/rev 高是正常的
        if capex_ratio >= 20:
            capex_score = 90
        elif capex_ratio >= 10:
            capex_score = 70
        elif capex_ratio >= 5:
            capex_score = 50
        else:
            capex_score = 30
        details["capex_to_revenue"] = f"{capex_ratio:.1f}%"

        # 资本支出增速
        if len(cf_q) >= 5:
            capex_old = abs(float(cf_q[4].get("capitalExpenditure", 0)))
            capex_growth = _pct_change(capex, capex_old)
            details["capex_growth_yoy"] = f"{capex_growth:.1f}%"
            if capex_growth > 50:
                capex_score = min(100, capex_score + 20)
    scores.append(("capex_intensity", capex_score, 0.25))

    # 预付款 / 合同负债增长（用 deferred revenue 作代理）
    deferred_score = 50
    if len(balance_q) >= 5:
        dr_curr = float(balance_q[0].get("deferredRevenue", 0) or 0)
        dr_prev = float(balance_q[4].get("deferredRevenue", 0) or 0)
        if dr_prev > 0:
            dr_growth = _pct_change(dr_curr, dr_prev)
            deferred_score = _clamp(50 + dr_growth / 2)
            details["deferred_revenue_growth"] = f"{dr_growth:+.1f}%"
        details["deferred_revenue"] = f"${dr_curr / 1e9:.2f}B"
    scores.append(("deferred_revenue", deferred_score, 0.25))

    total = sum(s * w for _, s, w in scores)
    return {"score": round(total, 1), "details": details}


# ============================================================
# 退化信号检测
# ============================================================
def detect_degradation_signals(data: dict) -> dict:
    """
    检测退化信号，返回 {yellow: [...], red: [...]}
    """
    yellow = []
    red = []

    # ── 高增长豁免标注（叙事驱动风险）──────────────────────────
    is_exempt, rev_growth = _check_high_growth_exempt(data)
    if is_exempt:
        yellow.append(
            f"⚡ 叙事驱动风险：现金流维度已豁免（收入增速 {rev_growth:.0f}%+量价齐升），"
            f"盈利拐点未出现前估值高度依赖叙事，注意回撤风险"
        )

    income_q = data.get("income_q", [])
    surprises = data.get("surprises", [])

    # --- 收入增速二阶导 ---
    if len(income_q) >= 9:
        # 最近一季 YoY
        g1 = _pct_change(
            float(income_q[0].get("revenue", 0)),
            float(income_q[4].get("revenue", 0))
        )
        # 上一季 YoY
        g2 = _pct_change(
            float(income_q[1].get("revenue", 0)),
            float(income_q[5].get("revenue", 0))
        )
        if g1 > 0 and g2 > 0 and g1 < g2:
            yellow.append(f"收入增速减速: {g2:.0f}% → {g1:.0f}%（二阶导为负）")
        if g1 > 0 and g1 < 30 and g2 > 100:
            red.append(f"收入增速大幅放缓: {g2:.0f}% → {g1:.0f}%")

    # --- 毛利率环比变化 ---
    if len(income_q) >= 2:
        def _gm(q):
            r = float(q.get("revenue", 0))
            c = float(q.get("costOfRevenue", 0))
            return (r - c) / r * 100 if r > 0 else 0

        gm_curr = _gm(income_q[0])
        gm_prev = _gm(income_q[1])
        gm_delta = gm_curr - gm_prev
        if gm_delta < -2:
            yellow.append(f"毛利率环比下降 {gm_delta:.1f}pp ({gm_prev:.1f}% → {gm_curr:.1f}%)")
        if len(income_q) >= 3:
            gm_prev2 = _gm(income_q[2])
            if gm_curr < gm_prev < gm_prev2:
                red.append(f"毛利率连续 2 季下降 ({gm_prev2:.1f}% → {gm_prev:.1f}% → {gm_curr:.1f}%)")

    # --- 目标价离散度（用近 180 天数据的 P10/P90，过滤离群值和过期目标价）---
    yahoo = data.get("yahoo", {})
    pt = data.get("pt_consensus", {})
    ptd = yahoo.get("price_targets_dated", {})

    if ptd.get("count", 0) >= 3:
        target_high = ptd["high"]
        target_low = ptd["low"]
        target_mean = ptd["wmedian"]
        src_note = ptd.get("coverage_label", f"{ptd['count']}家")
    else:
        # 数据不足回退 FMP
        target_high = float(pt.get("targetHigh") or yahoo.get("target_high") or 0)
        target_low = float(pt.get("targetLow") or yahoo.get("target_low") or 0)
        target_mean = float(pt.get("targetConsensus") or pt.get("targetMedian") or yahoo.get("target_mean") or 0)
        src_note = "FMP"

    if target_mean > 0 and target_high > 0 and target_low > 0:
        spread = (target_high - target_low) / target_mean
        if spread > 0.8:  # P10/P90 下 80% 才是真正分歧大
            yellow.append(f"分析师目标价分歧大({src_note}): ${target_low:.0f}–${target_high:.0f} (P10/P90 spread {spread:.0%})")

    # --- EPS 不及预期 ---
    if surprises and len(surprises) >= 2:
        actual = float(surprises[0].get("epsActual") or surprises[0].get("actualEarningResult") or 0)
        estimated = float(surprises[0].get("epsEstimated") or surprises[0].get("estimatedEarning") or 0)
        if actual < estimated:
            red.append(f"最新季度 EPS 不及预期: 实际 ${actual:.2f} vs 预期 ${estimated:.2f}")

    return {"yellow": yellow, "red": red}


# ============================================================
# 综合评分
# ============================================================
def compute_composite(dimension_scores: dict, weights: dict) -> dict:
    """
    计算加权总分并分级
    """
    total = 0
    breakdown = {}
    for dim, weight in weights.items():
        s = dimension_scores.get(dim, {}).get("score", 0)
        weighted = s * weight
        total += weighted
        breakdown[dim] = {"raw": s, "weight": weight, "weighted": round(weighted, 1)}

    total = round(total, 1)

    if total >= 85:
        grade = "S"
    elif total >= 70:
        grade = "A"
    elif total >= 55:
        grade = "B"
    else:
        grade = "C"

    return {"total": total, "grade": grade, "breakdown": breakdown}
