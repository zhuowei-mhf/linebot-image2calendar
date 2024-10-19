import json
import logging
import os
import sys
import openai
import re

from fastapi import FastAPI, HTTPException, Request
from linebot.v3 import WebhookHandler
from linebot.v3.messaging import (
    Configuration,
    ReplyMessageRequest,
    TextMessage,
    ApiClient,
    MessagingApi,
)
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.webhooks import MessageEvent, TextMessageContent
from dotenv import load_dotenv
from firebase import firebase
import uvicorn
from openai import AssistantEventHandler
from typing_extensions import override

# Load environment variables from .env file
if os.getenv("API_ENV") != "production":
    load_dotenv()

# Logging setup
logging.basicConfig(level=os.getenv("LOG", "INFO"))
logger = logging.getLogger(__file__)

# FastAPI app initialization
app = FastAPI()

# LINE Bot configuration
channel_secret = os.getenv("LINE_CHANNEL_SECRET")
channel_access_token = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")

if not channel_secret or not channel_access_token:
    print("LINE credentials not set.")
    sys.exit(1)

configuration = Configuration(access_token=channel_access_token)
handler = WebhookHandler(channel_secret)

# OpenAI client initialization
openai.api_key = os.getenv("OPENAI_API_KEY")
client = openai.OpenAI()

# Assistant ID from environment variables
assistant_id = os.getenv("OPENAI_ASSISTANT_ID")

# Firebase setup
firebase_url = os.getenv("FIREBASE_URL")
fdb = firebase.FirebaseApplication(firebase_url, None)

# Define an EventHandler for streaming responses
class EventHandler(AssistantEventHandler):
    def __init__(self):
        super().__init__()
        self.final_response = ""

    @override
    def on_text_created(self, text: str) -> None:
        """Handle the initial creation of text."""
        print(f"\nassistant > {text}", end="", flush=True)

    @override
    def on_text_delta(self, delta, snapshot):
        """Accumulate text deltas as they stream in."""
        self.final_response += delta.value
        print(delta.value, end="", flush=True)

    @override
    def on_tool_call_created(self, tool_call):
        """Log when a tool call is made."""
        print(f"\nassistant > Tool call: {tool_call.type}\n", flush=True)

# Health check endpoint
@app.get("/health")
async def health():
    return "ok"

# LINE webhook endpoint
@app.post("/webhooks/line")
async def handle_callback(request: Request):
    signature = request.headers["X-Line-Signature"]
    body = await request.body()
    body = body.decode()

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        raise HTTPException(status_code=400, detail="Invalid signature")

@handler.add(MessageEvent, message=TextMessageContent)
def handle_text_message(event: MessageEvent):
    """Handle incoming messages."""
    text = event.message.text.strip()
    user_id = event.source.user_id

    # Paths for user data in Firebase
    user_chat_path = f"chat/{user_id}"
    user_data_path = f"users/{user_id}"

    # Retrieve or create thread ID
    thread_id = fdb.get(user_chat_path, "thread_id")
    if not thread_id:
        logger.info(f"Creating a new thread for user {user_id}.")
        thread = client.beta.threads.create()
        thread_id = thread.id
        fdb.put(user_chat_path, "thread_id", thread_id)

    # Retrieve user data
    user_data = fdb.get(user_data_path, None) or {}
    user_state = user_data.get('state', 'new')

    # Initialize the response message
    reply_message = ""

    # State machine logic
    if user_state == 'new':
        # User is new, ask for country/language
        reply_message = "Welcome! Please enter your Country/Language (e.g., Japan/Japanese)."
        user_data['state'] = 'waiting_for_country_language'
        fdb.put(user_data_path, None, user_data)

    elif user_state == 'waiting_for_country_language':
        # Expecting Country/Language input
        if re.match(r"^\w+/\w+$", text):
            country, language = text.split('/')
            user_data['country'] = country
            user_data['language'] = language
            user_data['state'] = 'waiting_for_major_grade'
            fdb.put(user_data_path, None, user_data)
            reply_message = "Thank you! What's your major/grade? Please enter in the format Major/Grade (e.g., Computer Science/26)."
        else:
            reply_message = "Please enter your Country/Language in the correct format (e.g., Japan/Japanese)."

    elif user_state == 'waiting_for_major_grade':
        # Expecting Major/Grade input
        if re.match(r"^\w+/\d+$", text):
            major, grade = text.split('/')
            user_data['major'] = major
            user_data['grade'] = grade
            user_data['state'] = 'complete'
            fdb.put(user_data_path, None, user_data)
            reply_message = "Thank you! You can now start asking questions."
        else:
            reply_message = "Please enter your Major/Grade in the correct format (e.g., Computer Science/26)."

    else:
        # User has completed onboarding, proceed with assistant interaction
        # Prepare assistant prompt with user info
        country = user_data.get('country', '')
        language = user_data.get('language', '')
        major = user_data.get('major', '')
        grade = user_data.get('grade', '')

        # Add the user's message to the thread with additional context
        assistant_prompt = f"Answer the following question in {language}, based on a {grade}-year-old {major} student from {country}."
        client.beta.threads.messages.create(
            thread_id=thread_id,
            role="user",
            content=f"{assistant_prompt}\n\nUser: {text}",
        )

        # Stream the assistant's response
        event_handler = EventHandler()

        try:
            with client.beta.threads.runs.stream(
                thread_id=thread_id,
                assistant_id=assistant_id,
                event_handler=event_handler,
            ) as stream:
                stream.until_done()

            assistant_reply = event_handler.final_response

        except Exception as e:
            logger.error(f"OpenAI API error: {e}")
            assistant_reply = "Sorry, I couldn't process your request."

        # Remove content within 【】 from the assistant's reply
        assistant_reply_cleaned = re.sub(r'【.*?】', '', assistant_reply)

        # Store the assistant's reply in Firebase (optional)
        fdb.put_async(user_chat_path, None, {"assistant_reply": assistant_reply_cleaned})

        reply_message = assistant_reply_cleaned.strip()

    # Send the reply to the user via LINE
    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        line_bot_api.reply_message(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text=reply_message)],
            )
        )

    return "OK"

@handler.add(MessageEvent, message=ImageMessageContent)
def handle_github_message(event):
    image_content = b""
    with ApiClient(configuration) as api_client:
        line_bot_blob_api = MessagingApiBlob(api_client)
        image_content = line_bot_blob_api.get_message_content(event.message.id)
    image_data = check_image(b_image=image_content)
    image_data = json.loads(image_data)
    logger.info("---- Image handler JSON ----")
    logger.info(image_data)
    g_url = create_gcal_url(
        image_data["title"],
        image_data["time"],
        image_data["location"],
        image_data["content"],
    )
    reply_msg = shorten_url_by_reurl_api(g_url)

    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        line_bot_api.reply_message(
            ReplyMessageRequest(
                replyToken=event.reply_token, messages=[TextMessage(text=reply_msg)]
            )
        )
    return "OK"
    
# Entry point to run the application
if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "test":
        local_test()  # Run local test if 'test' argument is provided
    else:
        port = int(os.getenv("PORT", 8080))
        debug = os.getenv("API_ENV") == "develop"
        logging.info("Starting the application...")
        uvicorn.run("main:app", host="0.0.0.0", port=port, reload=debug)
