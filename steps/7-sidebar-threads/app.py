from __future__ import annotations

import html
import os
import sqlite3
import uuid
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from openai import AsyncOpenAI

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "db.sqlite3"
app = FastAPI(title="Step 7 - Sidebar + Threads")
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
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS threads (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                thread_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );
            """
        )


def get_threads() -> list[dict]:
    with db() as conn:
        rows = conn.execute(
            """
            SELECT t.id, m.content AS first_message
            FROM threads t
            LEFT JOIN messages m ON m.id = (
                SELECT m2.id
                FROM messages m2
                WHERE m2.thread_id = t.id
                ORDER BY m2.id
                LIMIT 1
            )
            ORDER BY t.created_at DESC
            """
        ).fetchall()

    threads: list[dict] = []
    for row in rows:
        first_message = (row["first_message"] or "").strip()
        first_line = first_message.splitlines()[0] if first_message else "New chat"
        threads.append({"id": row["id"], "label": first_line})
    return threads


def thread_exists(thread_id: str) -> bool:
    with db() as conn:
        row = conn.execute("SELECT 1 FROM threads WHERE id=?", (thread_id,)).fetchone()
    return row is not None


def create_thread_with_first_message(message: str) -> str:
    thread_id = str(uuid.uuid4())
    title = "New chat"
    with db() as conn:
        conn.execute("INSERT INTO threads(id, title) VALUES(?, ?)", (thread_id, title))
        conn.execute(
            "INSERT INTO messages(thread_id, role, content) VALUES(?, 'user', ?)",
            (thread_id, message),
        )
        conn.execute(
            "INSERT INTO messages(thread_id, role, content) VALUES(?, 'assistant', '')",
            (thread_id,),
        )
    return thread_id


def create_assistant_placeholder(thread_id: str, message: str) -> int:
    with db() as conn:
        conn.execute(
            "INSERT INTO messages(thread_id, role, content) VALUES(?, 'user', ?)",
            (thread_id, message),
        )
        cursor = conn.execute(
            "INSERT INTO messages(thread_id, role, content) VALUES(?, 'assistant', '')",
            (thread_id,),
        )
    return int(cursor.lastrowid)


def get_messages(thread_id: str) -> list[dict]:
    with db() as conn:
        rows = conn.execute(
            "SELECT id, role, content FROM messages WHERE thread_id=? ORDER BY id",
            (thread_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def get_context_messages(thread_id: str) -> list[dict]:
    with db() as conn:
        rows = conn.execute(
            "SELECT role, content FROM messages WHERE thread_id=? AND content<>'' ORDER BY id",
            (thread_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def sse_event(event: str, data: str) -> str:
    lines = data.splitlines() or [""]
    payload = "".join(f"data: {line}\n" for line in lines)
    return f"event: {event}\n{payload}\n"


def build_context(request: Request, thread_id: str | None, messages: list[dict]) -> dict:
    return {
        "request": request,
        "thread_id": thread_id,
        "messages": messages,
        "threads": get_threads(),
    }


@app.on_event("startup")
async def startup() -> None:
    init_db()


@app.get("/", response_class=HTMLResponse)
async def landing(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context=build_context(request, None, []),
    )


@app.post("/start")
async def start_thread(message: str = Form(...)):
    message = message.strip()
    if not message:
        return RedirectResponse("/", status_code=303)
    thread_id = create_thread_with_first_message(message)
    return RedirectResponse(f"/{thread_id}", status_code=303)


@app.get("/{thread_id}", response_class=HTMLResponse)
async def thread_page(request: Request, thread_id: str):
    if not thread_exists(thread_id):
        raise HTTPException(status_code=404)
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context=build_context(request, thread_id, get_messages(thread_id)),
    )


@app.post("/{thread_id}/messages", response_class=HTMLResponse)
async def create_message(request: Request, thread_id: str, message: str = Form(...)):
    if not thread_exists(thread_id):
        raise HTTPException(status_code=404)
    message = message.strip()
    if not message:
        if request.headers.get("HX-Request"):
            return HTMLResponse("")
        return RedirectResponse(f"/{thread_id}", status_code=303)

    assistant_id = create_assistant_placeholder(thread_id, message)
    stream_url = f"/stream/{assistant_id}?thread_id={thread_id}"

    if request.headers.get("HX-Request"):
        return templates.TemplateResponse(
            request=request,
            name="partials/message_pair.html",
            context={"user_message": message, "assistant_id": assistant_id, "stream_url": stream_url},
        )

    return RedirectResponse(f"/{thread_id}", status_code=303)


@app.get("/stream/{assistant_id}")
async def stream_response(assistant_id: int, thread_id: str):
    context_messages = get_context_messages(thread_id)

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
