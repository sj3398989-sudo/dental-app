"""Tab 1: AI一括登録（アップロード → AI解析 → 確認・修正 → 一括保存）。

アップロードしたファイルはブラウザ/メモリ上でのプレビューとAI解析にのみ使用し、
ストレージへは保存しない（画像はDBにも残さない）。
"""

import time
from datetime import date

import pandas as pd
import streamlit as st

from config import (
    MATERIAL_LIST, MAX_UPLOAD_SIZE_MB, SCORE_MAX, SCORE_MIN, SHEET_TYPE_LIST, TYPE_LIST,
    oversized_files, safe_int,
)
from database import get_db, insert_evaluations
import ai_service


def display_file_preview(file_obj):
    """アップロードされた画像/PDFのプレビュー表示（メモリ上のデータのみを使用）。"""
    if not file_obj:
        st.write("ファイルがありません")
        return
    if "pdf" in file_obj.type:
        st.info("🔒 ブラウザのセキュリティ制限により、PDFの直接表示がブロックされています。")
        st.download_button(
            label="📄 PDFファイルを開いて確認する", data=file_obj.getvalue(),
            file_name=file_obj.name, mime="application/pdf", type="secondary",
        )
    else:
        try:
            st.image(file_obj.getvalue(), use_container_width=True)
        except Exception:
            st.warning("画像を表示できません")


def _run_extraction(up_files, global_df):
    """AI解析を実行し、結果をセッションに格納する。"""
    with st.spinner("AIがシートを精密解析中..."):
        clinic_list_str = ai_service.build_clinic_list_str(global_df)

        progress_bar = st.progress(0)
        status_text = st.empty()

        r_list = ai_service.extract_sheets_from_files(
            up_files,
            clinic_list_str,
            on_status=lambda txt: status_text.markdown(txt),
            on_progress=lambda ratio: progress_bar.progress(ratio),
            on_error=lambda msg: st.error(msg),
        )

        status_text.empty()
        progress_bar.empty()

        st.session_state["r_list"] = r_list
        st.session_state["f_list"] = up_files
        st.toast(f"合計 {len(r_list)} 件のデータを検出しました！", icon="✨")


def _to_editor_rows(r_list):
    """AI抽出結果を data_editor 用の表形式に整形する。"""
    formatted_data = []
    for item in r_list:
        try:
            dt = date.fromisoformat(str(item.get("completion_date", ""))[:10])
        except Exception:
            dt = date.today()
        formatted_data.append({
            "✅ 選択": False, "画像No": item.get("_f_idx", 0) + 1,
            "医院名": item.get("clinic_name", ""),
            "伝票番号": item.get("slip_number", ""), "完成日": dt,
            "シート種別": item.get("sheet_type", "セパレートレス模型"),
            "種別": item.get("restoration_type", ""), "材料": item.get("material", ""),
            "部位": item.get("tooth_position", ""),
            "コンタクト": safe_int(item.get("contact")), "バイト": safe_int(item.get("bite")),
            "fit": safe_int(item.get("fit")),
            "コメント": item.get("comments", ""), "_f_idx": item.get("_f_idx"),
        })
    return formatted_data


def _render_editor(df_edit):
    return st.data_editor(
        df_edit,
        column_config={
            "✅ 選択": st.column_config.CheckboxColumn("✅ 選択", default=False),
            "画像No": st.column_config.NumberColumn("画像No", disabled=True, width="small"),
            "医院名": st.column_config.TextColumn("🏥 医院名", required=True),
            "伝票番号": st.column_config.TextColumn("📝 伝票番号", required=True),
            "完成日": st.column_config.DateColumn("📅 完成日"),
            "シート種別": st.column_config.SelectboxColumn("📄 シート種別", options=SHEET_TYPE_LIST),
            "種別": st.column_config.SelectboxColumn("🦷 種別", options=TYPE_LIST),
            "材料": st.column_config.SelectboxColumn("💎 材料", options=MATERIAL_LIST),
            "部位": st.column_config.TextColumn("📍 部位"),
            "コンタクト": st.column_config.NumberColumn(
                "コンタクト", min_value=SCORE_MIN, max_value=SCORE_MAX, step=1, width="small"),
            "バイト": st.column_config.NumberColumn(
                "バイト", min_value=SCORE_MIN, max_value=SCORE_MAX, step=1, width="small"),
            "fit": st.column_config.NumberColumn(
                "適合", min_value=SCORE_MIN, max_value=SCORE_MAX, step=1, width="small"),
            "コメント": st.column_config.TextColumn("💬 コメント"),
            "_f_idx": None,
        },
        use_container_width=True, hide_index=True, num_rows="dynamic", height=400,
    )


