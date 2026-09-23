"""应用配置：从环境变量 / 项目根 .env 读取。"""
from __future__ import annotations

import os

from predict_stock import load_env

# 复用 predict_stock 的 .env 加载器（读取项目根目录 .env 的 TYPESAFE_API_KEY / HITHINK_FINANCE_API_KEY）
load_env()

# --- JWT ---
JWT_SECRET = os.environ.get("JWT_SECRET", "dev-insecure-secret-change-me")
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_MINUTES = int(os.environ.get("JWT_EXPIRE_MINUTES", "60"))

# --- 简单账号（生产请务必通过环境变量覆盖）---
ADMIN_USERNAME = os.environ.get("APP_USERNAME", "admin")
ADMIN_PASSWORD = os.environ.get("APP_PASSWORD", "@dmiN213")
