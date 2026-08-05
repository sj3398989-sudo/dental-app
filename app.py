import streamlit as st
import pandas as pd
import plotly.express as px
from supabase import create_client, Client
from google import genai
from google.genai import types
import io
import time
import uuid
import re
from datetime import date
import concurrent.futures
from PIL import Image, ImageOps, ImageEnhance

# ------------------------------------------
# 画面全体設定
# ------------------------------------------
st.set_page_config(page_title="AI品質管理カルテ", page_icon="🦷", layout="wide", initial_sidebar_state="collapsed")

# カスタムCSS（iOS風デザイン）
st.markdown("""
<style>
    .stApp { font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text", "Helvetica Neue", sans-serif !important; }
    #MainMenu, header, footer {visibility: hidden;}
    .custom-title { font-size: clamp(1.8rem, 5vw, 2.4rem); font-weight: 700; letter-spacing: -0.02em; color: #1D1D1F; margin-bottom: 20px; }
    .stButton>button[kind="primary"] { border-radius: 12px !important; font-weight: 600 !important; font-size: 15px !important; box-shadow: 0 4px 12px rgba(0, 122, 255, 0.2) !important; transition: all 0.2s cubic-bezier(0.25, 0.1, 0.25, 1) !important; }
    div[data-testid="stVerticalBlock"] > div[style*="border"] { border-radius: 18px !important; box-shadow: 0 4px 20px rgba(0, 0, 0, 0.03) !important; padding: 24px !important; border: 1px solid rgba(0,0,0,0.06) !important; background-color: #FFFFFF !important; }
    .metric-card { background: rgba(255, 255, 255, 0.8); backdrop-filter: blur(20px); -webkit-backdrop-filter: blur(20px); padding: 24px; border-radius: 20px; border: 1px solid rgba(255, 255, 255, 0.6); text-align: center; box-shadow: 0 8px 24px rgba(0,0,0,0.04); }
    .metric-card h2 { font-family: -apple-system, BlinkMacSystemFont, "SF Pro Rounded", sans-serif; letter-spacing: -0.04em; }
    .alert-card { padding: 14px 18px; border-left: 4px solid #FF3B30; background-color: rgba(255, 59, 48, 0.05); border-radius: 12px; margin-bottom: 10px; color: #1D1D1F; font-weight: 500; }
</style>
""", unsafe_allow_html=True)

st.markdown('<div class="custom-title">🦷 AI品質管理カルテ <span style="font-size: 0.5em; font-weight: 500; color: #8E8E93;">(大阪センター)</span></div>', unsafe_allow_html=True)

# ------------------------------------------
# 定数・キー設定
# ------------------------------------------
SHEET_TYPE_LIST = ["セパレートレス模型", "IOS"]
MATERIAL_LIST = ["ジルコニア", "CAD/CAM冠", "e.max", "チタン", "3Dプリント", "PEEK", "その他"]
TYPE_LIST = ["クラウン（単冠）", "ブリッジ", "インレー", "インプラント", "義歯", "その他"]
STORAGE_BUCKET = "sheet_images"

# ⚠️ ご自身のAPIキー・URLを張り付けてください
KEY = "ここにGeminiのAPIキーを貼り付け"
URL = "ここにSupabaseのURLを貼り付け"
S_KEY = "ここにSupabaseのAPIキーを貼り付け"

DEFAULT_MODEL = "gemini-3.5-flash"
FALLBACK_MODELS = ["gemini-3.5-flash-lite", "gemini-3-flash"]
GEMINI_MODELS = [DEFAULT_MODEL] + FALLBACK_MODELS

# ------------------------------------------
# データベース & AI クライアント接続
# ------------------------------------------
@st.cache_resource
def get_db() -> Client:
    try:
        return create_client(URL, S_KEY) if URL and S_KEY else None
    except Exception as e:
        st.error(f"データベース接続エラー: {e}")
        return None

