from __future__ import annotations

import json
import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from openai import OpenAI

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent
app = FastAPI(title="Step 1 - Basic Chat")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")


def ask_llm(prompt: str) -> str:
    if not os.getenv("OPENAI_API_KEY"):
        return "OPENAI_API_KEY is not set. Add it in .env and retry."

    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": "You are a concise assistant."},
            {"role": "user", "content": prompt},
        ],
    )
    return response.choices[0].message.content or ""


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    messages: list[dict] = []
    payload = request.cookies.get("step1_last_exchange")
    if payload:
        try:
            data = json.loads(payload)
            if isinstance(data, list):
                messages = data
        except json.JSONDecodeError:
            messages = []

    response = templates.TemplateResponse(
        request=request,
        name="index.html",
        context={"messages": messages},
    )
    if payload:
        response.delete_cookie("step1_last_exchange")
    return response


@app.post("/", response_class=HTMLResponse)
async def create_message(message: str = Form(...)):
    message = message.strip()
    if not message:
        return RedirectResponse("/", status_code=303)

    answer = ask_llm(message)
    exchange = json.dumps(
        [
            {"role": "user", "content": message},
            {"role": "assistant", "content": answer},
        ]
    )
    response = RedirectResponse("/", status_code=303)
    response.set_cookie("step1_last_exchange", exchange, max_age=60, samesite="lax")
    return response
