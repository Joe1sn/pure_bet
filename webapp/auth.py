"""JWT Bearer 认证：登录换取 token，受保护接口校验 token。

- 密码用 stdlib 的 PBKDF2-SHA256 加盐哈希存储（内存中，进程内一致）。
- Token 用 PyJWT 签发 HS256。
"""
from __future__ import annotations

import hashlib
import hmac
import os
import time
from typing import Dict

import jwt
from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from .config import (ADMIN_PASSWORD, ADMIN_USERNAME, JWT_ALGORITHM,
                     JWT_EXPIRE_MINUTES, JWT_SECRET)

router = APIRouter(prefix="/auth", tags=["auth"])

# ---------------- 密码哈希（stdlib，无第三方依赖） ----------------
_SALT_BYTES = 16
_ITERATIONS = 100_000


def hash_password(password: str, salt: bytes | None = None) -> bytes:
    salt = salt or os.urandom(_SALT_BYTES)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _ITERATIONS)
    return salt + dk  # 结构：salt || dk


def verify_password(password: str, stored: bytes) -> bool:
    salt = stored[:_SALT_BYTES]
    return hmac.compare_digest(hash_password(password, salt), stored)


# 简单用户表：admin / admin123（可经环境变量覆盖）
USERS: Dict[str, bytes] = {ADMIN_USERNAME: hash_password(ADMIN_PASSWORD)}

# ---------------- JWT 签发 / 校验 ----------------
def create_token(username: str) -> str:
    payload = {
        "sub": username,
        "iat": int(time.time()),
        "exp": int(time.time()) + JWT_EXPIRE_MINUTES * 60,
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_token(token: str) -> dict:
    return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])


# ---------------- FastAPI 依赖 ----------------
bearer_scheme = HTTPBearer(auto_error=False)


def get_current_user(
    cred: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> str:
    if cred is None or not cred.credentials:
        raise HTTPException(status_code=401, detail="缺少认证凭据")
    try:
        payload = decode_token(cred.credentials)
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="token 无效或已过期")
    username = payload.get("sub")
    if username not in USERS:
        raise HTTPException(status_code=401, detail="未知用户")
    return username


# ---------------- 接口 ----------------
class LoginRequest(BaseModel):
    username: str
    password: str


@router.post("/login")
def login(body: LoginRequest):
    stored = USERS.get(body.username)
    if stored is None or not verify_password(body.password, stored):
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    return {"access_token": create_token(body.username), "token_type": "bearer"}


@router.get("/me")
def me(username: str = Depends(get_current_user)):
    return {"username": username, "message": "认证成功"}