@st.cache_resource
def get_gemini_client():
    if not KEY: return None
    return genai.Client(api_key=KEY)

db = get_db()

@st.cache_data(ttl=300)
def fetch_evaluations():
    if not db: return pd.DataFrame()
    try:
        res = db.table("evaluations").select("*").order("completion_date", desc=True).execute()
        if not res.data: return pd.DataFrame()
        df = pd.DataFrame(res.data)
        df['completion_date'] = pd.to_datetime(df['completion_date'], errors='coerce').dt.date
        for col in ['contact', 'bite', 'fit', 'id']:
            if col in df.columns: df[col] = pd.to_numeric(df[col], errors='coerce')
        return df
    except Exception as e:
        st.error(f"データ読み込みエラー: {e}")
        return pd.DataFrame()

def clear_db_cache():
    fetch_evaluations.clear()

def upload_image(file_obj):
    if not file_obj or not db: return None
    try:
        f_b = file_obj.getvalue()
        is_pdf = "pdf" in file_obj.type
        ext, mime = ("pdf", "application/pdf") if is_pdf else ("jpg", "image/jpeg")
        file_path = f"{uuid.uuid4()}.{ext}"
        
        if not is_pdf:
            try:
                img = Image.open(io.BytesIO(f_b))
                img = ImageOps.exif_transpose(img)
                img.thumbnail((1800, 1800), Image.Resampling.LANCZOS)
                if img.mode != 'RGB': img = img.convert('RGB')
                buf = io.BytesIO()
                img.save(buf, format='JPEG', quality=85, optimize=True)
                f_b = buf.getvalue()
            except Exception: pass
            
        db.storage.from_(STORAGE_BUCKET).upload(file_path, f_b, {"content-type": mime})
        return file_path
    except Exception as e:
        st.warning(f"画像アップロードスキップ: {e}")
        return None

def safe_int(val, default=3):
    try: return max(1, min(5, int(float(val))))
    except (ValueError, TypeError): return default

def display_file_preview(file_obj):
    if not file_obj:
        st.write("ファイルがありません")
        return
    if "pdf" in file_obj.type:
        st.info("🔒 ブラウザの制限により、PDFの直接表示がブロックされています。")
        st.download_button(label="📄 PDFファイルを開いて確認する", data=file_obj.getvalue(), file_name=file_obj.name, mime="application/pdf")
    else:
        try: st.image(file_obj.getvalue(), use_container_width=True)
        except Exception: st.warning("画像を表示できません")

def call_gemini_with_fallback(prompt_text, image_part=None):
    client = get_gemini_client()
    if not client: raise ValueError("GEMINI_API_KEY が設定されていません。")
    payload = [image_part, prompt_text] if image_part else prompt_text
    for idx, model in enumerate(GEMINI_MODELS):
        try:
            return client.models.generate_content(model=model, contents=payload)
        except Exception as e:
            if idx == len(GEMINI_MODELS) - 1: raise e
            time.sleep(0.5)
    return None

def process_single_file(f, actual_idx, prompt_text):
    try:
        if "pdf" in f.type:
            cp = types.Part.from_bytes(data=f.getvalue(), mime_type="application/pdf")
        else:
            img = Image.open(io.BytesIO(f.getvalue()))
            img = ImageOps.exif_transpose(img)
            img = ImageEnhance.Contrast(img).enhance(1.2)
            cp = img
            
        res = call_gemini_with_fallback(prompt_text, cp)
        if res and res.text:
            cleaned = res.text.strip().replace("```json", "").replace("```", "").strip()
            import json
            parsed = json.loads(cleaned)
            if isinstance(parsed, dict): parsed = [parsed]
            
            for item in parsed:
                item["_f_idx"] = actual_idx
                raw_date = str(item.get("raw_completion_date", "")).strip().replace('.', '/').replace('・', '/').replace('-', '/')
                parts = re.split(r'/', raw_date)
                dt_obj = date.today()
                if len(parts) >= 3:
                    y, m, d = parts[0], parts[1], parts[2]
                    if len(y) == 2 and y.isdigit(): y = "20" + y
                    try: dt_obj = date(int(y), int(m), int(d))
                    except: pass
                item["completion_date"] = dt_obj.isoformat()
            return parsed
    except Exception as e:
        return {"error": f"解析エラー ({f.name}): {e}"}
    return None

