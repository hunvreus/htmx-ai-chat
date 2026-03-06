# HTMX Chatbot Tutorial (FastAPI)

This repo is a step-by-step build of a chat app with FastAPI + HTMX, with just enough JS when needed.

The goal is not “build the fanciest app”.
The goal is understanding the mechanics: request/response flow, HTMX primitives, Basecoat UI patterns, and where SSE fits.

## Run

```bash
uv sync
uv run python run.py --step 1
```

Use `--step` with any active step number (`1` to `7`).

## Steps

1. Basic Chat (`steps/1-basic-chat`)
2. HTMX Basics (`steps/2-htmx-basics`)
3. SQLite Persistence (`steps/3-sqlite-persistence`)
4. Basecoat UI (`steps/4-basecoat-ui`)
5. HTMX Thinking Placeholder (`steps/5-htmx-thinking`)
6. SSE Streaming (`steps/6-sse-streaming`)
7. Sidebar + Threads (`steps/7-sidebar-threads`)

## Step-by-Step

### Step 1: Basic Chat

This step is all about wiring the AI API, nothing else.

What we send to OpenAI:
- a `messages` array (role/content pairs)
- model name from env

What we get back:
- a normal completion response
- assistant text from `response.choices[0].message.content`

Flow:
- browser submits form
- backend calls OpenAI
- backend returns HTML once answer is done

Limitation (intentional for teaching):
- it feels slow, because the UI only updates after the backend has the final answer.

Relevant code:
- `steps/1-basic-chat/app.py`
- `steps/1-basic-chat/templates/index.html`

### Step 2: HTMX Basics

This is the first HTMX step.

Core idea:
- keep normal server-rendered HTML
- progressively enhance forms/links with HTMX attributes

Key attributes:
```html
hx-post="/"
hx-target="#chat"
hx-swap="beforeend"
```

In this codebase we target `#chat-list` so the loading row can stay outside the append area, but the pattern is the same.

How partial rendering works:
- HTMX sends `HX-Request: true`
- backend checks `request.headers.get("HX-Request")`
- if true, it returns a fragment (`partials/message_pair.html`) instead of a full page

Also introduced here:
- `hx-indicator` for loading state
- `hx-disabled-elt` to disable submit while request is in flight
- HTMX event hook with `hx-on::after-request="this.reset(); this.querySelector('#message')?.focus();"`

Relevant code:
- `steps/2-htmx-basics/templates/index.html`
- `steps/2-htmx-basics/templates/partials/message_pair.html`
- `steps/2-htmx-basics/app.py`

### Step 3: SQLite Persistence

Here we keep the HTMX behavior, but persist chat messages in SQLite.

Main change:
- messages survive refresh/restart

Important API impact:
- now we build conversation context from stored history
- we send that history to OpenAI (not just the latest user message)
- so responses become context-aware across turns

Relevant code:
- `steps/3-sqlite-persistence/app.py` (`init_db`, history read/write, OpenAI call)
- `steps/3-sqlite-persistence/templates/index.html`

### Step 4: Basecoat UI

This step is about UI polish without adding frontend build complexity.

What Basecoat is:
- a UI layer with clean primitives/components that works well in server-rendered apps

What we use here:
- Tailwind Play CDN
- Basecoat CSS/JS from CDN

Why CDN in this tutorial:
- fewer moving parts
- no Node build pipeline
- easier to focus on HTMX behavior

But for production:
- prefer proper build tooling and asset pipeline

What Tailwind Play CDN is:
- browser-side Tailwind compilation for quick prototyping/tutorials

What we wire in this step:
- chat layout (thread area + bottom composer)
- loading row style improvements
- theme toggle event (`basecoat:theme`) + dark mode classes

Relevant code:
- `steps/4-basecoat-ui/templates/index.html`

### Step 5: HTMX Thinking Placeholder

This introduces a more advanced HTMX pattern.

Pattern:
- form submit returns immediately with two rendered pieces:
1. user message
2. assistant placeholder (`Thinking...`)

Then HTMX updates that placeholder by hitting a backend endpoint and swapping the fragment.
It’s the same UX goal as `hx-indicator`: show immediate feedback while the server is working, but now scoped to the specific assistant message row.

Why this matters:
- faster perceived responsiveness
- still plain server-rendered HTML
- no global client state machinery

HTMX mindset note:
- the “dumb” server-first approach is often the right one
- avoid React-style reflexes (global client state everywhere) unless you truly need it

Relevant code:
- `steps/5-htmx-thinking/app.py`
- `steps/5-htmx-thinking/templates/partials/message_pair.html`
- `steps/5-htmx-thinking/templates/partials/assistant_message.html`

### Step 6: SSE Streaming

Now we add true token streaming.

HTMX extensions:
- HTMX has extensions for things outside core HTML-over-the-wire patterns
- examples: SSE extension (used here), ws extension, etc.

What SSE is:
- Server-Sent Events is a one-way server -> browser stream over HTTP
- perfect for progressive token output

How we use HTMX SSE extension:
- `hx-ext="sse"`
- `sse-connect="..."`
- `sse-swap="delta"`
- `sse-close="done"`

We also use events around SSE lifecycle to manage UI state (like submit enable/disable) and scroll behavior.

Relevant code:
- `steps/6-sse-streaming/app.py` (`stream_response`, SSE event formatting)
- `steps/6-sse-streaming/templates/partials/message_pair.html`
- `steps/6-sse-streaming/templates/index.html`

### Step 7: Sidebar + Threads

This step adds multi-thread UX with a Basecoat sidebar:
- Basecoat Sidebar docs: https://basecoatui.com/components/sidebar/

Most of this step is regular web app wiring:
- thread IDs (UUID)
- routes (`/`, `/{thread_id}`, post message route)
- templates split for sidebar / new-thread / thread content

HTMX focus here is `hx-boost`:
- boost link navigation
- swap only the main content area
- keep page shell/sidebar in place
- push URL so browser history works

We also add small JS to keep sidebar active link state in sync after HTMX swaps and popstate navigation.

Why the landing page form is not HTMX:
- creating a new thread changes more than one region (URL + sidebar + content)
- doing a normal redirect is simpler and clearer
- and CSS/assets are cached anyway, so the full navigation cost is usually fine

Relevant code:
- `steps/7-sidebar-threads/app.py`
- `steps/7-sidebar-threads/templates/partials/sidebar.html`
- `steps/7-sidebar-threads/templates/partials/content_new_thread.html`
- `steps/7-sidebar-threads/templates/partials/content_thread.html`

## Notes

- One top-level dependency environment, no per-step installs.
- Active tutorial steps live in `steps/`.
- Archived experiments/removed steps are kept in `_legacy/`.

## Environment

The runner loads `.env` automatically.

Required:
```env
OPENAI_API_KEY=...
```

Optional:
```env
OPENAI_MODEL=gpt-4.1-mini
```
