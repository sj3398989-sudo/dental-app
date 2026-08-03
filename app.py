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
from datetime import date

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

# 改善3: タブを4つに分割し、目的別にスッキリ配置
tab1, tab2, tab3, tab4 = st.tabs([
    "🤖 AI一括", 
    "✍️ 手動", 
    "📊 分析", 
    "📋 管理"
])

MATERIAL_LIST = ["ジルコニア", "CAD/CAM冠", "e.max", "メタル", "3Dプリント", "その他"]
TYPE_LIST = ["クラウン", "ブリッジ", "インプラント", "義歯", "その他"]

with tab1:
    st.subheader("シート一括登録（AI解析）")
    up_files = st.file_uploader(
        "画像/PDF(複数選択・複数ページ対応)",
        type=["jpg", "png", "pdf"],
        accept_multiple_files=True
    )

    if up_files and KEY:
        if st.button("一括AI解析"):
            with st.spinner("解析およびデータ抽出中..."):
                c = genai.Client(api_key=KEY)
                prm = (
                    "このファイルには1枚または複数の補綴物評価シートが含まれています。\n"
                    "含まれているすべてのシートを個別に検出し、以下のキーを持つJSONオブジェクトの配列（リスト: [...]）形式で抽出してください。\n"
                    "各項目のキー:\n"
                    "- clinic_name (医院名)\n"
                    "- patient_name (患者名)\n"
                    "- slip_number (伝票番号)\n"
                    "- completion_date (完成日、YYYY-MM-DD形式。記載がない場合は空文字)\n"
                    "- restoration_type (クラウン、ブリッジ、インプラント、義歯、その他のいずれか)\n"
                    "- material (材料: ジルコニア、CAD/CAM冠、e.max、メタル、3Dプリント、その他のいずれか)\n"
                    "- tooth_position (部位)\n"
                    "- contact (コンタクト 1〜5の数値)\n"
                    "- bite (バイト 1〜5の数値)\n"
                    "- fit (適合 1〜5の数値)\n"
                    "- comments (コメント)\n"
                    "必ずJSONの配列形式のみを出力してください。"
                )
                
                r_list = []
                for idx, f in enumerate(up_files):
                    f_b = f.getvalue()
                    f_t = f.type
                    try:
                        if "pdf" in f_t:
                            cp = types.Part.from_bytes(data=f_b, mime_type="application/pdf")
                        else:
                            i_io = io.BytesIO(f_b)
                            cp = Image.open(i_io)
                            
                        res = c.models.generate_content(model='gemini-3.5-flash', contents=[cp, prm])
                        txt = res.text.strip()
                        if txt.startswith("```"):
                            lines = txt.splitlines()
                            txt = "\n".join(lines[1:-1])
                            
                        parsed = json.loads(txt)
                        if isinstance(parsed, dict):
                            parsed = [parsed]
                            
                        for item in parsed:
                            item["_fn"] = f.name
                            r_list.append(item)
                    except Exception as e:
                        st.error(f"{f.name} エラー: {e}")
                        
                st.session_state["r_list"] = r_list
                st.session_state["f_list"] = up_files
                # 改善2: フワッと消えるトースト通知
                st.toast(f"合計 {len(r_list)} 件のデータを検出しました！", icon="✨")

    if "r_list" in st.session_state:
        st.markdown("---")
        st.subheader("📝 抽出データの手動確認・修正")
        r_list = st.session_state["r_list"]
        
        for i, d in enumerate(r_list):
            p_name = d.get("patient_name", "患者名なし")
            c_name = d.get("clinic_name", "医院名なし")
            
            # 改善1: 折りたたみ式（Expander）にして縦幅を大幅に圧縮
            with st.expander(f"🔽 データ #{i+1} : {p_name} 様 ({c_name})", expanded=False):
                col1, col2 = st.columns(2)
                with col1:
                    d["clinic_name"] = st.text_input("医院名", d.get("clinic_name", ""), key=f"c_{i}")
                    d["patient_name"] = st.text_input("患者名", p_name, key=f"p_{i}")
                    d["slip_number"] = st.text_input("伝票番号", d.get("slip_number", ""), key=f"s_{i}")
                    
                    raw_date = d.get("completion_date", "")
                    def_date = date.today()
                    try:
                        if raw_date: def_date = date.fromisoformat(str(raw_date)[:10])
                    except: pass
                    c_date = st.date_input("完成日", value=def_date, key=f"dt_{i}")
                    d["completion_date"] = c_date.isoformat()
                    
                with col2:
                    r_def = d.get("restoration_type", "クラウン")
                    idx_t = TYPE_LIST.index(r_def) if r_def in TYPE_LIST else 0
                    d["restoration_type"] = st.selectbox("種別", TYPE_LIST, index=idx_t, key=f"rt_{i}")
                    
                    m_def = d.get("material", "ジルコニア")
                    idx_m = MATERIAL_LIST.index(m_def) if m_def in MATERIAL_LIST else 0
                    d["material"] = st.selectbox("材料", MATERIAL_LIST, index=idx_m, key=f"mat_{i}")
                    
                    d["tooth_position"] = st.text_input("部位", d.get("tooth_position", ""), key=f"tp_{i}")
                    
                    d["contact"] = st.slider("コンタクト", 1, 5, int(d.get("contact", 3) or 3), key=f"co_{i}")
                    d["bite"] = st.slider("バイト", 1, 5, int(d.get("bite", 3) or 3), key=f"bi_{i}")
                    d["fit"] = st.slider("適合", 1, 5, int(d.get("fit", 3) or 3), key=f"fi_{i}")
                
                d["comments"] = st.text_area("コメント", d.get("comments", ""), key=f"cm_{i}")

        if st.button("💾 AI解析データを全て保存", type="primary"):
            if db:
                s_cnt = 0
                f_list = st.session_state["f_list"]
                with st.spinner("データベースへ保存中..."):
                    for i, d in enumerate(r_list):
                        img_url = None
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
                                db.storage.from_("sheet_images").upload(f_nm, f_b, {"content-type": mime})
                                img_url = db.storage.from_("sheet_images").get_public_url(f_nm)
                            except Exception:
                                pass

                        db.table("evaluations").insert({
                            "clinic_name": d.get("clinic_name"),
                            "patient_name": d.get("patient_name"),
                            "slip_number": d.get("slip_number"),
                            "completion_date": d.get("completion_date"),
                            "restoration_type": d.get("restoration_type"),
                            "material": d.get("material"),
                            "tooth_position": d.get("tooth_position"),
                            "contact": d.get("contact"),
                            "bite": d.get("bite"),
                            "fit": d.get("fit"),
                            "comments": d.get("comments"),
                            "image_url": img_url
                        }).execute()
                        s_cnt += 1
                        
                del st.session_state["r_list"]
                del st.session_state["f_list"]
                st.success(f"{s_cnt}件のデータを保存しました！")

