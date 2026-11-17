# LLM Gateway — 設計文件

## 目標

在現有的 OpenAI-compatible 後端 API
（例如數位發展部算力平台 AFS ModelSpace：`https://afspod-llm-api.dginfra.gov.tw/projects/<your-project-id>/api`）
前面加一層 Gateway,讓多個內部 Project 共用同一組後端 API Key,同時：

- 依 Project 切分並記錄每一筆 request 的 token 用量
- 提供 Dashboard,從 Overview / By Label / By Model / 逐筆 Request 等角度檢視用量
- 讓使用者日後可以依此估算每種任務大約需要多少 token,作為成本評估的依據

**不做的事(本次範圍外)**：

- 不做 $ 成本換算(只記 token 數,單價設定留待未來需要時再加)
- 不做協議轉換（例如 Anthropic↔OpenAI 格式轉換）
- 不支援多組不同的後端 API(目前只有一組後端 Base URL + Key)

## 架構

```
Client (帶 Gateway 發的虛擬 Project Key)
  → Gateway (驗證 Key → 換回真正後端 Key → 轉發 → 記錄 usage)
  → 後端 OpenAI-compatible API
```

- Gateway 對所有路徑（`/chat/completions`、`/embeddings`、`/models` 等）做通用轉發，
  不限定特定 endpoint（依 incoming path 組出 `BACKEND_BASE_URL + path` 再轉發）。
- Request/response body **不做任何轉換**，唯一例外是下方「串流 Token 用量擷取」一節
  所述的 `stream_options.include_usage` 注入與對應的 chunk 過濾。
- 後端只有一組真正的 API Key（存在 Gateway 的環境變數 `BACKEND_API_KEY`），所有虛擬
  Project 共用這一把 Key 轉發出去 —— Project 切分是 Gateway 這層的邏輯概念，不是後端
  真的有多組帳號。

## Project / API Key 機制

- Gateway 自己簽發「虛擬 Project Key」給每個 Project（格式如 `sk-proj-<random>`），
  只存 hash（例如 SHA-256）到 SQLite，不存明文；顯示時只給前綴（如 `sk-proj-a1b2••••`）。
- Client 改用這把虛擬 Key 打 Gateway
  (`Authorization: Bearer sk-proj-...`)，Gateway 驗證後解析出對應 Project，
  再把 `Authorization` header 換成真正的 `BACKEND_API_KEY` 後轉發。
- 驗證失敗（Key 不存在/已撤銷）→ 回 `401`，**不轉發、不記錄**到 `requests` 表（避免
  無效流量污染統計）。
- Project 狀態為 `disabled` → 回 `403`，不轉發。

### 選用的 Label 標記

- Client 可帶 `X-Task-Label` header，標記同一 Project 內不同的用途/任務
  （例如同一個 Project 但分「批次解析」「互動問答」等子分類）。
- Gateway 記錄該值到 `requests.label`，並在轉發前把這個 header 從 outgoing request
  中移除，後端完全不會看到它。
- 沒帶則記為 `NULL`（Dashboard 顯示為「未標記」）。

## Token 用量擷取

- **非串流**：直接讀後端回應 JSON 裡的 `usage` 欄位
  （`prompt_tokens` / `completion_tokens` / `total_tokens`）。
- **串流（SSE）**：
  - 若 request body 沒有 `stream_options.include_usage`，Gateway 在轉發前自動幫
    request body 加上 `"stream_options": {"include_usage": true}`，讓後端在串流
    結尾送出真實的 usage 資訊（這是唯一允許的請求修改例外）。
  - Gateway 解析 SSE chunk，抓到最後那個只含 `usage` 、`choices` 為空陣列的 chunk，
    記錄其中的 token 數，**接著把這個 chunk 從轉發給 client 的串流中濾掉**，讓
    client 端收到的串流內容與沒有 Gateway 時完全一致（除非 client 原本自己就有帶
    `include_usage: true`，此時該 chunk 是 client 本來就預期收到的，照樣轉發不濾掉）。
- 若後端回應中缺少 `usage`（例如發生錯誤），該筆 request 的 token 欄位記為 `0`/`NULL`，
  不做估算。

## 資料模型（SQLite）

