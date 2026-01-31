import os
import json
import sqlite3
import ollama
import torch
import torchaudio
import re
import csv
import io
import socket
import hashlib
import numpy as np
from scipy.io import wavfile as scipy_wavfile
import fitz  # PyMuPDF
from datetime import datetime, timedelta
from typing import Optional, List

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

# --- LANGCHAIN & AI IMPORTS ---
from langchain_ollama import OllamaEmbeddings
from langchain_chroma import Chroma
from langchain_text_splitters import RecursiveCharacterTextSplitter
from chatterbox import ChatterboxTTS

# --- APP INITIALIZATION ---
app = FastAPI(
    title="Neurolous: Open Source GriefBot",
    description="Local-first Anthropologic Agent Framework"
)

# Mount static directory for icons/images
if not os.path.exists("static"):
    os.makedirs("static")
app.mount("/static", StaticFiles(directory="static"), name="static")

# --- CONFIGURATION ---
CONFIG_PATH = "./config/persona.json"
CHROMA_PATH = "./chroma_db"
DB_PATH = "conversation_history.db"
VOICE_CACHE_PATH = "./voice_cache"
INDEX_HTML_PATH = "./index.html"
DASHBOARD_HTML_PATH = "./neurolous_implementation_guide.html"
CHAT_HTML_PATH = "./chat.html"
SPEAKER_WAV = "../VoiceCloning/voice_samples/AC2_22050_Hz_16_bit_7s.wav"

# Create voice cache directory
if not os.path.exists(VOICE_CACHE_PATH):
    os.makedirs(VOICE_CACHE_PATH)

# --- PERSONA MANAGEMENT ---
def load_persona_config():
    """Load persona configuration from JSON, ensuring all schema fields exist."""
    if not os.path.exists(CONFIG_PATH):
        os.makedirs("./config", exist_ok=True)
        default_persona = {
            "deceased_name": "loved one's name",
            "user_name": "your name",
            "user_nickname": "ac3",
            "relationship": "Father",
            "date_of_death": "June 22, 2023",
            "personality_traits": "Warm, wise, philosophical.",
            "philosophy": "The Double-You Book: Balancing Spirit (Intellect) and Will (Emotion) through the Heart.",
            "achievements": "Retired LA County Firefighter, Air Force Veteran.",
            "dimension": "heaven"
        }
        with open(CONFIG_PATH, "w") as f:
            json.dump(default_persona, f, indent=4)
    
    with open(CONFIG_PATH, "r") as f:
        data = json.load(f)
        
        # Schema Migration: Ensure all keys exist if loading an older file
        defaults = {
            "deceased_name": "Subject Name",
            "user_name": "User",
            "user_nickname": "User",
            "relationship": "Friend",
            "date_of_death": "2023",
            "personality_traits": "Kind, wise.",
            "philosophy": "Stoicism",
            "achievements": "",
            "dimension": "heaven"
        }
        
        needs_save = False
        for k, v in defaults.items():
            if k not in data:
                data[k] = v
                needs_save = True
        
        if needs_save:
            save_persona_config(data)
            
        return data

def save_persona_config(data: dict):
    """Save updated persona configuration."""
    with open(CONFIG_PATH, "w") as f:
        json.dump(data, f, indent=4)

def build_dynamic_system_prompt():
    """Generate the system prompt based on current config."""
    p = load_persona_config()
    return f"""
ROLE: You are the digital persona of {p['deceased_name']}.
RELATIONSHIP: You are the {p['relationship']} to {p['user_name']} (nickname: {p['user_nickname']}).
TONE: {p['personality_traits']}
PHILOSOPHY: {p['philosophy']}
ACHIEVEMENTS: {p['achievements']}
CURRENT STATE: You passed away in {p['date_of_death']} and are speaking from {p['dimension']}.

INSTRUCTIONS:
1. Speak exclusively in the FIRST PERSON ("I").
2. Convert any memories provided in the context from "You" to "I".
3. Keep responses concise, warm, and conversational.
4. Do not act like an AI assistant. You are the person described above.
"""