with tab2:
    st.subheader("✍️ 画像を使わずに手動で新規登録する")
    with st.form("manual_entry_form"):
        col_m1, col_m2 = st.columns(2)
        with col_m1:
            m_clinic = st.text_input("医院名")
            m_patient = st.text_input("患者名")
            m_slip = st.text_input("伝票番号")
            m_date = st.date_input("完成日", value=date.today())
        with col_m2:
            m_type = st.selectbox("種別", TYPE_LIST)
            m_material = st.selectbox("材料", MATERIAL_LIST)
            m_pos = st.text_input("部位")
            m_con = st.slider("コンタクト", 1, 5, 3)
            m_bit = st.slider("バイト", 1, 5, 3)
            m_fit = st.slider("適合", 1, 5, 3)
        m_com = st.text_area("コメント")
            
        if st.form_submit_button("手動で登録する", type="primary"):
            if db:
                try:
                    db.table("evaluations").insert({
                        "clinic_name": m_clinic,
                        "patient_name": m_patient,
                        "slip_number": m_slip,
                        "completion_date": m_date.isoformat(),
                        "restoration_type": m_type,
                        "material": m_material,
                        "tooth_position": m_pos,
                        "contact": m_con,
                        "bite": m_bit,
                        "fit": m_fit,
                        "comments": m_com,
                        "image_url": None
                    }).execute()
                    # 改善2: トースト通知で画面をスッキリ
                    st.toast("手動登録が完了しました！", icon="✅")
                except Exception as e:
                    st.error(f"登録エラー: {e}")

