# CLAUDE.MD - Neurolous Open Source Agent

## Project Context
**Neurolous Open Source** is a local-first, privacy-focused Anthropologic Agent framework. It runs entirely offline on Apple Silicon (Mac Mini M4) using FastAPI, Ollama (Gemma), and Chatterbox.

**Current Status:**
- [x] Backend (FastAPI + RAG)
- [x] Admin UI (Configuration)
- [x] Documentation (Dashboard)
- [ ] **Frontend (Flutter Mobile App)** - *Active Priority*

## 1. Ethical Guidelines (CRITICAL)
- **Rights:** You must possess the legal rights (consent or inheritance) to the voice and likeness of the persona.
- **Privacy:** This architecture is designed to run offline. Do not add cloud logging.
- **Labeling:** The agent is a simulation/griefbot, not a sentient being.

## 2. Completed Tasks
1.  [x] **Flutter Project Generation:** Created `mobile/pubspec.yaml` and `mobile/lib/main.dart` for the client app.
2.  [x] **Enhance `README.md`:** Complete guide with clone, venv, requirements, and server instructions.
3.  [x] **Generate `requirements.txt`:** Created `backend/requirements.txt` with all Python dependencies.
4.  [x] **Fix Dashboard:** Dashboard now shows memory stats (facts, philosophy, voice) and conversation counts from SQLite.
5.  [x] **Update Dashboard:** Enhanced "Client App" section in `neurolous_implementation_guide.html` with full Flutter build instructions.
6.  [x] **Update Admin:** Added consistent navigation header matching the dashboard page.

## 3. Configuration & Setup
- **Admin Panel:** `http://localhost:8000/admin`
- **Manual Config:** `config/persona.json`
- **Voice:** Place a 7-second WAV file in `../VoiceCloning/voice_samples/` to enable TTS.

## 4. Implementation Roadmap: Flutter Frontend
**Goal:** Create a mobile client to connect to the FastAPI backend.

### Tech Stack
- **Framework:** Flutter (Dart)
- **Target:** iOS (Primary), Android
- **Dependencies:** `http`, `speech_to_text`, `audioplayers`, `permission_handler`, `shared_preferences`.

### Feature Requirements
1.  **Connection Settings:** Input Backend IP (e.g., `http://192.168.1.X:8000`).
2.  **Chat Interface:** Clean Medical/Tech UI (Cyan/Indigo gradients).
3.  **Voice Input:** "Hold to Speak" -> STT -> Backend.
4.  **Audio Handling:** Auto-play WAV responses.