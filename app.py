import logging
import mimetypes
import os
from typing import Any, Dict, List, Optional, Tuple

import requests
from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException, Request
from google import genai
from google.genai import types

load_dotenv()

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger("gemini-telegram-ocr-bot")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
WEBHOOK_BASE_URL = os.getenv("WEBHOOK_BASE_URL") or os.getenv("RENDER_EXTERNAL_URL", "")
TELEGRAM_WEBHOOK_SECRET = os.getenv("TELEGRAM_WEBHOOK_SECRET", "")
AUTO_SET_WEBHOOK = os.getenv("AUTO_SET_WEBHOOK", "true").lower() == "true"
MAX_FILE_SIZE_MB = int(os.getenv("MAX_FILE_SIZE_MB", "15"))

if not TELEGRAM_BOT_TOKEN:
    logger.warning("TELEGRAM_BOT_TOKEN is not set yet.")
if not GEMINI_API_KEY:
    logger.warning("GEMINI_API_KEY is not set yet.")

TELEGRAM_API_BASE = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"
TELEGRAM_FILE_BASE = f"https://api.telegram.org/file/bot{TELEGRAM_BOT_TOKEN}"
GEMINI_CLIENT = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None

OCR_PROMPT = """You are a precise OCR engine.
Extract all visible text from the provided file.
Rules:
1. Preserve line breaks as much as possible.
2. Do not summarize.
3. Do not translate.
4. If there is a table, output it in readable plain text.
5. If any portion is unclear, make your best effort and mark uncertain parts with [?].
6. If there is no readable text, reply exactly with: NO_READABLE_TEXT
"""

HELP_TEXT = (
    "আমাকে ছবি বা PDF পাঠান, আমি OCR করে text বের করে দেব।\n\n"
    "কাজের নিয়ম:\n"
    "- photo পাঠালে text extract করব\n"
    "- image file / PDF document পাঠালেও কাজ করবে\n"
    "- চাইলে caption-এ extra instruction দিতে পারেন\n\n"
    "উদাহরণ:\n"
    "1) শুধু ছবি পাঠান\n"
    "2) PDF পাঠিয়ে caption দিন: only extract invoice total"
)

app = FastAPI(title="Gemini Telegram OCR Bot")


def chunk_text(text: str, max_length: int = 4000) -> List[str]:
    if len(text) <= max_length:
        return [text]

    chunks: List[str] = []
    current = ""
    for line in text.splitlines(True):
        if len(current) + len(line) > max_length:
            if current:
                chunks.append(current)
                current = ""
        if len(line) > max_length:
            start = 0
            while start < len(line):
                chunks.append(line[start : start + max_length])
                start += max_length
        else:
            current += line
    if current:
        chunks.append(current)
    return chunks


