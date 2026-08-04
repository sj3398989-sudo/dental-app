import streamlit as st
import pandas as pd
import plotly.express as px
from google import genai
from google.genai import types
from supabase import create_client
from PIL import Image, ImageOps, ImageEnhance
import json
import io
import time
from datetime import date
import base64

# ==========================================
# 1. アプリケーション初期設定 & CSS (Apple風ライトモード)
# ==========================================
st.set_page_config(page_title="AI品質管理カルテ", page_icon="🦷", layout="wide", initial_sidebar_state="collapsed")

st.markdown("""
<style>
    /* 全体の背景とフォント (Apple風) */
    .stApp {
        background-color: #F5F5F7 !important; 
        font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text", "Helvetica Neue", "Hiragino Sans", "Hiragino Kaku Gothic ProN", Arial, sans-serif !important;
    }
    #MainMenu, header, footer {visibility: hidden;}
    
    /* タイトル周り */
    .custom-title {
        font-size: clamp(1.8rem, 5vw, 2.4rem);
        font-weight: 700;
        letter-spacing: -0.02em;
        color: #1D1D1F;
        margin-bottom: 20px;
    }
    
    /* プライマリボタン (Apple Blue) */
    .stButton>button[kind="primary"] {
        background-color: #007AFF !important;
        color: #FFFFFF !important;
        border: none !important;
        border-radius: 12px !important;
        padding: 0.6rem 1.2rem !important;
        font-weight: 600 !important;
        font-size: 15px !important;
        letter-spacing: 0.01em;
        box-shadow: 0 4px 12px rgba(0, 122, 255, 0.25) !important;
        transition: all 0.2s cubic-bezier(0.25, 0.1, 0.25, 1) !important;
    }
    .stButton>button[kind="primary"]:hover {
        background-color: #0062CC !important;
        transform: scale(0.98) !important; /* クリック時の心地よい沈み込み */
        box-shadow: 0 2px 6px rgba(0, 122, 255, 0.2) !important;
    }
    
    /* 枠やコンテナ (カードUIのなめらかな角丸と影) */
    div[data-testid="stVerticalBlock"] > div[style*="border"] {
        background-color: #FFFFFF !important;
        border: 1px solid rgba(0,0,0,0.05) !important;
        border-radius: 18px !important; /* Squircle風の角丸 */
        box-shadow: 0 4px 24px rgba(0, 0, 0, 0.04) !important;
        padding: 24px !important;
    }
    
    /* Expander (折りたたみ) */
    .streamlit-expanderHeader {
        background-color: #FFFFFF !important;
        border-radius: 14px !important;
        border: 1px solid #E5E5EA !important;
        font-weight: 600 !important;
        color: #1D1D1F !important;
    }
    
    /* 入力フォーム */
    input, select, textarea {
        background-color: #F2F2F7 !important;
        border: 1px solid transparent !important;
        border-radius: 10px !important;
        color: #1D1D1F !important;
        transition: all 0.2s ease !important;
    }
    input:focus, select:focus, textarea:focus {
        background-color: #FFFFFF !important;
        border: 1px solid #007AFF !important;
        box-shadow: 0 0 0 3px rgba(0, 122, 255, 0.2) !important;
    }
    
    /* メトリックカード（数値表示・グラスモーフィズム効果） */
    .metric-card {
        background: rgba(255, 255, 255, 0.7);
        backdrop-filter: blur(20px);
        -webkit-backdrop-filter: blur(20px);
        padding: 24px; 
        border-radius: 20px; 
        border: 1px solid rgba(255, 255, 255, 0.5);
        text-align: center; 
        box-shadow: 0 8px 32px rgba(0,0,0,0.06);
    }
    .metric-card h2 {
        font-family: -apple-system, BlinkMacSystemFont, "SF Pro Rounded", sans-serif;
        letter-spacing: -0.04em;
    }
    
    /* タブのスタイリング */
    button[data-baseweb="tab"] {
        background-color: transparent !important;
        font-weight: 600 !important;
        color: #8E8E93 !important;
        font-size: 15px !important;
    }
    button[data-baseweb="tab"][aria-selected="true"] {
        color: #1D1D1F !important;
    }
    div[data-baseweb="tab-highlight"] {
        background-color: #1D1D1F !important;
        height: 3px !important;
        border-radius: 3px 3px 0 0 !important;
    }
    
    /* ガイド・アラート類 */
    .shortcut-guide {
        font-size: 0.85rem;
        color: #1D1D1F;
        background: rgba(0, 122, 255, 0.08);
        padding: 8px 14px;
        border-radius: 10px;
        margin-bottom: 14px;
        display: inline-block;
        font-weight: 500;
    }
    .alert-card {
        padding: 14px 18px;
        border-left: 4px solid #FF3B30; /* Apple Red */
        background-color: rgba(255, 59, 48, 0.05);
        border-radius: 12px;
        margin-bottom: 10px;
        color: #1D1D1F;
        font-weight: 500;
    }
</style>
""", unsafe_allow_html=True)