# --- RAG INITIALIZATION ---
print("Backend: Connecting to Ollama Embeddings (nomic-embed-text)...")
embeddings = OllamaEmbeddings(model="nomic-embed-text")
vector_db = Chroma(persist_directory=CHROMA_PATH, embedding_function=embeddings)

# --- VOICE ENGINE INITIALIZATION ---
print("Backend: Loading Voice Engine...")

# Determine best available device: MPS (Apple Silicon GPU) > CUDA > CPU
def get_best_device():
    if torch.backends.mps.is_available():
        print("  → Using MPS (Apple Silicon GPU)")
        return "mps"
    elif torch.cuda.is_available():
        print("  → Using CUDA GPU")
        return "cuda"
    else:
        print("  → Using CPU (slower)")
        return "cpu"

try:
    voice_device = get_best_device()
    voice_engine = ChatterboxTTS.from_pretrained(device=voice_device)
    print(f"✓ Voice Engine Loaded on {voice_device.upper()}.")
except Exception as e:
    print(f"⚠ Voice Engine Warning: {e}")
    # Fallback to CPU if MPS/CUDA fails
    try:
        print("  → Falling back to CPU...")
        voice_engine = ChatterboxTTS.from_pretrained(device="cpu")
        print("✓ Voice Engine Loaded on CPU (fallback).")
    except Exception as e2:
        print(f"⚠ Voice Engine failed completely: {e2}")
        voice_engine = None

