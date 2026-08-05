import streamlit as st
import pandas as pd
from supabase import create_client, Client
import uuid
import io
import hmac
import hashlib
from PIL import Image, ImageOps
from config import URL, S_KEY, STORAGE_BUCKET, HASH_SECRET

@st.cache_resource
def get_db() -> Client:
    try: return create_client(URL, S_KEY) if URL and S_KEY else None
    except Exception as e:
        st.error(f"データベース接続エラー: {e}")
        return None

# ★ セキュリティ強化: HMAC-SHA256による匿名化（レインボーテーブル攻撃を無効化）
def hash_patient_name(name: str) -> str:
    if not name or not isinstance(name, str): return ""
    clean_name = name.strip()
    if not clean_name: return ""
    return hmac.new(HASH_SECRET.encode('utf-8'), clean_name.encode('utf-8'), hashlib.sha256).hexdigest()[:8]

# ★ Repositoryパターン: DB操作のカプセル化
class EvaluationRepository:
    def __init__(self, db_client: Client):
        self.db = db_client

    def get_all(self) -> pd.DataFrame:
        if not self.db: return pd.DataFrame()
        try:
            res = self.db.table("evaluations").select("*").order("completion_date", desc=True).execute()
            if not res.data: return pd.DataFrame()
            df = pd.DataFrame(res.data)
            df['completion_date'] = pd.to_datetime(df['completion_date'], errors='coerce').dt.date
            for col in ['contact', 'bite', 'fit', 'id']:
                if col in df.columns: df[col] = pd.to_numeric(df[col], errors='coerce')
            return df
        except Exception as e:
            st.error(f"データ読み込みエラー: {e}")
            return pd.DataFrame()

    def insert_bulk(self, data_list: list):
        if not self.db or not data_list: return
        chunk_size = 100
        for i in range(0, len(data_list), chunk_size):
            self.db.table("evaluations").insert(data_list[i:i + chunk_size]).execute()

    def update_bulk(self, update_data: dict, ids: list):
        if not self.db or not ids: return
        self.db.table("evaluations").update(update_data).in_("id", ids).execute()
        
    def update_single(self, update_data: dict, row_id: int):
        if not self.db: return
        self.db.table("evaluations").update(update_data).eq("id", row_id).execute()

    def delete_bulk(self, ids: list):
        if not self.db or not ids: return
        self.db.table("evaluations").delete().in_("id", ids).execute()

    def upload_image(self, file_obj) -> str:
        if not file_obj or not self.db: return None
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
            
            self.db.storage.from_(STORAGE_BUCKET).upload(file_path, f_b, {"content-type": mime})
            return file_path
        except Exception as e:
            st.warning(f"画像アップロードスキップ: {e}")
            return None

    def remove_images(self, paths: list):
        if self.db and paths:
            self.db.storage.from_(STORAGE_BUCKET).remove(paths)

@st.cache_data(ttl=600)
def fetch_evaluations_cached():
    db = get_db()
    return EvaluationRepository(db).get_all() if db else pd.DataFrame()

def clear_db_cache():
    fetch_evaluations_cached.clear()
