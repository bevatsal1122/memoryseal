"""Wallet-authorized, persistent Sepolia demo worker for the hosted dashboard."""
import asyncio
import json
import os
from pathlib import Path
from typing import Annotated, Literal
from uuid import UUID
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from memoryseal.auth import authenticate

router = APIRouter(prefix="/demo", tags=["demo"])
_tasks: set[asyncio.Task] = set()
_worker = Path(__file__).resolve().parents[3] / "web/scripts/hosted-demo-worker.mjs"


def authorize_operator(signer: str) -> None:
    if os.environ.get("MEMORYSEAL_DEMO_ENABLED", "").lower() != "true":
        raise HTTPException(503, "Hosted demo is not configured. Enable it on Railway first.")
    operators = {value.strip().lower() for value in os.environ.get("MEMORYSEAL_DEMO_OPERATORS", "").split(",") if value.strip()}
    if signer.lower() not in operators:
        raise HTTPException(403, "Connect an approved demo operator wallet.")
    for name in ("MEMORYSEAL_DEMO_PRIVATE_KEY", "MEMORYSEAL_DEMO_RECIPIENT", "MEMORYSEAL_DEMO_DATA_DIR", "MEMORYSEAL_DEMO_FRONTEND_ORIGIN"):
        if not os.environ.get(name):
            raise HTTPException(503, f"Configure {name} on Railway.")
    origin = urlparse(os.environ["MEMORYSEAL_DEMO_FRONTEND_ORIGIN"])
    if origin.scheme != "https" or not origin.netloc or origin.path not in ("", "/") or origin.username or origin.password or origin.query or origin.fragment:
        raise HTTPException(503, "Configure the exact HTTPS demo frontend origin.")
    mount = Path(os.environ.get("RAILWAY_VOLUME_MOUNT_PATH", "/data")).resolve()
    directory = Path(os.environ["MEMORYSEAL_DEMO_DATA_DIR"]).resolve()
    if not directory.is_relative_to(mount):
        raise HTTPException(503, "Demo journal must be on the persistent Railway volume.")
    if not _worker.is_file():
        raise HTTPException(503, "Deploy the hosted demo worker first.")


def worker_env() -> dict[str, str]:
    env = dict(os.environ)
    env["MEMORYSEAL_DEMO_GATEWAY_URL"] = f"http://127.0.0.1:{int(env.get('PORT', '8000'))}"
    return env


class DemoRun(BaseModel):
    mode: Literal["baseline", "protected"]
    runId: UUID


@router.get("/wallet")
async def demo_wallet(signer: Annotated[str, Depends(authenticate)]):
    authorize_operator(signer)
    process = await asyncio.create_subprocess_exec("node", str(_worker), "status", stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL, env=worker_env())
    try:
        stdout, _ = await asyncio.wait_for(process.communicate(), timeout=50)
        messages = [json.loads(line) for line in stdout.splitlines() if line]
        if process.returncode or not messages or messages[-1].get("type") != "wallet":
            raise HTTPException(503, "Demo wallet unavailable. Check the Sepolia RPC and Railway configuration.")
        return messages[-1]["value"]
    except TimeoutError:
        process.kill()
        await process.wait()
        raise HTTPException(504, "Sepolia wallet status timed out.") from None


@router.post("/run")
async def demo_run(data: DemoRun, signer: Annotated[str, Depends(authenticate)]):
    authorize_operator(signer)
    queue: asyncio.Queue = asyncio.Queue()

    async def work():
        process = None
        try:
            process = await asyncio.create_subprocess_exec("node", str(_worker), "run", stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL, env=worker_env())
            process.stdin.write(data.model_dump_json().encode())
            await process.stdin.drain()
            process.stdin.close()
            async with asyncio.timeout(300):
                async for line in process.stdout:
                    await queue.put(line)
                await process.wait()
        except Exception:
            if process and process.returncode is None:
                process.kill()
                await process.wait()
            await queue.put(b'{"type":"error","value":"Demo interrupted. Check wallet transaction status before retrying."}\n')
        finally:
            await queue.put(None)

    # Keep draining the worker after a browser disconnect so transaction journaling completes.
    task = asyncio.create_task(work())
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)

    async def stream():
        while (line := await queue.get()) is not None:
            yield line

    return StreamingResponse(stream(), media_type="application/x-ndjson", headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})
