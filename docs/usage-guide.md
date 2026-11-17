# 如何透過 Gateway 呼叫 LLM 並監控用量

Gateway 是一個透明代理:呼叫方式跟直接打後端 API 幾乎一樣,只需要換 Base URL 跟 API Key,其他(路徑、`model`、`messages`、`stream` 等參數)完全不變。

## 1. 到 Dashboard 建立 Project、拿一把 API Key

1. 開啟 `http://<Gateway位址>/_gateway/login`,輸入管理密碼登入
2. 在總覽頁「新增 Project」,輸入名稱(例如你的應用/任務名稱)
3. 建立完成會顯示一組 `sk-proj-...` 開頭的 Key —— **只會顯示這一次**,請立刻複製保存

## 2. 改你的程式打 Gateway,而不是直接打後端

只要換兩個東西:

| | 原本 | 改成 |
|---|---|---|
| Base URL | 後端 API 位址 | Gateway 位址 |
| `Authorization` | 後端的真實 Key | 剛剛拿到的 `sk-proj-...` |

路徑、body 格式完全不變。例如原本這樣打:

```bash
curl -X POST "https://afspod-llm-api.dginfra.gov.tw/projects/<id>/api/chat/completions" \
  -H "Authorization: Bearer <後端真實Key>" \
  -H "Content-Type: application/json" \
  -d '{"model":"gpt-4o","messages":[{"role":"user","content":"hi"}]}'
```

改成打 Gateway:

```bash
curl -X POST "http://<Gateway位址>/chat/completions" \
  -H "Authorization: Bearer sk-proj-xxxxxxxx" \
  -H "Content-Type: application/json" \
  -d '{"model":"gpt-4o","messages":[{"role":"user","content":"hi"}]}'
```

**串流也一樣**,直接帶 `"stream": true` 即可,Gateway 會自動處理 token 統計,不需要自己加 `stream_options`,回應內容跟直接打後端時看到的完全一樣。

## 3.(選用)幫請求貼標籤,方便之後細分統計

如果同一個 Project 底下想再細分不同用途(例如「批次解析」「互動問答」),額外帶一個 header:

```bash
-H "X-Task-Label: 批次解析"
```

這個 header 只會被 Gateway 記錄下來,**不會**轉發給後端。

## 4. 到 Dashboard 看用量

點進剛剛建立的 Project,四個分頁:

- **Overview**:整個 Project 的總量、平均每次請求 token 數、每日趨勢圖
- **By Label**:依你貼的 `X-Task-Label` 分類統計
- **By Model**:依呼叫的 `model` 分類統計
- **Requests**:逐筆請求紀錄(每 3 秒自動更新),可以匯出 CSV

用量資料永久保留,方便之後回頭估算「這種任務大概要花多少 token」。

## 5. 其他

- Project 若在 Dashboard 上被「停用」,該 Project 底下所有 Key 打 Gateway 都會收到 `403`,重新啟用即恢復。
- Key 若被「撤銷」,打 Gateway 會收到 `401`,需要重新產生一把新的。
