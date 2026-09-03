"""teruo on a single screen — the same agent, reached through a browser.

The point of this entry point is that it is only an entry point. The
calculation layer (tools.py), the state (store.py), the judgment layer
(agents.py) and the wording (i18n.py) are untouched: what changes is where a
typed line comes from and where a fact is printed.

Two things make that possible:

  * ``main.build_agent`` builds the same agent the CLI builds, so onboarding
    and everyday operation behave identically here.
  * ``tools.set_output_sink`` redirects the facts Python prints (principle 3)
    into this request's event stream instead of stdout. They stay verbatim —
    the browser shows the exact text the tools produced, tagged as such, so
    the numbers on screen are still Python's and not the model's paraphrase.

The screen shows one conversation. While teruo works, the roles it calls
(record keeper, observer) and the tools they run appear inline, so the
agents-as-tools structure is visible rather than asserted.

Run with:  python web.py        (PORT and HOST are honoured; default 0.0.0.0:5000)
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import sys
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import tools
from fastapi import FastAPI, Form, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from i18n import get_language, t, tool_label
from main import build_agent, needs_counseling, resolve_language, validate_environment

PAGE = Path(__file__).parent / "web" / "index.html"

# One shop, one conversation — the CLI's model, kept. The lock is what makes
# that safe: Strands refuses concurrent invocations on one Agent, and two
# browser tabs would otherwise race into that error.
_agent: Any = None
_counseling = False
_lock = asyncio.Lock()
_uploads = Path(tempfile.mkdtemp(prefix="teruo-uploads-"))


@asynccontextmanager
async def lifespan(_app: FastAPI):
    global _agent, _counseling
    resolve_language(sys.argv[1:])
    validate_environment()
    _counseling = "--setup" in sys.argv[1:] or needs_counseling()
    _agent = build_agent(_counseling)
    yield
    shutil.rmtree(_uploads, ignore_errors=True)


app = FastAPI(lifespan=lifespan)


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


@app.get("/")
def page() -> FileResponse:
    return FileResponse(PAGE)


@app.get("/api/config")
def config() -> dict:
    """What the page needs to render itself in the owner's language."""
    return {
        "language": get_language(),
        "counseling": _counseling,
        "strings": {
            key: t(key)
            for key in (
                "web_tagline",
                "web_placeholder",
                "web_send",
                "web_fact_badge",
                "web_working",
                "web_drop_hint",
                "web_busy",
                "web_counseling_banner",
                "web_greeting",
                "web_disconnected",
            )
        },
    }


async def _save_uploads(files: list[UploadFile]) -> list[tuple[str, Path]]:
    saved: list[tuple[str, Path]] = []
    for index, upload in enumerate(files):
        if not upload.filename:
            continue
        # Never trust the browser's path. Keep only the suffix, which is what
        # attachments.py classifies on, and name the file ourselves.
        suffix = Path(upload.filename).suffix
        destination = _uploads / f"upload-{index}{suffix}"
        destination.write_bytes(await upload.read())
        saved.append((Path(upload.filename).name, destination))
    return saved


async def _turn(prompt: Any, notes: list[str]):
    """One turn of the conversation, as a stream of screen events.

    Facts arrive on a queue because they are produced on the worker thread
    Strands runs a sync tool on, while the model's text arrives on this
    coroutine. Merging both into one queue keeps them in the order they
    actually happened, which is what makes the screen readable.
    """
    for note in notes:
        yield _sse({"type": "note", "text": note})
    if prompt is None:
        yield _sse({"type": "done"})
        return
    if _lock.locked():
        yield _sse({"type": "note", "text": t("web_busy")})
        yield _sse({"type": "done"})
        return

    async with _lock:
        queue: asyncio.Queue = asyncio.Queue()
        loop = asyncio.get_running_loop()

        def sink(fact: str) -> None:
            loop.call_soon_threadsafe(queue.put_nowait, {"type": "fact", "text": fact})

        token = tools.set_output_sink(sink)

        async def drive() -> None:
            try:
                async for event in _agent.stream_async(prompt):
                    started = (
                        event.get("event", {})
                        .get("contentBlockStart", {})
                        .get("start", {})
                        .get("toolUse")
                    )
                    if started:
                        await queue.put(
                            {
                                "type": "tool",
                                "name": started["name"],
                                "label": tool_label(started["name"]),
                            }
                        )
                    if event.get("data"):
                        await queue.put({"type": "text", "delta": event["data"]})
            except Exception as error:  # surfaced on screen, not swallowed
                await queue.put({"type": "error", "text": t("cli_error", error=error)})
            finally:
                await queue.put({"type": "done"})

        task = asyncio.create_task(drive())
        try:
            while True:
                item = await queue.get()
                yield _sse(item)
                if item["type"] == "done":
                    break
        finally:
            tools.reset_output_sink(token)
            if not task.done():
                task.cancel()


def _stream(source) -> StreamingResponse:
    return StreamingResponse(
        source,
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/api/start")
async def start() -> StreamingResponse:
    """Onboarding opens with teruo's first question, as it does in the CLI."""
    if not _counseling:
        return _stream(iter([_sse({"type": "done"})]))
    return _stream(_turn(t("cli_counseling_kickoff"), []))


@app.post("/api/message")
async def message(
    text: str = Form(default=""), files: list[UploadFile] | None = None
) -> StreamingResponse:
    # Import here so attachments' i18n lookups run after the language is set.
    from attachments import build_prompt_from_uploads

    uploads = await _save_uploads(files or [])
    prompt, notes = build_prompt_from_uploads(text.strip(), uploads)
    return _stream(_turn(prompt, notes))


def main() -> None:
    import uvicorn

    uvicorn.run(
        app,
        host=os.environ.get("HOST", "0.0.0.0"),
        port=int(os.environ.get("PORT", "5000")),
        log_level="warning",
    )


if __name__ == "__main__":
    main()
