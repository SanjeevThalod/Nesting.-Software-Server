# Nesting Software API (Server)

## Deploy to Vercel

1. **Install Vercel CLI** (optional): `npm i -g vercel`

2. **Deploy from the `server` directory:**
   ```bash
   cd server
   vercel
   ```
   Or connect this folder to Vercel via the dashboard (Root Directory = `server`).

3. **Requirements:**
   - `vercel.json` routes all requests to `index.py` (which exports the FastAPI `app` from `main.py`).
   - On Vercel, uploads and outputs use `/tmp` (ephemeral); the API still works for process + download in the same request.

4. **Environment:** Vercel sets `VERCEL=1` automatically; the app uses `/tmp` for file storage when that is set.

## Health check APIs

| Endpoint | Purpose |
|----------|--------|
| `GET /api/health` | Basic health – API is up and responding. |
| `GET /api/health/live` | Liveness – process is alive (for orchestrators). |
| `GET /api/health/ready` | Readiness – app can accept work (temp dirs writable). Returns 503 if not ready. |

Example:
```bash
curl https://your-app.vercel.app/api/health
curl https://your-app.vercel.app/api/health/live
curl https://your-app.vercel.app/api/health/ready
```

## Local development

```bash
pip install -r requirements.txt
python main.py
# API at http://localhost:8000
```
