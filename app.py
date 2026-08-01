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
                    response = client.models.generate_content(
                        model='gemini-2.5-flash',
                        contents=[image, prompt]
                    )
                    raw_text = response.text.strip().replace("```json", "").replace("```", "")
                    data = json.loads(raw_text)
                    st.session_state["parsed_data"] = data
                    
                    # 画像をバイトデータとして一時保持
                    img_byte_arr = io.BytesIO()
                    image.save(img_byte_arr, format=image.format if image.format else 'JPEG')
                    st.session_state["uploaded_img_bytes"] = img_byte_arr.getvalue()
                    
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
                # 画像の保存処理（Supabase Storageへアップロード）
                if "uploaded_img_bytes" in st.session_state:
                    file_name = f"{int(time.time())}_{slip_number}.jpg"
                    try:
                        supabase.storage.from_("sheet_images").upload(file_name, st.session_state["uploaded_img_bytes"], {"content-type": "image/jpeg"})
                        image_url = supabase.storage.from_("sheet_images").get_public_url(file_name)
                    except Exception as img_err:
                        # バケット未作成等の場合はURL保存をスキップして進める
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
                if "uploaded_img_bytes" in st.session_state:
                    del st.session_state["uploaded_img_bytes"]

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
                        prompt = f"医院({selected_clinic})の傾向と今後の技工注意事項をまとめてください。データ:{filtered_df[['restoration_type', 'contact', 'bite', 'fit', 'comments']].to_dict()}"
                        res_ai = client.models.generate_content(model='gemini-2.5-flash', contents=prompt)
                        st.info(res_ai.text)
            
            fig = px.bar(x=["コンタクト", "バイト", "適合"], y=[filtered_df['contact'].mean(), filtered_df['bite'].mean(), filtered_df['fit'].mean()], range_y=[1, 5])
            st.plotly_chart(fig, use_container_width=True)

with tab3:
    st.subheader("📋 登録済みデータ・検索")
    if supabase:
        res = supabase.table("evaluations").select("*").order("created_at", desc=True).execute()
        if res.data:
            df = pd.DataFrame(res.data)
            
            # 検索機能
            search_query = st.text_input("🔍 患者名・伝票番号・医院名で検索")
            if search_query:
                df = df[
                    df['patient_name'].astype(str).str.contains(search_query, case=False, na=False) |
                    df['slip_number'].astype(str).str.contains(search_query, case=False, na=False) |
                    df['clinic_name'].astype(str).str.contains(search_query, case=False, na=False)
                ]
            
            # CSVダウンロード機能
            csv = df.to_csv(index=False).encode('utf-8-sig')
            st.download_button(
                label="📥 データをCSV（Excel用）でダウンロード",
                data=csv,
                file_name="evaluation_data.csv",
                mime="text/csv"
            )
            
            st.dataframe(df, use_container_width=True)