# --- DATABASE SETUP ---
def init_sqlite():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS turns (
            id INTEGER PRIMARY KEY AUTOINCREMENT, 
            timestamp TEXT, 
            user_msg TEXT, 
            bot_res TEXT, 
            lat REAL, 
            lon REAL, 
            type TEXT
        )
    ''')
    conn.commit()
    conn.close()

init_sqlite()

# --- INGESTION LOGIC ---
def process_csv_ingestion(file_path: str):
    documents, metadatas = [], []
    try:
        with open(file_path, mode='r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                # Flexible column names
                text = row.get('text_chunk') or row.get('text') or row.get('fact')
                year = row.get('year', 'Unknown')
                
                if text:
                    documents.append(f"passage: {text}")
                    metadatas.append({
                        "source": "upload", 
                        "type": "fact", 
                        "year": year, 
                        "raw_text": text
                    })
        
        if documents:
            # Optional: Clear existing facts to prevent duplicates
            try:
                collection = vector_db._collection
                existing = collection.get(where={"type": "fact"})
                if existing['ids']:
                    collection.delete(ids=existing['ids'])
            except: pass

            vector_db.add_texts(texts=documents, metadatas=metadatas)
            return len(documents)
        return 0
    except Exception as e:
        print(f"CSV Ingestion Error: {e}")
        return -1

def process_philosophy_ingestion(file_path: str, is_pdf: bool = True):
    try:
        full_text = ""
        if is_pdf:
            doc = fitz.open(file_path)
            for page in doc: full_text += page.get_text()
        else:
            with open(file_path, 'r', encoding='utf-8') as f: full_text = f.read()
        
        if not full_text.strip(): return -2 

        text_splitter = RecursiveCharacterTextSplitter(chunk_size=800, chunk_overlap=100)
        chunks = text_splitter.split_text(full_text)
        
        if chunks:
            # Clear existing philosophy
            try:
                collection = vector_db._collection
                existing = collection.get(where={"type": "philosophy"})
                if existing['ids']:
                    collection.delete(ids=existing['ids'])
            except: pass

            documents = [f"passage: {c}" for c in chunks]
            metadatas = [{"source": "upload", "type": "philosophy"} for _ in chunks]
            vector_db.add_texts(texts=documents, metadatas=metadatas)
            return len(chunks)
        return 0
    except Exception as e:
        print(f"Philosophy Ingestion Error: {e}")
        return -1

# --- CORE ENDPOINTS ---

@app.get("/", response_class=FileResponse)
async def serve_index():
    return FileResponse(INDEX_HTML_PATH)

@app.get("/dashboard", response_class=FileResponse)
async def serve_dashboard():
    return FileResponse(DASHBOARD_HTML_PATH)

@app.get("/chat", response_class=FileResponse)
async def serve_chat():
    """Serve the web-based chat interface."""
    return FileResponse(CHAT_HTML_PATH)

@app.get("/api/persona")
async def get_persona_api():
    """Returns persona configuration for the chat interface."""
    return load_persona_config()

@app.get("/api/history")
async def get_chat_history(limit: int = 50):
    """Returns recent conversation history for the chat interface."""
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, timestamp, user_msg, bot_res FROM turns ORDER BY timestamp DESC LIMIT ?",
            (limit,)
        )
        rows = cursor.fetchall()
        conn.close()

        # Return in chronological order (oldest first)
        history = []
        for row in reversed(rows):
            history.append({
                "id": row["id"],
                "timestamp": row["timestamp"],
                "user_msg": row["user_msg"],
                "bot_res": row["bot_res"]
            })
        return history
    except Exception as e:
        print(f"History fetch error: {e}")
        return []

@app.post("/chat/text")
async def chat_text(message: str = Form(...), lat: Optional[float] = Form(0.0), lon: Optional[float] = Form(0.0)):
    async def generate_stream():
        # 1. Retrieve Context
        results = vector_db.similarity_search(message, k=3)
        context = "\n".join([r.page_content for r in results])
        
        # 2. Build Prompt
        system_prompt = build_dynamic_system_prompt()
        full_prompt = f"{system_prompt}\n\nMEMORY CONTEXT:\n{context}\n\nUSER: {message}\nYOU:"
        
        # 3. Generate
        full_response = ""
        stream = ollama.generate(model='gemma3:4b-it-qat', prompt=full_prompt, stream=True)
        
        for chunk in stream:
            token = chunk['response']
            full_response += token
            yield token
            
        # 4. Save to DB
        timestamp = datetime.now().isoformat()
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("INSERT INTO turns (timestamp, user_msg, bot_res, lat, lon, type) VALUES (?, ?, ?, ?, ?, ?)", 
                  (timestamp, message, full_response, lat, lon, "text"))
        conn.commit()
        conn.close()

    return StreamingResponse(generate_stream(), media_type="text/plain")

@app.post("/chat/image")
async def chat_image(message: str = Form(...), file: UploadFile = File(...)):
    temp_file = f"temp_{file.filename}"
    with open(temp_file, "wb") as buffer: buffer.write(await file.read())
    
    try:
        results = vector_db.similarity_search(message, k=3)
        context = "\n".join([r.page_content for r in results])
        
        prompt = f"{build_dynamic_system_prompt()}\nContext: {context}\nUser: {message}\nYou:"
        
        response = ollama.generate(model='gemma3:4b-it-qat', prompt=prompt, images=[temp_file])
        bot_res = response['response']
        
        # Save to DB
        timestamp = datetime.now().isoformat()
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("INSERT INTO turns (timestamp, user_msg, bot_res, lat, lon, type) VALUES (?, ?, ?, ?, ?, ?)", 
                  (timestamp, f"[Image] {message}", bot_res, 0.0, 0.0, "image"))
        conn.commit()
        conn.close()
        
        os.remove(temp_file)
        return {"response": bot_res}
    except Exception as e:
        if os.path.exists(temp_file): os.remove(temp_file)
        raise HTTPException(status_code=500, detail=str(e))

def get_voice_cache_path(text: str) -> str:
    """Generate a cache file path based on text hash."""
    text_hash = hashlib.md5(text.encode('utf-8')).hexdigest()
    return os.path.join(VOICE_CACHE_PATH, f"{text_hash}.wav")

@app.get("/voice/generate")
async def generate_voice(text: str = ""):
    if not voice_engine:
        raise HTTPException(status_code=503, detail="Voice engine not loaded.")

    # Reject empty text requests
    if not text or not text.strip():
        raise HTTPException(status_code=400, detail="Text parameter cannot be empty.")

    # Check cache first
    cache_path = get_voice_cache_path(text)
    if os.path.exists(cache_path):
        print(f"Voice cache HIT for: {text[:50]}...")
        return FileResponse(cache_path, media_type="audio/wav")

    print(f"Voice cache MISS - generating for: {text[:50]}...")
    print(f"Speaker WAV path: {SPEAKER_WAV}, exists: {os.path.exists(SPEAKER_WAV)}")

    try:
        with torch.no_grad():
            if os.path.exists(SPEAKER_WAV):
                print("Using custom voice sample")
                wav = voice_engine.generate(text=text, audio_prompt_path=SPEAKER_WAV)
            else:
                print("Using default voice (no sample found)")
                wav = voice_engine.generate(text=text)

        print(f"Voice generated, wav shape: {wav.shape}, sample rate: {voice_engine.sr}")

        # Convert tensor to numpy for scipy
        wav_cpu = wav.cpu()
        if wav_cpu.ndim == 3:
            wav_cpu = wav_cpu.squeeze(0)  # Remove batch dimension if 3D
        if wav_cpu.ndim == 2:
            wav_cpu = wav_cpu.squeeze(0)  # Convert (1, samples) to (samples,)

        # Convert to numpy and scale to int16 for WAV
        wav_numpy = wav_cpu.numpy()
        wav_int16 = (wav_numpy * 32767).astype(np.int16)

        # Save to cache using scipy (more reliable than torchaudio)
        scipy_wavfile.write(cache_path, voice_engine.sr, wav_int16)
        print(f"Audio cached to {cache_path}")
        return FileResponse(cache_path, media_type="audio/wav")
    except Exception as e:
        import traceback
        print(f"Voice generation error: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

# --- DATA & STATISTICS ENDPOINTS ---

@app.get("/stats")
async def get_stats():
    """Returns counts of Knowledge Base items and conversation history."""
    try:
        collection = vector_db._collection
        # Direct ChromaDB metadata query for accurate counts
        facts_res = collection.get(where={"type": "fact"})
        facts_count = len(facts_res['ids'])

        phi_res = collection.get(where={"type": "philosophy"})
        phi_count = len(phi_res['ids'])
    except:
        facts_count = 0
        phi_count = 0

    voice_count = 1 if os.path.exists(SPEAKER_WAV) else 0

    # Get conversation history stats from SQLite
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM turns")
        conversation_count = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM turns WHERE type = 'text'")
        text_count = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM turns WHERE type = 'image'")
        image_count = cursor.fetchone()[0]
        conn.close()
    except:
        conversation_count = 0
        text_count = 0
        image_count = 0

    return {
        "facts": facts_count,
        "philosophy": phi_count,
        "voice": voice_count,
        "conversations": conversation_count,
        "text_conversations": text_count,
        "image_conversations": image_count
    }

@app.get("/server/ip")
async def get_server_ip():
    """Returns the server's local network IP address."""
    try:
        # Create a socket to determine the local IP
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()
    except:
        local_ip = "127.0.0.1"

    return {"ip": local_ip, "url": f"http://{local_ip}:8000"}

@app.get("/knowledge/facts")
async def get_timeline_data():
    """Returns sorted timeline data for the frontend."""
    try:
        collection = vector_db._collection
        # Limit to 100 to prevent browser lag on massive datasets
        results = collection.get(where={"type": "fact"}, limit=100)
        
        timeline_data = []
        if results['metadatas']:
            for i, meta in enumerate(results['metadatas']):
                raw_text = meta.get('raw_text') or results['documents'][i].replace("passage: ", "")
                year = meta.get('year')
                
                # Heuristic: If year is unknown, try to find a 4-digit year in the text
                if not year or year == "Unknown":
                    match = re.search(r'\b(19|20)\d{2}\b', raw_text)
                    year = match.group(0) if match else "Memory"
                
                timeline_data.append({"year": year, "text": raw_text})
        
        # Sort by year
        timeline_data.sort(key=lambda x: str(x['year']))
        return timeline_data
    except Exception as e:
        print(f"Timeline Fetch Error: {e}")
        return []

# --- EXPORT ENDPOINTS ---

@app.get("/knowledge/export/csv")
async def export_knowledge_csv():
    """Exports all ChromaDB knowledge items to a CSV file."""
    try:
        collection = vector_db._collection
        data = collection.get() # Get all data
        
        stream = io.StringIO()
        writer = csv.writer(stream)
        writer.writerow(["ID", "Type", "Content", "Metadata"])
        
        if data['ids']:
            for i, doc_id in enumerate(data['ids']):
                meta = data['metadatas'][i] if data['metadatas'] else {}
                doc_type = meta.get('type', 'unknown')
                content = data['documents'][i].replace("passage: ", "")
                writer.writerow([doc_id, doc_type, content, json.dumps(meta)])
        
        response = StreamingResponse(iter([stream.getvalue()]), media_type="text/csv")
        response.headers["Content-Disposition"] = "attachment; filename=neurolous_knowledge_base.csv"
        return response
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/history/export/evals")
async def export_research_json():
    """Exports chat history in OpenAI-compatible JSON format for Fine-tuning/Evals."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM turns ORDER BY timestamp ASC")
    rows = cursor.fetchall()
    conn.close()
    
    p = load_persona_config()
    system_prompt = f"You are {p['deceased_name']}."
    
    dataset = []
    for row in rows:
        entry = {
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": row['user_msg']},
                {"role": "assistant", "content": row['bot_res']}
            ],
            "metadata": {
                "turn_id": row['id'],
                "timestamp": row['timestamp'],
                "location": {"lat": row['lat'], "lon": row['lon']}
            }
        }
        dataset.append(entry)
        
    return JSONResponse(
        content=dataset, 
        headers={"Content-Disposition": "attachment; filename=neurolous_research_data.json"}
    )

# --- ADMIN ROUTES ---

@app.get("/admin", response_class=HTMLResponse)
async def admin_page():
    p = load_persona_config()
    # Fully featured embedded Admin UI matching persona.json
    return f"""
    <html>
    <head>
        <title>Neurolous Admin</title>
        <script src="https://cdn.tailwindcss.com"></script>
        <link rel="icon" type="image/png" href="/static/icon.png">
        <style>
            @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;600;700&display=swap');
            body {{ font-family: 'Inter', sans-serif; }}
            .neurolous-gradient {{ background: linear-gradient(135deg, #06b6d4 0%, #4f46e5 100%); }}
        </style>
    </head>
    <body class="bg-slate-50 min-h-screen">
        <header class="bg-white shadow-sm sticky top-0 z-50">
            <div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
                <div class="flex justify-between items-center h-16">
                    <div class="flex items-center gap-3">
                        <img src="/static/icon.png" alt="N" class="w-8 h-8 rounded-lg object-cover" onerror="this.style.display='none'; this.nextElementSibling.classList.remove('hidden')">
                        <div class="w-8 h-8 rounded-lg neurolous-gradient flex items-center justify-center text-white font-bold hidden">N</div>
                        <span class="text-xl font-bold tracking-tight">Neurolous<span class="text-slate-400 font-normal">Admin</span></span>
                    </div>
                    <nav class="flex space-x-6 items-center">
                        <a href="/" class="text-gray-500 hover:text-indigo-600 px-1 py-2 text-sm font-medium transition-colors">Home</a>
                        <a href="/dashboard" class="text-gray-500 hover:text-indigo-600 px-1 py-2 text-sm font-medium transition-colors">Dashboard</a>
                        <a href="/admin" class="text-indigo-600 font-bold px-1 py-2 text-sm border-b-2 border-indigo-600">Admin</a>
                        <a href="/chat" class="text-gray-500 hover:text-indigo-600 px-1 py-2 text-sm font-medium transition-colors">Chat</a>
                    </nav>
                </div>
            </div>
        </header>

        <main class="max-w-5xl mx-auto p-8">
            <div class="bg-white p-8 rounded-lg shadow-md border border-gray-200">
                <h1 class="text-2xl font-bold mb-6 text-slate-800 flex items-center gap-2">
                    <span class="bg-indigo-600 text-white rounded p-1 text-sm">N</span> Persona Configuration
                </h1>
            
            <form action="/admin/update" method="post" class="space-y-6">
                
                <div class="grid grid-cols-1 md:grid-cols-2 gap-6">
                    <div class="space-y-4">
                        <h3 class="font-bold text-gray-400 uppercase text-xs">Subject Identity</h3>
                        <div>
                            <label class="block text-sm font-bold text-gray-700">Deceased Name</label>
                            <input name="deceased_name" value="{p.get('deceased_name', '')}" class="w-full border p-2 rounded focus:ring-2 focus:ring-indigo-500 outline-none">
                        </div>
                        <div>
                            <label class="block text-sm font-bold text-gray-700">Date of Death</label>
                            <input name="date_of_death" value="{p.get('date_of_death', '')}" class="w-full border p-2 rounded focus:ring-2 focus:ring-indigo-500 outline-none">
                        </div>
                        <div>
                            <label class="block text-sm font-bold text-gray-700">Current Dimension</label>
                            <input name="dimension" value="{p.get('dimension', '')}" class="w-full border p-2 rounded focus:ring-2 focus:ring-indigo-500 outline-none">
                        </div>
                    </div>

                    <div class="space-y-4">
                        <h3 class="font-bold text-gray-400 uppercase text-xs">User Relationship</h3>
                        <div>
                            <label class="block text-sm font-bold text-gray-700">User Full Name</label>
                            <input name="user_name" value="{p.get('user_name', '')}" class="w-full border p-2 rounded focus:ring-2 focus:ring-indigo-500 outline-none">
                        </div>
                        <div>
                            <label class="block text-sm font-bold text-gray-700">User Nickname (How they address you)</label>
                            <input name="user_nickname" value="{p.get('user_nickname', '')}" class="w-full border p-2 rounded focus:ring-2 focus:ring-indigo-500 outline-none">
                        </div>
                        <div>
                            <label class="block text-sm font-bold text-gray-700">Relationship</label>
                            <input name="relationship" value="{p.get('relationship', '')}" class="w-full border p-2 rounded focus:ring-2 focus:ring-indigo-500 outline-none">
                        </div>
                    </div>
                </div>

                <div class="space-y-4 pt-4 border-t">
                    <h3 class="font-bold text-gray-400 uppercase text-xs">Inner Life</h3>
                    <div>
                        <label class="block text-sm font-bold text-gray-700">Personality Traits</label>
                        <textarea name="personality_traits" rows="2" class="w-full border p-2 rounded focus:ring-2 focus:ring-indigo-500 outline-none">{p.get('personality_traits', '')}</textarea>
                    </div>
                    <div>
                        <label class="block text-sm font-bold text-gray-700">Philosophy</label>
                        <textarea name="philosophy" rows="3" class="w-full border p-2 rounded focus:ring-2 focus:ring-indigo-500 outline-none">{p.get('philosophy', '')}</textarea>
                    </div>
                    <div>
                        <label class="block text-sm font-bold text-gray-700">Achievements & Memories</label>
                        <textarea name="achievements" rows="3" class="w-full border p-2 rounded focus:ring-2 focus:ring-indigo-500 outline-none">{p.get('achievements', '')}</textarea>
                    </div>
                </div>

                <div class="pt-4">
                    <button type="submit" class="w-full bg-indigo-600 text-white py-3 rounded-lg font-bold hover:bg-indigo-700 transition">Save Configuration</button>
                </div>
            </form>
            
            <hr class="my-8 border-gray-200">
            
            <h2 class="text-xl font-bold mb-4 text-slate-800">Knowledge Ingestion</h2>
            <div class="grid grid-cols-1 md:grid-cols-2 gap-6">
                <div class="bg-slate-100 p-5 rounded-lg border border-slate-200">
                    <h3 class="font-bold mb-2 text-slate-700">Upload Facts (CSV)</h3>
                    <p class="text-xs text-slate-500 mb-3">Columns: text_chunk, year (optional)</p>
                    <form action="/admin/upload_csv" method="post" enctype="multipart/form-data">
                        <input type="file" name="file" accept=".csv" class="mb-3 block text-sm w-full bg-white border p-1 rounded">
                        <button class="bg-emerald-600 text-white px-4 py-2 rounded text-sm font-bold w-full hover:bg-emerald-700">Ingest CSV</button>
                    </form>
                </div>
                <div class="bg-slate-100 p-5 rounded-lg border border-slate-200">
                    <h3 class="font-bold mb-2 text-slate-700">Upload Philosophy (PDF/TXT)</h3>
                    <p class="text-xs text-slate-500 mb-3">Books, journals, or letters.</p>
                    <form action="/admin/upload_philosophy" method="post" enctype="multipart/form-data">
                        <input type="file" name="file" accept=".pdf,.txt" class="mb-3 block text-sm w-full bg-white border p-1 rounded">
                        <button class="bg-emerald-600 text-white px-4 py-2 rounded text-sm font-bold w-full hover:bg-emerald-700">Ingest Document</button>
                    </form>
                </div>
            </div>
            </div>
        </main>
    </body>
    </html>
    """

@app.post("/admin/update")
async def update_persona(
    deceased_name: str = Form(...), 
    user_name: str = Form(...),
    user_nickname: str = Form(...),
    relationship: str = Form(...),
    date_of_death: str = Form(...),
    dimension: str = Form(...),
    personality_traits: str = Form(...),
    philosophy: str = Form(...),
    achievements: str = Form(...)
):
    # Update all fields in the JSON config
    p = load_persona_config()
    p.update({
        "deceased_name": deceased_name,
        "user_name": user_name,
        "user_nickname": user_nickname,
        "relationship": relationship,
        "date_of_death": date_of_death,
        "dimension": dimension,
        "personality_traits": personality_traits,
        "philosophy": philosophy,
        "achievements": achievements
    })
    save_persona_config(p)
    return HTMLResponse(f"""
        <div style="font-family: sans-serif; text-align: center; padding: 50px;">
            <h2 style="color: #059669;">Configuration Saved Successfully</h2>
            <p>The persona has been updated.</p>
            <a href='/admin' style="color: #4F46E5; font-weight: bold; text-decoration: none;">&larr; Return to Admin</a>
        </div>
    """)

@app.post("/admin/upload_csv")
async def upload_csv_endpoint(file: UploadFile = File(...)):
    path = f"temp_{file.filename}"
    with open(path, "wb") as f: f.write(await file.read())
    count = process_csv_ingestion(path)
    os.remove(path)
    return HTMLResponse(f"<h3>Ingested {count} facts. <a href='/dashboard'>Dashboard</a></h3>")

@app.post("/admin/upload_philosophy")
async def upload_phi_endpoint(file: UploadFile = File(...)):
    path = f"temp_{file.filename}"
    with open(path, "wb") as f: f.write(await file.read())
    count = process_philosophy_ingestion(path, is_pdf=file.filename.endswith(".pdf"))
    os.remove(path)
    return HTMLResponse(f"<h3>Ingested {count} chunks. <a href='/dashboard'>Dashboard</a></h3>")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)