# 把宣傳文宣轉換成行事曆連結！

平時收到各種廣告文宣(職棒比賽、系上活動、社團...etc)，收到後卻因為忘了放進行事曆而錯過了很多活動跟獎品

因此透過這個專案，只要把`圖片`或`圖片網址`給 LINE Bot，就能夠幫你產生一個 Google Calendar 連結，讓你變成一個活動達人！

## Features

- 健康檢查
- 圖片關鍵字搜尋並生成 Google Calendar URL
- 使用 Google Gemini Pro API 生成對話內容
- 對話記錄儲存於 Firebase

## Prerequisites

- Python 3.7+
- LINE Messaging API account
- Gemini AI API key
- Firebase project
- 環境變數檔案請參考 `.env.sample`，地端開發請改名為 `.env`:
  - `API_ENV`: 應用程式運行環境（例如：`production` 或 `develop`）
  - `LINE_CHANNEL_SECRET`
  - `LINE_CHANNEL_ACCESS_TOKEN`
  - `LOG`
  - `FIREBASE_URL`: Firebase Realtime DB url
  - `GEMINI_API_KEY`: Google 生成式 API key
  - `REURL_API_KEY`: REURL 服務的 API key，縮短網址用

## Installation

1. Clone 專案:
    ```bash
    git clone https://github.com/louis70109/linebot-image2calendar.git
    cd linebot-image2calendar
    ```

2. 透過虛擬環境開啟:
    ```bash
    python -m venv venv
    source venv/bin/activate  # On Windows use `venv\Scripts\activate`
    ```

3. 安裝套件:
    ```bash
    pip install -r requirements.txt
    ```

4. 將 `.env.sample` 改名為 `.env` 並把相對應的參數都放入

## 啟動服務

1. 開啟 FastAPI application:
    ```bash
    uvicorn main:app --host 0.0.0.0 --port 8080 --reload
    // python main.py
    ```


## Endpoints

- **GET /?img_url=xxx**: 透過網址抓取圖片，並藉由 Gemini 找到其中的關鍵字，生成 Google Calendar URL
- **GET /health**: 健康檢查
- **POST /webhooks/line**: LINE Bot webhook 使用

## License

MIT License.

