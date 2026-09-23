"""FastAPI 应用入口。

启动：
    uvicorn webapp.main:app --reload --port 8000

- 前端页面：http://127.0.0.1:8000/
- Swagger 文档：http://127.0.0.1:8000/docs
"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from .auth import router as auth_router
from .predict import router as predict_router

app = FastAPI(
    title="Small Web Framework",
    version="0.1.0",
    description="小型 FastAPI 服务：JWT Bearer 认证 + 受保护的股票预测接口。",
)

app.include_router(auth_router)
app.include_router(predict_router)

# 前端页面
UI_FILE = Path(__file__).resolve().parent / "static" / "index.html"
_ui_html = UI_FILE.read_text(encoding="utf-8")


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def ui():
    return _ui_html


@app.get("/health", tags=["meta"])
def health():
    return {"status": "ok"}

