"""Supabase 接続・データ取得・レコードのCRUD。

個人情報保護と運用コスト削減のため、患者名（patient_name）と
画像のストレージ保存（image_url / Supabase Storage）は一切扱わない。
"""

import pandas as pd
import streamlit as st
from supabase import create_client

from config import GENERIC_ERROR_MESSAGE, log_error, safe_int

TABLE_NAME = "evaluations"

# 数値として扱うカラム
NUMERIC_COLUMNS = ["contact", "bite", "fit", "id"]

# DBへ書き込むカラム（患者名・画像URLは含めない）
RECORD_COLUMNS = (
    "clinic_name", "slip_number", "completion_date", "sheet_type", "restoration_type",
    "material", "tooth_position", "contact", "bite", "fit", "comments",
)

# 過去データに残っている可能性のあるカラム。読み込み時点で切り離し、
# 画面表示・CSV出力・AI送信のどこにも流れ込まないようにする。
LEGACY_COLUMNS = ("patient_name", "image_url")


# ==========================================
# 接続
# ==========================================
@st.cache_resource
def get_db():
    url = st.secrets.get("SUPABASE_URL")
    key = st.secrets.get("SUPABASE_KEY")
    try:
        return create_client(url, key) if url and key else None
    except Exception as e:
        log_error("データベース接続エラー", e)
        st.error(GENERIC_ERROR_MESSAGE)
        return None


# ==========================================
# 全体データの一括取得
# ==========================================
def load_all_evaluations():
    """evaluations テーブル全件を DataFrame で返す。失敗時は空の DataFrame。"""
    db = get_db()
    if not db:
        return pd.DataFrame()
    try:
        res = db.table(TABLE_NAME).select("*").order("completion_date", desc=True).execute()
        if not res.data:
            return pd.DataFrame()
        temp_df = pd.DataFrame(res.data)
        # 旧データの患者名・画像URLはアプリ内へ持ち込まない
        temp_df = temp_df.drop(
            columns=[c for c in LEGACY_COLUMNS if c in temp_df.columns], errors="ignore")
        temp_df["completion_date"] = pd.to_datetime(
            temp_df["completion_date"], errors="coerce"
        ).dt.date
        for col in NUMERIC_COLUMNS:
            if col in temp_df.columns:
                temp_df[col] = pd.to_numeric(temp_df[col], errors="coerce")
        return temp_df
    except Exception as e:
        log_error("データ読み込みエラー", e)
        st.error(GENERIC_ERROR_MESSAGE)
        return pd.DataFrame()


# ==========================================
# レコード登録
# ==========================================
def build_record(d):
    """フォーム/表の1行を DB のカラム構成に整形する。"""
    return {
        "clinic_name": d.get("clinic_name"),
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
    }


def sanitize_record(record):
    """INSERT 前に、扱わないカラム（患者名・画像URL等）と欠損値を取り除く。"""
    clean = {}
    for key, val in record.items():
        if key not in RECORD_COLUMNS:
            continue
        # CSV由来の NaN はそのまま送れないため None に寄せる
        clean[key] = None if isinstance(val, float) and val != val else val
    return clean


def save_single_evaluation(d):
    """手動登録：1件のレコードを登録する。"""
    db = get_db()
    try:
        db.table(TABLE_NAME).insert(build_record(d)).execute()
    except Exception as e:
        log_error("データベース登録エラー", e)
        st.error(GENERIC_ERROR_MESSAGE)


def insert_evaluations(records):
    """AI一括登録：複数レコードをまとめて INSERT する。"""
    db = get_db()
    if not db or not records:
        return
    try:
        db.table(TABLE_NAME).insert([sanitize_record(r) for r in records]).execute()
    except Exception as e:
        log_error("一括保存エラー", e)
        st.error(GENERIC_ERROR_MESSAGE)


def restore_evaluations(records):
    """CSV復旧：例外を呼び出し側に伝播させる INSERT。

    過去のCSVに患者名・画像URLの列が残っていても、ここで確実に取り除く。
    """
    db = get_db()
    if db and records:
        db.table(TABLE_NAME).insert([sanitize_record(r) for r in records]).execute()


# ==========================================
# レコード更新・削除
# ==========================================
def update_evaluation(row_id, update_data):
    db = get_db()
    clean = sanitize_record(update_data or {})
    if db and clean:
        db.table(TABLE_NAME).update(clean).eq("id", int(row_id)).execute()


def update_many(row_ids, update_data):
    for row_id in row_ids:
        update_evaluation(row_id, update_data)


def delete_evaluation(row_id):
    db = get_db()
    if db:
        db.table(TABLE_NAME).delete().eq("id", int(row_id)).execute()


def delete_many(row_ids):
    for row_id in row_ids:
        delete_evaluation(row_id)


def merge_clinic_name(old_name, new_name):
    """医院名の名寄せ（一括置換）。"""
    db = get_db()
    if db:
        db.table(TABLE_NAME).update({"clinic_name": new_name}).eq(
            "clinic_name", old_name
        ).execute()