# ------------------------------------------
# UI カラム設定ヘルパー
# ------------------------------------------
def get_column_configs(is_edit_mode=False):
    cols = {
        "✅ 選択": st.column_config.CheckboxColumn("✅ 選択", default=False),
        "医院名": st.column_config.TextColumn("🏥 医院名", required=True),
        "伝票番号": st.column_config.TextColumn("📝 伝票番号"),
        "完成日": st.column_config.DateColumn("📅 完成日"),
        "シート種別": st.column_config.SelectboxColumn("📄 シート種別", options=SHEET_TYPE_LIST),
        "種別": st.column_config.SelectboxColumn("🦷 種別", options=TYPE_LIST),
        "材料": st.column_config.SelectboxColumn("💎 材料", options=MATERIAL_LIST),
        "部位": st.column_config.TextColumn("📍 部位"),
        "コンタクト": st.column_config.NumberColumn("コンタクト", min_value=1, max_value=5),
        "バイト": st.column_config.NumberColumn("バイト", min_value=1, max_value=5),
        "適合": st.column_config.NumberColumn("適合", min_value=1, max_value=5),
        "コメント": st.column_config.TextColumn("💬 コメント"),
    }
    if is_edit_mode:
        cols["id"] = st.column_config.NumberColumn("ID", width="small", disabled=True)
        cols["患者名"] = st.column_config.TextColumn("👤 患者名", required=True)
    else:
        cols["画像No"] = st.column_config.NumberColumn("画像No", disabled=True, width="small")
        cols["患者名"] = st.column_config.TextColumn("👤 患者名", required=True)
        cols["_f_idx"] = None
    return cols

# ------------------------------------------
# メイン画面（タブ構成）
# ------------------------------------------
tab1, tab2, tab3, tab4 = st.tabs(["🤖 AI一括", "✍️ 手動", "📊 分析", "📋 管理"])

