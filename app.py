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

# ==========================================
# 1. アプリケーション初期設定 & CSS
# ==========================================
st.set_page_config(page_title="AI分析 Pro (大阪センター)", page_icon="🦷", layout="wide", initial_sidebar_state="collapsed")

st.markdown("""
<style>
    #MainMenu, header, footer {visibility: hidden;}
    .stApp {background-color: transparent !important;}
    
    .custom-title {
        font-size: clamp(1.3rem, 5vw, 2.0rem);
        font-weight: 800;
        color: #3B82F6;
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
        border: 1px solid rgba(128, 128, 128, 0.2);
    }
    .metric-card {
        padding: 15px; 
        border-radius: 8px; 
        border: 1px solid rgba(128, 128, 128, 0.2);
        background-color: transparent; 
        text-align: center; 
        box-shadow: 0 2px 4px rgba(0,0,0,0.05);
    }
</style>
""", unsafe_allow_html=True)

st.markdown('<div class="custom-title">🦷 セパレートレスモデル評価 AI分析<br><span style="font-size: 0.7em; color: #888;">(大阪センター)</span></div>', unsafe_allow_html=True)
st.markdown('<div class="title-underline"></div>', unsafe_allow_html=True)

# ==========================================
# 2. データベース接続 & 共通関数
# ==========================================
KEY = st.secrets.get("GEMINI_API_KEY")
URL = st.secrets.get("SUPABASE_URL")
S_KEY = st.secrets.get("SUPABASE_KEY")

@st.cache_resource
def get_db():
    return create_client(URL, S_KEY) if URL and S_KEY else None

db = get_db()

MATERIAL_LIST = ["ジルコニア", "CAD/CAM冠", "e.max", "メタル", "3Dプリント", "その他"]
TYPE_LIST = ["クラウン", "ブリッジ", "インプラント", "義歯", "その他"]

def safe_int(val, default=3):
    """AIの出力ブレを吸収し、確実に1〜5の整数に変換する安全装置"""
    try:
        return max(1, min(5, int(float(val))))
    except (ValueError, TypeError):
        return default

def save_evaluation_data(d, file_obj=None, idx=0):
    """データベース保存処理の共通化モジュール"""
    img_url = None
    if file_obj and db:
        f_b = file_obj.getvalue()
        is_pdf = "pdf" in file_obj.type
        ext, mime = ("pdf", "application/pdf") if is_pdf else ("jpg", "image/jpeg")
        f_nm = f"{int(time.time())}_{idx}.{ext}"
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
        "contact": safe_int(d.get("contact")),
        "bite": safe_int(d.get("bite")),
        "fit": safe_int(d.get("fit")),
        "comments": d.get("comments", ""),
        "image_url": img_url
    }).execute()

def display_file_preview(file_obj):
    """画像およびPDFプレビュー用の共通モジュール"""
    if not file_obj:
        st.write("ファイルがありません")
        return
        
    if "pdf" in file_obj.type:
        try:
            b64_pdf = base64.b64encode(file_obj.getvalue()).decode('utf-8')
            st.markdown(f'<iframe src="data:application/pdf;base64,{b64_pdf}" width="100%" height="450" style="border: 1px solid rgba(128,128,128,0.2); border-radius: 8px;"></iframe>', unsafe_allow_html=True)
        except Exception:
            st.warning("PDFを表示できません")
    else:
        try:
            st.image(file_obj.getvalue(), use_container_width=True)
        except Exception:
            st.warning("画像を表示できません")

# ==========================================
# 3. 画面描画 (Tabs)
# ==========================================
tab1, tab2, tab3, tab4 = st.tabs(["🤖 AI一括", "✍️ 手動", "📊 分析", "📋 管理"])

