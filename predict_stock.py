#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
使用 jev(TypeSafe System One 模型)+ 同花顺金融数据 API,
根据某只股票过去一个月(约 20 个交易日)的每日涨跌,判断「明天上涨」的概率.

依赖: 仅标准库(urllib / json / datetime),无需安装第三方包.

用法: 
    python predict_stock.py 600519.SH
    python predict_stock.py 贵州茅台
    python predict_stock.py 600519 --days 30 --adjust forward

凭据(二选一即可,优先环境变量): 
  - 环境变量: TYPESAFE_API_KEY、HITHINK_FINANCE_API_KEY
  - 本脚本同目录下的 .env 文件(KEY=value 每行一个,可注释)

注意: 输出仅为概率判断,非投资建议.
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from typing import Optional

# ---------------- 配置 ----------------
TYPESAFE_BASE = "https://api.typesafe.ai"   # jev / TypeSafe
HITHINK_BASE = "https://fuyao.aicubes.cn"   # 同花顺金融数据服务
DEFAULT_MODEL = "jev-latest"
TIMEZONE_HINT = "Asia/Shanghai"


def load_env() -> None:
    """加载脚本同目录下的 .env(仅当环境变量未设置时补齐,不覆盖)."""
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if not os.path.isfile(env_path):
        return
    with open(env_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            k = k.strip().strip('"').strip("'")
            v = v.strip().strip('"').strip("'")
            if k:
                os.environ.setdefault(k, v)


# 浏览器样式的默认请求头: urllib 默认的 "Python-urllib" UA 会被 Cloudflare
# 风控识别为机器人而返回 403 / error code 1010,这里模拟真实浏览器规避.
DEFAULT_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/126.0.0.0 Safari/537.36"),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Connection": "keep-alive",
}


def http_json(url: str, method: str = "GET", headers: Optional[dict] = None,
              payload: Optional[dict] = None, timeout: int = 40) -> dict:
    """通用 HTTP 调用,返回解析后的 JSON 对象."""
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    merged = dict(DEFAULT_HEADERS)
    if headers:
        merged.update(headers)
    for k, v in merged.items():
        req.add_header(k, v)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {e.code} 于 {url}\n{body}") from e


# ---------------- 同花顺: 取数 ----------------
def resolve_thscode(query: str) -> dict:
    """按代码或名称消歧为唯一 thscode(优先 A 股)."""
    params = urllib.parse.urlencode({
        "q": query, "asset_type": "a-share", "limit": 8,
    })
    data = http_json(
        f"{HITHINK_BASE}/api/meta/tickers/search?{params}",
        headers={"X-api-key": _hithink_key()},
    )
    if data.get("code") != 0:
        raise RuntimeError(
            f"标的检索失败 code={data.get('code')} message={data.get('message')}")
    items = data["data"]["item"]
    if not items:
        raise RuntimeError(f"未找到股票: {query}")
    # 精确匹配优先: query 本身就是完整 thscode 或纯代码
    for it in items:
        if it["thscode"] == query or it["ticker"] == query:
            return it
    return items[0]


def get_daily_kline(thscode: str, start_ms: int, end_ms: int,
                    adjust: str = "forward") -> list:
    """获取单只标的日线 K 线(前复权默认)."""
    params = urllib.parse.urlencode({
        "thscode": thscode, "interval": "1d",
        "start": str(start_ms), "end": str(end_ms), "adjust": adjust,
    })
    data = http_json(
        f"{HITHINK_BASE}/api/a-share/prices/historical?{params}",
        headers={"X-api-key": _hithink_key()},
    )
    if data.get("code") != 0:
        raise RuntimeError(
            f"历史 K 线失败 code={data.get('code')} message={data.get('message')}")
    return data["data"]["item"]


# ---------------- jev: 概率判断 ----------------
def jev_predict(state_text: str, model: str = DEFAULT_MODEL) -> dict:
    """调用 jev,返回方向(choice)与上涨概率(noul)两类答案."""
    body = {
        "state": state_text,
        "model": model,
        "questions": {
            "direction": {
                "type": "choice",
                "instructions": "基于给定股票的近期行情,判断下一个交易日收盘时最可能的走向.",
                "criteria": {
                    "up":   "次日收盘价高于当日(最新)收盘价,即上涨",
                    "down": "次日收盘价低于当日(最新)收盘价,即下跌",
                    "flat": "次日收盘价与当日(最新)收盘价基本持平(涨跌幅在 ±0.5% 以内)",
                },
            },
            "rise_prob": {
                "type": "noul",
                "instructions": "下一个交易日该股票收盘价相对最新收盘价上涨的概率",
            },
        },
    }
    data = http_json(
        f"{TYPESAFE_BASE}/v1/systemone", method="POST",
        headers={"Authorization": f"Bearer {_typesafe_key()}"},
        payload=body,
    )
    if "error" in data:
        raise RuntimeError(f"jev 调用失败: {data['error']}")
    return data


# ---------------- 凭据 ----------------
def _typesafe_key() -> str:
    key = os.environ.get("TYPESAFE_API_KEY", "").strip()
    if not key:
        raise RuntimeError(
            "缺少 TYPESAFE_API_KEY(jev/TypeSafe).请设置环境变量或在 .env 中填写.")
    return key


def _hithink_key() -> str:
    key = os.environ.get("HITHINK_FINANCE_API_KEY", "").strip()
    if not key:
        raise RuntimeError(
            "缺少 HITHINK_FINANCE_API_KEY(同花顺).请设置环境变量或在 .env 中填写.")
    return key


