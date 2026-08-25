"""Tab 4: 履歴・管理（検索/CSV・一括更新/削除・名寄せ・CSV復旧）。

患者名・画像は保持しないため、レコードの識別は伝票番号（slip_number）で行う。
"""

import time

import pandas as pd
import streamlit as st

from config import (
    GENERIC_ERROR_MESSAGE, MATERIAL_LIST, SCORE_MAX, SCORE_MIN, SHEET_TYPE_LIST, TYPE_LIST,
    log_error,
)
from database import (
    delete_evaluation, delete_many, merge_clinic_name, restore_evaluations,
    update_evaluation, update_many,
)

# 管理テーブルに表示するカラム順
EDIT_COLUMNS = [
    "id", "completion_date", "clinic_name", "slip_number", "sheet_type",
    "restoration_type", "material", "tooth_position", "contact", "bite", "fit",
    "comments",
]

EDITOR_KEY = "bulk_edit_editor"

# 画面表示用に付与しただけのカラム（DBへ書き戻してはいけない）
DISPLAY_ONLY_COLUMNS = {"✅ 選択"}


# ==========================================
# 検索 & CSV
# ==========================================
def _render_search(df):
    with st.container(border=True):
        col_s1, col_s2, col_s3 = st.columns([2, 1, 1])
        search_query = col_s1.text_input(
            "検索", placeholder="🔍 伝票番号・医院名で検索...", label_visibility="collapsed")
        col_s2.button("🔍 検索", type="primary", use_container_width=True)
        col_s3.download_button(
            "📥 CSVダウンロード", df.to_csv(index=False).encode("utf-8-sig"),
            "evaluations.csv", "text/csv", use_container_width=True)

    if not search_query:
        return df

    # regex=False：入力をそのままの文字列として扱う（正規表現の誤爆・過負荷を防ぐ）
    matched = (
        df["slip_number"].astype(str).str.contains(search_query, na=False, regex=False)
        | df["clinic_name"].astype(str).str.contains(search_query, na=False, regex=False)
    )
    return df[matched]


# ==========================================
# 一括編集テーブル
# ==========================================
def _render_editor(df_for_edit):
    return st.data_editor(
        df_for_edit,
        use_container_width=True, hide_index=True, key=EDITOR_KEY, disabled=["id"],
        column_config={
            "✅ 選択": st.column_config.CheckboxColumn("✅ 選択", default=False),
            "id": st.column_config.NumberColumn("ID", width="small"),
            "completion_date": st.column_config.DateColumn("📅 完成日"),
            "clinic_name": st.column_config.TextColumn("🏥 医院名", required=True),
            "slip_number": st.column_config.TextColumn("📝 伝票番号", required=True),
            "sheet_type": st.column_config.SelectboxColumn("📄 シート種別", options=SHEET_TYPE_LIST),
            "restoration_type": st.column_config.SelectboxColumn("🦷 種別", options=TYPE_LIST),
            "material": st.column_config.SelectboxColumn("💎 材料", options=MATERIAL_LIST),
            "tooth_position": st.column_config.TextColumn("📍 部位"),
            "contact": st.column_config.NumberColumn(
                "コンタクト", min_value=SCORE_MIN, max_value=SCORE_MAX),
            "bite": st.column_config.NumberColumn(
                "バイト", min_value=SCORE_MIN, max_value=SCORE_MAX),
            "fit": st.column_config.NumberColumn(
                "適合", min_value=SCORE_MIN, max_value=SCORE_MAX),
            "comments": st.column_config.TextColumn("💬 コメント"),
        },
        height=500,
    )


def _render_bulk_actions(selected_rows):
    st.markdown(f"**☑️ 選択した {len(selected_rows)} 件のデータに対する操作**")
    with st.container(border=True):
        bc1, bc2, bc3 = st.columns(3)
        b_sheet = bc1.selectbox("📄 シート種別を一括変更", ["変更しない"] + SHEET_TYPE_LIST, key="b4_sh")
        b_type = bc2.selectbox("🦷 種別を一括変更", ["変更しない"] + TYPE_LIST, key="b4_ty")
        b_mat = bc3.selectbox("💎 材料を一括変更", ["変更しない"] + MATERIAL_LIST, key="b4_ma")

        btn_c1, btn_c2 = st.columns(2)

        if btn_c1.button("🚀 チェックした項目を一括更新（DB保存）", type="primary", use_container_width=True):
            update_data = {}
            if b_sheet != "変更しない":
                update_data["sheet_type"] = b_sheet
            if b_type != "変更しない":
                update_data["restoration_type"] = b_type
            if b_mat != "変更しない":
                update_data["material"] = b_mat

            if update_data:
                with st.spinner("一括更新中..."):
                    update_many(selected_rows["id"].tolist(), update_data)
                st.success("一括更新が完了しました！画面を再読み込みします。")
                time.sleep(1.5)
                st.rerun()
            else:
                st.warning("変更する項目を選んでください。")

        if btn_c2.button("🗑️ 選択したデータを一括削除", use_container_width=True):
            st.session_state.confirm_bulk_del = True

    if st.session_state.get("confirm_bulk_del", False):
        st.error(f"⚠️ 本当に選択した {len(selected_rows)} 件のデータを完全に削除しますか？ この操作は元に戻せません。")
        del_c1, del_c2 = st.columns(2)
        if del_c1.button("✅ はい、完全に削除します", type="primary", use_container_width=True):
            with st.spinner("データベースから削除中..."):
                delete_many(selected_rows["id"].tolist())
            st.session_state.confirm_bulk_del = False
            st.success("一括削除が完了しました！画面を再読み込みします。")
            time.sleep(1.5)
            st.rerun()
        if del_c2.button("❌ キャンセル", use_container_width=True):
            st.session_state.confirm_bulk_del = False
            st.rerun()


