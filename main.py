import os
import asyncio
import base64
from functools import lru_cache
from typing import Optional
from typing_extensions import Annotated
from dotenv import load_dotenv
from fastapi import FastAPI, Request, Depends, Form, UploadFile, File
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import StreamingResponse
from openai import OpenAI
import config
import time

load_dotenv()

app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")

@lru_cache
def get_settings():
    return config.Settings()

templates = Jinja2Templates(directory='templates')
templates.env.globals["config"] = get_settings()

client = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))

messages: list[dict] = []

@app.get('/demo')
async def demo(request: Request):
    return templates.TemplateResponse(
        request=request,
        name='demo.html'
    )

@app.get('/fragment')
async def demo(request: Request):
    time.sleep(5)
    return templates.TemplateResponse(
        request=request,
        name='partials/_fragment.html'
    )

@app.get('/')
async def index(request: Request):
    return templates.TemplateResponse(
        request=request,
        name='index.html',
        context={'messages': messages}
    )

@app.post('/message')
async def chat(
    request: Request,
    message: Optional[str] = Form(None),
    file: Optional[UploadFile] = File(None)
):
    content = []
    if message:
        content.append({
            "type": "text",
            "text": message
        })

    if file:
        if not file.content_type.startswith("image/"):
            # Handle non-image file error appropriately
            return "Error: Uploaded file is not an image."

        base64_image = base64.b64encode(await file.read()).decode("utf-8")
        image_url = f"data:{file.content_type};base64,{base64_image}"
        content.append({
            "type": "image_url",
            "image_url": {
                "url": image_url,
            }
        })

    user_message = {
        'role': 'user',
        'content': content if file else message # Keep it a simple string if no file
    }
    messages.append(user_message)

    return templates.TemplateResponse(
        request=request,
        name='partials/_chat.html',
        context={
            'messages': [user_message],
            'index': len(messages) - 1,
            'request': request
        }
    )

@app.get('/stream/{index}')
async def stream_response(request: Request, index: int):
    context_messages = messages[max(0, index-3):index+1]
    
    async def generate():
        try:
            response = client.chat.completions.create(
                model='gpt-4o',
                messages=context_messages,
                stream=True
            )
            
            full_response = ''
            for chunk in response:
                if chunk.choices[0].delta.content:
                    content = chunk.choices[0].delta.content
                    print(repr(content))  # shows \n explicitly
                    full_response += content
                    yield f'event: message\n'
                    yield f'data: {content}\n\n'
                    await asyncio.sleep(0.01)
            
            messages.append({
                'role': 'assistant',
                'content': full_response
            })
            
        except Exception as e:
            yield f'event: message\ndata: Error: {str(e)}\n\n'

        finally:
            yield f"event: done\n"
            yield f"data: Completion complete\n\n"
    
    return StreamingResponse(generate(), media_type='text/event-stream', headers={
        'Cache-Control': 'no-cache',
        'Connection': 'keep-alive',
        'X-Accel-Buffering': 'no',
    })