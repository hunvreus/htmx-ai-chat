from __future__ import annotations

import os
import sqlite3
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from openai import OpenAI

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "db.sqlite3"
app = FastAPI(title="Step 5 - HTMX Thinking Placeholder")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
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
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'complete',
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );
            """
        )

        cols = [row[1] for row in conn.execute("PRAGMA table_info(messages)").fetchall()]
        if "status" not in cols:
            conn.execute("ALTER TABLE messages ADD COLUMN status TEXT NOT NULL DEFAULT 'complete'")


def get_messages() -> list[dict]:
    with db() as conn:
        rows = conn.execute("SELECT id, role, content, status FROM messages ORDER BY id").fetchall()
    return [dict(row) for row in rows]


def build_context(before_message_id: int) -> list[dict]:
    with db() as conn:
        rows = conn.execute(
            """
            SELECT role, content
            FROM messages
            WHERE id < ? AND status = 'complete'
            ORDER BY id
            """,
            (before_message_id,),
        ).fetchall()
    return [{"role": row["role"], "content": row["content"]} for row in rows]


def ask_llm(history: list[dict]) -> str:
    if not os.getenv("OPENAI_API_KEY"):
        return "OPENAI_API_KEY is not set. Add it in .env and retry."

    response = client.chat.completions.create(model=MODEL, messages=history)
    return response.choices[0].message.content or ""


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
        conn.execute("INSERT INTO messages(role, content, status) VALUES('user', ?, 'complete')", (message,))
        cursor = conn.execute("INSERT INTO messages(role, content, status) VALUES('assistant', '', 'pending')")
        assistant_id = int(cursor.lastrowid)

    if request.headers.get("HX-Request"):
        return templates.TemplateResponse(
            request=request,
            name="partials/message_pair.html",
            context={"user_message": message, "assistant_id": assistant_id},
        )

    return RedirectResponse("/", status_code=303)


@app.get("/messages/{message_id}", response_class=HTMLResponse)
async def get_message(request: Request, message_id: int):
    with db() as conn:
        row = conn.execute(
            "SELECT id, role, content, status FROM messages WHERE id = ?",
            (message_id,),
        ).fetchone()

    if row is None:
        return HTMLResponse("")

    message = dict(row)
    if message["status"] == "pending":
        try:
            answer = ask_llm(build_context(message_id))
        except Exception as exc:
            answer = f"Error: {exc}"

        with db() as conn:
            conn.execute(
                "UPDATE messages SET content = ?, status = 'complete' WHERE id = ?",
                (answer, message_id),
            )
            refreshed = conn.execute(
                "SELECT id, role, content, status FROM messages WHERE id = ?",
                (message_id,),
            ).fetchone()
        if refreshed:
            message = dict(refreshed)

    return templates.TemplateResponse(
        request=request,
        name="partials/assistant_message.html",
        context={"message": message},
    )