def _save_manual_edits(df_for_edit):
    """data_editor でセルを直接書き換えた内容をDBへ反映する。"""
    changes = st.session_state[EDITOR_KEY].get("edited_rows", {})
    if not changes:
        st.warning("セルが直接変更されたデータはありません。")
        return

    applied = 0
    with st.spinner("データベースを更新中..."):
        for row_idx, col_changes in changes.items():
            row_id = int(df_for_edit.iloc[row_idx]["id"])
            update_data = {}
            for col_name, new_val in col_changes.items():
                # 表示専用カラムはDBへ書き戻さない
                if col_name in DISPLAY_ONLY_COLUMNS:
                    continue
                if col_name == "completion_date" and new_val is not None:
                    update_data[col_name] = str(new_val)[:10]
                else:
                    update_data[col_name] = new_val
            if update_data:
                update_evaluation(row_id, update_data)
                applied += 1

    if applied == 0:
        st.warning("保存できる変更がありませんでした。")
        return

    st.success("🎉 編集内容を更新しました！画面を再読み込みします。")
    time.sleep(1.5)
    st.rerun()


# ==========================================
# メンテナンス機能
# ==========================================
def _render_clinic_merge(df):
    with st.expander("🏥 医院名の名寄せ・統合（一括置換）", expanded=False):
        st.info("表記揺れ（例：「田中」「田中歯科」）を正しい医院名（例：「田中歯科医院」）に一括で統合します。")
        all_clinics = sorted(list(df["clinic_name"].dropna().unique()))

        m_col1, m_col2 = st.columns(2)
        old_name = m_col1.selectbox(
            "変更対象の医院名（誤表記・略称）", ["選択してください"] + all_clinics, key="merge_old")
        new_name = m_col2.selectbox(
            "統合先の正規医院名", ["選択してください"] + all_clinics, key="merge_new")

        if st.button("⚠️ 指定した医院名を統合する", type="primary"):
            if old_name == "選択してください" or new_name == "選択してください":
                st.warning("変更対象と統合先の両方を選択してください。")
            elif old_name == new_name:
                st.warning("変更対象と統合先が同じです。")
            else:
                with st.spinner("医院名を統合中..."):
                    merge_clinic_name(old_name, new_name)
                st.success(f"🎉 「{old_name}」を「{new_name}」に統合しました！画面を再読み込みします。")
                time.sleep(1.5)
                st.rerun()


def _render_individual_delete(df):
    with st.expander("🗑️ データの一括削除（取り扱い注意）", expanded=False):
        st.warning("選択したデータをDBから完全に消去します。")
        selected_ids = [
            row["id"] for _, row in df.iterrows()
            if st.checkbox(
                f"ID:{row['id']} | {row['clinic_name']} - 伝票番号:{row['slip_number']}",
                key=f"del_{row['id']}")
        ]
        if selected_ids and st.button(f"⚠️ 選択した {len(selected_ids)} 件のデータを完全に削除する"):
            for tid in selected_ids:
                delete_evaluation(tid)
            st.success("削除完了しました！")
            time.sleep(1)
            st.rerun()


def _render_csv_restore():
    with st.expander("🚑 万が一のデータ復旧 (CSVから一括インポート)", expanded=False):
        st.info("過去にダウンロードしたバックアップ用のCSVファイルをアップロードして、データを一括復元します。")
        st.caption("💡 古いCSVに患者名・画像URLの列が含まれていても、それらは復元されません。")
        restore_file = st.file_uploader("復旧用CSVファイルを選択", type=["csv"], key="restore_csv")

        if restore_file and st.button("⚠️ CSVからデータを一括復元する", type="primary"):
            try:
                df_restore = pd.read_csv(restore_file)
                records = df_restore.to_dict(orient="records")

                with st.spinner("データをデータベースに復元中..."):
                    restore_evaluations(records)

                st.success(f"🎉 {len(records)} 件のデータを無事に復元しました！画面を再読み込みします。")
                time.sleep(2)
                st.rerun()
            except Exception as e:
                log_error("CSV復元エラー", e)
                st.error(GENERIC_ERROR_MESSAGE)


# ==========================================
# エントリーポイント
# ==========================================
def render(global_df):
    st.markdown("### 📋 保存済みデータの管理・編集")
    if global_df.empty:
        st.info("保存されたデータはまだありません。")
        return

    df = _render_search(global_df.copy())

    st.markdown("---")
    st.markdown("#### 📝 データの一括編集・削除")
    st.info("💡 操作方法：左端のチェックボックスにチェックを入れると、下部の専用パネルから複数データを一気に変更・削除できます。")

    df_for_edit = df[[c for c in EDIT_COLUMNS if c in df.columns]].copy()
    df_for_edit.insert(0, "✅ 選択", False)

    edited_df = _render_editor(df_for_edit)

    selected_rows = edited_df[edited_df["✅ 選択"] == True]
    if len(selected_rows) > 0:
        _render_bulk_actions(selected_rows)

    st.markdown("<br>", unsafe_allow_html=True)

    if st.button("💾 手動での直接編集内容を保存", type="primary"):
        _save_manual_edits(df_for_edit)

    st.markdown("---")
    _render_clinic_merge(df)

    st.markdown("---")
    _render_individual_delete(df)

    st.markdown("---")
    _render_csv_restore()
