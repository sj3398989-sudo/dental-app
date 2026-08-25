"""Gemini API クライアント・フォールバック機構・シート解析処理。"""

import io
import json
import re
import time

import streamlit as st
from google import genai
from google.genai import types
from PIL import Image, ImageEnhance, ImageOps

from config import MATERIAL_LIST, TYPE_LIST, log_error

# 優先順にフォールバックするモデル
MODEL_FALLBACK_CHAIN = [
    "gemini-3.7-flash",
    "gemini-3.6-flash",
    "gemini-3.5-flash",
    "gemini-3.5-flash-lite",
]

# 1回のバッチで処理するファイル数
BATCH_SIZE = 5


def get_api_key():
    return st.secrets.get("GEMINI_API_KEY")


# ==========================================
# フォールバック付き呼び出し
# ==========================================
def call_gemini_with_fallback(contents, prm=None, ai_config=None):
    key = get_api_key()
    if not key:
        raise ValueError("GEMINI_API_KEY が設定されていません。")
    client = genai.Client(api_key=key)
    payload = [contents, prm] if prm else contents
    last_exception = None
    for idx, model in enumerate(MODEL_FALLBACK_CHAIN):
        try:
            return client.models.generate_content(model=model, contents=payload, config=ai_config)
        except Exception as e:
            last_exception = e
            if idx < len(MODEL_FALLBACK_CHAIN) - 1:
                time.sleep(0.5 * (idx + 1))
            else:
                raise last_exception
    return None


# ==========================================
# 評価シート抽出
# ==========================================
def build_sheet_extraction_prompt(clinic_list_str):
    """登録済み医院名リストを注入した抽出プロンプトを組み立てる。"""
    return (
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
        "4. 医院名の自動名寄せ: 抽出した医院名が略称や表記揺れであっても、以下の【登録医院リスト】に同一と判断できるものがあれば、リスト内の正式名称で出力してください。\n"
        "   ただし、「たなか歯科」と「田中歯科」のように表記違いの候補が存在して確信が持てない場合や、リストに該当しない新規医院の場合は、無理に変換せず読み取ったままの文字を出力してください。\n"
        f"   【登録医院リスト】: {clinic_list_str}\n"
        "5. 読み取れない・未記入項目は空文字（\"\"）にしてください。\n"
        "6. 【個人情報保護】患者名（患者氏名・カナ氏名など個人を特定する氏名）は一切読み取らず、"
        "完全に無視してください。出力にも含めず、他の項目（コメント等）にも転記しないでください。\n"
        "出力キー: clinic_name, slip_number, completion_date (YYYY-MM-DD), "
        "sheet_type, restoration_type, material, tooth_position, contact, bite, fit, comments"
    )


def build_clinic_list_str(global_df):
    """DB上の既知の医院名一覧を、プロンプト注入用の文字列にする。"""
    if global_df.empty or "clinic_name" not in global_df.columns:
        return "登録なし"
    names = sorted(list(global_df["clinic_name"].dropna().unique()))
    return ", ".join(names) if names else "登録なし"


def _file_to_content_part(f):
    """アップロードファイルを Gemini に渡せる形式に変換する。"""
    if "pdf" in f.type:
        return types.Part.from_bytes(data=f.getvalue(), mime_type="application/pdf")
    img = Image.open(io.BytesIO(f.getvalue()))
    img = ImageOps.exif_transpose(img)
    return ImageEnhance.Contrast(img).enhance(1.2)


def _apply_bridge_rule(item):
    """部位に複数歯を示す表記があればブリッジと判定する。"""
    tp = str(item.get("tooth_position", ""))
    if re.search(r"\d{2,}", tp) or re.search(r"\d[-~]\d", tp):
        item["restoration_type"] = "ブリッジ"
    return item


def extract_sheets_from_files(up_files, clinic_list_str,
                              on_status=None, on_progress=None, on_error=None):
    """アップロードされた全ファイルを BATCH_SIZE 件ずつ解析し、抽出結果のリストを返す。

    on_status(text) / on_progress(ratio) / on_error(message) は
    呼び出し側（UI）が進捗表示に使うコールバック。
    """
    prm = build_sheet_extraction_prompt(clinic_list_str)
    ai_config = types.GenerateContentConfig(temperature=0.0, response_mime_type="application/json")

    r_list = []
    total_files = len(up_files)

    for i in range(0, total_files, BATCH_SIZE):
        chunk_files = up_files[i:i + BATCH_SIZE]
        current_end = min(i + BATCH_SIZE, total_files)
        if on_status:
            on_status(f"**⏳ 処理中... {i + 1}〜{current_end}枚目 / 全{total_files}枚**")

        for idx, f in enumerate(chunk_files):
            actual_idx = i + idx
            try:
                cp = _file_to_content_part(f)
                res = call_gemini_with_fallback(cp, prm, ai_config)

                if res and res.text:
                    parsed = json.loads(res.text.strip())
                    if isinstance(parsed, dict):
                        parsed = [parsed]
                    for item in parsed:
                        item["_f_idx"] = actual_idx
                        r_list.append(_apply_bridge_rule(item))
            except Exception as e:
                # 例外の詳細はログにのみ出力し、画面には安全なメッセージを返す。
                # ファイル名は患者名を含みうるため、ログには連番のみを記録する。
                log_error(f"ファイル解析エラー ({actual_idx + 1}件目)", e)
                if on_error:
                    on_error(f"⚠️ ファイルの解析に失敗しました（{f.name}）。このファイルはスキップされます。")

        if on_progress:
            on_progress(current_end / total_files)
        time.sleep(1.0)

    return r_list


# ==========================================
# 品質データの傾向分析
# ==========================================
def build_analysis_prompt(records, total, clinic, sheet_type, material, restoration_type):
    return (
        f"【重要：必ず日本語で回答してください】\n"
        f"対象データは全{total}件です。条件（医院:{clinic}, シート種別:{sheet_type}, "
        f"材料:{material}, 種別:{restoration_type}）の傾向分析をお願いします。\n"
        "評価スコアは「3が適正」「1が弱い（緩い・低い）」「5がきついの前提で、"
        "プロの歯科技工士の視点から考察・分析を行ってください。\n"
        f"データ:\n{records}"
    )


def analyze_quality_data(records, total, clinic, sheet_type, material, restoration_type):
    """分析タブ用：絞り込み済みデータについて考察テキストを生成する。"""
    prm = build_analysis_prompt(records, total, clinic, sheet_type, material, restoration_type)
    res = call_gemini_with_fallback(prm)
    return res.text if res else None