# ==========================================
# Tab 1: AI一括登録
# ==========================================
with tab1:
    st.markdown("### 📄 評価シートのアップロード")
    st.info("写真やPDFを選択し、「一括AI解析」ボタンを押してください。")
    
    if "uploader_key" not in st.session_state:
        st.session_state["uploader_key"] = "uploader_" + str(time.time())
        
    up_files = st.file_uploader("画像/PDF(複数選択可)", type=["jpg", "png", "pdf"], accept_multiple_files=True, label_visibility="collapsed", key=st.session_state["uploader_key"])

    if up_files and KEY and st.button("✨ 一括AI解析をスタート", type="primary"):
        with st.spinner("AIがシートを並列解析中..."):
            prompt_text = (
                "歯科補綴物の評価シート（手書き含む）です。以下のフィールドを抽出しJSON配列形式で返してください。\n"
                "[clinic_name, patient_name, slip_number, raw_completion_date, sheet_type, restoration_type, material, tooth_position, contact, bite, fit, comments]\n"
                "※ sheet_type は 'IOS' または 'セパレートレス模型' のいずれか。\n"
                "※ contact, bite, fit は 1〜5 の数値。\n"
                "※ raw_completion_date は紙の表記のまま出力。"
            )
            r_list = []
            total_files = len(up_files)
            progress_bar = st.progress(0)
            status_text = st.empty()
            processed_count = 0
            
            with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
                future_to_idx = {executor.submit(process_single_file, f, idx, prompt_text): idx for idx, f in enumerate(up_files)}
                for future in concurrent.futures.as_completed(future_to_idx):
                    processed_count += 1
                    status_text.markdown(f"**⏳ 並列解析中... {processed_count} / 全{total_files}枚 完了**")
                    progress_bar.progress(processed_count / total_files)
                    res = future.result()
                    if res:
                        if isinstance(res, list): r_list.extend(res)
                        elif "error" in res: st.error(res["error"])

            status_text.empty()
            progress_bar.empty()
            
            st.session_state["r_list"] = sorted(r_list, key=lambda x: x.get("_f_idx", 0))
            st.session_state["f_list"] = up_files
            st.toast(f"合計 {len(r_list)} 件のデータを検出しました！", icon="✨")

    if "r_list" in st.session_state:
        st.markdown("<br>### 📝 抽出データの確認と修正", unsafe_allow_html=True)
        r_list, f_list = st.session_state["r_list"], st.session_state["f_list"]
        
        with st.container(border=True):
            file_names = [f"画像No.{i+1} : {f.name}" for i, f in enumerate(f_list)]
            selected_idx = file_names.index(st.selectbox("👀 画像を確認する", file_names))
            with st.expander("プレビューを展開", expanded=False):
                display_file_preview(f_list[selected_idx])

        formatted_data = [{
            "✅ 選択": False, "画像No": item.get("_f_idx", 0) + 1,
            "医院名": item.get("clinic_name", ""), "患者名": item.get("patient_name", ""),
            "伝票番号": item.get("slip_number", ""), 
            "完成日": pd.to_datetime(item.get("completion_date", ""), errors='coerce').date() if item.get("completion_date") else date.today(),
            "シート種別": item.get("sheet_type", "セパレートレス模型"),
            "種別": item.get("restoration_type", ""), "材料": item.get("material", ""),
            "部位": item.get("tooth_position", ""),
            "コンタクト": safe_int(item.get("contact")), "バイト": safe_int(item.get("bite")), "適合": safe_int(item.get("fit")),
            "コメント": item.get("comments", ""), "_f_idx": item.get("_f_idx")
        } for item in r_list]
        
        edited_df = st.data_editor(
            pd.DataFrame(formatted_data), column_config=get_column_configs(is_edit_mode=False),
            use_container_width=True, hide_index=True, num_rows="dynamic", height=400
        )

        selected_indices = edited_df[edited_df["✅ 選択"]].index.tolist()
        if selected_indices:
            with st.container(border=True):
                st.markdown(f"**☑️ 選択した {len(selected_indices)} 件を一括変更**")
                bc1, bc2, bc3 = st.columns(3)
                b_sheet = bc1.selectbox("📄 シート種別", ["変更しない"] + SHEET_TYPE_LIST, key="b1_sh")
                b_type = bc2.selectbox("🦷 種別", ["変更しない"] + TYPE_LIST, key="b1_ty")
                b_mat = bc3.selectbox("💎 材料", ["変更しない"] + MATERIAL_LIST, key="b1_ma")
                if st.button("適用する"):
                    for idx in selected_indices:
                        if b_sheet != "変更しない": st.session_state["r_list"][idx]["sheet_type"] = b_sheet
                        if b_type != "変更しない": st.session_state["r_list"][idx]["restoration_type"] = b_type
                        if b_mat != "変更しない": st.session_state["r_list"][idx]["material"] = b_mat
                    st.rerun()

        if st.button("💾 確認したデータを全て一括保存", type="primary", use_container_width=True):
            if edited_df["医院名"].isnull().any() or (edited_df["医院名"].astype(str).str.strip() == "").any():
                st.error("⚠️ 未入力の「医院名」があります。")
            else:
                with st.spinner("データベースへ保存中..."):
                    insert_data, uploaded_paths = [], []
                    for _, row in edited_df.iterrows():
                        f_idx = row.get("_f_idx")
                        file_obj = f_list[int(f_idx)] if pd.notna(f_idx) and int(f_idx) < len(f_list) else None
                        img_path = upload_image(file_obj)
                        if img_path: uploaded_paths.append(img_path)
                        
                        insert_data.append({
                            "clinic_name": str(row.get("医院名", "")), "patient_name": str(row.get("患者名", "")),
                            "slip_number": str(row.get("伝票番号", "")),
                            "completion_date": row.get("完成日").isoformat() if pd.notna(row.get("完成日")) else date.today().isoformat(),
                            "sheet_type": str(row.get("シート種別", "セパレートレス模型")),
                            "restoration_type": str(row.get("種別", "")), "material": str(row.get("材料", "")),
                            "tooth_position": str(row.get("部位", "")),
                            "contact": safe_int(row.get("コンタクト")), "bite": safe_int(row.get("バイト")), "fit": safe_int(row.get("適合")),
                            "comments": str(row.get("コメント", "")), "image_url": img_path
                        })
                    
                    if insert_data and db:
                        try:
                            db.table("evaluations").insert(insert_data).execute()
                            clear_db_cache()
                            del st.session_state["r_list"], st.session_state["f_list"]
                            st.session_state["uploader_key"] = "uploader_" + str(time.time())
                            st.success("🎉 一括保存が完了しました！")
                            time.sleep(1.5)
                            st.rerun()
                        except Exception as e:
                            st.error(f"保存エラー: {e}")
                            if uploaded_paths: db.storage.from_(STORAGE_BUCKET).remove(uploaded_paths)

