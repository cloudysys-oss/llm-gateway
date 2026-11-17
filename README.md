# LLM Gateway

OpenAI 相容的 LLM 反向代理：讓多個應用（Project）共用同一組後端 API Key，並記錄每一筆請求的 Token 用量，提供網頁 Dashboard 檢視與匯出。

本專案是「中小企業私有化生成式 AI 導入平台暨企業知識推論服務驗證計畫」的 AI 推論服務中介層，於數位發展部數位產業署 115 年算力平台（AFS ModelSpace）上實際運作，承接 AI 知識庫、AI OCR 等應用的模型呼叫。

## 功能

- **透明代理**：通用轉發所有路徑（`/chat/completions`、`/embeddings`、`/models`…），request / response 內容不做轉換；應用端只要換 Base URL 和 API Key。
- **多 Project、虛擬 API Key**：每個應用拿到自己的 `sk-proj-...` Key，可以隨時撤銷，或停用整個 Project；後端真正的金鑰只存在 Gateway。
- **Token 用量記錄**：記錄每筆請求的模型、Prompt / Completion Token 數與狀態碼；串流請求會自動注入 `stream_options.include_usage` 取得用量，回給應用端的內容與直接呼叫後端時一致。
- **任務標籤**：請求可帶 `X-Task-Label` 標頭，用來細分同一個 Project 底下的不同用途（不會轉發給後端）。
- **Dashboard**：密碼登入；Overview（總量與每日趨勢）、By Label、By Model、即時 Requests 四個分頁，皆可匯出 CSV。

## 架構

```text
應用程式（帶 Gateway 發的虛擬 Key）
  → LLM Gateway：驗證 Key → 換成後端金鑰 → 轉發 → 記錄用量（SQLite）
  → 後端 OpenAI 相容 API（例如 AFS ModelSpace）
```

技術棧：Python、FastAPI、uvicorn、httpx、Jinja2、SQLite、Docker Compose。設計細節見 [`docs/design.md`](docs/design.md)。

## 快速開始

### Docker Compose

```bash
cp .env.example .env
# 編輯 .env：BACKEND_BASE_URL、BACKEND_API_KEY、DASHBOARD_PASSWORD、SESSION_SECRET
docker compose up -d --build
```

### 本機執行

```bash
python -m venv .venv
.venv/Scripts/activate        # Windows；Linux / macOS 用 source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env
# 編輯 .env
uvicorn app.main:create_app --factory --host 0.0.0.0 --port 8080
```

啟動後：

1. 開啟 `http://localhost:8080/_gateway/login`，用 `DASHBOARD_PASSWORD` 登入。
2. 新增 Project，取得 `sk-proj-...` Key（只會顯示一次）。
3. 應用程式把 Base URL 改成 `http://localhost:8080`，Bearer Token 改用這把 Key。

完整用法見 [`docs/usage-guide.md`](docs/usage-guide.md)。

## 環境變數

| 變數 | 說明 | 預設值 |
|---|---|---|
| `BACKEND_BASE_URL` | 後端 OpenAI 相容 API 的 Base URL | （必填） |
| `BACKEND_API_KEY` | 後端真正的 API Key | （必填） |
| `DASHBOARD_PASSWORD` | Dashboard 登入密碼 | （必填） |
| `SESSION_SECRET` | Session 簽章用的隨機字串 | （必填） |
| `DATABASE_PATH` | SQLite 資料庫路徑 | `/data/gateway.db` |
| `PORT` | 服務埠號 | `8080` |
| `REQUEST_TIMEOUT_SECONDS` | 轉發到後端的逾時秒數 | `600` |

## 測試

```bash
pip install -r requirements-dev.txt
pytest
```

## 授權

[MIT License](LICENSE)
