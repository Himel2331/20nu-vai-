# Gemini Telegram OCR Bot

A GitHub-ready Telegram OCR bot built with **FastAPI + Gemini API**.
It accepts **photos, image files, and PDFs** from Telegram, extracts the text with Gemini, and replies back in chat.

## Features

- OCR for Telegram photos
- OCR for image documents (`jpg`, `jpeg`, `png`, `webp`, etc.)
- OCR for PDF files
- Optional caption-based instructions
- Render-ready deployment with `render.yaml`
- Auto webhook setup on startup
- Manual webhook endpoint: `/set-webhook`

## Project Structure

```text
.
├── app.py
├── requirements.txt
├── .env.example
├── render.yaml
├── .gitignore
└── README.md
```

## 1) Create the Telegram bot

1. Open Telegram and talk to **@BotFather**
2. Run `/newbot`
3. Copy the bot token

## 2) Get your Gemini API key

Create a Gemini API key from Google AI Studio and keep it in your environment variables.

## 3) Local setup

```bash
git clone <your-repo-url>
cd gemini-telegram-ocr-bot
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
```

Then edit `.env`:

```env
TELEGRAM_BOT_TOKEN=your_bot_token
GEMINI_API_KEY=your_gemini_api_key
GEMINI_MODEL=gemini-2.5-flash
WEBHOOK_BASE_URL=https://your-public-url.com
TELEGRAM_WEBHOOK_SECRET=change_this_secret_token
AUTO_SET_WEBHOOK=true
MAX_FILE_SIZE_MB=15
LOG_LEVEL=INFO
```

Run locally:

```bash
uvicorn app:app --reload --host 0.0.0.0 --port 8000
```

## 4) Deploy to Render

### Option A — easiest (with Blueprint)

1. Push this project to GitHub
2. Go to Render
3. Create a **Blueprint** from your repo
4. Render will detect `render.yaml`
5. Add these secret env vars:
   - `TELEGRAM_BOT_TOKEN`
   - `GEMINI_API_KEY`
6. Redeploy

If you leave `WEBHOOK_BASE_URL` empty on Render, the app can use `RENDER_EXTERNAL_URL` automatically.

### Option B — manual web service

Create a new **Web Service** on Render with:

- **Build Command**: `pip install -r requirements.txt`
- **Start Command**: `uvicorn app:app --host 0.0.0.0 --port $PORT`
- **Health Check Path**: `/healthz`

Add env vars:

```env
TELEGRAM_BOT_TOKEN=your_bot_token
GEMINI_API_KEY=your_gemini_api_key
GEMINI_MODEL=gemini-2.5-flash
TELEGRAM_WEBHOOK_SECRET=your_secret_token
AUTO_SET_WEBHOOK=true
MAX_FILE_SIZE_MB=15
LOG_LEVEL=INFO
```

Optional:

```env
WEBHOOK_BASE_URL=https://your-app.onrender.com
```

## 5) Webhook setup

The app tries to auto-set the Telegram webhook on startup.

If you want to set it manually after deployment, open:

```text
https://your-app.onrender.com/set-webhook
```

Or send `/setwebhook` to the bot.

## 6) How to use

- Send a **photo** → the bot extracts the text
- Send an **image file** → the bot extracts the text
- Send a **PDF** → the bot extracts the text
- Add a caption for extra instruction

Example caption:

```text
only extract invoice total and date
```

## Notes

- The bot splits long OCR output into multiple Telegram messages.
- If no readable text is detected, it will say so.
- By default, the bot uses `gemini-2.5-flash`, but you can switch with `GEMINI_MODEL`.

## GitHub push

```bash
git init
git add .
git commit -m "Initial commit: Gemini Telegram OCR bot"
git branch -M main
git remote add origin <your-github-repo-url>
git push -u origin main
```
