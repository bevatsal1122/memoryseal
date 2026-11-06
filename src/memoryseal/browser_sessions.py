"""Short-lived, origin-bound browser read sessions; never authorize signed writes."""

import hashlib
import secrets
import time
from datetime import UTC, datetime

from eth_account import Account
from eth_account.messages import encode_defunct
from eth_utils import is_address
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select

from memoryseal.config import settings
from memoryseal.cors import dashboard_origins
from memoryseal.db import SessionLocal
from memoryseal.models import BrowserCredential

router = APIRouter(prefix="/auth", tags=["browser authentication"])
SESSION_SECONDS = 1800


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def origin(request):
    value = request.headers.get("origin", "")
    if value not in dashboard_origins(settings.dashboard_origins):
        raise HTTPException(403, "dashboard origin is not allowed")
    return value


class ChallengeInput(BaseModel):
    address: str = Field(max_length=42)


class LoginInput(BaseModel):
    challenge: str = Field(max_length=128)
    signature: str = Field(max_length=132)


@router.post("/challenge")
def challenge(body: ChallengeInput, request: Request):
    site = origin(request)
    if not is_address(body.address):
        raise HTTPException(422, "invalid wallet address")
    now = int(time.time())
    nonce = secrets.token_urlsafe(32)
    message = (
        f"Sign in to MemorySeal\n\nWebsite: {site}\nWallet: {body.address.lower()}\n"
        f"Gateway audience: {settings.request_audience}\n\n"
        "Allow this browser to read your workspace for 30 minutes.\n"
        "This does not authorize transfers or permission changes.\n"
        f"\nIssued at: {datetime.fromtimestamp(now, UTC).isoformat()}\n"
        f"Sign before: {datetime.fromtimestamp(now + 300, UTC).isoformat()}\nNonce: {nonce}"
    )
    with SessionLocal() as db:
        db.execute(delete(BrowserCredential).where(BrowserCredential.expires_at <= now))
        # Bound unauthenticated challenge storage, including repeated requests for one wallet.
        count = db.scalar(select(func.count()).select_from(BrowserCredential))
        if count >= 10000:
            raise HTTPException(429, "login service busy; try again later")
        db.add(
            BrowserCredential(
                id=digest(nonce),
                address=body.address.lower(),
                origin=site,
                audience=settings.request_audience,
                expires_at=now + 300,
                kind="challenge",
                message=message,
            )
        )
        db.commit()
    return {
        "challenge": nonce,
        "message": message,
        "issued_at": datetime.fromtimestamp(now, UTC).isoformat(),
        "sign_before": datetime.fromtimestamp(now + 300, UTC).isoformat(),
    }


@router.post("/session")
def login(body: LoginInput, request: Request):
    site = origin(request)
    now = int(time.time())
    with SessionLocal() as db:
        row = db.get(BrowserCredential, digest(body.challenge))
        if (
            not row
            or row.kind != "challenge"
            or row.expires_at <= now
            or row.origin != site
            or row.audience != settings.request_audience
        ):
            raise HTTPException(401, "login challenge expired or invalid")
        try:
            signer = Account.recover_message(
                encode_defunct(text=row.message), signature=body.signature
            ).lower()
        except Exception as exc:
            raise HTTPException(401, "invalid login signature") from exc
        if signer != row.address:
            raise HTTPException(401, "wrong login signer")
        consumed = db.execute(delete(BrowserCredential).where(BrowserCredential.id == row.id))
        if consumed.rowcount != 1:
            raise HTTPException(401, "login challenge already used")
        token = secrets.token_urlsafe(32)
        db.add(
            BrowserCredential(
                id=digest(token),
                address=signer,
                origin=site,
                audience=settings.request_audience,
                expires_at=now + SESSION_SECONDS,
                kind="session",
                message="",
            )
        )
        db.commit()
    return {"token": token, "expires_at": now + SESSION_SECONDS}


def session_signer(request):
    site = origin(request)
    token = request.headers.get("authorization", "").removeprefix("Bearer ")
    with SessionLocal() as db:
        row = db.get(BrowserCredential, digest(token))
        if (
            not row
            or row.kind != "session"
            or row.expires_at <= time.time()
            or row.origin != site
            or row.audience != settings.request_audience
        ):
            raise HTTPException(401, "browser session expired or invalid")
        return row.address


@router.post("/logout")
def logout(request: Request):
    signer = session_signer(request)
    token = request.headers.get("authorization", "").removeprefix("Bearer ")
    with SessionLocal() as db:
        db.execute(
            delete(BrowserCredential).where(
                BrowserCredential.id == digest(token), BrowserCredential.address == signer
            )
        )
        db.commit()
    return {"signed_out": True}
