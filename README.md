# Internal Docs — org-ready RAG chatbot

Self-hosted appliance for question answering over internal documents. Hybrid retrieval (hashed dense vectors + BM25 + Reciprocal Rank Fusion) grounds answers in spaces the signed-in user can access. You deploy it once on an internal server. The customer operates it: health, token usage, and which models are free vs premium. Nothing phones home.

The seed corpus is a fake **Northstar** handbook (policy IDs such as `PTO-12`) used as optional demo content for the HR space.

## What you get

- ChatGPT-like chat: threads, follow-ups, streamed answers, clickable citation chips
- Spaces with ACL (HR / Engineering / Finance, plus any you create)
- Local accounts; optional OIDC SSO
- Background ingest, drag-and-drop uploads, per-space watch folder (`inbox/`)
- Free extractive + local Ollama models; optional paid OpenAI-compatible APIs with **your** keys
- Admin ops: health, token usage, model catalog, audit CSV
- Retrieval lab at `/lab` (dense vs BM25 vs hybrid) — not the employee home screen
- Prometheus text at `/metrics`, liveness at `/health`

## Fastest start (recommended)

```bash
docker compose up --build
```

Open [http://localhost:8765](http://localhost:8765). The first visit is the setup wizard (org name, admin user, default spaces). Optionally load the demo handbook into HR.

Without Docker, from this folder:

```powershell
.\scripts\run.ps1
```

macOS / Linux:

```bash
chmod +x scripts/run.sh
./scripts/run.sh
```

Open [http://127.0.0.1:8765](http://127.0.0.1:8765).

## Optional chat model

Retrieval and extractive answers work with no LLM. For written answers, install [Ollama](https://ollama.com) and pull a **small** default:

```bash
ollama pull llama3.2
```

If the model is missing, the wizard and chat still work: answers quote the indexed documents until you pull a model.

Neural embeddings are optional. Leave `EMBEDDING_MODEL=hash` (zero download). To use Ollama embeddings instead:

```
EMBEDDING_MODEL=nomic-embed-text
```

then `ollama pull nomic-embed-text`.

## Operate it yourself

| Page / path | Who | Purpose |
| --- | --- | --- |
| `/` | Employees | Chat against allowed spaces |
| `/admin` | Org admin | Health, token usage, users, models, uploads |
| `/lab` | Admins / editors | Compare hybrid vs dense vs BM25 |
| `/health` | IT | Liveness probe |
| `/metrics` | IT | Prometheus gauges (tokens, users, chunks) |
| `/api/admin/audit.csv` | Org admin | Who asked what, which space |

**Backup:** copy the `data/` directory (or the Docker volume `docs-data`). That includes `app.db`, space files, and indexes. Restore by putting the folder back and starting the app. There is no vendor control plane.

**Watch folder:** drop files into `data/spaces/{space_id}/inbox/` on the server. The app moves them into that space’s docs folder and reindexes.

**Demo people** (created when you check “Load demo handbook + sample people”):

| Email | Space | Password |
| --- | --- | --- |
| maya@northstar.demo | HR | `demo1234` |
| jordan@northstar.demo | Engineering | `demo1234` |
| priya@northstar.demo | Finance | `demo1234` |

**SSO:** set `OIDC_ISSUER`, `OIDC_CLIENT_ID`, and `OIDC_CLIENT_SECRET` in `.env`. Leave blank to use local passwords only.

**Models:** in Admin, keep extractive and local Ollama on the **free** tier. Add a paid OpenAI-compatible endpoint on **premium** with the customer's API key and base URL. Assign users `free` or `premium`. Keys stay in SQLite on this server.

## API (after setup)

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/auth/status` | Setup + session |
| POST | `/api/auth/login` | Email + password |
| GET/POST | `/api/spaces` | List / create spaces |
| POST | `/api/spaces/{id}/upload` | Files → background ingest |
| POST | `/api/chat/threads/{id}/messages` | Chat turn |
| POST | `/api/chat/threads/{id}/messages/stream` | Same turn as SSE |
| GET | `/api/admin/ops` | Health + usage |
| POST | `/api/query` | Lab retrieval (`space_id` required once set up) |

CORS is locked to `PUBLIC_ORIGIN` / `CORS_ORIGINS`. Login and chat are rate-limited.

## Tests

```bash
pytest
```

Retrieval Hit@1 / Hit@5 on the seed corpus (hashed embeddings, no model download):

```bash
python tests/eval_retrieval.py
```

## Layout

```
app/           FastAPI app, ingest, retrieve, generate, static UI
data/docs/     Seed handbook (copied into a space via “Load demo”)
data/spaces/   Per-space files and indexes after setup
data/app.db    Users, sessions, spaces, threads, usage, audit
scripts/       run.ps1 / run.sh laptop demo
```

## Config

See `.env.example`. Optional cross-encoder rerank (`RERANK_ENABLED=true`) needs an extra `sentence-transformers` install and downloads `BAAI/bge-reranker-base`.
