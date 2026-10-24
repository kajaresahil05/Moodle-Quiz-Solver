# Gemini-Powered Moodle Quiz Automation Assistant

A robust, secure quiz-assistance web application with automated practice-quiz workflows, AI-powered question extraction, answer suggestions, progress tracking, and completion notifications.

**Target Stack:** Python · Playwright · FastAPI · Gemini API · SQLite · pytest

---

## ⚡ Quick Start

### 1. Prerequisites
- Python 3.12+
- Google Gemini API key (get one at [aistudio.google.com](https://aistudio.google.com))

### 2. Setup

```bash
# Navigate to project directory
cd moodle_quiz_assistant

# Create virtual environment
python -m venv venv

# Activate (Windows)
venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Install Playwright browser
playwright install chromium

# Configure API key
copy .env.example .env
# Edit .env and set: GEMINI_API_KEY=your_actual_key_here
```

### 3. Run

```bash
# Option A: Use the startup script (Windows)
start.bat

# Option B: Manual
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

Open **http://127.0.0.1:8000** in your browser.

---

## 🏗️ Project Structure

```
moodle_quiz_assistant/
├── app/
│   ├── main.py              # FastAPI app factory & lifespan
│   ├── config.py            # Settings (pydantic-settings)
│   ├── database.py          # SQLite layer (WAL mode)
│   ├── models.py            # Pydantic schemas & enums
│   ├── routes/
│   │   ├── auth.py          # Authentication: Login & Logout
│   │   ├── dashboard.py     # HTML page routes (protected)
│   │   ├── workflows.py     # REST API: workflow CRUD
│   │   └── settings.py      # REST API: health & notifications
│   └── services/
│       ├── auth_service.py      # Session & user auth management
│       ├── gemini_service.py    # Gemini API integration
│       ├── browser_service.py   # Playwright browser management
│       ├── quiz_parser.py       # Moodle DOM parser
│       ├── workflow_service.py  # Orchestration engine
│       └── notification_service.py  # Notification system
├── templates/
│   ├── base.html            # Sidebar + topbar layout
│   ├── login.html           # Moodle ID & Password login page
│   ├── dashboard.html       # Main dashboard
│   ├── workflow_detail.html # Per-workflow view
│   ├── settings.html        # Configuration page
│   └── error.html
├── static/
│   ├── css/main.css         # Premium dark UI styles
│   └── js/main.js           # Frontend logic & toasts
├── tests/
│   ├── conftest.py          # Fixtures
│   ├── test_api.py          # FastAPI integration tests
│   ├── test_auth.py         # Multi-user login & auth tests
│   ├── test_database.py     # Database CRUD tests
│   ├── test_gemini_service.py  # AI response parsing tests
│   └── test_url_validation.py  # SSRF protection tests
├── requirements.txt
├── pyproject.toml           # pytest config
├── .env.example
├── start.bat                # Quick start (Windows)
└── run_tests.bat            # Test runner (Windows)
```

---

## 🎯 Execution Modes

| Mode | Description |
|------|-------------|
| **Practice** | Extracts questions, asks Gemini for answers, and automatically clicks the suggested options. For authorized, ungraded practice quizzes only. |
| **Review** | Reads questions and shows AI suggestions without clicking anything. Safe for any quiz. |

---

## 📋 Features

- **Question Extraction** — Parses Moodle quiz pages using Playwright with resilient multi-selector fallbacks
- **AI Answer Suggestions** — Gemini provides structured JSON answers with confidence scores
- **Confidence Scores** — Each suggestion shows a 0–100% confidence rating
- **Ambiguity Detection** — Questions requiring images or unclear context are flagged for manual review
- **Auto-Submit (Practice)** — Detects confirmation dialog and submits via verified DOM selectors
- **Live Dashboard** — Real-time workflow status, progress bars, event logs
- **Desktop Notifications** — Via plyer with in-dashboard fallback
- **URL Sanitization** — Session tokens/cookies never stored in database
- **SSRF Protection** — URL validation before any navigation
- **Structured Logging** — Timestamped logs with workflow IDs

---

## 🔐 Security Notes

- API keys live only in `.env` — never in code or database
- Session cookies/tokens are never stored
- Only safe URL parameters (attempt, cmid) are persisted
- Auto-submit is protected by a confirmation dialog check
- Graded assessments should use **Review** mode only

---

## 🧪 Running Tests

```bash
# Activate venv first
venv\Scripts\activate

# Run all tests
pytest

# Or use the batch script
run_tests.bat
```

Tests use mocked Gemini outputs and temp SQLite databases — no API quota consumed.

---

## ⚙️ Configuration (.env)

| Variable | Default | Description |
|----------|---------|-------------|
| `GEMINI_API_KEY` | *(required)* | Your Google Gemini API key |
| `GEMINI_MODEL` | `gemini-2.0-flash` | Gemini model identifier |
| `APP_HOST` | `127.0.0.1` | Server bind address |
| `APP_PORT` | `8000` | Server port |
| `BROWSER_HEADLESS` | `false` | Run browser headless |
| `BROWSER_TIMEOUT_MS` | `30000` | Navigation timeout |
| `DATABASE_PATH` | `./quiz_assistant.db` | SQLite file path |

---

## 🚀 Usage

1. Log in to Moodle in the browser window that opens
2. Navigate to an authorized practice quiz and start an attempt
3. Copy the quiz URL from your browser
4. In the dashboard, click **New Workflow**
5. Paste the URL, choose **Practice** or **Review** mode
6. Click **Start Workflow** and monitor progress in real-time

---

> ⚠️ **Important:** This tool is designed for authorized practice quizzes only. Never use auto-submit on graded assessments. AI suggestions are not guaranteed to be correct.
