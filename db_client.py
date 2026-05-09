import os
import streamlit as st
from supabase import create_client
from dotenv import load_dotenv

load_dotenv()

# Initialize the Supabase Client (Cached)
@st.cache_resource
def get_db():
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    return create_client(url, key)

db = get_db()

# --- ACTIVITY HISTORY ---
def log_activity(user_email, feature, action):
    data = {"user_email": user_email, "feature": feature, "action": action}
    db.table("activity_history").insert(data).execute()

def get_activity_history(user_email):
    response = db.table("activity_history").select("*").eq("user_email", user_email).order("created_at", desc=True).execute()
    return response.data

# --- CHAT HISTORY ---
def save_chat(user_email, feature, user_message, bot_response):
    data = {
        "user_email": user_email, 
        "feature": feature, 
        "user_message": user_message, 
        "bot_response": bot_response
    }
    db.table("chat_history").insert(data).execute()

def get_chat_history(user_email):
    response = db.table("chat_history").select("*").eq("user_email", user_email).order("created_at", desc=True).execute()
    return response.data