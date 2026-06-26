"""
Era Champion Scanner — 数据采集模块
从 Yahoo Finance 和 FMP stable API 获取所有必要数据
（FMP legacy v3/v4 已于 2025-08-31 停用，全部迁移至 /stable/）
"""

import requests
import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime
import time
import sys

from config import FMP_API_KEY, PROXY


def _build_proxies() -> dict | None:
    return {"http": PROXY, "https": PROXY} if PROXY else None


# ============================================================
# FMP stable API 封装
# ============================================================
class FMPClient:
    BASE = "https://financialmodelingprep.com/stable"

    def __init__(self, api_key: str, proxy: str = None):
        self.api_key = api_key
        # 优先用传入的 proxy，没有则读 config
        p = proxy or PROXY
        self.proxies = {"http": p, "https": p} if p else None

    def _get(self, path: str, params: dict = None) -> list | dict | None:
        params = params or {}
        params["apikey"] = self.api_key
        url = f"{self.BASE}/{path}"
        try:
            r = requests.get(url, params=params, timeout=30, proxies=self.proxies)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            print(f"  [FMP] 请求失败 {path}: {e}", file=sys.stderr)
            return None

    # --- 财务报表（stable 端点，period=quarter 免费可用）---
    def income_quarterly(self, ticker: str, limit: int = 8) -> list:
        return self._get("income-statement", {"symbol": ticker, "period": "quarter", "limit": limit}) or []

    def cashflow_quarterly(self, ticker: str, limit: int = 8) -> list:
        return self._get("cash-flow-statement", {"symbol": ticker, "period": "quarter", "limit": limit}) or []

    def balance_quarterly(self, ticker: str, limit: int = 8) -> list:
        return self._get("balance-sheet-statement", {"symbol": ticker, "period": "quarter", "limit": limit}) or []

    # --- EPS/Revenue Surprise（stable/earnings 替代 v3/earnings-surprises）---
    def earnings_surprises(self, ticker: str, limit: int = 8) -> list:
        """
        stable/earnings 返回 epsActual/epsEstimated/revenueActual/revenueEstimated
        只取历史已有 epsActual 的记录（过滤未来预期）
        """
        data = self._get("earnings", {"symbol": ticker, "limit": limit + 4}) or []
        # 过滤掉还没公布的季度（epsActual 为 null）
        return [d for d in data if d.get("epsActual") is not None]

    # --- 分析师目标价 ---
    def price_target_consensus(self, ticker: str) -> dict:
        data = self._get("price-target-consensus", {"symbol": ticker})
        if isinstance(data, list) and data:
            return data[0]
        return data if isinstance(data, dict) else {}

    # --- 分析师评级 ---
    def analyst_grades(self, ticker: str, limit: int = 30) -> list:
        return self._get("grades", {"symbol": ticker, "limit": limit}) or []

    # --- 公司信息 ---
    def profile(self, ticker: str) -> dict:
        data = self._get("profile", {"symbol": ticker})
        if isinstance(data, list) and data:
            return data[0]
        return data if isinstance(data, dict) else {}

    # --- 同行业公司 ---
    def stock_peers(self, ticker: str) -> list:
        """stable/stock-peers 返回同行业股票列表（含市值等）"""
        data = self._get("stock-peers", {"symbol": ticker})
        if isinstance(data, list):
            return [d.get("symbol", "") for d in data if d.get("symbol")]
        return []

    # ratios/key-metrics 季度版需要 premium，用年度代替或跳过
    def ratios_quarterly(self, ticker: str, limit: int = 8) -> list:
        """季度 ratios 需要 premium；降级用年度（limit 较少）"""
        data = self._get("ratios", {"symbol": ticker, "period": "annual", "limit": 3})
        if data and not isinstance(data, list):
            return []
        # 若返回 402/premium 提示则降级静默
        return data or []

    def key_metrics_quarterly(self, ticker: str, limit: int = 8) -> list:
        return []  # 季度版需要 premium，暂不使用


# ============================================================
# 目标价置信度计算（按发布日期衰减）
# ============================================================
def _extract_raw_targets(upgrades_df, cutoff_days: int = 90) -> list:
    """返回近 cutoff_days 内有目标价的原始记录列表，用于报告展示。"""
    if upgrades_df is None or upgrades_df.empty:
        return []
    df = upgrades_df.copy()
    if not isinstance(df.index, pd.DatetimeIndex):
        return []
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC")
    now = pd.Timestamp(datetime.utcnow(), tz="UTC")
    cutoff = now - pd.Timedelta(days=cutoff_days)
    df = df[df.index >= cutoff]
    df = df[df["currentPriceTarget"].notna() & (df["currentPriceTarget"] > 0)]
    if df.empty:
        return []
    records = []
    for ts, row in df.iterrows():
        records.append({
            "date": ts.strftime("%Y-%m-%d"),
            "firm": str(row.get("Firm", "")),
            "grade": str(row.get("ToGrade", "")),
            "action": str(row.get("Action", "")),
            "price_target": float(row["currentPriceTarget"]),
            "prior_target": float(row["priorPriceTarget"]) if pd.notna(row.get("priorPriceTarget")) else None,
        })
    return records


