import streamlit as st
import pandas as pd
import plotly.express as px
from google import genai
from google.genai import types
from supabase import create_client
from PIL import Image
import json
import io
import time

st.set_page_config(
    page_title="AI分析 Pro",
    layout="wide"
)

KEY = st.secrets.get("GEMINI_API_KEY")
URL = st.secrets.get("SUPABASE_URL")
S_KEY = st.secrets.get("SUPABASE_KEY")

@st.cache_resource
def get_db():
    if URL and S_KEY:
        return create_client(URL, S_KEY)
    return None

db = get_db()
st.title("🦷 補綴物評価 AI分析 Pro")

tab1, tab2, tab3 = st.tabs([
    "📷 登録", 
    "📊 分析", 
    "📋 履歴"
])

with tab1:
    st.subheader("シートアップロード")
    up_file = st.file_uploader(
        "画像またはPDF",
        type=["jpg", "png", "pdf"]
    )

    if up_file and KEY:
        f_byte = up_file.read()
        f_type = up_file.type

        if "image" in f_type:
            try:
                img_io = io.BytesIO(f_byte)
                img = Image.open(img_io)
                st.image(img, use_container_width=True)
            except Exception:
                pass
        elif "pdf" in f_type:
            st.info("PDF選択中")

        if st.button("AI解析"):
            with st.spinner("解析中"):
                try:
                    c = genai.Client(api_key=KEY)
                    prm = (
                        "以下をJSONで抽出:\n"
                        "clinic_name\n"
                        "patient_name\n"
                        "slip_number\n"
                        "restoration_type\n"
                        "tooth_position\n"
                        "contact\n"
                        "bite\n"
                        "fit\n"
                        "comments"
                    )
                    
                    if "pdf" in f_type:
                        cp = types.Part.from_bytes(
                            data=f_byte,
                            mime_type="application/pdf"
                        )
                    else:
                        i_io = io.BytesIO(f_byte)
                        cp = Image.open(i_io)

                    # 💡ここを最新かつ無料枠対象の gemini-3.5-flash に変更しました
                    res = c.models.generate_content(
                        model='gemini-3.5-flash',
                        contents=[cp, prm]
                    )

                    txt = res.text.strip()
                    if txt.startswith("```"):
                        lines = txt.splitlines()
                        txt = "\n".join(lines[1:-1])

                    d = json.loads(txt)
                    st.session_state["d"] = d
                    st.session_state["f_b"] = f_byte
                    st.session_state["f_t"] = f_type
                    st.success("完了")
                except Exception as e:
                    st.error(f"エラー: {e}")

    if "d" in st.session_state:
        d = st.session_state["d"]
        st.markdown("---")
        with st.form("form"):
            col1, col2 = st.columns(2)
            with col1:
                c_n = st.text_input(
                    "医院",
                    d.get("clinic_name", "")
                )
                p_n = st.text_input(
                    "患者",
                    d.get("patient_name", "")
                )
                s_n = st.text_input(
                    "伝票",
                    d.get("slip_number", "")
                )
                
                t_list = [
                    "クラウン",
                    "ブリッジ",
                    "インプラント",
                    "義歯",
                    "その他"
                ]
                r_def = d.get(
                    "restoration_type",
                    "クラウン"
                )
                idx = 0
                if r_def in t_list:
                    idx = t_list.index(r_def)
                
                r_t = st.selectbox(
                    "種別",
                    t_list,
                    index=idx
                )
                
                t_p = st.text_input(
                    "部位",
                    d.get("tooth_position", "")
                )
            with col2:
                v_c = int(d.get("contact", 3))
                con = st.slider(
                    "コンタクト",
                    1, 5, v_c
                )
                
                v_b = int(d.get("bite", 3))
                bit = st.slider(
                    "バイト",
                    1, 5, v_b
                )
                
                v_f = int(d.get("fit", 3))
                fit = st.slider(
                    "適合",
                    1, 5, v_f
                )
                
                com = st.text_area(
                    "コメント",
                    d.get("comments", "")
                )

            sub = st.form_submit_button("保存")
            
            if sub and db:
                img_url = None
                if "f_b" in st.session_state:
                    f_t = st.session_state["f_t"]
                    pdf = "pdf" in f_t
                    ext = "pdf" if pdf else "jpg"
                    mime = "application/pdf" if pdf else "image/jpeg"
                    
                    ts = int(time.time())
                    f_nm = f"{ts}.{ext}"
                    try:
                        f_b = st.session_state["f_b"]
                        db.storage.from_(
                            "sheet_images"
                        ).upload(
                            f_nm,
                            f_b,
                            {"content-type": mime}
                        )
                        img_url = db.storage.from_(
                            "sheet_images"
                        ).get_public_url(f_nm)
                    except Exception:
                        pass

                db.table("evaluations").insert({
                    "clinic_name": c_n,
                    "patient_name": p_n,
                    "slip_number": s_n,
                    "restoration_type": r_t,
                    "tooth_position": t_p,
                    "contact": con,
                    "bite": bit,
                    "fit": fit,
                    "comments": com,
                    "image_url": img_url
                }).execute()
                
                st.success("保存完了")
                del st.session_state["d"]
                if "f_b" in st.session_state:
                    del st.session_state["f_b"]

with tab2:
    st.subheader("📊 分析")
    if db:
        res = db.table("evaluations").select("*").execute()
        
        if res.data:
            df = pd.DataFrame(res.data)
            clinics = ["すべて"]
            clinics += list(df["clinic_name"].unique())
            s_c = st.selectbox("医院", clinics)
            
            if s_c == "すべて":
                f_df = df
            else:
                cond = df["clinic_name"] == s_c
                f_df = df[cond]

            col1, col2, col3, col4 = st.columns(4)
            col1.metric("件数", len(f_df))
            
            c_m = f_df['contact'].mean()
            b_m = f_df['bite'].mean()
            f_m = f_df['fit'].mean()
            
            col2.metric("コン", f"{c_m:.2f}")
            col3.metric("バイ", f"{b_m:.2f}")
            col4.metric("適合", f"{f_m:.2f}")

            if st.button("AI分析"):
                with st.spinner("..."):
                    c = genai.Client(api_key=KEY)
                    cols = [
                        'restoration_type',
                        'contact',
                        'bite',
                        'fit',
                        'comments'
                    ]
                    dic = f_df[cols].to_dict()
                    prm = f"({s_c})の傾向:{dic}"
                    
                    # 💡こちらも gemini-3.5-flash に変更
                    r_ai = c.models.generate_content(
                        model='gemini-3.5-flash',
                        contents=prm
                    )
                    st.info(r_ai.text)

            fig = px.bar(
                x=["コンタクト", "バイト", "適合"],
                y=[c_m, b_m, f_m],
                range_y=[1, 5]
            )
            st.plotly_chart(
                fig,
                use_container_width=True
            )

with tab3:
    st.subheader("📋 履歴")
    if db:
        res = db.table(
            "evaluations"
        ).select("*").order(
            "created_at",
            desc=True
        ).execute()
        
        if res.data:
            df = pd.DataFrame(res.data)
            
            q = st.text_input("検索")
            if q:
                c1 = df['patient_name'].astype(
                    str
                ).str.contains(q, na=False)
                c2 = df['clinic_name'].astype(
                    str
                ).str.contains(q, na=False)
                df = df[c1 | c2]

            csv = df.to_csv(
                index=False
            ).encode('utf-8-sig')
            
            st.download_button(
                "CSVダウンロード",
                csv,
                "data.csv",
                "text/csv"
            )
            
            st.dataframe(
                df,
                use_container_width=True
            )
