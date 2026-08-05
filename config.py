import streamlit as st

# ==========================================
# 定数マスター
# ==========================================
SHEET_TYPE_LIST = ["セパレートレス模型", "IOS"]
MATERIAL_LIST = ["ジルコニア", "CAD/CAM冠", "e.max", "チタン", "3Dプリント", "PEEK", "その他"]
TYPE_LIST = ["クラウン（単冠）", "ブリッジ", "インレー", "インプラント", "義歯", "その他"]

STORAGE_BUCKET = "sheet_images"

# ==========================================
# 環境変数・API設定
# ==========================================
try:
    KEY = st.secrets["GEMINI_API_KEY"]
    URL = st.secrets["SUPABASE_URL"]
    S_KEY = st.secrets["SUPABASE_KEY"]
    
    # ★ 改善: モデル名をsecretsから取得し、コードを触らずに変更可能にする
    DEFAULT_MODEL = st.secrets.get("GEMINI_MODEL", "gemini-3.5-flash")
except Exception:
    KEY, URL, S_KEY = None, None, None
    DEFAULT_MODEL = "gemini-3.5-flash"

# フォールバック用モデル
FALLBACK_MODELS = ["gemini-3.5-flash-lite", "gemini-3-flash"]
GEMINI_MODELS = [DEFAULT_MODEL] + FALLBACK_MODELS
