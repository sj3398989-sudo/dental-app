import streamlit as st
import pandas as pd
from supabase import create_client
import uuid
import io
import hashlib
from PIL import Image, ImageOps
from config import URL, S_KEY, STORAGE_BUCKET

@st.cache_resource
def get_db():
    try: return create_client(URL, S_KEY) if URL and S_KEY else None
    except Exception as e:
        st.error(f"データベース接続エラー: {e}")
        return None

# ★ 個人情報保護: 患者名を不可逆なハッシュ値（匿名ID）に変換する関数
def hash_patient_name(name):
    if not name or not isinstance(name, str): return ""
    clean_name = name.strip()
    if not clean_name: return ""
    # SHA-256でハッシュ化し、先頭8文字を匿名IDとして使用
    return hashlib.sha256(clean_name.encode('utf-8')).hexdigest()[:8]

def prep_dataframe(df):
    if not df.empty:
        df['completion_date'] = pd.to_datetime(df['completion_date'], errors='coerce').dt.date
        for col in ['contact', 'bite', 'fit', 'id']:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce')
    return df

@st.cache_data(ttl=600)
def fetch_evaluations():
    db = get_db()
    if not db: return pd.DataFrame()
    try:
        res = db.table("evaluations").select("*").order("completion_date", desc=True).execute()
        if res.data: return prep_dataframe(pd.DataFrame(res.data))
    except Exception as e: st.error(f"データ読み込みエラー: {e}")
    return pd.DataFrame()

def clear_db_cache():
    fetch_evaluations.clear()

def upload_file_to_storage(file_obj):
    db = get_db()
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
    except Exception as e:
        st.warning(f"画像アップロードスキップ: {e}")
        return None

def remove_files_from_storage(paths):
    db = get_db()
    if db and paths:
        db.storage.from_(STORAGE_BUCKET).remove(paths)