```sql
projects (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'active',  -- active | disabled
  created_at TEXT NOT NULL
)

api_keys (
  id INTEGER PRIMARY KEY,
  project_id INTEGER NOT NULL REFERENCES projects(id),
  key_hash TEXT NOT NULL UNIQUE,
  key_prefix TEXT NOT NULL,      -- 顯示用，如 sk-proj-a1b2
  created_at TEXT NOT NULL,
  revoked_at TEXT              -- NULL 表示仍有效
)

requests (
  id INTEGER PRIMARY KEY,
  project_id INTEGER NOT NULL REFERENCES projects(id),
  label TEXT,                    -- 來自 X-Task-Label，可為 NULL
  model TEXT,
  endpoint_path TEXT NOT NULL,   -- 例如 /chat/completions
  method TEXT NOT NULL,
  is_streaming INTEGER NOT NULL, -- 0/1
  prompt_tokens INTEGER,
  completion_tokens INTEGER,
  total_tokens INTEGER,
  status_code INTEGER,
  latency_ms INTEGER,
  created_at TEXT NOT NULL
)
```

- 資料**永久保存**，不做自動清理／過期機制。
- Overview / By Label / By Model 三個分析角度都是對 `requests` 做不同的
  `GROUP BY` 查詢（依 project 全部彙總 / 依 label / 依 model），不需要額外的彙總表。

## Dashboard

併在同一個 FastAPI app 裡，伺服器端渲染（Jinja2 模板），圖表使用本地打包的輕量 JS
函式庫（不透過 CDN，避免內網環境無法連外網）。

**登入**：單一共用密碼（環境變數 `DASHBOARD_PASSWORD`），簽章過的 Cookie session。

**頁面**：

- `GET /login`
- `GET /dashboard`：所有 Project 的卡片/表格總覽（今日、本月 requests / tokens），
  新增 Project 的表單（建立後立刻產生第一把 API Key 顯示給使用者，僅顯示這一次）
- `GET /dashboard/{project_id}`：四個分頁
  - **Overview**：整個 Project 彙總數字（總 requests、總 tokens、平均 tokens/請求）
    + 每日 token 用量折線圖
  - **By Label**：依 `label` 分組的統計表
  - **By Model**：依 `model` 分組的統計表
  - **Requests**：逐筆 request 列表，用輪詢（每 2-3 秒 AJAX）做出「準即時」效果，
    不使用 WebSocket
  - Project 頁內可產生新的 API Key／撤銷既有 Key
- 上述列表頁皆提供 CSV 匯出

## Docker 部署

- `Dockerfile`：`python:3-slim` 基底，安裝依賴、以 `uvicorn app.main:app` 啟動
- `docker-compose.yml`：單一 `gateway` service
  - volume：掛載 SQLite 檔案所在目錄（例如 `./data:/data`）
  - 環境變數：`BACKEND_BASE_URL`、`BACKEND_API_KEY`、`DASHBOARD_PASSWORD`、
    `SESSION_SECRET`、`DATABASE_PATH`
  - 對外一個 port（預設 `8080`）

## 錯誤處理

| 情境 | 回應 | 是否記錄到 requests |
|---|---|---|
| 後端逾時/連線失敗 | 502 | 是（token 數為 0，記下 status_code） |
| 虛擬 Key 不存在/已撤銷 | 401 | 否 |
| Project 為 disabled | 403 | 否 |
| 後端回應非 2xx | 原樣轉發後端的 status code | 是（token 數視後端回應內容而定） |

## Config 參考（`.env`）

| 變數 | 必填 | 說明 |
|---|---|---|
| `BACKEND_BASE_URL` | 是 | 後端 OpenAI-compatible API 的 base URL |
| `BACKEND_API_KEY` | 是 | 真正打後端用的 Bearer token |
| `DASHBOARD_PASSWORD` | 是 | 登入 Dashboard 用的共用密碼 |
| `SESSION_SECRET` | 是 | 簽章 Dashboard session cookie 用 |
| `DATABASE_PATH` | 否 | SQLite 檔案路徑，預設 `/data/gateway.db` |
| `PORT` | 否 | 監聽 port，預設 `8080` |

## 測試計畫

- 單元測試：虛擬 Key 驗證邏輯、`X-Task-Label` 擷取與移除、usage chunk 過濾邏輯、
  各分析角度的 SQL 彙總查詢
- 整合測試：以假的後端（mock httpx transport）驗證非串流/串流兩種情境下 token
  記錄是否正確、include_usage 注入與過濾是否正確、401/403/502 情境