def _render_bulk_panel(selected_indices):
    """保存前の一括変更パネル（セッション上の抽出結果を直接書き換える）。"""
    st.markdown(f"**☑️ 選択した {len(selected_indices)} 件のデータを一括変更（保存前）**")
    with st.container(border=True):
        bc1, bc2, bc3 = st.columns(3)
        b_sheet = bc1.selectbox("📄 シート種別を一括変更", ["変更しない"] + SHEET_TYPE_LIST, key="b1_sh")
        b_type = bc2.selectbox("🦷 種別を一括変更", ["変更しない"] + TYPE_LIST, key="b1_ty")
        b_mat = bc3.selectbox("💎 材料を一括変更", ["変更しない"] + MATERIAL_LIST, key="b1_ma")

        if st.button("適用する（表に反映）"):
            for idx in selected_indices:
                if b_sheet != "変更しない":
                    st.session_state["r_list"][idx]["sheet_type"] = b_sheet
                if b_type != "変更しない":
                    st.session_state["r_list"][idx]["restoration_type"] = b_type
                if b_mat != "変更しない":
                    st.session_state["r_list"][idx]["material"] = b_mat
            st.rerun()


def _has_blank_required(edited_df):
    """医院名・伝票番号（主要な識別子）の未入力チェック。"""
    for column in ("医院名", "伝票番号"):
        if (edited_df[column].fillna("").astype(str).str.strip() == "").any():
            return True
    return False


def _save_all(edited_df):
    with st.spinner("データベースへ一括保存中..."):
        insert_data = [
            {
                "clinic_name": str(row.get("医院名", "")),
                "slip_number": str(row.get("伝票番号", "")),
                "completion_date": row.get("完成日").isoformat()
                if pd.notna(row.get("完成日")) else date.today().isoformat(),
                "sheet_type": str(row.get("シート種別", "セパレートレス模型")),
                "restoration_type": str(row.get("種別", "")), "material": str(row.get("材料", "")),
                "tooth_position": str(row.get("部位", "")),
                "contact": safe_int(row.get("コンタクト")), "bite": safe_int(row.get("バイト")),
                "fit": safe_int(row.get("fit")),
                "comments": str(row.get("コメント", "")),
            }
            for _, row in edited_df.iterrows()
        ]

        insert_evaluations(insert_data)

    # 解析に使ったファイルはセッションからも破棄する（メモリ上にも残さない）
    del st.session_state["r_list"], st.session_state["f_list"]
    st.session_state["uploader_key"] = "uploader_" + str(time.time())
    st.success("🎉 データの一括保存が完了しました！")
    time.sleep(1.5)
    st.rerun()


def render(global_df):
    st.markdown("### 📄 クイック AI 登録")
    st.caption("評価シートの写真や PDF をドラッグ＆ドロップまたは選択してください")

    with st.container(border=True):
        up_files = st.file_uploader(
            "画像/PDF", type=["jpg", "png", "pdf"], accept_multiple_files=True,
            label_visibility="collapsed", key=st.session_state["uploader_key"],
        )

    st.caption("🔒 <span style='color: #9CA3AF;'>ファイルは解析とプレビュー確認にのみ使用。保存されるのは文字データのみ。</span>", unsafe_allow_html=True)

    # アップロードサイズの検証（上限超過分があれば解析を中断する）
    oversize_names = oversized_files(up_files)
    if oversize_names:
        st.warning(
            f"⚠️ 以下のファイルは上限（{MAX_UPLOAD_SIZE_MB}MB）を超えているため処理を中断しました。"
            f"サイズを小さくしてから再度アップロードしてください。\n\n"
            + "\n".join(f"- {name}" for name in oversize_names)
        )

    can_extract = bool(up_files) and not oversize_names and ai_service.get_api_key()
    if can_extract and st.button("✨ 一括AI解析をスタート", type="primary"):
        _run_extraction(up_files, global_df)

    if "r_list" not in st.session_state:
        return

    st.markdown("<br>", unsafe_allow_html=True)
    st.markdown("### 📝 抽出データの確認と修正")
    st.info("💡 操作方法：左端のチェックボックスにチェックを入れると、下部の専用パネルから複数データを一気に変更できます。直接セルを書き換えての保存も可能です。")

    r_list, f_list = st.session_state["r_list"], st.session_state["f_list"]

    with st.container(border=True):
        st.markdown("**🖼️ 元画像の確認 (プレビュー)**")
        file_names = [f"画像No.{i+1} : {f.name}" for i, f in enumerate(f_list)]
        selected_idx = file_names.index(
            st.selectbox("確認したい画像を選んでください", file_names, label_visibility="collapsed"))
        with st.expander("👀 画像を開く", expanded=False):
            display_file_preview(f_list[selected_idx])

    df_edit = pd.DataFrame(_to_editor_rows(r_list))
    edited_df = _render_editor(df_edit)

    st.markdown("<br>", unsafe_allow_html=True)

    selected_indices = edited_df[edited_df["✅ 選択"] == True].index.tolist()
    if len(selected_indices) > 0:
        _render_bulk_panel(selected_indices)

    st.markdown("<br>", unsafe_allow_html=True)

    if st.button("💾 確認したデータを全て一括保存", type="primary", use_container_width=True):
        if _has_blank_required(edited_df):
            st.error("⚠️ 未入力の「医院名」または「伝票番号」があります。表を確認してください。")
        elif get_db():
            _save_all(edited_df)