# ==========================================
# Tab 2: 手動登録
# ==========================================
with tab2:
    st.markdown("### ✍️ 新規データの手動入力")
    with st.container(border=True):
        with st.form("manual_entry_form", clear_on_submit=True):
            m_file = st.file_uploader("📄 評価シート画像 (任意)", type=["jpg", "png", "pdf"])
            c1, c2 = st.columns(2)
            with c1:
                m_clinic = st.text_input("🏥 医院名 (必須)")
                m_patient = st.text_input("👤 患者名 (必須)")
                m_slip = st.text_input("📝 伝票番号")
                m_date = st.date_input("📅 完成日", value=date.today())
                m_stype = st.selectbox("📄 シート種別", SHEET_TYPE_LIST)
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
                    img_path = upload_image(m_file)
                    try:
                        db.table("evaluations").insert([{
                            "clinic_name": m_clinic, "patient_name": m_patient, "slip_number": m_slip,
                            "completion_date": m_date.isoformat(), "sheet_type": m_stype,
                            "restoration_type": m_type, "material": m_material, "tooth_position": m_pos, 
                            "contact": m_con, "bite": m_bit, "fit": m_fit, "comments": m_com, "image_url": img_path
                        }]).execute()
                        clear_db_cache()
                        st.toast("手動登録が完了しました！", icon="✅")
                    except Exception as e:
                        st.error(f"データベース登録エラー: {e}")
                        if img_path: db.storage.from_(STORAGE_BUCKET).remove([img_path])

