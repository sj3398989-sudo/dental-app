import streamlit as st
import pandas as pd
import plotly.express as px
from google import genai
from supabase import create_client
from PIL import Image
import json

st.set_page_config(page_title="補綴物評価 AI分析", layout="wide")

GEMINI_API_KEY = st.secrets.get("GEMINI_API_KEY")
SUPABASE_URL = st.secrets.get("SUPABASE_URL")
SUPABASE_KEY = st.secrets.get("SUPABASE_KEY")

@st.cache_resource
def init_supabase():
    return create_client(SUPABASE_URL, SUPABASE_KEY) if SUPABASE_URL and SUPABASE_KEY else None

supabase = init_supabase()

st.title("🦷 補綴物評価コミュニケーションシート AI分析")

tab1, tab2, tab3 = st.tabs(["📷 シート読み取り・登録", "📊 医院別分析ダッシュボード", "📋 登録履歴一覧"])

with tab1:
    st.subheader("評価シートのアップロード")
    uploaded_file = st.file_uploader("手書きシートの画像(JPG/PNG)またはPDFをアップロード", type=["jpg", "jpeg", "png", "pdf"])
    
    if uploaded_file and GEMINI_API_KEY:
        image = Image.open(uploaded_file)
        st.image(image, caption="アップロード画像", use_container_width=True)
        
        if st.button("AI解析を実行する", type="primary"):
            with st.spinner("AIがシートの内容を抽出中..."):
                try:
                    client = genai.Client(api_key=GEMINI_API_KEY)
                    prompt = """
                    この画像は歯科補綴物のコミュニケーション評価シートです。
                    以下の項目を抽出し、指定されたJSONフォーマットのみで出力してください。
                    1. 医院名 (clinic_name)
                    2. 患者名 (patient_name)
                    3. 伝票番号 (slip_number)
                    4. コンタクト評価 1~5の数値 (contact) [1:弱い, 3:適正, 5:強い]
                    5. バイト評価 1~5の数値 (bite) [1:弱い, 3:適正, 5:強い]
                    6. 適合評価 1~5の数値 (fit) [1:緩い, 3:適正, 5:きつい]
                    7. その他コメント・注意事項 (comments)
                    
                    JSONフォーマット:
                    {
                      "clinic_name": "〇〇歯科",
                      "patient_name": "山田太郎",
                      "slip_number": "12345",
                      "contact": 3,
                      "bite": 4,
                      "fit": 3,
                      "comments": "コメント内容"
                    }
                    """
                    response = client.models.generate_content(
                        model='gemini-2.5-flash',
                        contents=[image, prompt]
                    )
                    raw_text = response.text.strip().replace("```json", "").replace("```", "")
                    data = json.loads(raw_text)
                    st.session_state["parsed_data"] = data
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
            with col2:
                contact = st.slider("コンタクト", 1, 5, int(p.get("contact", 3)))
                bite = st.slider("バイト", 1, 5, int(p.get("bite", 3)))
                fit = st.slider("適合", 1, 5, int(p.get("fit", 3)))
            comments = st.text_area("コメント", value=p.get("comments", ""))
            submit = st.form_submit_button("データベースへ保存")
            if submit and supabase:
                supabase.table("evaluations").insert({
                    "clinic_name": clinic_name,
                    "patient_name": patient_name,
                    "slip_number": slip_number,
                    "contact": contact,
                    "bite": bite,
                    "fit": fit,
                    "comments": comments
                }).execute()
                st.success("正常に保存されました！")
                del st.session_state["parsed_data"]

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
            col1.metric("総評価件数", f"{len(filtered_df)} 件")
            col2.metric("コンタクト平均", f"{filtered_df['contact'].mean():.2f}")
            col3.metric("バイト平均", f"{filtered_df['bite'].mean():.2f}")
            col4.metric("適合平均", f"{filtered_df['fit'].mean():.2f}")
            
            st.markdown("---")
            if st.button("🤖 AIでこの医院の傾向を分析する", type="primary"):
                if GEMINI_API_KEY:
                    with st.spinner("分析中..."):
                        client = genai.Client(api_key=GEMINI_API_KEY)
                        prompt = f"医院({selected_clinic})の傾向と今後の技工注意事項をまとめてください。データ:{filtered_df.to_dict()}"
                        res_ai = client.models.generate_content(model='gemini-2.5-flash', contents=prompt)
                        st.info(res_ai.text)
            
            fig = px.bar(x=["コンタクト", "バイト", "適合"], y=[filtered_df['contact'].mean(), filtered_df['bite'].mean(), filtered_df['fit'].mean()], range_y=[1, 5])
            st.plotly_chart(fig, use_container_width=True)

with tab3:
    st.subheader("📋 登録済みデータ")
    if supabase:
        res = supabase.table("evaluations").select("*").order("created_at", desc=True).execute()
        if res.data:
            st.dataframe(pd.DataFrame(res.data), use_container_width=True)
