"""Verify signed HTTP requests and consume their nonces atomically."""

from fastapi import HTTPException, Request
from sqlalchemy.exc import IntegrityError

from memoryseal.config import settings
from memoryseal.db import SessionLocal
from memoryseal.models import Nonce
from memoryseal.signatures import InvalidSignature, verify_request


async def authenticate(request: Request) -> str:
    headers = request.headers
    try:
        address = headers["x-memoryseal-address"]
        signature = headers["x-memoryseal-signature"]
        timestamp = int(headers["x-memoryseal-timestamp"])
        nonce = headers["x-memoryseal-nonce"]
        target = request.url.path
        if request.url.query:
            target += "?" + request.url.query
        signer = verify_request(
            address=address,
            signature=signature,
            audience=settings.request_audience,
            method=request.method,
            target=target,
            body=await request.body(),
            timestamp=timestamp,
            nonce=nonce,
            max_skew=settings.max_clock_skew_seconds,
        )
    except (KeyError, ValueError, InvalidSignature) as exc:
        raise HTTPException(status_code=401, detail="invalid signed request") from exc

    # Commit independently before processing so even failed requests cannot be replayed.
    with SessionLocal() as session:
        session.add(Nonce(address=signer, nonce=nonce))
        try:
            session.commit()
        except IntegrityError as exc:
            session.rollback()
            raise HTTPException(status_code=401, detail="request nonce already used") from exc
    return signer