# ------------------------------------------
# Tab 1: AI一括登録
# ------------------------------------------
with tab1:
    st.markdown("### 📄 評価シートのアップロード")
    st.info("写真やPDFを選択し、「一括AI解析」ボタンを押してください。")
    up_files = st.file_uploader("画像/PDF(複数選択可)", type=["jpg", "png", "pdf"], accept_multiple_files=True, label_visibility="collapsed")

    if up_files and KEY and st.button("✨ 一括AI解析をスタート", type="primary"):
        with st.spinner("AIがシートを高速解析中..."):
            c = genai.Client(api_key=KEY)
            prm = (
                "このファイルには1枚または複数の補綴物評価シートが含まれています。\n"
                "以下のキーを持つJSONオブジェクトの配列（リスト: [...]）形式で抽出してください。\n"
                "キー: clinic_name, patient_name, slip_number, completion_date (YYYY-MM-DD), "
                "restoration_type, material, tooth_position, contact (1〜5), bite (1〜5), fit (1〜5), comments\n"
                "必ずJSONの配列形式のみを出力してください。"
            )
            r_list = []
            for idx, f in enumerate(up_files):
                try:
                    cp = types.Part.from_bytes(data=f.getvalue(), mime_type="application/pdf") if "pdf" in f.type else Image.open(io.BytesIO(f.getvalue()))
                    res = c.models.generate_content(model='gemini-3.5-flash', contents=[cp, prm])
                    txt = res.text.strip()
                    if txt.startswith("```"): txt = "\n".join(txt.splitlines()[1:-1])
                    parsed = json.loads(txt)
                    if isinstance(parsed, dict): parsed = [parsed]
                    for item in parsed:
                        item["_f_idx"] = idx 
                        r_list.append(item)
                except Exception as e:
                    st.error(f"ファイル解析エラー ({f.name}): {e}")
            
            st.session_state["r_list"] = r_list
            st.session_state["f_list"] = up_files
            st.toast(f"合計 {len(r_list)} 件のデータを検出しました！", icon="✨")

    if "r_list" in st.session_state:
        st.markdown("<br>### 📝 抽出データの確認と修正", unsafe_allow_html=True)
        r_list, f_list = st.session_state["r_list"], st.session_state["f_list"]
        
        for i, d in enumerate(r_list):
            with st.expander(f"👤 データ #{i+1} : {d.get('patient_name', '未入力')} 様  |  🏥 {d.get('clinic_name', '未入力')}", expanded=False):
                col_img, col_form1, col_form2 = st.columns([2, 2, 2], gap="medium")
                
                with col_img:
                    st.markdown("**🖼️ 元画像/PDFプレビュー**")
                    f_idx = d.get("_f_idx")
                    display_file_preview(f_list[f_idx] if (f_idx is not None and f_idx < len(f_list)) else None)
                
                with col_form1:
                    d["clinic_name"] = st.text_input("医院名 (必須)", d.get("clinic_name", ""), key=f"c_{i}")
                    d["patient_name"] = st.text_input("患者名 (必須)", d.get("patient_name", ""), key=f"p_{i}")
                    d["slip_number"] = st.text_input("伝票番号", d.get("slip_number", ""), key=f"s_{i}")
                    try: def_date = date.fromisoformat(str(d.get("completion_date", ""))[:10])
                    except: def_date = date.today()
                    d["completion_date"] = st.date_input("完成日", value=def_date, key=f"dt_{i}").isoformat()
                    
                with col_form2:
                    d["restoration_type"] = st.selectbox("種別", TYPE_LIST, index=TYPE_LIST.index(d.get("restoration_type")) if d.get("restoration_type") in TYPE_LIST else 0, key=f"rt_{i}")
                    d["material"] = st.selectbox("材料", MATERIAL_LIST, index=MATERIAL_LIST.index(d.get("material")) if d.get("material") in MATERIAL_LIST else 0, key=f"mat_{i}")
                    d["tooth_position"] = st.text_input("部位", d.get("tooth_position", ""), key=f"tp_{i}")
                    d["contact"] = st.slider("コンタクト", 1, 5, safe_int(d.get("contact")), key=f"co_{i}")
                    d["bite"] = st.slider("バイト", 1, 5, safe_int(d.get("bite")), key=f"bi_{i}")
                    d["fit"] = st.slider("適合", 1, 5, safe_int(d.get("fit")), key=f"fi_{i}")
                
                d["comments"] = st.text_area("コメント", d.get("comments", ""), key=f"cm_{i}")

        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("💾 確認したデータを全て保存", type="primary", use_container_width=True):
            if any(not d.get("clinic_name") or not d.get("patient_name") for d in r_list):
                st.error("⚠️ 未入力の「医院名」または「患者名」があります。")
            elif db:
                with st.spinner("安全にデータベースへ保存中..."):
                    for i, d in enumerate(r_list):
                        f_idx = d.get("_f_idx")
                        f_obj = f_list[f_idx] if (f_idx is not None and f_idx < len(f_list)) else None
                        save_evaluation_data(d, f_obj, i)
                del st.session_state["r_list"], st.session_state["f_list"]
                st.success("🎉 データの保存が完了しました！")
                time.sleep(1.5)
                st.rerun()

