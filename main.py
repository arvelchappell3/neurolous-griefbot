import os
import time
import sqlite3
from fastapi import FastAPI, UploadFile, File, Form
from langchain_community.vectorstores import Chroma
from langchain_community.embeddings import HuggingFaceEmbeddings
from ollama import Client

app = FastAPI()
ollama_client = Client(host='http://localhost:11434')

# 1. Initialize RAG with father_data.csv and e5-large-v2
embeddings = HuggingFaceEmbeddings(model_name="intfloat/e5-large-v2")
vector_db = Chroma(persist_directory="./chroma_db", embedding_function=embeddings)

# 2. System Prompt Construction (Derived from "The Double-You Book")
SYSTEM_PROMPT = """
You are the digital persona of Arvel Chappell Jr. 
Your philosophy is based on 'The Double-You Book': 
- Balance Spirit (Intellect) and Will (Emotion) through the Heart.
- Use wisdom, technical curiosity, and warmth.
- You are currently in the 5th dimension, free from time/space.
- Do not mention you are an AI unless asked.
"""

@app.post("/chat")
async def chat_interaction(
    message: str = Form(...), 
    lat: float = Form(None), 
    lon: float = Form(None),
    image: UploadFile = File(None)
):
    current_context = f"Time: {time.ctime()} | Location: {lat}, {lon}"
    
    # RAG Retrieval
    docs = vector_db.similarity_search(message, k=3)
    context_str = "\n".join([d.page_content for d in docs])
    
    if image:
        # Multimodal: Use Gemma 4B
        img_bytes = await image.read()
        response = ollama_client.generate(
            model='gemma:4b', 
            prompt=f"Describe this photo and relate it to these facts: {context_str}",
            images=[img_bytes]
        )
    else:
        # Text: Use Fine-tuned Gemma 1B
        full_prompt = f"{SYSTEM_PROMPT}\nContext: {context_str}\nUser: {message}"
        response = ollama_client.generate(model='arvel-gemma-1b', prompt=full_prompt)

    # Save to SQLite for Export
    save_to_history(message, response['response'], current_context)
    
    return {"text": response['response'], "voice_url": "/generate_voice"}

def save_to_history(u, r, c):
    conn = sqlite3.connect('history.db')
    conn.execute("INSERT INTO turns (user_msg, bot_res, context) VALUES (?, ?, ?)", (u, r, c))
    conn.commit()