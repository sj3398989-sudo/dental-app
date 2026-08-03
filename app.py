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
    if SUPABASE_URL and SUPABASE_KEY:
        return create_client(SUPABASE_URL, SUPABASE_KEY)
    return None

supabase = init_supabase()

st.title("🦷 補綴物評価 AI分析 Pro")

tabs = st.tabs(["📷 登録", "📊 分析", "📋 履歴"])
tab1, tab2, tab3 = tabs

with tab1:
    st.subheader("評価シートのアップロード")
    uploaded_file = st.file_uploader(
        "手書きシート画像/PDFをアップロード",
        type=["jpg", "jpeg", "png", "pdf"]
    )

    if uploaded_file and GEMINI_API_KEY:
        file_bytes = uploaded_file.read()
        file_type = uploaded_file.type

        if "image" in file_type:
            try:
                img_io = io.BytesIO(file_bytes)
                image = Image.open(img_io)
                st.image(image, use_container_width=True)
            except Exception:
                st.warning("画像プレビュー失敗(解析は可能)")
        elif "pdf" in file_type:
            st.info(f"📄 PDF選択中: {uploaded_file.name}")

        if st.button("AI解析を実行する", type="primary"):
            with st.spinner("AI抽出中..."):
                try:
                    client = genai.Client(api_key=GEMINI_API_KEY)
                    prompt = (
                        "以下を抽出してJSONのみ出力:\n"
                        "clinic_name(医院名)\n"
                        "patient_name(患者名)\n"
                        "slip_number(伝票番号)\n"
                        "restoration_type(クラウン/ブリッジ等)\n"
                        "tooth_position(部位歯番)\n"
                        "contact(コンタクト1-5)\n"
                        "bite(バイト1-5)\n"
                        "fit(適合1-5)\n"
                        "comments(コメント)"
                    )

                    if "pdf" in file_type:
                        content_part = {
                            "mime_type": "application/pdf",
                            "data": file_bytes
                        }
                    else:
                        img_io = io.BytesIO(file_bytes)
                        content_part = Image.open(img_io)

                    response = client.models.generate_content(
                        model='gemini-2.5-flash',
                        contents=[content_part, prompt]
                    )

                    raw_text = response.text.strip()
                    if raw_text.startswith("```"):
                        lines = raw_text.splitlines()
                        raw_text = "\n".join(lines[1:-1])

                    data = json.loads(raw_text)
                    st.session_state["p_data"] = data
                    st.session_state["f_bytes"] = file_bytes
                    st.session_state["f_type"] = file_type

                    st.success("解析完了！")
                except Exception as e:
                    st.error(f"解析エラー: {e}")

    if "p_data" in st.session_state:
        p = st.session_state["p_data"]
        st.markdown("---")
        st.subheader("📝 結果の確認・修正")
        with st.form("eval_form"):
            col1, col2 = st.columns(2)
            with col1:
                c_name = st.text_input("医院名", p.get("clinic_name", ""))
                p_name = st.text_input("患者名", p.get("patient_name", ""))
                s_num = st.text_input("伝票番号", p.get("slip_number", ""))
                
                types = ["クラウン", "ブリッジ", "インプラント", "義歯", "その他"]
                def_t = p.get("restoration_type", "クラウン")
                t_idx = types.index(def_t) if def_t in types else 0
                r_type = st.selectbox("補綴種別", types, index=t_idx)
                
                t_pos = st.text_input("部位・歯番", p.get("tooth_position", ""))
            with col2:
                contact = st.slider("コンタクト", 1, 5, int(p.get("contact", 3)))
                bite = st.slider("バイト", 1