# ------------------------------------------
# Tab 2: 手動登録
# ------------------------------------------
with tab2:
    st.markdown("### ✍️ 新規データの手動入力")
    with st.container(border=True):
        with st.form("manual_entry_form"):
            c1, c2 = st.columns(2)
            with c1:
                m_clinic = st.text_input("🏥 医院名 (必須)")
                m_patient = st.text_input("👤 患者名 (必須)")
                m_slip = st.text_input("📝 伝票番号")
                m_date = st.date_input("📅 完成日", value=date.today())
            with c2:
                m_type = st.selectbox("🦷 種別", TYPE_LIST)
                m_material = st.selectbox("💎 材料", MATERIAL_LIST)
                m_pos = st.text_input("📍 部位")
                m_con = st.slider("コンタクト", 1, 5, 3)
                m_bit = st.slider("バイト", 1, 5, 3)
                m_fit = st.slider("適合", 1, 5, 3)
            m_com = st.text_area("💬 コメント")
                
            if st.form_submit_button("手動で登録する", type="primary"):
                if not m_clinic or not m_patient:
                    st.error("⚠️ 医院名と患者名は必須入力です。")
                elif db:
                    save_evaluation_data({
                        "clinic_name": m_clinic, "patient_name": m_patient, "slip_number": m_slip,
                        "completion_date": m_date.isoformat(), "restoration_type": m_type, "material": m_material,
                        "tooth_position": m_pos, "contact": m_con, "bite": m_bit, "fit": m_fit, "comments": m_com
                    })
                    st.toast("手動登録が完了しました！", icon="✅")

