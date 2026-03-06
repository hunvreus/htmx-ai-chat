from __future__ import annotations

import html
import os
import sqlite3
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from openai import AsyncOpenAI

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "db.sqlite3"
app = FastAPI(title="Step 6 - SSE Streaming")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))
MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")


def db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with db() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
            """
        )

        cols = [row[1] for row in conn.execute("PRAGMA table_info(messages)").fetchall()]
        # Handle legacy schema from earlier step variants that used thread_id.
        if "thread_id" in cols:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS messages_new (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT (datetime('now'))
                );
                INSERT INTO messages_new(role, content, created_at)
                SELECT role, content, COALESCE(created_at, datetime('now'))
                FROM messages;
                DROP TABLE messages;
                ALTER TABLE messages_new RENAME TO messages;
                """
            )


def get_messages() -> list[dict]:
    with db() as conn:
        rows = conn.execute("SELECT id, role, content FROM messages ORDER BY id").fetchall()
    return [dict(row) for row in rows]


def get_context_messages() -> list[dict]:
    with db() as conn:
        rows = conn.execute(
            "SELECT role, content FROM messages WHERE content <> '' ORDER BY id"
        ).fetchall()
    return [dict(row) for row in rows]


def sse_event(event: str, data: str) -> str:
    lines = data.splitlines() or [""]
    payload = "".join(f"data: {line}\n" for line in lines)
    return f"event: {event}\n{payload}\n"


@app.on_event("startup")
async def startup() -> None:
    init_db()


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse(request=request, name="index.html", context={"messages": get_messages()})


@app.post("/", response_class=HTMLResponse)
async def create_message(request: Request, message: str = Form(...)):
    message = message.strip()
    if not message:
        if request.headers.get("HX-Request"):
            return HTMLResponse("")
        return RedirectResponse("/", status_code=303)

    with db() as conn:
        conn.execute("INSERT INTO messages(role, content) VALUES('user', ?)", (message,))
        cursor = conn.execute("INSERT INTO messages(role, content) VALUES('assistant', '')")
        assistant_id = int(cursor.lastrowid)

    stream_url = f"/stream/{assistant_id}"

    if request.headers.get("HX-Request"):
        return templates.TemplateResponse(
            request=request,
            name="partials/message_pair.html",
            context={
                "user_message": message,
                "assistant_id": assistant_id,
                "stream_url": stream_url,
            },
        )

    return RedirectResponse("/", status_code=303)


@app.get("/stream/{assistant_id}")
async def stream_response(assistant_id: int):
    context_messages = get_context_messages()

    async def event_stream():
        if not os.getenv("OPENAI_API_KEY"):
            fallback = html.escape("OPENAI_API_KEY is not set.")
            yield sse_event("delta", fallback)
            yield sse_event("done", "ok")
            return

        yield ": stream-open\n\n"

        full_text = ""
        try:
            stream = await client.chat.completions.create(
                model=MODEL,
                messages=context_messages,
                stream=True,
            )
            async for chunk in stream:
                delta = chunk.choices[0].delta.content or ""
                if not delta:
                    continue
                full_text += delta
                yield sse_event("delta", html.escape(full_text))
        except Exception as exc:
            full_text = f"Error: {exc}"
            yield sse_event("delta", html.escape(full_text))

        with db() as conn:
            conn.execute("UPDATE messages SET content=? WHERE id=?", (full_text, assistant_id))

        yield sse_event("done", "ok")

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