with tab3:
    st.subheader("📊 分析ダッシュボード")
    if db:
        res = db.table("evaluations").select("*").order("completion_date", desc=True).execute()
        
        if res.data:
            df = pd.DataFrame(res.data)
            df['completion_date'] = pd.to_datetime(df['completion_date'], errors='coerce')
            
            col_f1, col_f2, col_f3 = st.columns(3)
            with col_f1:
                clinics = ["すべて"] + list(df["clinic_name"].dropna().unique())
                s_c = st.selectbox("🏥 医院", clinics)
            with col_f2:
                periods = ["すべて", "直近1ヶ月", "直近2ヶ月", "直近3ヶ月", "直近6ヶ月"]
                s_p = st.selectbox("📅 期間", periods)
            with col_f3:
                materials_opt = ["すべて"] + list(df.get("material", pd.Series([""])).dropna().unique())
                s_m = st.selectbox("💎 材料", materials_opt)
            
            f_df = df.copy()
            if s_c != "すべて": f_df = f_df[f_df["clinic_name"] == s_c]
            if s_m != "すべて" and "material" in f_df.columns: f_df = f_df[f_df["material"] == s_m]
                
            today = pd.Timestamp.today()
            if s_p == "直近1ヶ月": f_df = f_df[f_df['completion_date'] >= (today - pd.DateOffset(months=1))]
            elif s_p == "直近2ヶ月": f_df = f_df[f_df['completion_date'] >= (today - pd.DateOffset(months=2))]
            elif s_p == "直近3ヶ月": f_df = f_df[f_df['completion_date'] >= (today - pd.DateOffset(months=3))]
            elif s_p == "直近6ヶ月": f_df = f_df[f_df['completion_date'] >= (today - pd.DateOffset(months=6))]

            st.markdown("---")
            
            # 改善5: ダッシュボード感のある指標表示（基準値3.0からの差分を色付きで表示）
            col1, col2, col3, col4 = st.columns(4)
            col1.metric("📄 対象件数", f"{len(f_df)} 件")
            c_m = f_df['contact'].mean() if len(f_df) > 0 else 0
            b_m = f_df['bite'].mean() if len(f_df) > 0 else 0
            f_m = f_df['fit'].mean() if len(f_df) > 0 else 0
            
            col2.metric("コンタクト平均", f"{c_m:.2f}", f"{c_m - 3.0:.2f} (基準値3比)")
            col3.metric("バイト平均", f"{b_m:.2f}", f"{b_m - 3.0:.2f} (基準値3比)")
            col4.metric("適合平均", f"{f_m:.2f}", f"{f_m - 3.0:.2f} (基準値3比)")

            if st.button("🤖 AI詳細分析（傾向と改善点）", type="primary"):
                with st.spinner("AIがデータを分析中..."):
                    c = genai.Client(api_key=KEY)
                    cols = ['completion_date', 'restoration_type', 'material', 'contact', 'bite', 'fit', 'comments']
                    dic = f_df[[c for c in cols if c in f_df.columns]].to_dict(orient='records')
                    prm = f"条件（医院:{s_c}, 期間:{s_p}, 材料:{s_m}）の補綴物データの傾向を分析し、特に材料や設計による特徴・改善点を考察してください:\n{dic}"
                    r_ai = c.models.generate_content(model='gemini-3.5-flash', contents=prm)
                    st.info(r_ai.text)

            st.markdown("<br>", unsafe_allow_html=True)
            col_chart1, col_chart2 = st.columns(2)
            with col_chart1:
                st.markdown("**📊 全体平均**")
                fig_bar = px.bar(x=["コンタクト", "バイト", "適合"], y=[c_m, b_m, f_m], range_y=[1, 5], color_discrete_sequence=['#4CAF50'])
                st.plotly_chart(fig_bar, use_container_width=True)
                
            with col_chart2:
                st.markdown("**📈 月別推移（品質トレンド）**")
                if len(f_df) > 0:
                    f_df['month'] = f_df['completion_date'].dt.to_period('M').astype(str)
                    trend_df = f_df.groupby('month')[['contact', 'bite', 'fit']].mean().reset_index()
                    fig_line = px.line(trend_df, x='month', y=['contact', 'bite', 'fit'], markers=True, range_y=[1, 5])
                    st.plotly_chart(fig_line, use_container_width=True)