# ------------------------------------------
# Tab 3: 分析ダッシュボード
# ------------------------------------------
with tab3:
    st.markdown("### 📊 品質分析ダッシュボード")
    if db:
        res = db.table("evaluations").select("*").order("completion_date", desc=True).execute()
        if res.data:
            df = pd.DataFrame(res.data)
            df['completion_date'] = pd.to_datetime(df['completion_date'], errors='coerce')
            
            with st.container(border=True):
                cf1, cf2, cf3 = st.columns(3)
                s_c = cf1.selectbox("🏥 医院で絞り込み", ["すべて"] + list(df["clinic_name"].dropna().unique()))
                s_p = cf2.selectbox("📅 期間で絞り込み", ["すべて", "直近1ヶ月", "直近2ヶ月", "直近3ヶ月", "直近6ヶ月"])
                s_m = cf3.selectbox("💎 材料で絞り込み", ["すべて"] + list(df.get("material", pd.Series([""])).dropna().unique()))
            
            # フィルタリング処理
            f_df = df.copy()
            if s_c != "すべて": f_df = f_df[f_df["clinic_name"] == s_c]
            if s_m != "すべて" and "material" in f_df.columns: f_df = f_df[f_df["material"] == s_m]
            
            p_map = {"直近1ヶ月": 1, "直近2ヶ月": 2, "直近3ヶ月": 3, "直近6ヶ月": 6}
            if s_p in p_map: f_df = f_df[f_df['completion_date'] >= (pd.Timestamp.today() - pd.DateOffset(months=p_map[s_p]))]

            st.markdown("<br>", unsafe_allow_html=True)
            
            # スコア計算
            def get_stats(col):
                return (f_df[col].mean(), (f_df[col] == 3).sum() / len(f_df) * 100) if len(f_df) > 0 else (0, 0)

            c_m, c_opt = get_stats('contact')
            b_m, b_opt = get_stats('bite')
            f_m, f_opt = get_stats('fit')
            
            def render_metric(label, mean_val, opt_rate):
                if mean_val == 0: return f'<div class="metric-card"><p style="font-weight:bold;">{label}</p><h2>- %</h2></div>'
                color = "#10B981" if opt_rate >= 80 else ("#F59E0B" if opt_rate >= 50 else "#EF4444")
                return f"""
                <div class="metric-card">
                    <p style="margin: 0; font-size: 14px; font-weight: bold;">{label} (適正率)</p>
                    <h2 style="margin: 10px 0; color: {color}; font-size: 32px; font-weight: 800;">{opt_rate:.1f}%</h2>
                    <p style="margin: 0; font-size: 13px;">平均点: {mean_val:.2f} (誤差 {mean_val-3.0:+.2f})</p>
                </div>
                """

            col1, col2, col3, col4 = st.columns(4)
            with col1: st.markdown(f'<div class="metric-card"><p style="margin: 0; font-size: 14px; font-weight: bold;">📄 対象件数</p><h2 style="margin: 10px 0; font-size: 32px; font-weight: 800;">{len(f_df)}<span style="font-size:16px;">件</span></h2><p style="margin: 0; font-size: 13px; color: transparent;">-</p></div>', unsafe_allow_html=True)
            with col2: st.markdown(render_metric("コンタクト", c_m, c_opt), unsafe_allow_html=True)
            with col3: st.markdown(render_metric("バイト", b_m, b_opt), unsafe_allow_html=True)
            with col4: st.markdown(render_metric("適合", f_m, f_opt), unsafe_allow_html=True)

            st.markdown("<br>", unsafe_allow_html=True)

            # AI詳細分析 (スコアカード直後)
            if st.button("🤖 AI詳細分析（専門基準による考察）", type="primary", use_container_width=True):
                with st.spinner("AIがデータを分析中..."):
                    dic = f_df[['completion_date', 'restoration_type', 'material', 'contact', 'bite', 'fit', 'comments']].to_dict(orient='records')
                    prm = f"条件（医院:{s_c}, 期間:{s_p}, 材料:{s_m}）の傾向分析をお願いします。3が適正、1が弱い、5がきついの前提で分析してください:\n{dic}"
                    st.info(genai.Client(api_key=KEY).models.generate_content(model='gemini-3.5-flash', contents=prm).text)

            st.markdown("<br>", unsafe_allow_html=True)
            col_chart1, col_chart2 = st.columns(2)
            
            with col_chart1:
                with st.container(border=True):
                    st.markdown("**📈 月別推移（品質トレンド）**")
                    if len(f_df) > 0:
                        trend_df = f_df.assign(month=f_df['completion_date'].dt.to_period('M').astype(str)).groupby('month')[['contact', 'bite', 'fit']].mean().reset_index()
                        fig_line = px.line(trend_df, x='month', y=['contact', 'bite', 'fit'], markers=True, range_y=[1, 5])
                        fig_line.add_hline(y=3.0, line_dash="dash", line_color="#3B82F6", annotation_text="適正値 (3.0)")
                        st.plotly_chart(fig_line, use_container_width=True)
                
            with col_chart2:
                with st.container(border=True):
                    st.markdown("**📊 スコア分布**")
                    if len(f_df) > 0:
                        name_map = {'contact': 'コンタクト', 'bite': 'バイト', 'fit': '適合'}
                        dist_data = [
                            {'評価項目': name_map[col], 'スコア': str(score), '件数': count, '割合': f"<b>{count/len(f_df)*100:.1f}%</b>" if count > 0 else ""}
                            for col in ['contact', 'bite', 'fit']
                            for score, count in f_df[col].value_counts().reindex([1,2,3,4,5], fill_value=0).items()
                        ]
                        fig_dist = px.bar(pd.DataFrame(dist_data), x='評価項目', y='件数', color='スコア', color_discrete_map={'1': '#93C5FD', '2': '#BFDBFE', '3': '#10B981', '4': '#FDBA74', '5': '#F97316'}, barmode='stack', text='割合')
                        fig_dist.update_traces(textposition='inside', textfont_size=16)
                        fig_dist.update_layout(xaxis=dict(tickfont=dict(size=18, color="#3B82F6", weight="bold"), title=""), yaxis=dict(title="件数"))
                        st.plotly_chart(fig_dist, use_container_width=True)

            st.markdown("<br>", unsafe_allow_html=True)
            # 医院向けレポート (一番下)
            if len(f_df) > 0:
                html = f"""
                <html><head><meta charset="utf-8"><title>品質分析レポート</title></head>
                <body style="font-family: sans-serif; padding: 20px; color: #333;">
                    <h2 style="color: #1E3A8A; border-bottom: 2px solid #3B82F6;">セパレートレスモデル 品質分析レポート (大阪センター)</h2>
                    <p>医院: {s_c} | 期間: {s_p} | 材料: {s_m} | 出力日: {date.today().isoformat()}</p>
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
                </body></html>
                """
                b64 = base64.b64encode(html.encode('utf-8')).decode()
                st.markdown(f'<a href="data:text/html;base64,{b64}" download="quality_report.html" target="_blank" style="display: inline-block; padding: 10px 20px; background: linear-gradient(135deg, #10B981, #059669); color: white; text-decoration: none; border-radius: 8px; font-weight: bold; box-shadow: 0 4px 6px rgba(0,0,0,0.1);">📥 医院向けレポートを出力 (HTML)</a>', unsafe_allow_html=True)

