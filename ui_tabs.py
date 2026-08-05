import streamlit as st
import pandas as pd
import plotly.express as px
from google.genai import types
import time
from datetime import date
import base64
import concurrent.futures

from config import SHEET_TYPE_LIST, MATERIAL_LIST, TYPE_LIST, KEY
from db import fetch_evaluations, clear_db_cache, upload_file_to_storage, remove_files_from_storage, hash_patient_name
from ai import process_single_file, call_gemini_with_fallback

def safe_int(val, default=3):
    try: return max(1, min(5, int(float(val))))
    except (ValueError, TypeError): return default

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

# ------------------------------------------
# Tab 1: AI一括登録
# ------------------------------------------
def render_tab1(db):
    st.markdown("### 📄 評価シートのアップロード")
    st.info("写真やPDFを選択し、「一括AI解析」ボタンを押してください。")
    
    if "uploader_key" not in st.session_state:
        st.session_state["uploader_key"] = "uploader_" + str(time.time())
        
    up_files = st.file_uploader("画像/PDF(複数選択可)", type=["jpg", "png", "pdf"], accept_multiple_files=True, label_visibility="collapsed", key=st.session_state["uploader_key"])

    if up_files and KEY and st.button("✨ 一括AI解析をスタート", type="primary"):
        with st.spinner("AIがシートを並列解析中... (高速・高精度モード)"):
            prompt_text = (
                "このファイルは歯科補綴物の評価シート（手書き含む）です。以下の指示に従い、正確にデータを抽出・推論してください。\n\n"
                "【1. 曖昧な手書きの文脈推測（材料・種別）】\n"
                "手書き文字が崩れていたり略称（「ジ」「2R」「ZR」など）であっても、文脈から以下の選択肢に必ず当てはめてください。\n"
                f"- material: {', '.join(MATERIAL_LIST)}\n"
                f"- restoration_type: {', '.join(TYPE_LIST)}\n"
                "不明な場合は「その他」にしてください。\n\n"
                "【2. 見たままの抽出（日付・部位・数値）】\n"
                "- 日付 (raw_completion_date): 西暦への変換などは絶対にせず、紙に書かれたままの文字（例: 26/8/5, 8.5）を抽出してください。\n"
                "- 部位 (tooth_position): 書かれたままの数字や記号を抽出してください。\n"
                "- 評価スコア (contact, bite, fit): 1〜5の数字のうち、丸（〇）やチェック（✓）がついている数字を正確に1つだけ抽出してください。\n\n"
                "【3. その他】\n"
                "- シート種別 (sheet_type): 「IOSデータ受注」等の記載があれば「IOS」、なければ「セパレートレス模型」。\n"
                "出力キー: clinic_name, patient_name, slip_number, raw_completion_date, sheet_type, restoration_type, material, tooth_position, contact, bite, fit, comments"
            )
            
            ai_config = types.GenerateContentConfig(temperature=0.0, response_mime_type="application/json")
            r_list = []
            total_files = len(up_files)
            progress_bar = st.progress(0)
            status_text = st.empty()
            processed_count = 0
            
            with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
                future_to_idx = {executor.submit(process_single_file, f, idx, prompt_text, ai_config): idx for idx, f in enumerate(up_files)}
                for future in concurrent.futures.as_completed(future_to_idx):
                    processed_count += 1
                    status_text.markdown(f"**⏳ 並列解析中... {processed_count} / 全{total_files}枚 完了**")
                    progress_bar.progress(processed_count / total_files)
                    result = future.result()
                    if result:
                        if isinstance(result, list): r_list.extend(result)
                        elif "error" in result: st.error(result["error"])

            status_text.empty()
            progress_bar.empty()
            r_list = sorted(r_list, key=lambda x: x.get("_f_idx", 0))
            
            st.session_state["r_list"] = r_list
            st.session_state["f_list"] = up_files
            st.toast(f"合計 {len(r_list)} 件のデータを検出しました！", icon="✨")

    if "r_list" in st.session_state:
        st.markdown("<br>", unsafe_allow_html=True)
        st.markdown("### 📝 抽出データの確認と修正")
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
            if edited_df["医院名"].isnull().any() or (edited_df["医院名"].astype(str).str.strip() == "").any():
                st.error("⚠️ 未入力の「医院名」があります。表を確認してください。")
            elif db:
                with st.spinner("データベースへ一括保存中... (匿名化＆バルクインサート)"):
                    insert_data = []
                    uploaded_paths = [] 
                    
                    for idx, row in edited_df.iterrows():
                        f_idx = row.get("_f_idx")
                        file_obj = f_list[int(f_idx)] if pd.notna(f_idx) and int(f_idx) < len(f_list) else None
                        img_path = upload_file_to_storage(file_obj)
                        if img_path: uploaded_paths.append(img_path)
                        
                        insert_data.append({
                            "clinic_name": str(row.get("医院名", "")), 
                            "patient_name": hash_patient_name(str(row.get("患者名", ""))),
                            "slip_number": str(row.get("伝票番号", "")),
                            "completion_date": row.get("完成日").isoformat() if pd.notna(row.get("完成日")) else date.today().isoformat(),
                            "sheet_type": str(row.get("シート種別", "セパレートレス模型")),
                            "restoration_type": str(row.get("種別", "")), "material": str(row.get("材料", "")),
                            "tooth_position": str(row.get("部位", "")),
                            "contact": safe_int(row.get("コンタクト")), "bite": safe_int(row.get("バイト")), "fit": safe_int(row.get("適合")),
                            "comments": str(row.get("コメント", "")),
                            "image_url": img_path
                        })
                    
                    if insert_data:
                        try:
                            chunk_size = 100
                            for i in range(0, len(insert_data), chunk_size):
                                chunk = insert_data[i:i + chunk_size]
                                db.table("evaluations").insert(chunk).execute()
                                
                            clear_db_cache()
                            del st.session_state["r_list"], st.session_state["f_list"]
                            st.session_state["uploader_key"] = "uploader_" + str(time.time())
                            st.success("🎉 データの一括保存が完了しました！（患者名は安全に匿名化されました）")
                            time.sleep(1.5)
                            st.rerun()
                        except Exception as e:
                            st.error(f"一括保存エラー: {e}")
                            if uploaded_paths:
                                remove_files_from_storage(uploaded_paths)