# ==========================================
# Tab 3: 品質分析ダッシュボード
# ==========================================
with tab3:
    st.markdown("### 📊 品質分析ダッシュボード")
    f_df = fetch_evaluations()
    
    if f_df.empty:
        st.info("保存されたデータはまだありません。")
    else:
        with st.container(border=True):
            cf1, cf2, cf3, cf4, cf5 = st.columns(5)
            s_c = cf1.selectbox("🏥 医院", ["すべて"] + sorted(list(f_df["clinic_name"].dropna().unique())))
            s_st = cf2.selectbox("📄 シート", ["すべて"] + list(f_df.get("sheet_type", pd.Series([""])).dropna().unique()))
            s_p = cf3.selectbox("📅 期間", ["すべて", "直近1ヶ月", "直近2ヶ月", "直近3ヶ月", "直近6ヶ月"])
            s_m = cf4.selectbox("💎 材料", ["すべて"] + list(f_df.get("material", pd.Series([""])).dropna().unique()))
            s_r = cf5.selectbox("🦷 種別", ["すべて"] + list(f_df.get("restoration_type", pd.Series([""])).dropna().unique()))
        
        if s_c != "すべて": f_df = f_df[f_df["clinic_name"] == s_c]
        if s_st != "すべて" and "sheet_type" in f_df.columns: f_df = f_df[f_df["sheet_type"] == s_st]
        if s_m != "すべて" and "material" in f_df.columns: f_df = f_df[f_df["material"] == s_m]
        if s_r != "すべて" and "restoration_type" in f_df.columns: f_df = f_df[f_df["restoration_type"] == s_r]
        
        p_map = {"直近1ヶ月": 1, "直近2ヶ月": 2, "直近3ヶ月": 3, "直近6ヶ月": 6}
        if s_p in p_map: 
            cutoff = pd.Timestamp.today().date() - pd.DateOffset(months=p_map[s_p])
            f_df = f_df[f_df['completion_date'] >= cutoff.date()]

        st.markdown("<br>", unsafe_allow_html=True)
        
        def get_stats(col):
            return (f_df[col].mean(), (f_df[col] == 3).sum() / len(f_df) * 100) if len(f_df) > 0 else (0, 0)

        c_m, c_opt = get_stats('contact')
        b_m, b_opt = get_stats('bite')
        f_m, f_opt = get_stats('fit')
        
        def render_metric(label, mean_val, opt_rate):
            if mean_val == 0: return f'<div class="metric-card"><p style="font-weight:bold; color: #1D1D1F;">{label}</p><h2 style="color: #1D1D1F;">- %</h2></div>'
            color = "#34C759" if opt_rate >= 80 else ("#FF9500" if opt_rate >= 50 else "#FF3B30")
            return f"""<div class="metric-card"><p style="margin: 0; font-size: 14px; font-weight: 600; color: #8E8E93;">{label} (適正率)</p>
                <h2 style="margin: 10px 0; color: {color}; font-size: 34px; font-weight: 800;">{opt_rate:.1f}%</h2>
                <p style="margin: 0; font-size: 13px; color: #1D1D1F; font-weight: 500;">平均点: {mean_val:.2f} <span style="color:#8E8E93;">(誤差 {mean_val-3.0:+.2f})</span></p></div>"""

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
                    コンタクト平均=('contact', 'mean'), バイト平均=('bite', 'mean'), 適合平均=('fit', 'mean')
                ).reset_index()
                
                alerts = []
                for _, row in cross_df[cross_df['件数'] >= 2].iterrows():
                    if row['バイト平均'] >= 3.4: alerts.append(f"⚠️ <b>{row['clinic_name']}</b> × <b>{row['material']}</b>: バイトが高めの傾向があります（平均: {row['バイト平均']:.2f}）")
                    elif row['バイト平均'] <= 2.6: alerts.append(f"⚠️ <b>{row['clinic_name']}</b> × <b>{row['material']}</b>: バイトが低めの傾向があります（平均: {row['バイト平均']:.2f}）")
                    if row['コンタクト平均'] >= 3.4: alerts.append(f"⚠️ <b>{row['clinic_name']}</b> × <b>{row['material']}</b>: コンタクトがきつい傾向があります（平均: {row['コンタクト平均']:.2f}）")
                    elif row['コンタクト平均'] <= 2.6: alerts.append(f"⚠️ <b>{row['clinic_name']}</b> × <b>{row['material']}</b>: コンタクトがゆるい傾向があります（平均: {row['コンタクト平均']:.2f}）")

                if alerts:
                    for alt in alerts: st.markdown(f'<div class="alert-card">{alt}</div>', unsafe_allow_html=True)
                else:
                    st.success("✅ 特定の医院×材料における顕著な品質偏差は検出されませんでした。")

                st.markdown("<br><b>【医院 × 材料別 スコアマトリクス】</b>", unsafe_allow_html=True)
                st.dataframe(cross_df.style.format({'コンタクト平均': '{:.2f}', 'バイト平均': '{:.2f}', '適合平均': '{:.2f}'}), use_container_width=True)

        st.markdown("<br>", unsafe_allow_html=True)

        if st.button("🤖 AI詳細分析（時系列トレンド・専門基準による考察）", type="primary", use_container_width=True):
            with st.spinner("AIが時系列データを含めて分析中..."):
                f_df_trend = f_df.copy()
                f_df_trend['年月'] = pd.to_datetime(f_df_trend['completion_date']).dt.strftime('%Y-%m')
                
                summary_df = f_df_trend.groupby(['年月', 'clinic_name', 'restoration_type', 'material']).agg(
                    件数=('id', 'count'),
                    コンタクト平均=('contact', 'mean'), バイト平均=('bite', 'mean'), 適合平均=('fit', 'mean')
                ).round(2).reset_index()
                
                dic_data = summary_df.to_dict(orient='records')
                prompt_text = (
                    f"【重要：必ず日本語で回答してください】\n"
                    f"対象データは全{len(f_df)}件です。条件（医院:{s_c}, シート種別:{s_st}, 材料:{s_m}, 種別:{s_r}）の傾向分析をお願いします。\n"
                    "評価スコアは「3が適正」「1が弱い」「5がきつい」の前提で、プロの歯科技工士の視点から考察してください。\n"
                    f"集計データ:\n{dic_data}"
                )
                try:
                    res_ai = call_gemini_with_fallback(prompt_text=prompt_text)
                    st.info(res_ai.text if res_ai else "分析を完了できませんでした。")
                except Exception as e: st.error(f"分析エラー: {e}")

        st.markdown("<br>", unsafe_allow_html=True)

        with st.container(border=True):
            st.markdown("**📊 スコア分布**")
            if len(f_df) > 0:
                name_map = {'contact': 'コンタクト', 'bite': 'バイト', 'fit': '適合'}
                dist_data = [
                    {'評価項目': name_map[col], 'スコア': str(score), '件数': count, '割合': f"<b>{count/len(f_df)*100:.1f}%</b>" if count > 0 else ""}
                    for col in ['contact', 'bite', 'fit']
                    for score, count in f_df[col].value_counts().reindex([1,2,3,4,5], fill_value=0).items()
                ]
                apple_colors = {'1': '#007AFF', '2': '#5AC8FA', '3': '#34C759', '4': '#FF9500', '5': '#FF3B30'}
                fig_dist = px.bar(pd.DataFrame(dist_data), x='評価項目', y='件数', color='スコア', color_discrete_map=apple_colors, barmode='stack', text='割合')
                fig_dist.update_traces(textposition='inside', textfont_size=16)
                fig_dist.update_layout(dragmode=False, xaxis=dict(title=""), yaxis=dict(title="件数"), plot_bgcolor='rgba(0,0,0,0)', paper_bgcolor='rgba(0,0,0,0)')
                st.plotly_chart(fig_dist, use_container_width=True, config={'displayModeBar': False})

        with st.expander("📈 月別推移（品質トレンド）を開く", expanded=False):
            if len(f_df) > 0:
                trend_df = f_df.assign(month=pd.to_datetime(f_df['completion_date']).dt.to_period('M').astype(str)).groupby('month')[['contact', 'bite', 'fit']].mean().reset_index()
                fig_line = px.line(trend_df, x='month', y=['contact', 'bite', 'fit'], markers=True, range_y=[1, 5], color_discrete_sequence=['#007AFF', '#5AC8FA', '#34C759'])
                fig_line.add_hline(y=3.0, line_dash="dash", line_color="#8E8E93", annotation_text="適正値 (3.0)")
                fig_line.update_layout(dragmode=False, plot_bgcolor='rgba(0,0,0,0)', paper_bgcolor='rgba(0,0,0,0)')
                st.plotly_chart(fig_line, use_container_width=True, config={'displayModeBar': False})