# ---------------- 组装 state ----------------
def build_state(rows: list, symbol: str) -> str:
    """把最近一个月的日线行情 + 每日涨跌幅整理成 jev 可读的文本 state."""
    # 计算每日涨跌幅
    bars = []
    for i, r in enumerate(rows):
        prev_close = rows[i - 1]["close_price"] if i > 0 else None
        pct = None
        if prev_close:
            pct = (r["close_price"] / prev_close - 1.0) * 100.0
        d = datetime.fromtimestamp(r["date_ms"] / 1000.0)
        bars.append({
            "date": d.strftime("%Y-%m-%d"),
            "open": r["open_price"],
            "high": r["high_price"],
            "low": r["low_price"],
            "close": r["close_price"],
            "vol": r.get("volume"),
            "pct": pct,
        })

    up_days = sum(1 for b in bars if b["pct"] is not None and b["pct"] > 0)
    down_days = sum(1 for b in bars if b["pct"] is not None and b["pct"] < 0)
    flat_days = sum(1 for b in bars if b["pct"] is not None and b["pct"] == 0)
    if bars:
        first, last = bars[0], bars[-1]
        net = (last["close"] / first["close"] - 1.0) * 100.0
    else:
        net = 0.0

    lines = [
        f"标的: {symbol}",
        f"数据范围: {bars[0]['date']} ~ {bars[-1]['date']},共 {len(bars)} 个交易日(前复权日线).",
        f"期间累计涨跌幅: {net:+.2f}%；上涨日 {up_days} 天、下跌日 {down_days} 天、平盘 {flat_days} 天.",
        "",
        "最近一个月每个交易日的行情(日期 | 收盘价 | 涨跌幅 | 开/高/低 | 成交量): ",
    ]
    for b in bars:
        pct_s = f"{b['pct']:+.2f}%" if b["pct"] is not None else "  --"
        vol_s = f"{b['vol']/1e4:.0f}万" if b["vol"] is not None else "--"
        lines.append(
            f"  {b['date']} | 收盘 {b['close']:.2f} | {pct_s} | "
            f"开{b['open']:.2f}/高{b['high']:.2f}/低{b['low']:.2f} | 量{vol_s}"
        )
    lines.append("")
    lines.append("请据此判断下一个交易日(最新一根 K 线之后的下一个交易日)的走势.")
    return "\n".join(lines)


# ---------------- 主流程 ----------------
def main() -> None:
    # 保证中文输出在 UTF-8 终端(VS Code / Windows Terminal)正常显示
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    load_env()

    args = sys.argv[1:]
    if not args:
        print(__doc__)
        sys.exit(1)

    query = args[0]
    days = 30      # 一个月(日历天)
    adjust = "forward"
    i = 1
    while i < len(args):
        if args[i] == "--days" and i + 1 < len(args):
            days = int(args[i + 1])
            i += 2
        elif args[i] == "--adjust" and i + 1 < len(args):
            adjust = args[i + 1]
            i += 2
        else:
            i += 1

    print(f"[1/4] 消歧标的: {query} ...")
    info = resolve_thscode(query)
    thscode = info["thscode"]
    print(f"      -> {thscode}({info.get('name')},交易所 {info.get('exchange')})")

    end = datetime.now()
    start = end - timedelta(days=days)
    start_ms = int(time.mktime(start.timetuple()) * 1000)
    end_ms = int(time.mktime(end.timetuple()) * 1000)

    print(f"[2/4] 拉取 {start.date()} ~ {end.date()} 的日线({adjust}复权)...")
    rows = get_daily_kline(thscode, start_ms, end_ms, adjust)
    rows.sort(key=lambda r: r["date_ms"])
    if not rows:
        raise RuntimeError(f"该时间段内没有 {thscode} 的日线数据.")
    print(
        f"      -> 共 {len(rows)} 个交易日,最新交易日 {datetime.fromtimestamp(rows[-1]['date_ms']/1000).date()}")

    print(f"[3/4] 组装 state 并调用 jev({DEFAULT_MODEL})...")
    state_text = build_state(rows, f"{thscode} {info.get('name')}")
    resp = jev_predict(state_text)

    ans = resp["answers"]
    direction = ans["direction"]
    rise = ans.get("rise_prob", {})

    print("[4/4] 结果: ")
    print("=" * 60)
    probs = direction.get("probabilities", {})
    up_p = probs.get("up")
    down_p = probs.get("down")
    flat_p = probs.get("flat")
    print(f"模型: {resp.get('model')}")
    print(
        f"下一交易日走向(choice): {direction.get('choice')},置信度 {direction.get('confidence'):.2%}")
    print(f"  上涨概率: {up_p:.2%}" if up_p is not None else "  上涨概率: --")
    print(f"  下跌概率: {down_p:.2%}" if down_p is not None else "  下跌概率: --")
    print(f"  平盘概率: {flat_p:.2%}" if flat_p is not None else "  平盘概率: --")
    if rise:
        print(f"「明天上涨」概率(noul,0~1): {rise.get('noul'):.2f}"
              if rise.get("noul") is not None else "「明天上涨」概率: --")
    print("=" * 60)
    usage = resp.get("usage", {})
    print(
        f"tokens: input={usage.get('input_tokens')} output={usage.get('output_tokens')}")
    print("注: 以上为模型概率判断,仅供参考,不构成投资建议.")


if __name__ == "__main__":
    main()