def telegram_request(method: str, *, json_payload: Optional[Dict[str, Any]] = None, data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    if not TELEGRAM_BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is missing")

    url = f"{TELEGRAM_API_BASE}/{method}"
    response = requests.post(url, json=json_payload, data=data, timeout=60)
    response.raise_for_status()
    payload = response.json()
    if not payload.get("ok"):
        raise RuntimeError(f"Telegram API error on {method}: {payload}")
    return payload["result"]


def send_message(chat_id: int, text: str, reply_to_message_id: Optional[int] = None) -> None:
    safe_text = text.strip() or "কোনো text detect হয়নি।"
    for idx, chunk in enumerate(chunk_text(safe_text)):
        payload: Dict[str, Any] = {
            "chat_id": chat_id,
            "text": chunk,
        }
        if idx == 0 and reply_to_message_id:
            payload["reply_to_message_id"] = reply_to_message_id
        telegram_request("sendMessage", json_payload=payload)


def send_chat_action(chat_id: int, action: str = "typing") -> None:
    payload = {"chat_id": chat_id, "action": action}
    telegram_request("sendChatAction", json_payload=payload)


def get_file_bytes(file_id: str) -> Tuple[bytes, str]:
    file_info = telegram_request("getFile", json_payload={"file_id": file_id})
    file_path = file_info["file_path"]
    response = requests.get(f"{TELEGRAM_FILE_BASE}/{file_path}", timeout=120)
    response.raise_for_status()
    return response.content, file_path


def detect_supported_file(message: Dict[str, Any]) -> Tuple[str, str, str]:
    if message.get("photo"):
        photo_sizes = message["photo"]
        best_photo = max(photo_sizes, key=lambda x: x.get("file_size", 0))
        return best_photo["file_id"], "image/jpeg", "photo.jpg"

    document = message.get("document")
    if not document:
        raise ValueError("No supported media found")

    file_id = document["file_id"]
    file_name = document.get("file_name", "document")
    mime_type = document.get("mime_type") or mimetypes.guess_type(file_name)[0] or "application/octet-stream"

    allowed_prefixes = ("image/",)
    allowed_exact = {"application/pdf"}
    if not (mime_type.startswith(allowed_prefixes) or mime_type in allowed_exact):
        raise ValueError("Only images and PDF documents are supported")

    return file_id, mime_type, file_name


def build_ocr_prompt(extra_instruction: str = "") -> str:
    extra_instruction = (extra_instruction or "").strip()
    if not extra_instruction:
        return OCR_PROMPT
    return f"{OCR_PROMPT}\nAdditional user instruction: {extra_instruction}"


def run_gemini_ocr(file_bytes: bytes, mime_type: str, extra_instruction: str = "") -> str:
    if GEMINI_CLIENT is None:
        raise RuntimeError("GEMINI_API_KEY is missing")

    part = types.Part.from_bytes(data=file_bytes, mime_type=mime_type)
    response = GEMINI_CLIENT.models.generate_content(
        model=GEMINI_MODEL,
        contents=[part, build_ocr_prompt(extra_instruction)],
    )
    text = (response.text or "").strip()
    if text == "NO_READABLE_TEXT":
        return "কোনো readable text পাওয়া যায়নি।"
    return text or "কোনো text পাওয়া যায়নি।"


def set_webhook() -> Dict[str, Any]:
    base_url = (WEBHOOK_BASE_URL or "").rstrip("/")
    if not base_url:
        raise RuntimeError("WEBHOOK_BASE_URL or RENDER_EXTERNAL_URL is required to set webhook")

    webhook_url = f"{base_url}/telegram/webhook"
    data: Dict[str, Any] = {
        "url": webhook_url,
        "drop_pending_updates": "true",
    }
    if TELEGRAM_WEBHOOK_SECRET:
        data["secret_token"] = TELEGRAM_WEBHOOK_SECRET

    result = telegram_request("setWebhook", data=data)
    logger.info("Webhook set to %s", webhook_url)
    return result


def handle_text_command(message: Dict[str, Any]) -> bool:
    text = (message.get("text") or "").strip()
    if not text:
        return False

    chat_id = message["chat"]["id"]
    message_id = message.get("message_id")
    command = text.split()[0].lower()

    if command in {"/start", "/help"}:
        send_message(chat_id, HELP_TEXT, reply_to_message_id=message_id)
        return True

    if command == "/setwebhook":
        try:
            result = set_webhook()
            send_message(chat_id, f"Webhook updated successfully.\n\n{result}", reply_to_message_id=message_id)
        except Exception as exc:
            logger.exception("Failed to set webhook")
            send_message(chat_id, f"Webhook set করতে সমস্যা হয়েছে: {exc}", reply_to_message_id=message_id)
        return True

    return False


def process_message(message: Dict[str, Any]) -> None:
    chat_id = message["chat"]["id"]
    message_id = message.get("message_id")

    if handle_text_command(message):
        return

    if not message.get("photo") and not message.get("document"):
        send_message(chat_id, "ছবি বা PDF পাঠান। `/help` দিলে usage দেখাবো।", reply_to_message_id=message_id)
        return

    try:
        file_id, mime_type, file_name = detect_supported_file(message)
        file_bytes, remote_path = get_file_bytes(file_id)

        file_size_mb = len(file_bytes) / (1024 * 1024)
        if file_size_mb > MAX_FILE_SIZE_MB:
            send_message(
                chat_id,
                f"ফাইলটি অনেক বড় ({file_size_mb:.2f} MB)। MAX_FILE_SIZE_MB এখন {MAX_FILE_SIZE_MB} MB সেট করা আছে।",
                reply_to_message_id=message_id,
            )
            return

        logger.info("Processing file %s (%s) from %s", file_name, mime_type, remote_path)
        send_chat_action(chat_id, action="typing")

        extra_instruction = message.get("caption", "")
        ocr_text = run_gemini_ocr(file_bytes, mime_type, extra_instruction)
        send_message(chat_id, ocr_text, reply_to_message_id=message_id)

    except ValueError as exc:
        send_message(chat_id, str(exc), reply_to_message_id=message_id)
    except Exception as exc:
        logger.exception("OCR processing failed")
        send_message(chat_id, f"প্রসেস করতে সমস্যা হয়েছে: {exc}", reply_to_message_id=message_id)


@app.on_event("startup")
def on_startup() -> None:
    logger.info("Starting Gemini Telegram OCR Bot")
    if AUTO_SET_WEBHOOK and TELEGRAM_BOT_TOKEN and (WEBHOOK_BASE_URL or os.getenv("RENDER_EXTERNAL_URL")):
        try:
            set_webhook()
        except Exception:
            logger.exception("Auto webhook setup failed during startup")


@app.get("/")
def root() -> Dict[str, Any]:
    return {
        "ok": True,
        "service": "gemini-telegram-ocr-bot",
        "model": GEMINI_MODEL,
    }


@app.get("/healthz")
def healthz() -> Dict[str, Any]:
    return {"ok": True}


@app.get("/set-webhook")
def manual_set_webhook() -> Dict[str, Any]:
    try:
        result = set_webhook()
        return {"ok": True, "result": result}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/telegram/webhook")
async def telegram_webhook(
    request: Request,
    x_telegram_bot_api_secret_token: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    if TELEGRAM_WEBHOOK_SECRET and x_telegram_bot_api_secret_token != TELEGRAM_WEBHOOK_SECRET:
        raise HTTPException(status_code=403, detail="Invalid secret token")

    update = await request.json()
    message = update.get("message") or update.get("edited_message")

    if message:
        process_message(message)

    return {"ok": True}