# ------------------------------------------
# Tab 4: 履歴・管理
# ------------------------------------------
with tab4:
    st.markdown("### 📋 保存済みデータの管理")
    if db:
        res = db.table("evaluations").select("*").order("completion_date", desc=True).execute()
        if res.data:
            df = pd.DataFrame(res.data)
            
            with st.container(border=True):
                col_s1, col_s2 = st.columns([3, 1])
                q = col_s1.text_input("🔍 患者名・医院名で検索")
                col_s2.markdown("<br>", unsafe_allow_html=True)
                col_s2.download_button("📥 CSVダウンロード", df.to_csv(index=False).encode('utf-8-sig'), "evaluations.csv", "text/csv", use_container_width=True)
                    
            if q:
                df = df[df['patient_name'].astype(str).str.contains(q, na=False) | df['clinic_name'].astype(str).str.contains(q, na=False)]

            display_cols = [c for c in ['completion_date', 'clinic_name', 'patient_name', 'restoration_type', 'material', 'contact', 'bite', 'fit'] if c in df.columns]
            st.dataframe(df[display_cols], use_container_width=True)
            
            st.markdown("---")
            st.markdown("#### 📝 データの編集")
            edit_map = {f"ID:{row['id']} | {row['clinic_name']} - {row['patient_name']} 様 ({row['completion_date']})": row for _, row in df.iterrows()}
            selected_edit_label = st.selectbox("編集するデータ", ["選択してください"] + list(edit_map.keys()))
            
            if selected_edit_label != "選択してください":
                target_row = edit_map[selected_edit_label]
                with st.container(border=True):
                    img_url = target_row.get('image_url')
                    if img_url:
                        if ".pdf" in img_url.lower():
                            st.markdown(f'<iframe src="{img_url}" width="100%" height="450" style="border: 1px solid rgba(128,128,128,0.2); border-radius: 8px;"></iframe>', unsafe_allow_html=True)
                        else:
                            st.image(img_url, use_container_width=True, caption="評価シート画像")
                        
                    with st.form("edit_form"):
                        col_e1, col_e2 = st.columns(2)
                        with col_e1:
                            e_clinic = st.text_input("医院名", value=str(target_row.get('clinic_name') or ""))
                            e_patient = st.text_input("患者名", value=str(target_row.get('patient_name') or ""))
                            e_slip = st.text_input("伝票番号", value=str(target_row.get('slip_number') or ""))
                            try: e_date_val = date.fromisoformat(str(target_row.get('completion_date'))[:10])
                            except: e_date_val = date.today()
                            e_date = st.date_input("完成日", value=e_date_val)
                        with col_e2:
                            e_type = st.selectbox("種別", TYPE_LIST, index=TYPE_LIST.index(target_row.get('restoration_type')) if target_row.get('restoration_type') in TYPE_LIST else 0)
                            e_material = st.selectbox("材料", MATERIAL_LIST, index=MATERIAL_LIST.index(target_row.get('material')) if target_row.get('material') in MATERIAL_LIST else 0)
                            e_pos = st.text_input("部位", value=str(target_row.get('tooth_position') or ""))
                            e_con = st.slider("コンタクト", 1, 5, safe_int(target_row.get('contact')))
                            e_bit = st.slider("バイト", 1, 5, safe_int(target_row.get('bite')))
                            e_fit = st.slider("適合", 1, 5, safe_int(target_row.get('fit')))
                        e_com = st.text_area("コメント", value=str(target_row.get('comments') or ""))
                        
                        if st.form_submit_button("🔄 変更を保存する", type="primary"):
                            db.table("evaluations").update({
                                "clinic_name": e_clinic, "patient_name": e_patient, "slip_number": e_slip,
                                "completion_date": e_date.isoformat(), "restoration_type": e_type, "material": e_material,
                                "tooth_position": e_pos, "contact": e_con, "bite": e_bit, "fit": e_fit, "comments": e_com
                            }).eq("id", target_row['id']).execute()
                            st.success("データを更新しました！画面を再読み込みしてください。")

            st.markdown("---")
            with st.expander("🧹 1年経過した古い画像を削除（文字データは残す・容量節約）", expanded=False):
                st.info("完成日から1年以上経過した「画像ファイルのみ」をストレージから削除します。データ分析用のテキストは残ります。")
                if 'completion_date' in df.columns:
                    old_df = df[(pd.to_datetime(df['completion_date'], errors='coerce') < (pd.Timestamp.today() - pd.DateOffset(years=1))) & (df['image_url'].notna())]
                    st.write(f"削除対象画像: **{len(old_df)} 件**")
                    if len(old_df) > 0 and st.button("⚠️ 対象の画像を削除する"):
                        with st.spinner("画像データをクリーンアップ中..."):
                            for _, row in old_df.iterrows():
                                file_name = row['image_url'].split('/')[-1]
                                db.storage.from_("sheet_images").remove([file_name])
                                db.table("evaluations").update({"image_url": None}).eq("id", row['id']).execute()
                            st.success("🎉 古い画像の削除が完了しました！")
                            time.sleep(1.5)
                            st.rerun()

            st.markdown("---")
            with st.expander("🗑️ データの一括削除（取り扱い注意）", expanded=False):
                st.warning("選択したデータをDBから完全に消去します。")
                selected_ids = [row['id'] for _, row in df.iterrows() if st.checkbox(f"ID:{row['id']} | {row['clinic_name']} - {row['patient_name']} 様", key=f"del_{row['id']}")]
                if selected_ids and st.button(f"⚠️ 選択した {len(selected_ids)} 件のデータを完全に削除する"):
                    for tid in selected_ids:
                        db.table("evaluations").delete().eq("id", tid).execute()
                    st.success("削除完了しました！")
                    time.sleep(1)
                    st.rerun()
        else:
            st.info("保存されたデータはまだありません。")