# ==========================================
# Tab 4: 履歴・管理
# ==========================================
with tab4:
    st.markdown("### 📋 保存済みデータの管理・編集")
    df = fetch_evaluations()
    
    if df.empty:
        st.info("データがありません。")
    else:
        with st.container(border=True):
            col_s1, col_s2 = st.columns([3, 1])
            q = col_s1.text_input("🔍 患者名・医院名で検索")
            col_s2.markdown("<br>", unsafe_allow_html=True)
            col_s2.download_button("📥 CSVダウンロード", df.to_csv(index=False).encode('utf-8-sig'), "evaluations.csv", "text/csv", use_container_width=True)
                
        if q: df = df[df['patient_name'].astype(str).str.contains(q, na=False) | df['clinic_name'].astype(str).str.contains(q, na=False)]

        st.markdown("#### 📝 データの一括編集")
        edit_cols = ['id', 'completion_date', 'clinic_name', 'patient_name', 'slip_number', 'sheet_type', 'restoration_type', 'material', 'tooth_position', 'contact', 'bite', 'fit', 'comments']
        df_for_edit = df[[c for c in edit_cols if c in df.columns]].copy()
        df_for_edit.insert(0, "✅ 選択", False)
        
        edited_df = st.data_editor(
            df_for_edit, use_container_width=True, hide_index=True, key="bulk_edit_editor",
            column_config=get_column_configs(is_edit_mode=True), height=500
        )

        selected_rows = edited_df[edited_df["✅ 選択"]]
        if not selected_rows.empty and db:
            with st.container(border=True):
                bc1, bc2, bc3 = st.columns(3)
                b_sheet = bc1.selectbox("📄 シート種別", ["変更しない"] + SHEET_TYPE_LIST, key="b4_sh")
                b_type = bc2.selectbox("🦷 種別", ["変更しない"] + TYPE_LIST, key="b4_ty")
                b_mat = bc3.selectbox("💎 材料", ["変更しない"] + MATERIAL_LIST, key="b4_ma")
                
                if st.button("🚀 チェック項目を一括更新", type="primary"):
                    update_data = {k: v for k, v in [("sheet_type", b_sheet), ("restoration_type", b_type), ("material", b_mat)] if v != "変更しない"}
                    if update_data:
                        with st.spinner("更新中..."):
                            db.table("evaluations").update(update_data).in_("id", selected_rows["id"].tolist()).execute()
                        clear_db_cache()
                        st.success("完了しました！")
                        time.sleep(1)
                        st.rerun()

        if st.button("💾 手動での直接編集内容を保存", type="primary") and db:
            changes = st.session_state["bulk_edit_editor"].get("edited_rows", {})
            if changes:
                with st.spinner("データベース更新中..."):
                    for row_idx, col_changes in changes.items():
                        row_id = int(df_for_edit.iloc[row_idx]['id'])
                        u_data = {k: (str(v)[:10] if k == 'completion_date' and v else v) for k, v in col_changes.items() if k != '✅ 選択'}
                        if u_data: db.table("evaluations").update(u_data).eq("id", row_id).execute()
                clear_db_cache()
                st.success("更新しました！")
                time.sleep(1)
                st.rerun()

        with st.expander("🗑️ データの一括削除", expanded=False):
            selected_ids = [row['id'] for _, row in df.iterrows() if st.checkbox(f"ID:{row['id']} | {row['clinic_name']}", key=f"del_{row['id']}")]
            if selected_ids and st.button("⚠️ 削除する") and db:
                db.table("evaluations").delete().in_("id", selected_ids).execute()
                clear_db_cache()
                st.success("削除完了しました！")
                time.sleep(1)
                st.rerun()
