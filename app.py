import os

# ==========================================
# ★ Streamlitの「テーマカラー（赤色）」を根本から青色に変更する自動設定
# ==========================================
def setup_theme():
    os.makedirs(".streamlit", exist_ok=True)
    theme_file = ".streamlit/config.toml"
    if not os.path.exists(theme_file):
        with open(theme_file, "w") as f:
            f.write("""
[theme]
primaryColor = "#007AFF"
backgroundColor = "#F5F5F7"
secondaryBackgroundColor = "#FFFFFF"
textColor = "#1D1D1F"
font = "sans serif"
""")
        return True
    return False

is_new_theme_created = setup_theme()

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
import re

# ==========================================
# 1. アプリケーション初期設定 & CSS (UI/UX改善)
# ==========================================
st.set_page_config(page_title="AI品質管理カルテ", page_icon="🦷", layout="wide", initial_sidebar_state="collapsed")

if is_new_theme_created:
    st.info("🎨 新しいテーマカラー（ブルー）を設定しました。完全に反映させるため、ブラウザを「再読み込み（F5キー）」してください。")

st.markdown("""
<style>
    .stApp { font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text", "Helvetica Neue", sans-serif !important; }
    #MainMenu, header, footer {visibility: hidden;}
    .custom-title { font-size: clamp(1.8rem, 5vw, 2.4rem); font-weight: 700; letter-spacing: -0.02em; color: #1D1D1F; margin-bottom: 20px; }
    .stButton>button[kind="primary"] { border-radius: 12px !important; font-weight: 600 !important; font-size: 15px !important; box-shadow: 0 4px 12px rgba(0, 122, 255, 0.2) !important; transition: all 0.2s cubic-bezier(0.25, 0.1, 0.25, 1) !important; }
    .stButton>button[kind="primary"]:hover { transform: translateY(-1px) scale(0.99) !important; box-shadow: 0 6px 16px rgba(0, 122, 255, 0.3) !important; }
    div[data-testid="stVerticalBlock"] > div[style*="border"] { border-radius: 18px !important; box-shadow: 0 4px 20px rgba(0, 0, 0, 0.03) !important; padding: 24px !important; border: 1px solid rgba(0,0,0,0.06) !important; background-color: #FFFFFF !important; }
    .streamlit-expanderHeader { border-radius: 14px !important; border: 1px solid #E5E5EA !important; font-weight: 600 !important; background-color: #FFFFFF !important; }
    input, select, textarea { border-radius: 10px !important; transition: all 0.2s ease !important; }
    .metric-card { background: rgba(255, 255, 255, 0.8); backdrop-filter: blur(20px); -webkit-backdrop-filter: blur(20px); padding: 24px; border-radius: 20px; border: 1px solid rgba(255, 255, 255, 0.6); text-align: center; box-shadow: 0 8px 24px rgba(0,0,0,0.04); }
    .metric-card h2 { font-family: -apple-system, BlinkMacSystemFont, "SF Pro Rounded", sans-serif; letter-spacing: -0.04em; }
    .shortcut-guide { font-size: 0.85rem; color: #1D1D1F; background: rgba(0, 122, 255, 0.08); padding: 8px 14px; border-radius: 10px; margin-bottom: 14px; display: inline-block; font-weight: 500; }
    .alert-card { padding: 14px 18px; border-left: 4px solid #FF3B30; background-color: rgba(255, 59, 48, 0.05); border-radius: 12px; margin-bottom: 10px; color: #1D1D1F; font-weight: 500; }
</style>
""", unsafe_allow_html=True)

st.markdown('<div class="custom-title">🦷 AI品質管理カルテ <span style="font-size: 0.5em; font-weight: 500; color: #8E8E93;">(大阪センター)</span></div>', unsafe_allow_html=True)

# ==========================================
# 2. 定数 & データベース設定
# ==========================================
SHEET_TYPE_LIST = ["セパレートレス模型", "IOS"]
MATERIAL_LIST = ["ジルコニア", "CAD/CAM冠", "e.max", "チタン", "3Dプリント", "PEEK", "その他"]
TYPE_LIST = ["クラウン（単冠）", "ブリッジ", "インレー", "インプラント", "義歯", "その他"]

KEY = st.secrets.get("GEMINI_API_KEY")
URL = st.secrets.get("SUPABASE_URL")
S_KEY = st.secrets.get("SUPABASE_KEY")

@st.cache_resource
def get_db():
    try: return create_client(URL, S_KEY) if URL and S_KEY else None
    except Exception as e:
        st.error(f"データベース接続エラー: {e}")
        return None
db = get_db()

# ==========================================
# 3. 全体データの1回のみ一括取得 (無駄を排除)
# ==========================================
global_df = pd.DataFrame()
if db:
    try:
        res = db.table("evaluations").select("*").order("completion_date", desc=True).execute()
        if res.data:
            temp_df = pd.DataFrame(res.data)
            temp_df['completion_date'] = pd.to_datetime(temp_df['completion_date'], errors='coerce').dt.date
            for col in ['contact', 'bite', 'fit', 'id']:
                if col in temp_df.columns:
                    temp_df[col] = pd.to_numeric(temp_df[col], errors='coerce')
            global_df = temp_df
    except Exception as e:
        st.error(f"データ読み込みエラー: {e}")