# ------------------------------------------
# Tab 2: 手動登録
# ------------------------------------------
def render_tab2(db):
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
                if not m_clinic or not m_patient: st.error("⚠️ 医院名と患者名は必須入力です。")
                elif db:
                    img_path = upload_file_to_storage(m_file)
                    try:
                        db.table("evaluations").insert({
                            "clinic_name": m_clinic, 
                            "patient_name": hash_patient_name(m_patient), 
                            "slip_number": m_slip,
                            "completion_date": m_date.isoformat(), "sheet_type": m_stype,
                            "restoration_type": m_type, "material": m_material,
                            "tooth_position": m_pos, "contact": m_con, "bite": m_bit, "fit": m_fit, "comments": m_com,
                            "image_url": img_path
                        }).execute()
                        clear_db_cache()
                        st.toast("手動登録が完了しました！（患者名は安全に匿名化されました）", icon="✅")
                    except Exception as e:
                        st.error(f"データベース登録エラー: {e}")
                        if img_path: remove_files_from_storage([img_path])

# ------------------------------------------
# Tab 3: 分析ダッシュボード
# ------------------------------------------
def render_tab3():
    st.markdown("### 📊 品質分析ダッシュボード")
    global_df = fetch_evaluations()
    
    if not global_df.empty:
        df = global_df.copy()
        
        with st.container(border=True):
            cf1, cf2, cf3, cf4, cf5 = st.columns(5)
            s_c = cf1.selectbox("🏥 医院", ["すべて"] + sorted(list(df["clinic_name"].dropna().unique())))
            s_st = cf2.selectbox("📄 シート", ["すべて"] + list(df.get("sheet_type", pd.Series([""])).dropna().unique()))
            s_p = cf3.selectbox("📅 期間", ["すべて", "直近1ヶ月", "直近2ヶ月", "直近3ヶ月", "直近6ヶ月"])
            s_m = cf4.selectbox("💎 材料", ["すべて"] + list(df.get("material", pd.Series([""])).dropna().unique()))
            s_r = cf5.selectbox("🦷 種別", ["すべて"] + list(df.get("restoration_type", pd.Series([""])).dropna().unique()))
        
        f_df = df.copy()
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
                    st.success("✅ 特定の医院×材料における顕著な品質偏差（大きなズレ）は検出されませんでした。")

                st.markdown("<br><b>【医院 × 材料別 スコアマトリクス】</b>", unsafe_allow_html=True)
                st.dataframe(cross_df.style.format({'コンタクト平均': '{:.2f}', 'バイト平均': '{:.2f}', '適合平均': '{:.2f}'}), use_container_width=True)

        st.markdown("<br>", unsafe_allow_html=True)

        if st.button("🤖 AI詳細分析（時系列トレンド・専門基準による考察）", type="primary", use_container_width=True):
            with st.spinner("AIが時系列データを含めて分析中..."):
                f_df_trend = f_df.copy()
                f_df_trend['年月'] = pd.to_datetime(f_df_trend['completion_date']).dt.strftime('%Y-%m')
                
                summary_df = f_df_trend.groupby(['年月', 'clinic_name', 'restoration_type', 'material']).agg(
                    件数=('id', 'count'),
                    コンタクト平均=('contact', 'mean'),
                    バイト平均=('bite', 'mean'),
                    適合平均=('fit', 'mean')
                ).round(2).reset_index()
                
                dic_data = summary_df.to_dict(orient='records')
                prompt_text = (
                    f"【重要：必ず日本語で回答してください】\n"
                    f"対象データは全{len(f_df)}件です。条件（医院:{s_c}, シート種別:{s_st}, 材料:{s_m}, 種別:{s_r}）の傾向分析をお願いします。\n"
                    "評価スコアは「3が適正」「1が弱い」「5がきつい」の前提で、プロの歯科技工士の視点から考察してください。\n"
                    "【重要】データには「年月」が含まれています。時系列での品質の変化があれば必ず言及してください。\n"
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
    else:
        st.info("保存されたデータはまだありません。")

# ------------------------------------------
# Tab 4: 履歴・管理
# ------------------------------------------
def render_tab4(db):
    st.markdown("### 📋 保存済みデータの管理・編集")
    global_df = fetch_evaluations()
    if not global_df.empty:
        df = global_df.copy()
        
        with st.container(border=True):
            col_s1, col_s2 = st.columns([3, 1])
            q = col_s1.text_input("🔍 患者ID・医院名で検索")
            col_s2.markdown("<br>", unsafe_allow_html=True)
            col_s2.download_button("📥 CSVダウンロード", df.to_csv(index=False).encode('utf-8-sig'), "evaluations.csv", "text/csv", use_container_width=True)
                
        if q:
            df = df[df['patient_name'].astype(str).str.contains(q, na=False) | df['clinic_name'].astype(str).str.contains(q, na=False)]

        st.markdown("---")
        st.markdown("#### 📝 データの一括編集")
        
        edit_cols = ['id', 'completion_date', 'clinic_name', 'patient_name', 'slip_number', 'sheet_type', 'restoration_type', 'material', 'tooth_position', 'contact', 'bite', 'fit', 'comments']
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
                "patient_name": st.column_config.TextColumn("👤 患者ID (匿名)", disabled=True),
                "slip_number": st.column_config.TextColumn("📝 伝票番号"),
                "sheet_type": st.column_config.SelectboxColumn("📄 シート種別", options=SHEET_TYPE_LIST),
                "restoration_type": st.column_config.SelectboxColumn("🦷 種別", options=TYPE_LIST),
                "material": st.column_config.SelectboxColumn("💎 材料", options=MATERIAL_LIST),
                "tooth_position": st.column_config.TextColumn("📍 部位"),
                "contact": st.column_config.NumberColumn("コンタクト", min_value=1, max_value=5),
                "bite": st.column_config.NumberColumn("バイト", min_value=1, max_value=5),
                "fit": st.column_config.NumberColumn("適合", min_value=1, max_value=5),
                "comments": st.column_config.TextColumn("💬 コメント"),
            },
            height=500
        )

        selected_rows = edited_df[edited_df["✅ 選択"] == True]
        if len(selected_rows) > 0:
            st.markdown(f"**☑️ 選択した {len(selected_rows)} 件のデータを一括変更**")
            with st.container(border=True):
                bc1, bc2, bc3 = st.columns(3)
                b_sheet = bc1.selectbox("📄 シート種別を一括変更", ["変更しない"] + SHEET_TYPE_LIST, key="b4_sh")
                b_type = bc2.selectbox("🦷 種別を一括変更", ["変更しない"] + TYPE_LIST, key="b4_ty")
                b_mat = bc3.selectbox("💎 材料を一括変更", ["変更しない"] + MATERIAL_LIST, key="b4_ma")
                
                if st.button("🚀 チェックした項目を一括更新（DB保存）", type="primary"):
                    update_data = {}
                    if b_sheet != "変更しない": update_data["sheet_type"] = b_sheet
                    if b_type != "変更しない": update_data["restoration_type"] = b_type
                    if b_mat != "変更しない": update_data["material"] = b_mat
                    
                    if update_data:
                        with st.spinner("一括更新中..."):
                            target_ids = selected_rows["id"].tolist()
                            db.table("evaluations").update(update_data).in_("id", target_ids).execute()
                        clear_db_cache()
                        st.success("一括更新が完了しました！画面を再読み込みします。")
                        time.sleep(1.5)
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
                clear_db_cache()
                st.success(f"🎉 編集内容を更新しました！")
                time.sleep(1.5)
                st.rerun()

        st.markdown("---")
        with st.expander("🗑️ データ・画像の一括削除", expanded=False):
            st.warning("選択したデータをDBから完全に消去します。")
            selected_ids = [row['id'] for _, row in df.iterrows() if st.checkbox(f"ID:{row['id']} | {row['clinic_name']} - 患者ID:{row['patient_name']}", key=f"del_{row['id']}")]
            if selected_ids and st.button(f"⚠️ 選択した {len(selected_ids)} 件のデータを完全に削除する"):
                db.table("evaluations").delete().in_("id", selected_ids).execute()
                clear_db_cache()
                st.success("削除完了しました！")
                time.sleep(1)
                st.rerun()
    else:
        st.info("保存されたデータはまだありません。")
