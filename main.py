import json
import logging
import os
import sys

if os.getenv("API_ENV") != "production":
    from dotenv import load_dotenv

    load_dotenv()


from fastapi import FastAPI, HTTPException, Request
from linebot.v3 import (
    WebhookHandler
)
from linebot.v3.messaging import (
    AsyncApiClient,
    AsyncMessagingApi,
    Configuration,
    ReplyMessageRequest,
    TextMessage,
)
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.webhooks import (
    MessageEvent,
    TextMessageContent,
)

import uvicorn
from fastapi.responses import RedirectResponse

logging.basicConfig(level=os.getenv("LOG", "WARNING"))
logger = logging.getLogger(__file__)

app = FastAPI()

channel_secret = os.getenv("LINE_CHANNEL_SECRET", None)
channel_access_token = os.getenv("LINE_CHANNEL_ACCESS_TOKEN", None)
if channel_secret is None:
    print("Specify LINE_CHANNEL_SECRET as environment variable.")
    sys.exit(1)
if channel_access_token is None:
    print("Specify LINE_CHANNEL_ACCESS_TOKEN as environment variable.")
    sys.exit(1)

configuration = Configuration(access_token=channel_access_token)

async_api_client = AsyncApiClient(configuration)
line_bot_api = AsyncMessagingApi(async_api_client)
handler = WebhookHandler(channel_secret)


import google.generativeai as genai
from firebase import firebase
from utils import check_image, create_gcal_url, is_url_valid


firebase_url = os.getenv("FIREBASE_URL")
gemini_key = os.getenv("GEMINI_API_KEY")


# Initialize the Gemini Pro API
genai.configure(api_key=gemini_key)


@app.get("/health")
async def health():
    return "ok"


@app.get("/")
async def find_image_keyword(img_url: str):
    image_data = check_image(img_url)
    print(image_data)
    image_data = json.loads(image_data)
    print("=" * 20)
    print(image_data["time"])
    print("=" * 20)
    g_url = create_gcal_url(
        image_data["title"],
        image_data["time"],
        image_data["location"],
        image_data["content"],
    )
    if is_url_valid(g_url):
        return RedirectResponse(g_url)
    else:
        return "Error"


@app.post("/webhooks/line")
async def handle_callback(request: Request):
    signature = request.headers["X-Line-Signature"]

    # get request body as text
    body = await request.body()
    body = body.decode()

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        raise HTTPException(status_code=400, detail="Invalid signature")

@handler.add(MessageEvent, message=TextMessageContent)
async def handle_text_message(event):
    logging.info(event)
    text = event.message.text
    user_id = event.source.user_id

    msg_type = event.message.type
    fdb = firebase.FirebaseApplication(firebase_url, None)

    user_chat_path = f"chat/{user_id}"
    # chat_state_path = f'state/{user_id}'
    chatgpt = fdb.get(user_chat_path, None)

    model = genai.GenerativeModel("gemini-1.5-pro")

    if chatgpt is None:
        messages = []
    else:
        messages = chatgpt
    
    if text == "C":
        fdb.delete(user_chat_path, None)
        reply_msg = "已清空對話紀錄"
    elif text == "A":
        response = model.generate_content(
            f"Summary the following message in Traditional Chinese by less 5 list points. \n{messages}"
        )
        reply_msg = response.text
    # model = genai.GenerativeModel('gemini-pro')
    messages.append({"role": "user", "parts": [text]})
    response = model.generate_content(messages)
    messages.append({"role": "model", "parts": [text]})
    # 更新firebase中的對話紀錄
    fdb.put_async(user_chat_path, None, messages)
    reply_msg = response.text

    await line_bot_api.reply_message(
        ReplyMessageRequest(
            reply_token=event.reply_token,
            messages=[TextMessage(text=reply_msg)],
        )
    )

    return "OK"


if __name__ == "__main__":
    port = int(os.environ.get("PORT", default=8080))
    debug = True if os.environ.get("API_ENV", default="develop") == "develop" else False
    logging.info("Application will start...")
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=debug)
