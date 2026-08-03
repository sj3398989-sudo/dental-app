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
    st.subheader("シート一括アップロード（複数ページ対応）")
    up_files = st.file_uploader(
        "画像/PDF(複数選択・複数ページ対応)",
        type=["jpg", "png", "pdf"],
        accept_multiple_files=True
    )

    if up_files and KEY:
        if st.button("一括AI解析"):
            with st.spinner("複数ページを自動分解して解析中..."):
                c = genai.Client(api_key=KEY)
                
                # 複数枚/複数ページを自動で分解してリスト（配列）で返すように指示
                prm = (
                    "このファイルには1枚または複数の補綴物評価シート（複数患者分など）が含まれている場合があります。\n"
                    "含まれているすべてのシートを個別に検出し、以下のキーを持つJSONオブジェクトの「配列（リスト: [...]）」形式で抽出してください。\n"
                    "各項目のキー:\n"
                    "- clinic_name\n"
                    "- patient_name\n"
                    "- slip_number\n"
                    "- restoration_type\n"
                    "- tooth_position\n"
                    "- contact\n"
                    "- bite\n"
                    "- fit\n"
                    "- comments\n"
                    "必ずJSONの配列形式（例: [{...}, {...}]）のみを出力してください。"
                )
                
                r_list = []
                for idx, f in enumerate(up_files):
                    f_b = f.getvalue()
                    f_t = f.type
                    
                    try:
                        if "pdf" in f_t:
                            cp = types.Part.from_bytes(
                                data=f_b,
                                mime_type="application/pdf"
                            )
                        else:
                            i_io = io.BytesIO(f_b)
                            cp = Image.open(i_io)
                            
                        res = c.models.generate_content(
                            model='gemini-3.5-flash',
                            contents=[cp, prm]
                        )
                        
                        txt = res.text.strip()
                        if txt.startswith("```"):
                            lines = txt.splitlines()
                            txt = "\n".join(lines[1:-1])
                            
                        parsed = json.loads(txt)
                        
                        # AIが単体オブジェクトで返した場合のケア（リストに変換）
                        if isinstance(parsed, dict):
                            parsed = [parsed]
                            
                        for item in parsed:
                            item["_fn"] = f.name
                            r_list.append(item)
                        
                    except Exception as e:
                        st.error(f"{f.name} エラー: {e}")
                        
                st.session_state["r_list"] = r_list
                st.session_state["f_list"] = up_files
                st.success(f"合計 {len(r_list)} 件のデータを検出しました")

    if "r_list" in st.session_state:
        st.markdown("---")
        st.subheader("📝 抽出されたデータの確認・修正")
        
        r_list = st.session_state["r_list"]
        
        for i, d in enumerate(r_list):
            st.markdown(f"**📄 [{d.get('_fn', '')}] 検出データ #{i+1}**")
            col1, col2 = st.columns(2)
            with col1:
                d["clinic_name"] = st.text_input(
                    "医院",
                    d.get("clinic_name", ""),
                    key=f"c_{i}"
                )
                d["patient_name"] = st.text_input(
                    "患者",
                    d.get("patient_name", ""),
                    key=f"p_{i}"
                )
                d["slip_number"] = st.text_input(
                    "伝票",
                    d.get("slip_number", ""),
                    key=f"s_{i}"
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
                idx_t = 0
                if r_def in t_list:
                    idx_t = t_list.index(r_def)
                    
                d["restoration_type"] = st.selectbox(
                    "種別",
                    t_list,
                    index=idx_t,
                    key=f"rt_{i}"
                )
                
                d["tooth_position"] = st.text_input(
                    "部位",
                    d.get("tooth_position", ""),
                    key=f"tp_{i}"
                )
            with col2:
                v_c = d.get("contact", 3)
                try:
                    v_c = int(v_c)
                except:
                    v_c = 3
                d["contact"] = st.slider(
                    "コンタクト",
                    1, 5, v_c,
                    key=f"co_{i}"
                )
                
                v_b = d.get("bite", 3)
                try:
                    v_b = int(v_b)
                except:
                    v_b = 3
                d["bite"] = st.slider(
                    "バイト",
                    1, 5, v_b,
                    key=f"bi_{i}"
                )
                
                v_f = d.get("fit", 3)
                try:
                    v_f = int(v_f)
                except:
                    v_f = 3
                d["fit"] = st.slider(
                    "適合",
                    1, 5, v_f,
                    key=f"fi_{i}"
                )
                
                d["comments"] = st.text_area(
                    "コメント",
                    d.get("comments", ""),
                    key=f"cm_{i}"
                )
            st.divider()

        if st.button("💾 全て保存"):
            if db:
                s_cnt = 0
                f_list = st.session_state["f_list"]
                with st.spinner("保存中..."):
                    for i, d in enumerate(r_list):
                        img_url = None
                        # 画像アップロード（複数ある場合は最初のファイルを紐付け、必要に応じて調整）
                        if len(f_list) > 0:
                            f_obj = f_list[0]
                            f_b = f_obj.getvalue()
                            f_t = f_obj.type
                            pdf = "pdf" in f_t
                            ext = "pdf" if pdf else "jpg"
                            mime = "application/pdf" if pdf else "image/jpeg"
                            
                            ts = int(time.time())
                            f_nm = f"{ts}_{i}.{ext}"
                            try:
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
                            "clinic_name": d.get("clinic_name"),
                            "patient_name": d.get("patient_name"),
                            "slip_number": d.get("slip_number"),
                            "restoration_type": d.get("restoration_type"),
                            "tooth_position": d.get("tooth_position"),
                            "contact": d.get("contact"),
                            "bite": d.get("bite"),
                            "fit": d.get("fit"),
                            "comments": d.get("comments"),
                            "image_url": img_url
                        }).execute()
                        s_cnt += 1
                        
                st.success(f"{s_cnt}件 保存完了")
                del st.session_state["r_list"]
                del st.session_state["f_list"]

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