def _extract_recent_targets(upgrades_df, cutoff_days: int = 90) -> dict:
    """
    从 yfinance upgrades_downgrades 提取近 cutoff_days（默认一个季度）内有目标价的记录。
    按时间衰减加权：距今越近权重越高，每过 30 天权重折半（半衰期 30 天）。
    返回 {high, low, wmean, wmedian, count, stale_count, coverage_days}
    """
    if upgrades_df is None or upgrades_df.empty:
        return {}

    df = upgrades_df.copy()
    if not isinstance(df.index, pd.DatetimeIndex):
        return {}
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC")

    now = pd.Timestamp(datetime.utcnow(), tz="UTC")
    cutoff = now - pd.Timedelta(days=cutoff_days)

    df = df[df["currentPriceTarget"].notna() & (df["currentPriceTarget"] > 0)]
    if df.empty:
        return {}

    stale_count = int((df.index < cutoff).sum())
    df = df[df.index >= cutoff]
    if df.empty:
        return {}

    # 时间衰减权重：半衰期 30 天（兼容 pandas 3.x：.days 返回 Index 而非 ndarray）
    days_ago = np.array((now - df.index).days, dtype=float)
    weights = np.exp(-days_ago * np.log(2) / 30)

    targets = df["currentPriceTarget"].values
    w = weights / weights.sum()

    wmean = float(np.dot(w, targets))

    # 加权中位数
    sort_idx = np.argsort(targets)
    cumw = np.cumsum(w[sort_idx])
    wmedian = float(targets[sort_idx[np.searchsorted(cumw, 0.5)]])

    # P10/P90（仍用未加权分位，避免样本太少时失真）
    p10 = float(np.percentile(targets, 10))
    p90 = float(np.percentile(targets, 90))

    return {
        "high": p90,
        "low": p10,
        "wmean": wmean,
        "wmedian": wmedian,
        "count": len(targets),
        "stale_count": stale_count,
        "coverage_days": cutoff_days,
    }


# ============================================================
# Yahoo Finance 封装
# ============================================================
class YahooClient:

    @staticmethod
    def get_stock_data(ticker: str) -> dict:
        try:
            proxies = _build_proxies()
            if proxies:
                session = requests.Session()
                session.proxies.update(proxies)
                stock = yf.Ticker(ticker, session=session)
            else:
                stock = yf.Ticker(ticker)
            info = stock.info or {}
            hist = stock.history(period="1y")

            result = {
                "info": info,
                "market_cap": info.get("marketCap", 0),
                "current_price": info.get("currentPrice") or info.get("regularMarketPrice", 0),
                "sector": info.get("sector", ""),
                "industry": info.get("industry", ""),
                "analyst_count": info.get("numberOfAnalystOpinions", 0),
                "target_mean": info.get("targetMeanPrice", 0),
                "target_high": info.get("targetHighPrice", 0),
                "target_low": info.get("targetLowPrice", 0),
                "recommendation": info.get("recommendationKey", ""),
                "institutional_pct": info.get("heldPercentInstitutions", 0),
                "hist": hist,
            }

            # 带日期的分析师目标价（两步分开，互不影响）
            try:
                ud = stock.upgrades_downgrades
            except Exception:
                ud = None
            try:
                result["price_targets_dated"] = _extract_recent_targets(ud)
            except Exception:
                result["price_targets_dated"] = {}
            try:
                result["price_targets_raw"] = _extract_raw_targets(ud, cutoff_days=90)
            except Exception:
                result["price_targets_raw"] = []


            if not hist.empty and len(hist) > 20:
                result["return_1y"] = (hist["Close"].iloc[-1] / hist["Close"].iloc[0] - 1) * 100
                mid = len(hist) // 2
                vol_recent = hist["Volume"].iloc[mid:].mean()
                vol_early = hist["Volume"].iloc[:mid].mean()
                result["volume_trend"] = (vol_recent / vol_early - 1) * 100 if vol_early > 0 else 0
            else:
                result["return_1y"] = 0
                result["volume_trend"] = 0

            return result

        except Exception as e:
            print(f"  [Yahoo] {ticker} 获取失败: {e}", file=sys.stderr)
            return {
                "info": {}, "market_cap": 0, "current_price": 0,
                "sector": "", "industry": "",
                "analyst_count": 0, "target_mean": 0, "target_high": 0,
                "target_low": 0, "recommendation": "",
                "institutional_pct": 0, "hist": pd.DataFrame(),
                "return_1y": 0, "volume_trend": 0,
            }


# ============================================================
# 综合数据采集
# ============================================================
def fetch_all_data(ticker: str, fmp: FMPClient, themes: list) -> dict:
    print(f"  📡 采集 {ticker} ...")

    yahoo = YahooClient.get_stock_data(ticker)
    time.sleep(0.3)

    income_q = fmp.income_quarterly(ticker)
    cashflow_q = fmp.cashflow_quarterly(ticker)
    balance_q = fmp.balance_quarterly(ticker)
    surprises = fmp.earnings_surprises(ticker)
    pt_consensus = fmp.price_target_consensus(ticker)
    grades = fmp.analyst_grades(ticker)
    profile = fmp.profile(ticker)
    ratios = fmp.ratios_quarterly(ticker)
    key_metrics = fmp.key_metrics_quarterly(ticker)
    peers = fmp.stock_peers(ticker)
    time.sleep(0.5)

    return {
        "ticker": ticker,
        "themes": themes,
        "price_targets_raw": yahoo.pop("price_targets_raw", []),
        "yahoo": yahoo,
        "income_q": income_q,
        "cashflow_q": cashflow_q,
        "balance_q": balance_q,
        "surprises": surprises,
        "pt_consensus": pt_consensus,
        "grades": grades,
        "profile": profile,
        "ratios": ratios,
        "key_metrics": key_metrics,
        "peers": peers,
    }
