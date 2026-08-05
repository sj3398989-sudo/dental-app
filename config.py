import streamlit as st

# ==========================================
# 定数マスター
# ==========================================
SHEET_TYPE_LIST = ["セパレートレス模型", "IOS"]
MATERIAL_LIST = ["ジルコニア", "CAD/CAM冠", "e.max", "チタン", "3Dプリント", "PEEK", "その他"]
TYPE_LIST = ["クラウン（単冠）", "ブリッジ", "インレー", "インプラント", "義歯", "その他"]
STORAGE_BUCKET = "sheet_images"

# ==========================================
# 環境変数・API設定（直書き版）
# ==========================================
# ⚠️ 注意: GitHubリポジトリが「Private（非公開）」になっていることを必ずご確認ください。

KEY = "ここにGeminiのAPIキーを貼り付け"
URL = "ここにSupabaseのURLを貼り付け"
S_KEY = "ここにSupabaseのAPIキーを貼り付け"
HASH_SECRET = "super-secret-lab-key-2026"
DEFAULT_MODEL = "gemini-3.5-flash"

FALLBACK_MODELS = ["gemini-3.5-flash-lite", "gemini-3-flash"]
GEMINI_MODELS = [DEFAULT_MODEL] + FALLBACK_MODELS
