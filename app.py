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
import base64

# --- 1. ページ全体の初期設定 ---
st.set_page_config(
    page_title="AI分析 Pro (大阪センター)",
    page_icon="🦷",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# --- 2. スマホ対応・スタイリッシュCSS ---
st.markdown("""
<style>
    #MainMenu {visibility: hidden;}
    header {visibility: hidden;}
    footer {visibility: hidden;}
    
    .custom-title {
        font-size: clamp(1.3rem, 5vw, 2.0rem);
        font-weight: 800;
        color: #1E3A8A;
        margin-bottom: 5px;
        line-height: 1.3;
    }
    
    .title-underline {
        height: 4px;
        background: linear-gradient(90deg, #3B82F6, #14B8A6);
        border-radius: 2px;
        width: 80px;
        margin-bottom: 25px;
    }
    
    .stButton>button[kind="primary"] {
        background: linear-gradient(135deg, #3B82F6, #14B8A6);
        color: white;
        border: none;
        border-radius: 8px;
        padding: 0.5rem 1rem;
        font-weight: 600;
        box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
        transition: all 0.3s ease;
    }
    .stButton>button[kind="primary"]:hover {
        box-shadow: 0 6px 12px rgba(0, 0, 0, 0.15);
        transform: translateY(-2px);
    }
    
    .streamlit-expanderHeader {
        border-radius: 8px;
        border: 1px solid #E2E8F0;
    }
</style>
""", unsafe_allow_html=True)

# --- カスタムヘッダー ---
st.markdown('<div class="custom-title">🦷 セパレートレスモデル評価 AI分析<br><span style="font-size: 0.7em; color: #888;">(大阪センター)</span></div>', unsafe_allow_html=True)
st.markdown('<div class="title-underline"></div>', unsafe_allow_html=True)

# --- データベース等の初期化 ---
KEY = st.secrets.get("GEMINI_API_KEY")
URL = st.secrets.get("SUPABASE_URL")
S_KEY = st.secrets.get("SUPABASE_KEY")

@st.cache_resource
def get_db():
    if URL and S_KEY:
        return create_client(URL, S_KEY)
    return None

db = get_db()

tab1, tab2, tab3, tab4 = st.tabs([
    "🤖 AI一括", 
    "✍️ 手動", 
    "📊 分析", 
    "📋 管理"
])

MATERIAL_LIST = ["ジルコニア", "CAD/CAM冠", "e.max", "メタル", "3Dプリント", "その他"]
TYPE_LIST = ["クラウン", "ブリッジ", "インプラント", "義歯", "その他"]

with tab1:
    st.markdown("### 📄 評価シートのアップロード")
    st.info("写真やPDFを選択し、「一括AI解析」ボタンを押してください。")
    up_files = st.file_uploader("画像/PDF(複数選択可)", type=["jpg", "png", "pdf"], accept_multiple_files=True, label_visibility="collapsed")

    if up_files and KEY:
        if st.button("✨ 一括AI解析をスタート", type="primary"):
            with st.spinner("AIがシートを読み取っています..."):
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
                            # ★修正ポイント1：ファイル名ではなく「何番目の画像か」を記録する
                            item["_f_idx"] = idx 
                            r_list.append(item)
                    except Exception as e:
                        st.error(f"{f.name} エラー: {e}")
                        
                st.session_state["r_list"] = r_list
                st.session_state["f_list"] = up_files
                st.toast(f"合計 {len(r_list)} 件のデータを検出しました！", icon="✨")

    if "r_list" in st.session_state:
        st.markdown("<br>### 📝 抽出データの確認と修正", unsafe_allow_html=True)
        r_list = st.session_state["r_list"]
        f_list = st.session_state["f_list"]
        
        for i, d in enumerate(r_list):
            p_name = d.get("patient_name", "患者名未入力")
            c_name = d.get("clinic_name", "医院名未入力")
            
            with st.expander(f"👤 データ #{i+1} : {p_name} 様  |  🏥 {c_name}", expanded=False):
                # ★修正ポイント2：記録した「順番（インデックス）」で画像を取り出す
                f_idx = d.get("_f_idx")
                matching_file = f_list[f_idx] if (f_idx is not None and f_idx < len(f_list)) else None
                
                col_img, col_form1, col_form2 = st.columns([2, 2, 2], gap="medium")
                
                with col_img:
                    st.markdown("**🖼️ 元画像プレビュー**")
                    if matching_file:
                        if "pdf" in matching_file.type:
                            st.info("📄 PDFファイルです")
                        else:
                            try:
                                # getvalue()を使うことで表示エラーを回避
                                st.image(matching_file.getvalue(), use_container_width=True)
                            except:
                                st.warning("画像を表示できません")
                    else:
                        st.write("画像がありません")
                
                with col_form1:
                    d["clinic_name"] = st.text_input("医院名 (必須)", d.get("clinic_name", ""), key=f"c_{i}")
                    d["patient_name"] = st.text_input("患者名 (必須)", d.get("patient_name", ""), key=f"p_{i}")
                    d["slip_number"] = st.text_input("伝票番号", d.get("slip_number", ""), key=f"s_{i}")
                    
                    raw_date = d.get("completion_date", "")
                    def_date = date.today()
                    try:
                        if raw_date: def_date = date.fromisoformat(str(raw_date)[:10])
                    except: pass
                    c_date = st.date_input("完成日", value=def_date, key=f"dt_{i}")
                    d["completion_date"] = c_date.isoformat()
                    
                with col_form2:
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

        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("💾 確認したデータを全て保存", type="primary", use_container_width=True):
            has_error = False
            for idx, d in enumerate(r_list):
                if not d.get("clinic_name") or not d.get("patient_name"):
                    st.error(f"⚠️ データ #{idx+1} の「医院名」または「患者名」が入力されていません。")
                    has_error = True
            
            if not has_error:
                if db:
                    s_cnt = 0
                    with st.spinner("安全にデータベースへ保存中..."):
                        for i, d in enumerate(r_list):
                            img_url = None
                            # ★修正ポイント3：保存時にも正確な順番で画像を引っ張ってくる
                            f_idx = d.get("_f_idx")
                            if f_idx is not None and f_idx < len(f_list):
                                f_obj = f_list[f_idx]
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
                    st.success(f"🎉 {s_cnt}件のデータを保存しました！")
                    time.sleep(1.5)
                    st.rerun()

with tab2:
    st.markdown("### ✍️ 新規データの手動入力")
    with st.container(border=True):
        with st.form("manual_entry_form"):
            col_m1, col_m2 = st.columns(2)
            with col_m1:
                m_clinic = st.text_input("🏥 医院名 (必須)")
                m_patient = st.text_input("👤 患者名 (必須)")
                m_slip = st.text_input("📝 伝票番号")
                m_date = st.date_input("📅 完成日", value=date.today())
            with col_m2:
                m_type = st.selectbox("🦷 種別", TYPE_LIST)
                m_material = st.selectbox("💎 材料", MATERIAL_LIST)
                m_pos = st.text_input("📍 部位")
                m_con = st.slider("コンタクト", 1, 5, 3)
                m_bit = st.slider("バイト", 1, 5, 3)
                m_fit = st.slider("適合", 1, 5, 3)
            m_com = st.text_area("💬 コメント")
                
            submit_btn = st.form_submit_button("手動で登録する", type="primary")
            if submit_btn:
                if not m_clinic or not m_patient:
                    st.error("⚠️ 医院名と患者名は必須入力です。")
                elif db:
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
                        st.toast("手動登録が完了しました！", icon="✅")
                    except Exception as e:
                        st.error(f"登録エラー: {e}")

with tab3:
    st.markdown("### 📊 品質分析ダッシュボード")
    if db:
        res = db.table("evaluations").select("*").order("completion_date", desc=True).execute()
        
        if res.data:
            df = pd.DataFrame(res.data)
            df['completion_date'] = pd.to_datetime(df['completion_date'], errors='coerce')
            
            with st.container(border=True):
                col_f1, col_f2, col_f3 = st.columns(3)
                with col_f1:
                    clinics = ["すべて"] + list(df["clinic_name"].dropna().unique())
                    s_c = st.selectbox("🏥 医院で絞り込み", clinics)
                with col_f2:
                    periods = ["すべて", "直近1ヶ月", "直近2ヶ月", "直近3ヶ月", "直近6ヶ月"]
                    s_p = st.selectbox("📅 期間で絞り込み", periods)
                with col_f3:
                    materials_opt = ["すべて"] + list(df.get("material", pd.Series([""])).dropna().unique())
                    s_m = st.selectbox("💎 材料で絞り込み", materials_opt)
            
            f_df = df.copy()
            if s_c != "すべて": f_df = f_df[f_df["clinic_name"] == s_c]
            if s_m != "すべて" and "material" in f_df.columns: f_df = f_df[f_df["material"] == s_m]
                
            today = pd.Timestamp.today()
            if s_p == "直近1ヶ月": f_df = f_df[f_df['completion_date'] >= (today - pd.DateOffset(months=1))]
            elif s_p == "直近2ヶ月": f_df = f_df[f_df['completion_date'] >= (today - pd.DateOffset(months=2))]
            elif s_p == "直近3ヶ月": f_df = f_df[f_df['completion_date'] >= (today - pd.DateOffset(months=3))]
            elif s_p == "直近6ヶ月": f_df = f_df[f_df['completion_date'] >= (today - pd.DateOffset(months=6))]

            st.markdown("<br>", unsafe_allow_html=True)
            
            c_m = f_df['contact'].mean() if len(f_df) > 0 else 0
            b_m = f_df['bite'].mean() if len(f_df) > 0 else 0
            f_m = f_df['fit'].mean() if len(f_df) > 0 else 0

            c_opt = (f_df['contact'] == 3).sum() / len(f_df) * 100 if len(f_df) > 0 else 0
            b_opt = (f_df['bite'] == 3).sum() / len(f_df) * 100 if len(f_df) > 0 else 0
            f_opt = (f_df['fit'] == 3).sum() / len(f_df) * 100 if len(f_df) > 0 else 0
            
            def render_metric(label, mean_val, opt_rate):
                if mean_val == 0:
                    color = "#9e9e9e"
                    mean_str = "-"
                    opt_str = "- %"
                else:
                    diff = mean_val - 3.0
                    color = "#10B981" if opt_rate >= 80 else ("#F59E0B" if opt_rate >= 50 else "#EF4444")
                    mean_str = f"{mean_val:.2f} (誤差 {diff:+.2f})"
                    opt_str = f"{opt_rate:.1f}%"
                
                return f"""
                <div style="padding: 15px; border-radius: 8px; border: 1px solid #E2E8F0; background-color: #FFFFFF; text-align: center; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05);">
                    <p style="margin: 0; font-size: 14px; color: #64748B; font-weight: bold;">{label} (適正率)</p>
                    <h2 style="margin: 10px 0; color: {color}; font-size: 32px; font-weight: 800;">{opt_str}</h2>
                    <p style="margin: 0; font-size: 13px; color: #64748B;">平均点: {mean_str}</p>
                </div>
                """

            col1, col2, col3, col4 = st.columns(4)
            with col1:
                st.markdown(f"""
                <div style="padding: 15px; border-radius: 8px; border: 1px solid #E2E8F0; background-color: #FFFFFF; text-align: center; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05);">
                    <p style="margin: 0; font-size: 14px; color: #64748B; font-weight: bold;">📄 対象件数</p>
                    <h2 style="margin: 10px 0; color: #0F172A; font-size: 32px; font-weight: 800;">{len(f_df)}<span style='font-size:16px;'>件</span></h2>
                    <p style="margin: 0; font-size: 13px; color: transparent;">-</p>
                </div>
                """, unsafe_allow_html=True)
            
            with col2: st.markdown(render_metric("コンタクト", c_m, c_opt), unsafe_allow_html=True)
            with col3: st.markdown(render_metric("バイト", b_m, b_opt), unsafe_allow_html=True)
            with col4: st.markdown(render_metric("適合", f_m, f_opt), unsafe_allow_html=True)

            st.markdown("<br>", unsafe_allow_html=True)

            if len(f_df) > 0:
                html_content = f"""
                <html>
                <head><meta charset="utf-8"><title>セパレートレスモデル 品質分析レポート</title></head>
                <body style="font-family: sans-serif; padding: 20px; color: #333;">
                    <h2 style="color: #1E3A8A; border-bottom: 2px solid #3B82F6; padding-bottom: 10px;">セパレートレスモデル 品質分析レポート (大阪センター)</h2>
                    <p><strong>医院:</strong> {s_c} &nbsp;&nbsp;|&nbsp;&nbsp; <strong>期間:</strong> {s_p} &nbsp;&nbsp;|&nbsp;&nbsp; <strong>材料:</strong> {s_m}</p>
                    <p><strong>出力日:</strong> {date.today().isoformat()}</p>
                    <div style="background-color: #F8FAFC; padding: 15px; border-radius: 8px; border: 1px solid #E2E8F0;">
                        <h3 style="color: #0F172A;">📊 総合評価（評価「3」の割合）</h3>
                        <ul style="font-size: 16px;">
                            <li>対象件数: <strong>{len(f_df)} 件</strong></li>
                            <li>コンタクト適正率: <strong>{c_opt:.1f}%</strong> (平均: {c_m:.2f})</li>
                            <li>バイト適正率: <strong>{b_opt:.1f}%</strong> (平均: {b_m:.2f})</li>
                            <li>適合適正率: <strong>{f_opt:.1f}%</strong> (平均: {f_m:.2f})</li>
                        </ul>
                        <p style="font-size: 12px; color: #666;">※評価基準: 1(弱い) ～ 3(適正) ～ 5(強い)</p>
                    </div>
                </body>
                </html>
                """
                b64 = base64.b64encode(html_content.encode('utf-8')).decode()
                href = f'<a href="data:text/html;base64,{b64}" download="quality_report.html" target="_blank" style="display: inline-block; padding: 10px 20px; background: linear-gradient(135deg, #10B981, #059669); color: white; text-decoration: none; border-radius: 8px; font-weight: bold; box-shadow: 0 4px 6px rgba(0,0,0,0.1);">📥 医院向けレポートを出力 (HTML)</a>'
                st.markdown(href, unsafe_allow_html=True)

            st.markdown("<br>", unsafe_allow_html=True)
            col_chart1, col_chart2 = st.columns(2)
            with col_chart1:
                with st.container(border=True):
                    st.markdown("**📈 月別推移（品質トレンド）**")
                    if len(f_df) > 0:
                        f_df['month'] = f_df['completion_date'].dt.to_period('M').astype(str)
                        trend_df = f_df.groupby('month')[['contact', 'bite', 'fit']].mean().reset_index()
                        fig_line = px.line(trend_df, x='month', y=['contact', 'bite', 'fit'], markers=True, range_y=[1, 5])
                        fig_line.add_hline(y=3.0, line_dash="dash", line_color="#3B82F6", annotation_text="適正値 (3.0)")
                        st.plotly_chart(fig_line, use_container_width=True)
                
            with col_chart2:
                with st.container(border=True):
                    st.markdown("**📊 スコア分布**")
                    if len(f_df) > 0:
                        dist_data = []
                        total_cnt = len(f_df)
                        name_map = {'contact': 'コンタクト', 'bite': 'バイト', 'fit': '適合'}
                        
                        for col in ['contact', 'bite', 'fit']:
                            counts = f_df[col].value_counts().reindex([1,2,3,4,5], fill_value=0)
                            for score, count in counts.items():
                                pct = (count / total_cnt * 100) if total_cnt > 0 else 0
                                txt = f"{pct:.1f}%" if count > 0 else ""
                                dist_data.append({
                                    '評価項目': name_map[col], 
                                    'スコア': str(score), 
                                    '件数': count,
                                    '割合': txt
                                })
                        dist_df = pd.DataFrame(dist_data)
                        color_map = {'1': '#93C5FD', '2': '#BFDBFE', '3': '#10B981', '4': '#FDBA74', '5': '#F97316'}
                        
                        fig_dist = px.bar(
                            dist_df, x='評価項目', y='件数', color='スコア', 
                            color_discrete_map=color_map, barmode='stack', text='割合'
                        )
                        fig_dist.update_traces(textposition='inside', textfont_size=14)
                        fig_dist.update_layout(
                            xaxis=dict(tickfont=dict(size=18, color="#1E3A8A", weight="bold"), title=""),
                            yaxis=dict(title="件数")
                        )
                        st.plotly_chart(fig_dist, use_container_width=True)

            if st.button("🤖 AI詳細分析（専門基準による考察）", type="primary", use_container_width=True):
                with st.spinner("AIがデータを分析中..."):
                    c = genai.Client(api_key=KEY)
                    cols = ['completion_date', 'restoration_type', 'material', 'contact', 'bite', 'fit', 'comments']
                    dic = f_df[[co for co in cols if co in f_df.columns]].to_dict(orient='records')
                    
                    prm = (
                        f"条件（医院:{s_c}, 期間:{s_p}, 材料:{s_m}）の補綴物データの傾向を分析してください。\n"
                        "【重要な前提条件】\n"
                        "評価スコア（1〜5）は「高いほど良い」わけではありません。\n"
                        "「3が適正（ピッタリ）」であり、1に近づくほど「弱い・ゆるい」、5に近づくほど「強い・きつい」を意味します。\n"
                        "この前提を踏まえた上で、材料や設計による特徴・改善点を考察してください:\n"
                        f"{dic}"
                    )
                    r_ai = c.models.generate_content(model='gemini-3.5-flash', contents=prm)
                    st.info(r_ai.text)

with tab4:
    st.markdown("### 📋 保存済みデータの管理")
    if db:
        res = db.table("evaluations").select("*").order("completion_date", desc=True).execute()
        
        if res.data:
            df = pd.DataFrame(res.data)
            
            with st.container(border=True):
                col_s1, col_s2 = st.columns([3, 1])
                with col_s1:
                    q = st.text_input("🔍 患者名・医院名で検索")
                with col_s2:
                    st.markdown("<br>", unsafe_allow_html=True)
                    csv = df.to_csv(index=False).encode('utf-8-sig')
                    st.download_button("📥 CSVダウンロード", csv, "evaluations.csv", "text/csv", use_container_width=True)
                    
            if q:
                c1 = df['patient_name'].astype(str).str.contains(q, na=False)
                c2 = df['clinic_name'].astype(str).str.contains(q, na=False)
                df = df[c1 | c2]

            display_cols = ['completion_date', 'clinic_name', 'patient_name', 'restoration_type', 'material', 'contact', 'bite', 'fit']
            available_cols = [c for c in display_cols if c in df.columns]
            st.dataframe(df[available_cols], use_container_width=True)
            
            st.markdown("---")
            st.markdown("#### 📝 データの編集")
            edit_options = ["選択してください"]
            edit_map = {}
            for _, row in df.iterrows():
                label = f"ID:{row['id']} | {row['clinic_name']} - {row['patient_name']} 様 ({row['completion_date']})"
                edit_options.append(label)
                edit_map[label] = row
                
            selected_edit_label = st.selectbox("編集するデータ", edit_options)
            if selected_edit_label != "選択してください":
                target_row = edit_map[selected_edit_label]
                
                with st.container(border=True):
                    if target_row.get('image_url'):
                        st.image(target_row['image_url'], width=300, caption="評価シート画像")
                        
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
                st.warning("削除したいデータにチェックを入れてください。一度削除すると元に戻せません。")
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
