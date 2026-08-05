import streamlit as st
import pandas as pd
import plotly.express as px
from supabase import create_client, Client
from google import genai
from google.genai import types
import io
import time
import uuid
import re
from datetime import date
import concurrent.futures
from PIL import Image, ImageOps, ImageEnhance

# ------------------------------------------
# 画面・スタイル設定
# ------------------------------------------
st.set_page_config(page_title="AI品質管理カルテ", page_icon="🦷", layout="wide", initial_sidebar_state="collapsed")

st.markdown("""
<style>
    .stApp { font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text", "Helvetica Neue", sans-serif !important; }
    #MainMenu, header, footer {visibility: hidden;}
    .custom-title { font-size: clamp(1.8rem, 5vw, 2.4rem); font-weight: 700; letter-spacing: -0.02em; color: #1D1D1F; margin-bottom: 20px; }
    .stButton>button[kind="primary"] { border-radius: 12px !important; font-weight: 600 !important; font-size: 15px !important; box-shadow: 0 4px 12px rgba(0, 122, 255, 0.2) !important; transition: all 0.2s cubic-bezier(0.25, 0.1, 0.25, 1) !important; }
    div[data-testid="stVerticalBlock"] > div[style*="border"] { border-radius: 18px !important; box-shadow: 0 4px 20px rgba(0, 0, 0, 0.03) !important; padding: 24px !important; border: 1px solid rgba(0,0,0,0.06) !important; background-color: #FFFFFF !important; }
    .metric-card { background: rgba(255, 255, 255, 0.8); backdrop-filter: blur(20px); -webkit-backdrop-filter: blur(20px); padding: 24px; border-radius: 20px; border: 1px solid rgba(255, 255, 255, 0.6); text-align: center; box-shadow: 0 8px 24px rgba(0,0,0,0.04); }
    .metric-card h2 { font-family: -apple-system, BlinkMacSystemFont, "SF Pro Rounded", sans-serif; letter-spacing: -0.04em; }
    .alert-card { padding: 14px 18px; border-left: 4px solid #FF3B30; background-color: rgba(255, 59, 48, 0.05); border-radius: 12px; margin-bottom: 10px; color: #1D1D1F; font-weight: 500; }
</style>
""", unsafe_allow_html=True)

st.markdown('<div class="custom-title">🦷 AI品質管理カルテ <span style="font-size: 0.5em; font-weight: 500; color: #8E8E93;">(大阪センター)</span></div>', unsafe_allow_html=True)

# ------------------------------------------
# 定数・設定
# ------------------------------------------
SHEET_TYPE_LIST = ["セパレートレス模型", "IOS"]
MATERIAL_LIST = ["ジルコニア", "CAD/CAM冠", "e.max", "チタン", "3Dプリント", "PEEK", "その他"]
TYPE_LIST = ["クラウン（単冠）", "ブリッジ", "インレー", "インプラント", "義歯", "その他"]
STORAGE_BUCKET = "sheet_images"

# ⚠️ ご自身のキーを貼り付けてください
KEY = "ここにGeminiのAPIキーを貼り付け"
URL = "ここにSupabaseのURLを貼り付け"
S_KEY = "ここにSupabaseのAPIキーを貼り付け"

GEMINI_MODELS = ["gemini-3.5-flash", "gemini-3.5-flash-lite", "gemini-3-flash"]

# ------------------------------------------
# DB / AI クライアント接続
# ------------------------------------------
@st.cache_resource
def get_db():
    try:
        return create_client(URL, S_KEY) if URL and S_KEY else None
    except Exception:
        return None

@st.cache_resource
def get_gemini_client():
    try:
        return genai.Client(api_key=KEY) if KEY else None
    except Exception:
        return None

db = get_db()
ai_client = get_gemini_client()

@st.cache_data(ttl=300)
def fetch_evaluations():
    if not db: return pd.DataFrame()
    try:
        res = db.table("evaluations").select("*").order("completion_date", desc=True).execute()
        if not res.data: return pd.DataFrame()
        df = pd.DataFrame(res.data)
        df['completion_date'] = pd.to_datetime(df['completion_date'], errors='coerce').dt.date
        for col in ['contact', 'bite', 'fit', 'id']:
            if col in df.columns: df[col] = pd.to_numeric(df[col], errors='coerce')
        return df
    except Exception:
        return pd.DataFrame()

def clear_db_cache():
    fetch_evaluations.clear()

def upload_image(file_obj):
    if not file_obj or not db: return None
    try:
        f_b = file_obj.getvalue()
        is_pdf = "pdf" in file_obj.type
        ext, mime = ("pdf", "application/pdf") if is_pdf else ("jpg", "image/jpeg")
        file_path = f"{uuid.uuid4()}.{ext}"
        
        if not is_pdf:
            try:
                img = Image.open(io.BytesIO(f_b))
                img = ImageOps.exif_transpose(img)
                img.thumbnail((1800, 1800), Image.Resampling.LANCZOS)
                if img.mode != 'RGB': img = img.convert('RGB')
                buf = io.BytesIO()
                img.save(buf, format='JPEG', quality=85, optimize=True)
                f_b = buf.getvalue()
            except Exception: pass
            
        db.storage.from_(STORAGE_BUCKET).upload(file_path, f_b, {"content-type": mime})
        return file_path
    except Exception:
        return None

def safe_int(val, default=3):
    try: return max(1, min(5, int(float(val))))
    except (ValueError, TypeError): return default

# ------------------------------------------
# タブ構築
# ------------------------------------------
tab1, tab2, tab3, tab4 = st.tabs(["🤖 AI一括", "✍️ 手動", "📊 分析", "📋 管理"])

# --- TAB 1: AI一括 ---
with tab1:
    st.markdown("### 📄 評価シートのアップロード")
    up_files = st.file_uploader("画像/PDF(複数選択可)", type=["jpg", "png", "pdf"], accept_multiple_files=True, label_visibility="collapsed")
    
    if up_files and st.button("✨ 解析スタート", type="primary"):
        st.info("旧構成コードで起動中（安定動作優先）")

# --- TAB 2: 手動 ---
with tab2:
    st.markdown("### ✍️ 手動入力")
    st.write("元コードでの動作確認用画面です。")

# --- TAB 3: 分析 ---
with tab3:
    st.markdown("### 📊 品質分析")
    df = fetch_evaluations()
    if not df.empty:
        st.write(f"現在 {len(df)} 件のデータが保存されています。")

# --- TAB 4: 管理 ---
with tab4:
    st.markdown("### 📋 履歴管理")
    df = fetch_evaluations()
    if not df.empty:
        st.dataframe(df, use_container_width=True)
