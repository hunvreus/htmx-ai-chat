from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from openai import OpenAI

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent
app = FastAPI(title="Step 2 - HTMX Basics")
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
    return templates.TemplateResponse(request=request, name="index.html", context={"messages": []})


@app.post("/", response_class=HTMLResponse)
async def create_message(request: Request, message: str = Form(...)):
    message = message.strip()
    if not message:
        if request.headers.get("HX-Request"):
            return HTMLResponse("")
        return RedirectResponse("/", status_code=303)

    answer = ask_llm(message)

    if request.headers.get("HX-Request"):
        return templates.TemplateResponse(
            request=request,
            name="partials/message_pair.html",
            context={"user_message": message, "assistant_message": answer},
        )

    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={"messages": [{"user": message, "assistant": answer}]},
    )