st.markdown('<div class="custom-title">🦷 AI品質管理カルテ <span style="font-size: 0.5em; font-weight: 500; color: #8E8E93;">(大阪センター)</span></div>', unsafe_allow_html=True)

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

SHEET_TYPE_LIST = ["セパレートレス模型", "IOS"]
MATERIAL_LIST = ["ジルコニア", "CAD/CAM冠", "e.max", "チタン", "3Dプリント", "その他"]
TYPE_LIST = ["クラウン（単冠）", "ブリッジ", "インレー", "インプラント", "義歯", "その他"]

def safe_int(val, default=3):
    try:
        return max(1, min(5, int(float(val))))
    except (ValueError, TypeError):
        return default

def upload_file_to_storage(file_obj, suffix_idx):
    if not file_obj or not db: return None
    f_b = file_obj.getvalue()
    is_pdf = "pdf" in file_obj.type
    ext, mime = ("pdf", "application/pdf") if is_pdf else ("jpg", "image/jpeg")
    f_nm = f"{int(time.time())}_{suffix_idx}.{ext}"
    
    if not is_pdf:
        try:
            img = Image.open(io.BytesIO(f_b))
            img = ImageOps.exif_transpose(img)
            img.thumbnail((1200, 1200), Image.Resampling.LANCZOS)
            if img.mode != 'RGB': img = img.convert('RGB')
            buf = io.BytesIO()
            img.save(buf, format='JPEG', quality=80, optimize=True)
            f_b = buf.getvalue()
        except Exception: pass
        
    try:
        db.storage.from_("sheet_images").upload(f_nm, f_b, {"content-type": mime})
        return db.storage.from_("sheet_images").get_public_url(f_nm)
    except Exception:
        return None

