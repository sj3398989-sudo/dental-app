import streamlit as st
import pandas as pd
import plotly.express as px
from google import genai
from supabase import create_client
from PIL import Image
import json
import io
import time

st.set_page_config(page_title="補綴物評価 AI分析 Pro", layout="wide")

GEMINI_API_KEY = st.secrets.get("GEMINI_API_KEY")
SUPABASE_URL = st.secrets.get("SUPABASE_URL")
SUPABASE_KEY = st.secrets.get("SUPABASE_KEY")

@st.cache_resource
def init_supabase():
    return create_client(SUPABASE_URL, SUPABASE_KEY) if SUPABASE_URL and SUPABASE_KEY else None

supabase = init_supabase()

st.title("🦷 補綴物評価コミュニケーションシート AI分析 Pro")

tab1, tab2, tab3 = st.tabs(["📷 シート読み取り・登録", "📊 医院別分析ダッシュボード", "📋 登録履歴・検索"])

with tab1:
    st.subheader("評価シートのアップロード")
    uploaded_file = st.file_uploader("手書きシートの画像(JPG/PNG)またはPDFをアップロード", type=["jpg", "jpeg", "png", "pdf"])
    
    if uploaded_file and GEMINI_API_KEY:
        file_bytes = uploaded_file.read()
        file_type = uploaded_file.type
        
        # プレビュー表示（画像の場合は画像、PDFの場合は案内）
        if "image" in file_type:
            try:
                image = Image.open(io.BytesIO(file_bytes))
                st.image(image, caption="アップロード画像", use_container_width=True)
            except Exception:
                st.warning("画像のプレビュー表示に失敗しましたが、解析は実行できます。")
        elif "pdf" in file_type:
            st.info(f"📄 PDFファイルが選択されました: {uploaded_file.name}")
        
        if st.button("AI解析を実行する", type="primary"):
            with st.spinner("AIがシートの内容を抽出中..."):
                try:
                    client = genai.Client(api_key=GEMINI_API_KEY)
                    prompt = """
                    このファイルは歯科補綴物のコミュニケーション評価シートです。
                    以下の項目を抽出し、指定されたJSONフォーマットのみで出力してください。
                    1. 医院名 (clinic_name)
                    2. 患者名 (patient_name)
                    3. 伝票番号 (slip_number)
                    4. 補綴種別 (restoration_type) [例: クラウン, ブリッジ, インプラント, 義歯, その他]
                    5. 部位・歯番 (tooth_position) [例: #16, 上顎前歯部 など]
                    6. コンタクト評価 1~5の数値 (contact) [1:弱い, 3:適正, 5:強い]
                    7. バイト評価 1~5の数値 (bite) [1:弱い, 3:適正, 5:強い]
                    8. 適合評価 1~5の数値 (fit) [1:緩い, 3:適正, 5:きつい]
                    9. その他コメント・注意事項 (comments)
                    
                    JSONフォーマット:
                    {
                      "clinic_name": "〇〇歯科",
                      "patient_name": "山田太郎",
                      "slip_number": "12345",
                      "restoration_type": "クラウン",
                      "tooth_position": "#16",
                      "contact": 3,
                      "bite": 4,
                      "fit": 3,
                      "comments": "コメント内容"
                    }
                    """
                    
                    # Gemini APIへファイルを渡す形式の判定
                    if "pdf" in file_type:
                        content_part = {
                            "mime_type": "application/pdf",
                            "data": file_bytes
                        }
                    else:
                        content_part = Image.open(io.BytesIO(file_bytes))
                        
                    response = client.models.generate_content(
                        model='gemini-2.5-flash',
                        contents=[content_part, prompt]
                    )
                    raw_text = response.text.strip().replace("```json", "").replace("