with tab4:
    st.subheader("📋 履歴管理（編集・削除）")
    if db:
        res = db.table("evaluations").select("*").order("completion_date", desc=True).execute()
        
        if res.data:
            df = pd.DataFrame(res.data)
            
            col_s1, col_s2 = st.columns([3, 1])
            with col_s1:
                q = st.text_input("🔍 患者名・医院名で検索")
            with col_s2:
                st.markdown("<br>", unsafe_allow_html=True)
                csv = df.to_csv(index=False).encode('utf-8-sig')
                st.download_button("📥 CSV出力", csv, "evaluations.csv", "text/csv", use_container_width=True)
                
            if q:
                c1 = df['patient_name'].astype(str).str.contains(q, na=False)
                c2 = df['clinic_name'].astype(str).str.contains(q, na=False)
                df = df[c1 | c2]

            # 改善4: 表の表示項目をスリム化して見やすく
            display_cols = ['completion_date', 'clinic_name', 'patient_name', 'restoration_type', 'material', 'contact', 'bite', 'fit']
            available_cols = [c for c in display_cols if c in df.columns]
            st.dataframe(df[available_cols], use_container_width=True)
            
            st.markdown("---")
            st.subheader("📝 保存済みデータの編集")
            edit_options = ["選択してください"]
            edit_map = {}
            for _, row in df.iterrows():
                label = f"ID:{row['id']} | {row['clinic_name']} - {row['patient_name']} 様 ({row['completion_date']})"
                edit_options.append(label)
                edit_map[label] = row
                
            selected_edit_label = st.selectbox("編集するデータ", edit_options)
            if selected_edit_label != "選択してください":
                target_row = edit_map[selected_edit_label]
                
                if target_row.get('image_url'):
                    st.image(target_row['image_url'], width=300, caption="アップロードされた評価シート")
                    
                with st.form("edit_form"):
                    col_e1, col_e2 = st.columns(2)
                    with col_e1:
                        e_clinic = st.text_input("医院名", value=str(target_row.get('clinic_name') or ""))
                        e_patient = st.text_input("患者名", value=str(target_row.get('patient_name') or ""))
                        e_slip = st.text_input("伝票番号", value=str(target_row.get('slip_number') or ""))
                        
                        e_date_val = date.today()
                        try:
                            if target_row.get('completion_date'):
                                e_date_val = date.fromisoformat(str(target_row['completion_date'])[:10])
                        except: pass
                        e_date = st.date_input("完成日", value=e_date_val)
                        
                    with col_e2:
                        r_def = target_row.get('restoration_type', "クラウン")
                        e_idx_t = TYPE_LIST.index(r_def) if r_def in TYPE_LIST else 0
                        e_type = st.selectbox("種別", TYPE_LIST, index=e_idx_t)
                        
                        m_def = target_row.get('material', "ジルコニア")
                        e_idx_m = MATERIAL_LIST.index(m_def) if m_def in MATERIAL_LIST else 0
                        e_material = st.selectbox("材料", MATERIAL_LIST, index=e_idx_m)
                        
                        e_pos = st.text_input("部位", value=str(target_row.get('tooth_position') or ""))
                        e_con = st.slider("コンタクト", 1, 5, int(target_row.get('contact') or 3))
                        e_bit = st.slider("バイト", 1, 5, int(target_row.get('bite') or 3))
                        e_fit = st.slider("適合", 1, 5, int(target_row.get('fit') or 3))
                    
                    e_com = st.text_area("コメント", value=str(target_row.get('comments') or ""))
                    
                    if st.form_submit_button("🔄 変更を保存する", type="primary"):
                        try:
                            db.table("evaluations").update({
                                "clinic_name": e_clinic,
                                "patient_name": e_patient,
                                "slip_number": e_slip,
                                "completion_date": e_date.isoformat(),
                                "restoration_type": e_type,
                                "material": e_material,
                                "tooth_position": e_pos,
                                "contact": e_con,
                                "bite": e_bit,
                                "fit": e_fit,
                                "comments": e_com
                            }).eq("id", target_row['id']).execute()
                            st.success("データを更新しました！画面を再読み込みしてください。")
                        except Exception as e:
                            st.error(f"更新エラー: {e}")

            st.markdown("---")
            with st.expander("🗑️ データの一括削除（取り扱い注意）", expanded=False):
                st.markdown("削除したいデータにチェックを入れてください。")
                selected_ids = []
                for _, row in df.iterrows():
                    chk_label = f"ID:{row['id']} | {row['clinic_name']} - {row['patient_name']} 様"
                    if st.checkbox(chk_label, key=f"del_{row['id']}"):
                        selected_ids.append(row['id'])
                
                if selected_ids:
                    if st.button(f"⚠️ 選択した {len(selected_ids)} 件のデータを完全に削除する"):
                        try:
                            for tid in selected_ids:
                                db.table("evaluations").delete().eq("id", tid).execute()
                            st.success(f"{len(selected_ids)} 件のデータを削除しました！")
                            time.sleep(1)
                            st.rerun()
                        except Exception as e:
                            st.error(f"削除エラー: {e}")
        else:
            st.info("保存されたデータはまだありません。")
