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
                    prompt = "このファイルから以下を抽出してJSONのみ出力: clinic_name(医院名), patient_name(患者名), slip_number(伝票番号), restoration_type(クラウン/ブリッジ/インプラント/義歯/その他), tooth_position(部位・歯番), contact(コンタクト1-5), bite(バイト1-5), fit(適合1-5), comments(コメント)"
                    
                    if "pdf" in file_type:
                        content_part = {"mime_type": "application/pdf", "data": file_bytes}
                    else:
                        content_part = Image.open(io.BytesIO(file_bytes))
                        
                    response = client.models.generate_content(
                        model='gemini-2.5-flash',
                        contents=[content_part, prompt]
                    )
                    
                    raw_text = response.text.strip()
                    if raw_text.startswith("```"):
                        lines = raw_text.splitlines()
                        raw_text = "\n".join(lines[1:-1])
                    
                    data = json.loads(raw_text)
                    st.session_state["parsed_data"] = data
                    st.session_state["uploaded_file_bytes"] = file_bytes
                    st.session_state["uploaded_file_type"] = file_type
                    
                    st.success("AI解析が完了しました！")
                except Exception as e:
                    st.error(f"解析エラー: {e}")

    if "parsed_data" in st.session_state:
        p = st.session_state["parsed_data"]
        st.markdown("---")
        st.subheader("📝 抽出結果の確認・修正")
        with st.form("eval_form"):
            col1, col2 = st.columns(2)
            with col1:
                clinic_name = st.text_input("医院名", value=p.get("clinic_name", ""))
                patient_name = st.text_input("患者名", value=p.get("patient_name", ""))
                slip_number = st.text_input("伝票番号", value=p.get("slip_number", ""))
                restoration_type = st.selectbox("補綴種別", ["クラウン", "ブリッジ", "インプラント", "義歯", "その他"], 
                                                 index=["クラウン", "ブリッジ", "インプラント", "義歯", "その他"].index(p.get("restoration_type", "クラウン")) if p.get("restoration_type") in ["クラウン", "ブリッジ", "インプラント", "義歯", "その他"] else 0)
                tooth_position = st.text_input("部位・歯番", value=p.get("tooth_position", ""))
            with col2:
                contact = st.slider("コンタクト", 1, 5, int(p.get("contact", 3)))
                bite = st.slider("バイト", 1, 5, int(p.get("bite", 3)))
                fit = st.slider("適合", 1, 5, int(p.get("fit", 3)))
                comments = st.text_area("コメント", value=p.get("comments", ""))
            
            submit = st.form_submit_button("データベースへ保存", type="primary")
            if submit and supabase:
                image_url = None
                if "uploaded_file_bytes" in st.session_state:
                    is_pdf = "pdf" in st.session_state.get("uploaded_file_type", "")
                    ext = "pdf" if is_pdf else "jpg"
                    mime = "application/pdf" if is_pdf else "image/jpeg"
                    file_name = f"{int(time.time())}_{slip_number}.{ext}"
                    try:
                        supabase.storage.from_("sheet_images").upload(file_name, st.session_state["uploaded_file_bytes"], {"content-type": mime})
                        image_url = supabase.storage.from_("sheet_images").get_public_url(file_name)
                    except Exception as img_err:
                        pass

                supabase.table("evaluations").insert({
                    "clinic_name": clinic_name,
                    "patient_name": patient_name,
                    "slip_number": slip_number,
                    "restoration_type": restoration_type,
                    "tooth_position": tooth_position,
                    "contact": contact,
                    "bite": bite,
                    "fit": fit,
                    "comments": comments,
                    "image_url": image_url
                }).execute()
                st.success("正常に保存されました！")
                del st.session_state["parsed_data"]
                if "uploaded_file_bytes" in st.session_state:
                    del st.session_state["uploaded_file_bytes"]

with tab2:
    st.subheader("📊 医院別の傾向分析")
    if supabase:
        res = supabase.table("evaluations").select("*").execute()
        if res.data:
            df = pd.DataFrame(res.data)
            clinic_list = ["すべて"] + list(df["clinic_name"].unique())
            selected_clinic = st.selectbox("分析対象の医院を選択", clinic_list)
            filtered_df = df if selected_clinic == "すべて" else df[df["clinic_name"] == selected_clinic]
            
            col1, col2, col3, col4 = st.columns(4)
            col1.metric("総評価件数", f"{len(filtered