# ==========================================
# 4. 共通・ヘルパー関数
# ==========================================
def safe_int(val, default=3):
    try: return max(1, min(5, int(float(val))))
    except (ValueError, TypeError): return default

def call_gemini_with_fallback(contents, prm=None, ai_config=None):
    if not KEY: raise ValueError("GEMINI_API_KEY が設定されていません。")
    client = genai.Client(api_key=KEY)
    # 最優先を gemini-3.7-flash に設定
    models = ['gemini-3.7-flash', 'gemini-3.6-flash', 'gemini-3.5-flash', 'gemini-3.5-flash-lite', 'gemini-3-flash']
    payload = [contents, prm] if prm else contents
    last_exception = None
    for idx, model in enumerate(models):
        try: return client.models.generate_content(model=model, contents=payload, config=ai_config)
        except Exception as e:
            last_exception = e
            if idx < len(models) - 1: time.sleep(0.5 * (idx + 1))
            else: raise last_exception
    return None

def upload_file_to_storage(file_obj, suffix_idx):
    if not file_obj or not db: return None
    try:
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
            
        db.storage.from_("sheet_images").upload(f_nm, f_b, {"content-type": mime})
        return db.storage.from_("sheet_images").get_public_url(f_nm)
    except Exception as e:
        st.warning(f"画像アップロードスキップ: {e}")
        return None

def save_single_evaluation(d, file_obj=None):
    try:
        img_url = upload_file_to_storage(file_obj, 0)
        db.table("evaluations").insert({
            "clinic_name": d.get("clinic_name"), "patient_name": d.get("patient_name"),
            "slip_number": d.get("slip_number"), "completion_date": d.get("completion_date"),
            "sheet_type": d.get("sheet_type", "セパレートレス模型"), "restoration_type": d.get("restoration_type"),
            "material": d.get("material"), "tooth_position": d.get("tooth_position"),
            "contact": safe_int(d.get("contact")), "bite": safe_int(d.get("bite")), "fit": safe_int(d.get("fit")),
            "comments": d.get("comments", ""), "image_url": img_url
        }).execute()
    except Exception as e: st.error(f"データベース登録エラー: {e}")

def display_file_preview(file_obj):
    if not file_obj:
        st.write("ファイルがありません")
        return
    if "pdf" in file_obj.type:
        st.info("🔒 ブラウザのセキュリティ制限により、PDFの直接表示がブロックされています。")
        st.download_button(label="📄 PDFファイルを開いて確認する", data=file_obj.getvalue(), file_name=file_obj.name, mime="application/pdf", type="secondary")
    else:
        try: st.image(file_obj.getvalue(), use_container_width=True)
        except Exception: st.warning("画像を表示できません")


# ==========================================
# 5. 画面描画 (Tabs)
# ==========================================
if "uploader_key" not in st.session_state:
    st.session_state["uploader_key"] = "uploader_" + str(time.time())

tab1, tab2, tab3, tab4 = st.tabs(["🤖 AI一括", "✍️ 手動", "📊 分析", "📋 管理"])