def save_single_evaluation(d, file_obj=None):
    img_url = upload_file_to_storage(file_obj, 0)
    db.table("evaluations").insert({
        "clinic_name": d.get("clinic_name"),
        "patient_name": d.get("patient_name"),
        "slip_number": d.get("slip_number"),
        "completion_date": d.get("completion_date"),
        "sheet_type": d.get("sheet_type", "セパレートレス模型"),
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
    if not file_obj:
        st.write("ファイルがありません")
        return
    if "pdf" in file_obj.type:
        try:
            b64_pdf = base64.b64encode(file_obj.getvalue()).decode('utf-8')
            st.markdown(f'<iframe src="data:application/pdf;base64,{b64_pdf}" width="100%" height="450" style="border: 1px solid #E5E5EA; border-radius: 12px;"></iframe>', unsafe_allow_html=True)
        except Exception:
            st.warning("PDFを表示できません")
    else:
        try: st.image(file_obj.getvalue(), use_container_width=True, style={"border-radius": "12px"})
        except Exception: st.warning("画像を表示できません")

# ==========================================
# 3. 画面描画 (Tabs)
# ==========================================
tab1, tab2, tab3, tab4 = st.tabs(["🤖 AI一括", "✍️ 手動", "📊 分析", "📋 管理"])

# ------------------------------------------
# Tab 1: AI一括登録
# ------------------------------------------
with tab1:
    st.markdown("### 📄 評価シートのアップロード")
    st.info("写真やPDFを選択し、「一括AI解析」ボタンを押してください。大量の枚数でも安全に処理されます。")
    up_files = st.file_uploader("画像/PDF(複数選択可)", type=["jpg", "png", "pdf"], accept_multiple_files=True, label_visibility="collapsed")

    if up_files and KEY and st.button("✨ 一括AI解析をスタート", type="primary"):
        with st.spinner("AIがシートを精密解析中..."):
            c = genai.Client(api_key=KEY)
            prm = (
                "このファイルには1枚または複数の補綴物評価シートが含まれています。以下の手順に従い抽出してください。\n\n"
                "1. シート上に「IOS」や「セパレートレス」などの記載やチェックがあれば判別してください（不明な場合は「セパレートレス模型」）。\n"
                "2. 丸（〇）で囲まれている数字やチェック（✓）が入っている評価数値（contact, bite, fit: 1〜5）を正確に読み取ってください。\n"
                "3. 読み取れない・未記入項目は空文字（\"\"）にしてください。\n"
                "キー: clinic_name, patient_name, slip_number, completion_date (YYYY-MM-DD), "
                "sheet_type (IOS または セパレートレス模型), "
                f"restoration_type ({', '.join(TYPE_LIST)} の中から最も近いもの), "
                f"material ({', '.join(MATERIAL_LIST)} の中から最も近いもの), "
                "tooth_position, contact, bite, fit, comments"
            )
            ai_config = types.GenerateContentConfig(temperature=0.0, response_mime_type="application/json")
            
            r_list = []
            BATCH_SIZE = 5
            total_files = len(up_files)
            
            progress_bar = st.progress(0)
            status_text = st.empty()
            
            for i in range(0, total_files, BATCH_SIZE):
                chunk_files = up_files[i : i + BATCH_SIZE]
                current_end = min(i + BATCH_SIZE, total_files)
                status_text.markdown(f"**⏳ 処理中... {i + 1}〜{current_end}枚目 / 全{total_files}枚**")
                
                for idx, f in enumerate(chunk_files):
                    actual_idx = i + idx 
                    try:
                        if "pdf" in f.type:
                            cp = types.Part.from_bytes(data=f.getvalue(), mime_type="application/pdf")
                        else:
                            img = Image.open(io.BytesIO(f.getvalue()))
                            img = ImageOps.exif_transpose(img)
                            img = ImageEnhance.Contrast(img).enhance(1.2)
                            cp = img
                        
                        res = None
                        try:
                            res = c.models.generate_content(model='gemini-3.5-flash', contents=[cp, prm], config=ai_config)
                        except Exception:
                            try:
                                res = c.models.generate_content(model='gemini-3.5-flash-lite', contents=[cp, prm], config=ai_config)
                                st.toast(f"ファイル {f.name}: 3.5 Flash Lite で代替解析しました", icon="ℹ️")
                            except Exception:
                                res = c.models.generate_content(model='gemini-2.5-flash', contents=[cp, prm], config=ai_config)
                                st.toast(f"ファイル {f.name}: 2.5 Flash で代替解析しました", icon="ℹ️")

                        if res and res.text:
                            parsed = json.loads(res.text.strip())
                            if isinstance(parsed, dict): parsed = [parsed]
                            for item in parsed:
                                item["_f_idx"] = actual_idx 
                                r_list.append(item)
                    except Exception as e:
                        st.error(f"ファイル解析エラー ({f.name}): {e}")
                
                progress_ratio = current_end / total_files
                progress_bar.progress(progress_ratio)
                time.sleep(1.0)
            
            status_text.empty()
            progress_bar.empty()
            
            st.session_state["r_list"] = r_list
            st.session_state["f_list"] = up_files
            st.toast(f"合計 {len(r_list)} 件のデータを検出しました！", icon="✨")

    if "r_list" in st.session_state:
        st.markdown("<br>### 📝 抽出データの確認と修正", unsafe_allow_html=True)
        st.markdown('<div class="shortcut-guide">⌨️ Excelのように表を直接クリックして修正できます。<b>Tab</b>キーで右へサクサク移動可能です。</div>', unsafe_allow_html=True)
        r_list, f_list = st.session_state["r_list"], st.session_state["f_list"]
        
        with st.container(border=True):
            st.markdown("**🖼️ 元画像の確認 (プレビュー)**")
            file_names = [f"画像No.{i+1} : {f.name}" for i, f in enumerate(f_list)]
            selected_file = st.selectbox("確認したい画像を選んでください", file_names, label_visibility="collapsed")
            selected_idx = file_names.index(selected_file)
            with st.expander("👀 画像を開く", expanded=False):
                display_file_preview(f_list[selected_idx])

        formatted_data = []
        for item in r_list:
            try: dt = date.fromisoformat(str(item.get("completion_date", ""))[:10])
            except: dt = date.today()
            formatted_data.append({
                "画像No": item.get("_f_idx", 0) + 1,
                "医院名": item.get("clinic_name", ""),
                "患者名": item.get("patient_name", ""),
                "伝票番号": item.get("slip_number", ""),
                "完成日": dt,
                "シート種別": item.get("sheet_type", "セパレートレス模型"),
                "種別": item.get("restoration_type", ""),
                "材料": item.get("material", ""),
                "部位": item.get("tooth_position", ""),
                "コンタクト": safe_int(item.get("contact")),
                "バイト": safe_int(item.get("bite")),
                "適合": safe_int(item.get("fit")),
                "コメント": item.get("comments", ""),
                "_f_idx": item.get("_f_idx")
            })
        
        df_edit = pd.DataFrame(formatted_data)
        
        edited_df = st.data_editor(
            df_edit,
            column_config={
                "画像No": st.column_config.NumberColumn("画像No", disabled=True, width="small"),
                "医院名": st.column_config.TextColumn("🏥 医院名", required=True),
                "患者名": st.column_config.TextColumn("👤 患者名", required=True),
                "伝票番号": st.column_config.TextColumn("📝 伝票番号"),
                "完成日": st.column_config.DateColumn("📅 完成日"),
                "シート種別": st.column_config.SelectboxColumn("📄 シート種別", options=SHEET_TYPE_LIST),
                "種別": st.column_config.SelectboxColumn("🦷 種別", options=TYPE_LIST),
                "材料": st.column_config.SelectboxColumn("💎 材料", options=MATERIAL_LIST),
                "部位": st.column_config.TextColumn("📍 部位"),
                "コンタクト": st.column_config.NumberColumn("コンタクト", min_value=1, max_value=5, step=1, width="small"),
                "バイト": st.column_config.NumberColumn("バイト", min_value=1, max_value=5, step=1, width="small"),
                "適合": st.column_config.NumberColumn("適合", min_value=1, max_value=5, step=1, width="small"),
                "コメント": st.column_config.TextColumn("💬 コメント"),
                "_f_idx": None,
            },
            use_container_width=True,
            hide_index=True,
            num_rows="dynamic",
            height=400
        )

        st.markdown("<br>", unsafe_allow_html=True)
        
        if st.button("💾 確認したデータを全て一括保存", type="primary", use_container_width=True):
            if edited_df["医院名"].isnull().any() or (edited_df["医院名"].astype(str).str.strip() == "").any() or \
               edited_df["患者名"].isnull().any() or (edited_df["患者名"].astype(str).str.strip() == "").any():
                st.error("⚠️ 未入力の「医院名」または「患者名」があります。表を確認してください。")
            elif db:
                with st.spinner("データベースへ一括保存中... (超高速化)"):
                    insert_data = []
                    for idx, row in edited_df.iterrows():
                        f_idx = row.get("_f_idx")
                        file_obj = f_list[int(f_idx)] if pd.notna(f_idx) and int(f_idx) < len(f_list) else None
                        img_url = upload_file_to_storage(file_obj, idx)
                        
                        insert_data.append({
                            "clinic_name": str(row.get("医院名", "")),
                            "patient_name": str(row.get("患者名", "")),
                            "slip_number": str(row.get("伝票番号", "")),
                            "completion_date": row.get("完成日").isoformat() if pd.notna(row.get("完成日")) else date.today().isoformat(),
                            "sheet_type": str(row.get("シート種別", "セパレートレス模型")),
                            "restoration_type": str(row.get("種別", "")),
                            "material": str(row.get("材料", "")),
                            "tooth_position": str(row.get("部位", "")),
                            "contact": safe_int(row.get("コンタクト")),
                            "bite": safe_int(row.get("バイト")),
                            "fit": safe_int(row.get("適合")),
                            "comments": str(row.get("コメント", "")),
                            "image_url": img_url
                        })
                    
                    if insert_data:
                        db.table("evaluations").insert(insert_data).execute()
                        
                del st.session_state["r_list"], st.session_state["f_list"]
                st.success("🎉 データの一括保存が完了しました！")
                time.sleep(1.5)
                st.rerun()

# ------------------------------------------
# Tab 2: 手動登録
# ------------------------------------------
with tab2:
    st.markdown("### ✍️ 新規データの手動入力")
    st.markdown('<div class="shortcut-guide">⌨️ PCナビゲーション: <b>Tab</b> で順にフォーカス移動、<b>Enter</b> で送信が可能です</div>', unsafe_allow_html=True)
    with st.container(border=True):
        with st.form("manual_entry_form", clear_on_submit=True):
            c1, c2 = st.columns(2)
            with c1:
                m_clinic = st.text_input("🏥 医院名 (必須)", key="m_c")
                m_patient = st.text_input("👤 患者名 (必須)", key="m_p")
                m_slip = st.text_input("📝 伝票番号", key="m_s")
                m_date = st.date_input("📅 完成日", value=date.today(), key="m_d")
                m_stype = st.selectbox("📄 シート種別", SHEET_TYPE_LIST, key="m_st")
            with c2:
                m_type = st.selectbox("🦷 種別", TYPE_LIST, key="m_t")
                m_material = st.selectbox("💎 材料", MATERIAL_LIST, key="m_m")
                m_pos = st.text_input("📍 部位", key="m_pos")
                m_con = st.slider("コンタクト", 1, 5, 3, key="m_co")
                m_bit = st.slider("バイト", 1, 5, 3, key="m_bi")
                m_fit = st.slider("適合", 1, 5, 3, key="m_fi")
            m_com = st.text_area("💬 コメント", key="m_cm")
                
            if st.form_submit_button("手動で登録する", type="primary"):
                if not m_clinic or not m_patient:
                    st.error("⚠️ 医院名と患者名は必須入力です。")
                elif db:
                    save_single_evaluation({
                        "clinic_name": m_clinic, "patient_name": m_patient, "slip_number": m_slip,
                        "completion_date": m_date.isoformat(), "sheet_type": m_stype,
                        "restoration_type": m_type, "material": m_material,
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
                cf1, cf2, cf3, cf4 = st.columns(4)
                s_c = cf1.selectbox("🏥 医院で絞り込み", ["すべて"] + list(df["clinic_name"].dropna().unique()))
                s_st = cf2.selectbox("📄 シート種別", ["すべて"] + list(df.get("sheet_type", pd.Series([""])).dropna().unique()))
                s_p = cf3.selectbox("📅 期間で絞り込み", ["すべて", "直近1ヶ月", "直近2ヶ月", "直近3ヶ月", "直近6ヶ月"])
                s_m = cf4.selectbox("💎 材料で絞り込み", ["すべて"] + list(df.get("material", pd.Series([""])).dropna().unique()))
            
            f_df = df.copy()
            if s_c != "すべて": f_df = f_df[f_df["clinic_name"] == s_c]
            if s_st != "すべて" and "sheet_type" in f_df.columns: f_df = f_df[f_df["sheet_type"] == s_st]
            if s_m != "すべて" and "material" in f_df.columns: f_df = f_df[f_df["material"] == s_m]
            
            p_map = {"直近1ヶ月": 1, "直近2ヶ月": 2, "直近3ヶ月": 3, "直近6ヶ月": 6}
            if s_p in p_map: f_df = f_df[f_df['completion_date'] >= (pd.Timestamp.today() - pd.DateOffset(months=p_map[s_p]))]

            st.markdown("<br>", unsafe_allow_html=True)
            
            def get_stats(col):
                return (f_df[col].mean(), (f_df[col] == 3).sum() / len(f_df) * 100) if len(f_df) > 0 else (0, 0)

            c_m, c_opt = get_stats('contact')
            b_m, b_opt = get_stats('bite')
            f_m, f_opt = get_stats('fit')
            
            def render_metric(label, mean_val, opt_rate):
                if mean_val == 0: return f'<div class="metric-card"><p style="font-weight:bold; color: #1D1D1F;">{label}</p><h2 style="color: #1D1D1F;">- %</h2></div>'
                # Apple風のカラーリング (Green, Orange, Red)
                color = "#34C759" if opt_rate >= 80 else ("#FF9500" if opt_rate >= 50 else "#FF3B30")
                return f"""
                <div class="metric-card">
                    <p style="margin: 0; font-size: 14px; font-weight: 600; color: #8E8E93;">{label} (適正率)</p>
                    <h2 style="margin: 10px 0; color: {color}; font-size: 34px; font-weight: 800;">{opt_rate:.1f}%</h2>
                    <p style="margin: 0; font-size: 13px; color: #1D1D1F; font-weight: 500;">平均点: {mean_val:.2f} <span style="color:#8E8E93;">(誤差 {mean_val-3.0:+.2f})</span></p>
                </div>
                """

            col1, col2, col3, col4 = st.columns(4)
            with col1: st.markdown(f'<div class="metric-card"><p style="margin: 0; font-size: 14px; font-weight: 600; color: #8E8E93;">📄 対象件数</p><h2 style="margin: 10px 0; font-size: 34px; font-weight: 800; color: #1D1D1F;">{len(f_df)}<span style="font-size:16px;">件</span></h2><p style="margin: 0; font-size: 13px; color: transparent;">-</p></div>', unsafe_allow_html=True)
            with col2: st.markdown(render_metric("コンタクト", c_m, c_opt), unsafe_allow_html=True)
            with col3: st.markdown(render_metric("バイト", b_m, b_opt), unsafe_allow_html=True)
            with col4: st.markdown(render_metric("適合", f_m, f_opt), unsafe_allow_html=True)

            st.markdown("<br>", unsafe_allow_html=True)
            if len(f_df) > 0 and 'material' in f_df.columns:
                with st.expander("🔍 医院 × 材料 クロス集計・品質偏差アラート", expanded=False):
                    cross_df = f_df.groupby(['clinic_name', 'material']).agg(
                        件数=('id', 'count'),
                        コンタクト平均=('contact', 'mean'),
                        バイト平均=('bite', 'mean'),
                        適合平均=('fit', 'mean')
                    ).reset_index()
                    
                    alerts = []
                    for _, row in cross_df[cross_df['件数'] >= 2].iterrows():
                        if row['バイト平均'] >= 3.4:
                            alerts.append(f"⚠️ <b>{row['clinic_name']}</b> × <b>{row['material']}</b>: バイトが高めの傾向があります（平均: {row['バイト平均']:.2f}）")
                        elif row['バイト平均'] <= 2.6:
                            alerts.append(f"⚠️ <b>{row['clinic_name']}</b> × <b>{row['material']}</b>: バイトが低めの傾向があります（平均: {row['バイト平均']:.2f}）")
                            
                        if row['コンタクト平均'] >= 3.4:
                            alerts.append(f"⚠️ <b>{row['clinic_name']}</b> × <b>{row['material']}</b>: コンタクトがきつい傾向があります（平均: {row['コンタクト平均']:.2f}）")
                        elif row['コンタクト平均'] <= 2.6:
                            alerts.append(f"⚠️ <b>{row['clinic_name']}</b> × <b>{row['material']}</b>: コンタクトがゆるい傾向があります（平均: {row['コンタクト平均']:.2f}）")

                    if alerts:
                        st.markdown("<b>【自動検知された品質アラート】</b>", unsafe_allow_html=True)
                        for alt in alerts:
                            st.markdown(f'<div class="alert-card">{alt}</div>', unsafe_allow_html=True)
                    else:
                        st.success("✅ 特定の医院×材料における顕著な品質偏差（大きなズレ）は検出されませんでした。")

                    st.markdown("<br><b>【医院 × 材料別 スコアマトリクス】</b>", unsafe_allow_html=True)
                    st.dataframe(cross_df.style.format({
                        'コンタクト平均': '{:.2f}', 'バイト平均': '{:.2f}', '適合平均': '{:.2f}'
                    }), use_container_width=True)

            st.markdown("<br>", unsafe_allow_html=True)

            if st.button("🤖 AI詳細分析（専門基準による考察）", type="primary", use_container_width=True):
                with st.spinner("AIがデータを分析中..."):
                    cols = ['completion_date', 'sheet_type', 'restoration_type', 'material', 'contact', 'bite', 'fit', 'comments']
                    dic = f_df[[c for c in cols if c in f_df.columns]].to_dict(orient='records')
                    prm = f"対象データは全{len(f_df)}件です。条件（医院:{s_c}, シート種別:{s_st}, 材料:{s_m}）の傾向分析をお願いします。3が適正、1が弱い、5がきついの前提で分析してください:\n{dic}"
                    
                    res_ai = None
                    c = genai.Client(api_key=KEY)
                    try:
                        res_ai = c.models.generate_content(model='gemini-3.5-flash', contents=prm).text
                    except Exception:
                        try:
                            res_ai = c.models.generate_content(model='gemini-3.5-flash-lite', contents=prm).text
                        except Exception:
                            res_ai = c.models.generate_content(model='gemini-2.5-flash', contents=prm).text
                    st.info(res_ai)

            st.markdown("<br>", unsafe_allow_html=True)
            col_chart1, col_chart2 = st.columns(2)
            
            with col_chart1:
                with st.container(border=True):
                    st.markdown("**📈 月別推移（品質トレンド）**")
                    if len(f_df) > 0:
                        trend_df = f_df.assign(month=f_df['completion_date'].dt.to_period('M').astype(str)).groupby('month')[['contact', 'bite', 'fit']].mean().reset_index()
                        # グラフの色合いもApple風に変更
                        fig_line = px.line(trend_df, x='month', y=['contact', 'bite', 'fit'], markers=True, range_y=[1, 5], color_discrete_sequence=['#007AFF', '#5AC8FA', '#34C759'])
                        fig_line.add_hline(y=3.0, line_dash="dash", line_color="#8E8E93", annotation_text="適正値 (3.0)")
                        fig_line.update_layout(plot_bgcolor='rgba(0,0,0,0)', paper_bgcolor='rgba(0,0,0,0)')
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
                        # スコアの色分けをAppleのシグナルカラーに
                        apple_colors = {'1': '#007AFF', '2': '#5AC8FA', '3': '#34C759', '4': '#FF9500', '5': '#FF3B30'}
                        fig_dist = px.bar(pd.DataFrame(dist_data), x='評価項目', y='件数', color='スコア', color_discrete_map=apple_colors, barmode='stack', text='割合')
                        fig_dist.update_traces(textposition='inside', textfont_size=16)
                        fig_dist.update_layout(xaxis=dict(tickfont=dict(size=16, color="#1D1D1F", weight="bold"), title=""), yaxis=dict(title="件数"), plot_bgcolor='rgba(0,0,0,0)', paper_bgcolor='rgba(0,0,0,0)')
                        st.plotly_chart(fig_dist, use_container_width=True)

            st.markdown("<br>", unsafe_allow_html=True)
            if len(f_df) > 0:
                html = f"""
                <html><head><meta charset="utf-8"><title>品質分析レポート</title></head>
                <body style="font-family: -apple-system, BlinkMacSystemFont, 'SF Pro Text', sans-serif; padding: 30px; color: #1D1D1F; background-color: #F5F5F7;">
                    <h2 style="color: #1D1D1F; border-bottom: 2px solid #E5E5EA; padding-bottom: 10px;">AI品質管理カルテ (大阪センター)</h2>
                    <p style="color: #8E8E93; font-weight: 500;">医院: {s_c} | 種別: {s_st} | 材料: {s_m} | 出力日: {date.today().isoformat()}</p>
                    <div style="background-color: #FFFFFF; padding: 25px; border-radius: 16px; border: 1px solid #E5E5EA; box-shadow: 0 4px 16px rgba(0,0,0,0.04);">
                        <h3 style="color: #1D1D1F; margin-top: 0;">📊 総合評価（適正スコア「3」の割合）</h3>
                        <ul style="font-size: 16px; line-height: 1.8;">
                            <li>対象件数: <strong>{len(f_df)} 件</strong></li>
                            <li>コンタクト適正率: <strong>{c_opt:.1f}%</strong> <span style="color:#8E8E93;">(平均: {c_m:.2f})</span></li>
                            <li>バイト適正率: <strong>{b_opt:.1f}%</strong> <span style="color:#8E8E93;">(平均: {b_m:.2f})</span></li>
                            <li>適合適正率: <strong>{f_opt:.1f}%</strong> <span style="color:#8E8E93;">(平均: {f_m:.2f})</span></li>
                        </ul>
                    </div>
                </body></html>
                """
                b64 = base64.b64encode(html.encode('utf-8')).decode()
                st.markdown(f'<a href="data:text/html;base64,{b64}" download="quality_report.html" target="_blank" style="display: inline-block; padding: 12px 24px; background-color: #007AFF; color: white; text-decoration: none; border-radius: 12px; font-weight: 600; box-shadow: 0 4px 12px rgba(0, 122, 255, 0.3);">📥 医院向けレポートを出力 (HTML)</a>', unsafe_allow_html=True)

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

            display_cols = [c for c in ['completion_date', 'sheet_type', 'clinic_name', 'patient_name', 'restoration_type', 'material', 'contact', 'bite', 'fit'] if c in df.columns]
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
                            st.markdown(f'<iframe src="{img_url}" width="100%" height="450" style="border: 1px solid #E5E5EA; border-radius: 12px;"></iframe>', unsafe_allow_html=True)
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
                            
                            st_val = str(target_row.get('sheet_type') or "セパレートレス模型")
                            e_stype = st.selectbox("📄 シート種別", SHEET_TYPE_LIST, index=SHEET_TYPE_LIST.index(st_val) if st_val in SHEET_TYPE_LIST else 0)
                            
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
                                "completion_date": e_date.isoformat(), "sheet_type": e_stype,
                                "restoration_type": e_type, "material": e_material,
                                "tooth_position": e_pos, "contact": e_con, "bite": e_bit, "fit": e_fit, "comments": e_com
                            }).eq("id", target_row['id']).execute()
                            st.success("データを更新しました！画面を再読み込みしてください。")

            st.markdown("---")
            with st.expander("🔧 既存データのシート種別を一括更新", expanded=False):
                st.info("過去に入力したすべてのデータの「シート種別」を、一括で「セパレートレス模型」に更新します。")
                if st.button("⚠️ 全データの種別を「セパレートレス模型」に更新する"):
                    try:
                        db.table("evaluations").update({"sheet_type": "セパレートレス模型"}).neq("id", 0).execute()
                        st.success("🎉 全データのシート種別を「セパレートレス模型」に更新しました！")
                        time.sleep(1.5)
                        st.rerun()
                    except Exception as e:
                        st.error(f"一括更新エラー: {e}")

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

            st.markdown("---")
            with st.expander("🚑 万が一のデータ復旧 (CSVから一括インポート)", expanded=False):
                st.info("過去にダウンロードしたバックアップ用のCSVファイルをアップロードして、データを一括復元します。")
                restore_file = st.file_uploader("復旧用CSVファイルを選択", type=["csv"], key="restore_csv")
                
                if restore_file and st.button("⚠️ CSVからデータを一括復元する", type="primary"):
                    try:
                        df_restore = pd.read_csv(restore_file)
                        if 'id' in df_restore.columns:
                            df_restore = df_restore.drop(columns=['id'])
                            
                        records = df_restore.to_dict(orient="records")
                        
                        with st.spinner("データをデータベースに復元中..."):
                            if records:
                                db.table("evaluations").insert(records).execute()
                                
                        st.success(f"🎉 {len(records)} 件のデータを無事に復元しました！画面を再読み込みします。")
                        time.sleep(2)
                        st.rerun()
                    except Exception as e:
                        st.error(f"復元エラー: {e}")
        else:
            st.info("保存されたデータはまだありません。")
```eof

This code replaces the dark, standard Streamlit UI with a beautiful, light-mode interface inspired by macOS and iOS. The new design features clean typography, "squircle" rounded corners, soft shadows, a glassmorphism effect on the metrics, and classic Apple blue buttons with subtle hover animations. Simply overwrite your current `app.py` on GitHub with this code to instantly upgrade the look and feel!
