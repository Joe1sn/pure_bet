"""受保护的股票预测接口：复用 predict_stock 的同花顺取数 + jev 判断。"""
from __future__ import annotations

import time
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query

from predict_stock import (DEFAULT_MODEL, build_state, get_daily_kline,
                           jev_predict, resolve_thscode)

from .auth import get_current_user

router = APIRouter(tags=["predict"])


@router.get("/predict")
def predict(
    q: str = Query(..., description="股票代码或名称，如 600519 / 贵州茅台"),
    days: int = Query(30, ge=5, le=365, description="取数天数（日历天）"),
    adjust: str = Query("forward", pattern="^(none|forward|backward)$", description="复权方式"),
    # 普通 def（非 async）：FastAPI 会自动放到线程池，避免阻塞事件循环
    _user: str = Depends(get_current_user),
):
    try:
        info = resolve_thscode(q)
    except RuntimeError as e:
        raise HTTPException(status_code=404, detail=str(e))

    thscode = info["thscode"]
    end = datetime.now()
    start = end - timedelta(days=days)
    start_ms = int(time.mktime(start.timetuple()) * 1000)
    end_ms = int(time.mktime(end.timetuple()) * 1000)

    try:
        rows = get_daily_kline(thscode, start_ms, end_ms, adjust)
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=f"取数失败：{e}")
    rows.sort(key=lambda r: r["date_ms"])
    if not rows:
        raise HTTPException(status_code=404, detail=f"{thscode} 在该时间段内无日线数据")

    state_text = build_state(rows, f"{thscode} {info.get('name')}")
    try:
        resp = jev_predict(state_text)
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=f"jev 调用失败：{e}")

    ans = resp["answers"]
    direction = ans["direction"]
    probs = direction.get("probabilities", {})
    first_day = datetime.fromtimestamp(rows[0]["date_ms"] / 1000).date()
    last_day = datetime.fromtimestamp(rows[-1]["date_ms"] / 1000).date()

    return {
        "symbol": thscode,
        "name": info.get("name"),
        "data_window": {"start": str(first_day), "end": str(last_day), "trading_days": len(rows)},
        "model": resp.get("model", DEFAULT_MODEL),
        "direction": direction.get("choice"),
        "confidence": direction.get("confidence"),
        "probabilities": {
            "up": probs.get("up"),
            "down": probs.get("down"),
            "flat": probs.get("flat"),
        },
        "rise_prob_noul": ans.get("rise_prob", {}).get("noul"),
        "usage": resp.get("usage"),
        "disclaimer": "非投资建议，仅供研究参考",
    }