# ------------------------------------------
# Tab 1: AI一括登録
# ------------------------------------------
with tab1:
    st.markdown("### 📄 評価シートのアップロード")
    st.info("写真やPDFを選択し、「一括AI解析」ボタンを押してください。")
    up_files = st.file_uploader("画像/PDF(複数選択可)", type=["jpg", "png", "pdf"], accept_multiple_files=True, label_visibility="collapsed", key=st.session_state["uploader_key"])

    if up_files and KEY and st.button("✨ 一括AI解析をスタート", type="primary"):
        with st.spinner("AIがシートを精密解析中..."):
            prm = (
                "このファイルには1枚または複数の補綴物評価シートが含まれています。以下の手順に従い抽出してください。\n\n"
                "1. シート種別の判定: シート上部に「IOSデータ受注」と記載がある場合、または「IOS」の指定がある場合は sheet_type を「IOS」にしてください。不明な場合は「セパレートレス模型」にしてください。\n"
                "2. 製品名からの種別・材料の判定ルール:\n"
                "   - 「CAD冠」が含まれる場合 => material: CAD/CAM冠, restoration_type: クラウン（単冠）\n"
                "   - 「CADIN」「CADインレー」「CADイン」が含まれる場合 => material: CAD/CAM冠, restoration_type: インレー\n"
                "   - 「ZR」や「ジル」から始まる場合 => material: ジルコニア\n"
                "   - 「ZR-IN」「ZRインレー」が含まれる場合 => material: ジルコニア, restoration_type: インレー\n"
                "   - 「ZR-C」や「ZR-E」が含まれる場合 => material: ジルコニア, restoration_type: クラウン（単冠）\n"
                f"   ※上記に当てはまらない場合は、restoration_typeは {', '.join(TYPE_LIST)} から、materialは {', '.join(MATERIAL_LIST)} から最も近いものを選択。\n"
                "3. スコアの抽出: 丸（〇）で囲まれている数字やチェック（✓）が入っている評価数値（contact, bite, fit: 1〜5）を正確に読み取ってください。\n"
                "4. 読み取れない・未記入項目は空文字（\"\"）にしてください。\n"
                "出力キー: clinic_name, patient_name, slip_number, completion_date (YYYY-MM-DD), "
                "sheet_type, restoration_type, material, tooth_position, contact, bite, fit, comments"
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
                        if "pdf" in f.type: cp = types.Part.from_bytes(data=f.getvalue(), mime_type="application/pdf")
                        else:
                            img = Image.open(io.BytesIO(f.getvalue()))
                            img = ImageOps.exif_transpose(img)
                            img = ImageEnhance.Contrast(img).enhance(1.2)
                            cp = img
                        
                        res = call_gemini_with_fallback(cp, prm, ai_config)
                        
                        if res and res.text:
                            parsed = json.loads(res.text.strip())
                            if isinstance(parsed, dict): parsed = [parsed]
                            for item in parsed:
                                item["_f_idx"] = actual_idx
                                tp = str(item.get("tooth_position", ""))
                                if re.search(r'\d{2,}', tp) or re.search(r'\d[-~]\d', tp):
                                    item["restoration_type"] = "ブリッジ"
                                r_list.append(item)
                    except Exception as e: st.error(f"ファイル解析エラー ({f.name}): {e}")
                
                progress_bar.progress(current_end / total_files)
                time.sleep(1.0)
            
            status_text.empty()
            progress_bar.empty()
            
            st.session_state["r_list"] = r_list
            st.session_state["f_list"] = up_files
            st.toast(f"合計 {len(r_list)} 件のデータを検出しました！", icon="✨")

    if "r_list" in st.session_state:
        st.markdown("<br>", unsafe_allow_html=True)
        st.markdown("### 📝 抽出データの確認と修正")
        st.info("💡 操作方法：左端のチェックボックスにチェックを入れると、下部の専用パネルから複数データを一気に変更できます。直接セルを書き換えての保存も可能です。")
        
        r_list, f_list = st.session_state["r_list"], st.session_state["f_list"]
        
        with st.container(border=True):
            st.markdown("**🖼️ 元画像の確認 (プレビュー)**")
            file_names = [f"画像No.{i+1} : {f.name}" for i, f in enumerate(f_list)]
            selected_idx = file_names.index(st.selectbox("確認したい画像を選んでください", file_names, label_visibility="collapsed"))
            with st.expander("👀 画像を開く", expanded=False):
                display_file_preview(f_list[selected_idx])

        formatted_data = []
        for item in r_list:
            try: dt = date.fromisoformat(str(item.get("completion_date", ""))[:10])
            except: dt = date.today()
            formatted_data.append({
                "✅ 選択": False, "画像No": item.get("_f_idx", 0) + 1,
                "医院名": item.get("clinic_name", ""), "患者名": item.get("patient_name", ""),
                "伝票番号": item.get("slip_number", ""), "完成日": dt,
                "シート種別": item.get("sheet_type", "セパレートレス模型"),
                "種別": item.get("restoration_type", ""), "材料": item.get("material", ""),
                "部位": item.get("tooth_position", ""),
                "コンタクト": safe_int(item.get("contact")), "バイト": safe_int(item.get("bite")), "適合": safe_int(item.get("fit")),
                "コメント": item.get("comments", ""), "_f_idx": item.get("_f_idx")
            })
        
        df_edit = pd.DataFrame(formatted_data)
        
        edited_df = st.data_editor(
            df_edit,
            column_config={
                "✅ 選択": st.column_config.CheckboxColumn("✅ 選択", default=False),
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
            use_container_width=True, hide_index=True, num_rows="dynamic", height=400
        )

        st.markdown("<br>", unsafe_allow_html=True)
        
        selected_indices = edited_df[edited_df["✅ 選択"] == True].index.tolist()
        if len(selected_indices) > 0:
            st.markdown(f"**☑️ 選択した {len(selected_indices)} 件のデータを一括変更（保存前）**")
            with st.container(border=True):
                bc1, bc2, bc3 = st.columns(3)
                b_sheet = bc1.selectbox("📄 シート種別を一括変更", ["変更しない"] + SHEET_TYPE_LIST, key="b1_sh")
                b_type = bc2.selectbox("🦷 種別を一括変更", ["変更しない"] + TYPE_LIST, key="b1_ty")
                b_mat = bc3.selectbox("💎 材料を一括変更", ["変更しない"] + MATERIAL_LIST, key="b1_ma")
                
                if st.button("適用する（表に反映）"):
                    for idx in selected_indices:
                        if b_sheet != "変更しない": st.session_state["r_list"][idx]["sheet_type"] = b_sheet
                        if b_type != "変更しない": st.session_state["r_list"][idx]["restoration_type"] = b_type
                        if b_mat != "変更しない": st.session_state["r_list"][idx]["material"] = b_mat
                    st.rerun()

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
                        
                        insert_data.append({
                            "clinic_name": str(row.get("医院名", "")), "patient_name": str(row.get("患者名", "")),
                            "slip_number": str(row.get("伝票番号", "")),
                            "completion_date": row.get("完成日").isoformat() if pd.notna(row.get("完成日")) else date.today().isoformat(),
                            "sheet_type": str(row.get("シート種別", "セパレートレス模型")),
                            "restoration_type": str(row.get("種別", "")), "material": str(row.get("材料", "")),
                            "tooth_position": str(row.get("部位", "")),
                            "contact": safe_int(row.get("コンタクト")), "bite": safe_int(row.get("バイト")), "fit": safe_int(row.get("適合")),
                            "comments": str(row.get("コメント", "")),
                            "image_url": upload_file_to_storage(file_obj, idx)
                        })
                    
                    if insert_data:
                        try: db.table("evaluations").insert(insert_data).execute()
                        except Exception as e: st.error(f"一括保存エラー: {e}")
                            
                del st.session_state["r_list"], st.session_state["f_list"]
                st.session_state["uploader_key"] = "uploader_" + str(time.time())
                st.success("🎉 データの一括保存が完了しました！")
                time.sleep(1.5)
                st.rerun()

# ------------------------------------------
# Tab 2: 手動登録
# ------------------------------------------
with tab2:
    st.markdown("### ✍️ 新規データの手動入力")
    st.info("⌨️ 各種項目を入力して、手動で登録ボタンを押して下さい。")
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
                if not m_clinic or not m_patient: st.error("⚠️ 医院名と患者名は必須入力です。")
                elif db:
                    save_single_evaluation({
                        "clinic_name": m_clinic, "patient_name": m_patient, "slip_number": m_slip,
                        "completion_date": m_date.isoformat(), "sheet_type": m_stype,
                        "restoration_type": m_type, "material": m_material,
                        "tooth_position": m_pos, "contact": m_con, "bite": m_bit, "fit": m_fit, "comments": m_com
                    }, file_obj=m_file)
                    st.toast("手動登録が完了しました！入力欄はリセットされました。", icon="✅")

# ------------------------------------------
# Tab 3: 分析ダッシュボード
# ------------------------------------------
with tab3:
    st.markdown("### 📊 品質分析ダッシュボード")
    if not global_df.empty:
        df = global_df.copy()
        
        # セッションステート初期化（連動絞り込み用）
        for k in ['s_c', 's_st', 's_p', 's_m', 's_r']:
            if k not in st.session_state: st.session_state[k] = "すべて"

        # 連動する選択肢を動的に計算する関数
        def get_dynamic_options(col_name):
            temp = df.copy()
            if st.session_state.s_p != "すべて":
                p_map = {"直近1ヶ月": 1, "直近2ヶ月": 2, "直近3ヶ月": 3, "直近6ヶ月": 6}
                cutoff = pd.Timestamp.today().date() - pd.DateOffset(months=p_map[st.session_state.s_p])
                temp = temp[temp['completion_date'] >= cutoff.date()]
            if st.session_state.s_c != "すべて" and col_name != "clinic_name": temp = temp[temp["clinic_name"] == st.session_state.s_c]
            if st.session_state.s_st != "すべて" and col_name != "sheet_type": temp = temp[temp["sheet_type"] == st.session_state.s_st]
            if st.session_state.s_m != "すべて" and col_name != "material": temp = temp[temp["material"] == st.session_state.s_m]
            if st.session_state.s_r != "すべて" and col_name != "restoration_type": temp = temp[temp["restoration_type"] == st.session_state.s_r]
            
            if col_name in temp.columns:
                opts = ["すべて"] + sorted(list(temp[col_name].dropna().unique()))
            else:
                opts = ["すべて"]
            return opts

        st.info("💡 **操作ガイド**: いずれかの条件を選ぶと、該当しない医院や材料の選択肢が自動で消えます（連動絞り込み）。医院へのフィードバック資料作成時は最下部のレポート出力機能をご活用ください。")
        
        with st.container(border=True):
            cf1, cf2, cf3, cf4, cf5 = st.columns(5)
            # 現在のステートが新しい選択肢リストに含まれない場合は "すべて" にフォールバック
            opt_c = get_dynamic_options("clinic_name")
            opt_st = get_dynamic_options("sheet_type")
            opt_m = get_dynamic_options("material")
            opt_r = get_dynamic_options("restoration_type")
            
            idx_p = ["すべて", "直近1ヶ月", "直近2ヶ月", "直近3ヶ月", "直近6ヶ月"].index(st.session_state.s_p) if st.session_state.s_p in ["すべて", "直近1ヶ月", "直近2ヶ月", "直近3ヶ月", "直近6ヶ月"] else 0
            idx_c = opt_c.index(st.session_state.s_c) if st.session_state.s_c in opt_c else 0
            idx_st = opt_st.index(st.session_state.s_st) if st.session_state.s_st in opt_st else 0
            idx_m = opt_m.index(st.session_state.s_m) if st.session_state.s_m in opt_m else 0
            idx_r = opt_r.index(st.session_state.s_r) if st.session_state.s_r in opt_r else 0

            cf3.selectbox("📅 期間", ["すべて", "直近1ヶ月", "直近2ヶ月", "直近3ヶ月", "直近6ヶ月"], index=idx_p, key="s_p")
            cf1.selectbox("🏥 医院", opt_c, index=idx_c, key="s_c")
            cf2.selectbox("📄 シート", opt_st, index=idx_st, key="s_st")
            cf4.selectbox("💎 材料", opt_m, index=idx_m, key="s_m")
            cf5.selectbox("🦷 種別", opt_r, index=idx_r, key="s_r")
        
        # 実際にデータを絞り込む
        f_df = df.copy()
        if st.session_state.s_c != "すべて": f_df = f_df[f_df["clinic_name"] == st.session_state.s_c]
        if st.session_state.s_st != "すべて" and "sheet_type" in f_df.columns: f_df = f_df[f_df["sheet_type"] == st.session_state.s_st]
        if st.session_state.s_m != "すべて" and "material" in f_df.columns: f_df = f_df[f_df["material"] == st.session_state.s_m]
        if st.session_state.s_r != "すべて" and "restoration_type" in f_df.columns: f_df = f_df[f_df["restoration_type"] == st.session_state.s_r]
        if st.session_state.s_p != "すべて": 
            p_map = {"直近1ヶ月": 1, "直近2ヶ月": 2, "直近3ヶ月": 3, "直近6ヶ月": 6}
            cutoff = pd.Timestamp.today().date() - pd.DateOffset(months=p_map[st.session_state.s_p])
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
                    st.markdown("<b>【自動検知された品質アラート】</b>", unsafe_allow_html=True)
                    for alt in alerts: st.markdown(f'<div class="alert-card">{alt}</div>', unsafe_allow_html=True)
                else:
                    st.success("✅ 特定の医院×材料における顕著な品質偏差（大きなズレ）は検出されませんでした。")

                st.markdown("<br><b>【医院 × 材料別 スコアマトリクス】</b>", unsafe_allow_html=True)
                st.dataframe(cross_df.style.format({'コンタクト平均': '{:.2f}', 'バイト平均': '{:.2f}', '適合平均': '{:.2f}'}), use_container_width=True)

        st.markdown("<br>", unsafe_allow_html=True)

        if st.button("🤖 AI詳細分析（専門基準による考察）", type="primary", use_container_width=True):
            with st.spinner("AIがデータを分析中..."):
                cols = ['completion_date', 'sheet_type', 'restoration_type', 'material', 'contact', 'bite', 'fit', 'comments']
                dic = f_df[[c for c in cols if c in f_df.columns]].astype(str).to_dict(orient='records')
                
                prm = (
                    f"【重要：必ず日本語で回答してください】\n"
                    f"対象データは全{len(f_df)}件です。条件（医院:{st.session_state.s_c}, シート種別:{st.session_state.s_st}, 材料:{st.session_state.s_m}, 種別:{st.session_state.s_r}）の傾向分析をお願いします。\n"
                    "評価スコアは「3が適正」「1が弱い（緩い・低い）」「5がきついの前提で、プロの歯科技工士の視点から考察・分析を行ってください。\n"
                    f"データ:\n{dic}"
                )
                try:
                    res_ai = call_gemini_with_fallback(prm)
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
                fig_dist.update_layout(
                    dragmode=False,
                    xaxis=dict(tickfont=dict(size=16, color="#1D1D1F", weight="bold"), title=""), 
                    yaxis=dict(title="件数"), 
                    plot_bgcolor='rgba(0,0,0,0)', 
                    paper_bgcolor='rgba(0,0,0,0)'
                )
                st.plotly_chart(fig_dist, use_container_width=True, config={'displayModeBar': False})

        with st.expander("📈 月別推移（品質トレンド）を開く", expanded=False):
            if len(f_df) > 0:
                trend_df = f_df.assign(month=pd.to_datetime(f_df['completion_date']).dt.to_period('M').astype(str)).groupby('month')[['contact', 'bite', 'fit']].mean().reset_index()
                fig_line = px.line(trend_df, x='month', y=['contact', 'bite', 'fit'], markers=True, range_y=[1, 5], color_discrete_sequence=['#007AFF', '#5AC8FA', '#34C759'])
                fig_line.add_hline(y=3.0, line_dash="dash", line_color="#8E8E93", annotation_text="適正値 (3.0)")
                fig_line.update_layout(
                    dragmode=False,
                    plot_bgcolor='rgba(0,0,0,0)', 
                    paper_bgcolor='rgba(0,0,0,0)'
                )
                st.plotly_chart(fig_line, use_container_width=True, config={'displayModeBar': False})

        st.markdown("<br>", unsafe_allow_html=True)
        if len(f_df) > 0:
            html = f"""
            <html><head><meta charset="utf-8"><title>品質分析レポート - {st.session_state.s_c}</title>
            <style>
                @media print {{
                    body {{ background-color: #FFFFFF !important; padding: 0 !important; font-size: 12pt !important; }}
                    div {{ box-shadow: none !important; border: 1px solid #CCC !important; margin-bottom: 15px !important; page-break-inside: avoid; }}
                    a {{ display: none !important; }}
                }}
            </style>
            </head>
            <body style="font-family: -apple-system, BlinkMacSystemFont, 'SF Pro Text', sans-serif; padding: 30px; color: #1D1D1F; background-color: #F5F5F7;">
                <h2 style="color: #1D1D1F; border-bottom: 2px solid #E5E5EA; padding-bottom: 10px;">AI品質管理カルテ (大阪センター) - 品質分析レポート</h2>
                <p style="color: #8E8E93; font-weight: 500;">医院: {st.session_state.s_c} | 種別: {st.session_state.s_st} | 材料: {st.session_state.s_m} | 出力日: {date.today().isoformat()}</p>
                
                <div style="background-color: #FFFFFF; padding: 25px; border-radius: 16px; border: 1px solid #E5E5EA; margin-bottom: 20px;">
                    <p style="margin: 0; font-size: 15px; line-height: 1.6;">
                        平素より当ラボの技工物をご愛顧いただき、誠にありがとうございます。<br>
                        先生方からいただいた評価シートのデータを元に、直近の品質傾向と分析レポートを作成いたしました。
                    </p>
                </div>

                <div style="background-color: #FFFFFF; padding: 25px; border-radius: 16px; border: 1px solid #E5E5EA; margin-bottom: 20px;">
                    <h3 style="color: #1D1D1F; margin-top: 0;">📊 総合評価（適正スコア「3」の割合）</h3>
                    <ul style="font-size: 16px; line-height: 1.8;">
                        <li>対象件数: <strong>{len(f_df)} 件</strong></li>
                        <li>コンタクト適正率: <strong>{c_opt:.1f}%</strong> <span style="color:#8E8E93;">(平均点: {c_m:.2f})</span></li>
                        <li>バイト適正率: <strong>{b_opt:.1f}%</strong> <span style="color:#8E8E93;">(平均点: {b_m:.2f})</span></li>
                        <li>適合適正率: <strong>{f_opt:.1f}%</strong> <span style="color:#8E8E93;">(平均点: {f_m:.2f})</span></li>
                    </ul>
                </div>
                
                <div style="background-color: #FFFFFF; padding: 25px; border-radius: 16px; border: 1px solid #E5E5EA; margin-bottom: 20px;">
                    <h3 style="color: #1D1D1F; margin-top: 0;">💡 評価スコアの基準について</h3>
                    <p style="font-size: 14px; color: #8E8E93; margin-bottom: 15px;">
                        当ラボでは、以下の基準で品質を管理・分析しております。理想的な状態（適正）を「3」とし、そこからのズレを数値化することで、より精度の高い補綴物製作に役立てています。
                    </p>
                    <table style="width: 100%; border-collapse: collapse; text-align: center; font-size: 14px;">
                        <tr style="background-color: #F2F2F7;">
                            <th style="padding: 10px; border: 1px solid #E5E5EA;">評価項目</th>
                            <th style="padding: 10px; border: 1px solid #E5E5EA;">1</th>
                            <th style="padding: 10px; border: 1px solid #E5E5EA;">2</th>
                            <th style="padding: 10px; border: 2px solid #007AFF; background-color: #E5F1FF; color: #007AFF;">3 (適正)</th>
                            <th style="padding: 10px; border: 1px solid #E5E5EA;">4</th>
                            <th style="padding: 10px; border: 1px solid #E5E5EA;">5</th>
                        </tr>
                        <tr>
                            <td style="padding: 10px; border: 1px solid #E5E5EA; font-weight: bold; background-color: #FAFAFA;">コンタクト</td>
                            <td style="padding: 10px; border: 1px solid #E5E5EA;">弱い（緩い）</td><td style="padding: 10px; border: 1px solid #E5E5EA;">やや弱い</td>
                            <td style="padding: 10px; border-top: 2px solid #007AFF; border-bottom: 2px solid #007AFF; border-left: 2px solid #007AFF; border-right: 2px solid #007AFF; background-color: #E5F1FF; font-weight: bold; color: #007AFF;">適正</td>
                            <td style="padding: 10px; border: 1px solid #E5E5EA;">ややきつい</td><td style="padding: 10px; border: 1px solid #E5E5EA;">きつい</td>
                        </tr>
                        <tr>
                            <td style="padding: 10px; border: 1px solid #E5E5EA; font-weight: bold; background-color: #FAFAFA;">バイト</td>
                            <td style="padding: 10px; border: 1px solid #E5E5EA;">低い</td><td style="padding: 10px; border: 1px solid #E5E5EA;">やや低い</td>
                            <td style="padding: 10px; border-top: 2px solid #007AFF; border-bottom: 2px solid #007AFF; border-left: 2px solid #007AFF; border-right: 2px solid #007AFF; background-color: #E5F1FF; font-weight: bold; color: #007AFF;">適正</td>
                            <td style="padding: 10px; border: 1px solid #E5E5EA;">やや高い</td><td style="padding: 10px; border: 1px solid #E5E5EA;">高い</td>
                        </tr>
                        <tr>
                            <td style="padding: 10px; border: 1px solid #E5E5EA; font-weight: bold; background-color: #FAFAFA;">適合</td>
                            <td style="padding: 10px; border: 1px solid #E5E5EA;">緩い</td><td style="padding: 10px; border: 1px solid #E5E5EA;">やや緩い</td>
                            <td style="padding: 10px; border-top: 2px solid #007AFF; border-bottom: 2px solid #007AFF; border-left: 2px solid #007AFF; border-right: 2px solid #007AFF; background-color: #E5F1FF; font-weight: bold; color: #007AFF;">適正</td>
                            <td style="padding: 10px; border: 1px solid #E5E5EA;">ややきつい</td><td style="padding: 10px; border: 1px solid #E5E5EA;">きつい</td>
                        </tr>
                    </table>
                </div>

                <div style="background-color: #FFFFFF; padding: 25px; border-radius: 16px; border: 1px solid #E5E5EA;">
                    <h3 style="color: #1D1D1F; margin-top: 0;">📌 今後の品質改善に向けて</h3>
                    <p style="font-size: 15px; line-height: 1.6; color: #333; margin-bottom: 0;">
                        先生からのフィードバックは、当ラボの技術向上において最も重要な指標です。<br>
                        上記のデータに基づき、特に適正値から誤差が見られる項目につきましては、担当技工士および製造部門に共有し、バイト・コンタクトの強さやセメントスペースのパラメータを継続的に見直して参ります。<br><br>
                        引き続き、より良い技工物をご提供できるよう努めてまいりますので、忌憚のないご意見をよろしくお願い申し上げます。
                    </p>
                </div>
            </body></html>
            """
            b64 = base64.b64encode(html.encode('utf-8')).decode()
            st.markdown(f'<a href="data:text/html;base64,{b64}" download="quality_report.html" target="_blank" style="display: inline-block; padding: 12px 24px; background-color: #007AFF; color: white; text-decoration: none; border-radius: 12px; font-weight: 600; box-shadow: 0 4px 12px rgba(0, 122, 255, 0.3);">📥 医院向けレポートを出力 (HTML)</a>', unsafe_allow_html=True)
    else:
        st.info("保存されたデータはまだありません。")

# ------------------------------------------
# Tab 4: 履歴・管理
# ------------------------------------------
with tab4:
    st.markdown("### 📋 保存済みデータの管理・編集")
    if not global_df.empty:
        df = global_df.copy()
        
        # ★ 検索ボックス（ラベルを隠してボタンとの高さを完璧に合わせる）
        with st.container(border=True):
            col_s1, col_s2, col_s3 = st.columns([2, 1, 1])
            search_query = col_s1.text_input("検索", placeholder="🔍 患者名・医院名で検索...", label_visibility="collapsed")
            search_btn = col_s2.button("🔍 検索", type="primary", use_container_width=True)
            col_s3.download_button("📥 CSVダウンロード", df.to_csv(index=False).encode('utf-8-sig'), "evaluations.csv", "text/csv", use_container_width=True)
                
        # 検索フィルタリング
        if search_query:
            df = df[df['patient_name'].astype(str).str.contains(search_query, na=False) | df['clinic_name'].astype(str).str.contains(search_query, na=False)]

        st.markdown("---")
        st.markdown("#### 📝 データの一括編集・削除")
        st.info("💡 操作方法：左端のチェックボックスにチェックを入れると、下部の専用パネルから複数データを一気に変更・削除できます。")
        
        edit_cols = ['id', 'completion_date', 'clinic_name', 'patient_name', 'slip_number', 'sheet_type', 'restoration_type', 'material', 'tooth_position', 'contact', 'bite', 'fit', 'comments', 'image_url']
        df_for_edit = df[[c for c in edit_cols if c in df.columns]].copy()
        df_for_edit.insert(0, "✅ 選択", False)
        
        edited_df = st.data_editor(
            df_for_edit,
            use_container_width=True, hide_index=True, key="bulk_edit_editor", disabled=["id"], 
            column_config={
                "✅ 選択": st.column_config.CheckboxColumn("✅ 選択", default=False),
                "id": st.column_config.NumberColumn("ID", width="small"),
                "completion_date": st.column_config.DateColumn("📅 完成日"),
                "clinic_name": st.column_config.TextColumn("🏥 医院名", required=True),
                "patient_name": st.column_config.TextColumn("👤 患者名", required=True),
                "slip_number": st.column_config.TextColumn("📝 伝票番号"),
                "sheet_type": st.column_config.SelectboxColumn("📄 シート種別", options=SHEET_TYPE_LIST),
                "restoration_type": st.column_config.SelectboxColumn("🦷 種別", options=TYPE_LIST),
                "material": st.column_config.SelectboxColumn("💎 材料", options=MATERIAL_LIST),
                "tooth_position": st.column_config.TextColumn("📍 部位"),
                "contact": st.column_config.NumberColumn("コンタクト", min_value=1, max_value=5),
                "bite": st.column_config.NumberColumn("バイト", min_value=1, max_value=5),
                "fit": st.column_config.NumberColumn("適合", min_value=1, max_value=5),
                "comments": st.column_config.TextColumn("💬 コメント"),
                "image_url": st.column_config.ImageColumn("🖼️ シート画像", width="medium"),
            },
            height=500
        )

        selected_rows = edited_df[edited_df["✅ 選択"] == True]
        if len(selected_rows) > 0:
            st.markdown(f"**☑️ 選択した {len(selected_rows)} 件のデータに対する操作**")
            with st.container(border=True):
                bc1, bc2, bc3 = st.columns(3)
                b_sheet = bc1.selectbox("📄 シート種別を一括変更", ["変更しない"] + SHEET_TYPE_LIST, key="b4_sh")
                b_type = bc2.selectbox("🦷 種別を一括変更", ["変更しない"] + TYPE_LIST, key="b4_ty")
                b_mat = bc3.selectbox("💎 材料を一括変更", ["変更しない"] + MATERIAL_LIST, key="b4_ma")
                
                # ★ 更新ボタンと削除ボタンを横並びに配置
                btn_c1, btn_c2 = st.columns(2)
                
                if btn_c1.button("🚀 チェックした項目を一括更新（DB保存）", type="primary", use_container_width=True):
                    update_data = {}
                    if b_sheet != "変更しない": update_data["sheet_type"] = b_sheet
                    if b_type != "変更しない": update_data["restoration_type"] = b_type
                    if b_mat != "変更しない": update_data["material"] = b_mat
                    
                    if update_data:
                        with st.spinner("一括更新中..."):
                            target_ids = selected_rows["id"].tolist()
                            for tid in target_ids:
                                db.table("evaluations").update(update_data).eq("id", int(tid)).execute()
                        st.success("一括更新が完了しました！画面を再読み込みします。")
                        time.sleep(1.5)
                        st.rerun()
                    else:
                        st.warning("変更する項目を選んでください。")
                
                if btn_c2.button("🗑️ 選択したデータを一括削除", use_container_width=True):
                    st.session_state.confirm_bulk_del = True
                    
            # ★ 削除前の確認ポップアップ表示
            if st.session_state.get("confirm_bulk_del", False):
                st.error(f"⚠️ 本当に選択した {len(selected_rows)} 件のデータを完全に削除しますか？ この操作は元に戻せません。")
                del_c1, del_c2 = st.columns(2)
                if del_c1.button("✅ はい、完全に削除します", type="primary", use_container_width=True):
                    with st.spinner("データベースから削除中..."):
                        target_ids = selected_rows["id"].tolist()
                        for tid in target_ids:
                            db.table("evaluations").delete().eq("id", int(tid)).execute()
                    st.session_state.confirm_bulk_del = False
                    st.success("一括削除が完了しました！画面を再読み込みします。")
                    time.sleep(1.5)
                    st.rerun()
                if del_c2.button("❌ キャンセル", use_container_width=True):
                    st.session_state.confirm_bulk_del = False
                    st.rerun()

        st.markdown("<br>", unsafe_allow_html=True)

        if st.button("💾 手動での直接編集内容を保存", type="primary"):
            changes = st.session_state["bulk_edit_editor"].get("edited_rows", {})
            if changes:
                with st.spinner("データベースを更新中..."):
                    for row_idx, col_changes in changes.items():
                        row_id = int(df_for_edit.iloc[row_idx]['id'])
                        update_data = {}
                        for col_name, new_val in col_changes.items():
                            if col_name == '✅ 選択': continue 
                            if col_name == 'completion_date' and new_val is not None:
                                update_data[col_name] = str(new_val)[:10]
                            else:
                                update_data[col_name] = new_val
                        if update_data:
                            db.table("evaluations").update(update_data).eq("id", row_id).execute()
                            
                st.success(f"🎉 編集内容を更新しました！画面を再読み込みします。")
                time.sleep(1.5)
                st.rerun()
            else:
                st.warning("セルが直接変更されたデータはありません。")

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
        with st.expander("🚑 万が一のデータ復旧 (CSVから一括インポート)", expanded=False):
            st.info("過去にダウンロードしたバックアップ用のCSVファイルをアップロードして、データを一括復元します。")
            restore_file = st.file_uploader("復旧用CSVファイルを選択", type=["csv"], key="restore_csv")
            
            if restore_file and st.button("⚠️ CSVからデータを一括復元する", type="primary"):
                try:
                    df_restore = pd.read_csv(restore_file)
                    if 'id' in df_restore.columns: df_restore = df_restore.drop(columns=['id'])
                    records = df_restore.to_dict(orient="records")
                    
                    with st.spinner("データをデータベースに復元中..."):
                        if records: db.table("evaluations").insert(records).execute()
                            
                    st.success(f"🎉 {len(records)} 件のデータを無事に復元しました！画面を再読み込みします。")
                    time.sleep(2)
                    st.rerun()
                except Exception as e: st.error(f"復元エラー: {e}")
    else:
        st.info("保存されたデータはまだありません。")

