import streamlit as st
import time
import re
from datetime import date
import io
from PIL import Image, ImageOps, ImageEnhance
from google import genai
from google.genai import types
from pydantic import BaseModel, Field
from config import KEY, GEMINI_MODELS

# ★ 厳密なJSON Schemaの定義 (AIはこの型の通りにしか返答できなくなる)
class EvaluationResult(BaseModel):
    clinic_name: str = Field(description="医院名")
    patient_name: str = Field(description="患者名")
    slip_number: str = Field(description="伝票番号")
    raw_completion_date: str = Field(description="完了日(西暦変換せず紙の表記まま)")
    sheet_type: str = Field(description="シート種別(IOSまたはセパレートレス模型)")
    restoration_type: str = Field(description="補綴物種別")
    material: str = Field(description="材料")
    tooth_position: str = Field(description="歯番・部位(書かれた数字や記号)")
    contact: int = Field(description="コンタクト評価スコア", ge=1, le=5)
    bite: int = Field(description="バイト評価スコア", ge=1, le=5)
    fit: int = Field(description="適合評価スコア", ge=1, le=5)
    comments: str = Field(description="コメント")

class EvaluationList(BaseModel):
    evaluations: list[EvaluationResult]

@st.cache_resource
def get_gemini_client():
    if not KEY: return None
    return genai.Client(api_key=KEY)

def process_single_file(f, actual_idx, prompt_text):
    try:
        if "pdf" in f.type: cp = types.Part.from_bytes(data=f.getvalue(), mime_type="application/pdf")
        else:
            img = Image.open(io.BytesIO(f.getvalue()))
            img = ImageOps.exif_transpose(img)
            img = ImageEnhance.Contrast(img).enhance(1.2)
            cp = img
        
        client = get_gemini_client()
        if not client: raise ValueError("GEMINI_API_KEY が未設定です")
        
        # ★ AIにSchemaを強制
        ai_config = types.GenerateContentConfig(
            temperature=0.0, 
            response_mime_type="application/json",
            response_schema=EvaluationList
        )
        
        res = None
        for idx, model in enumerate(GEMINI_MODELS):
            try:
                res = client.models.generate_content(model=model, contents=[cp, prompt_text], config=ai_config)
                break
            except Exception as e:
                if idx == len(GEMINI_MODELS) - 1: raise e
                time.sleep(0.5)

        if res and res.text:
            # Pydanticを使って受け取ったJSONを安全にパース・検証
            validated_data = EvaluationList.model_validate_json(res.text)
            parsed = [item.model_dump() for item in validated_data.evaluations]
            
            for item in parsed:
                item["_f_idx"] = actual_idx
                
                # 日付変換
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
    except Exception as e: return {"error": f"ファイル解析エラー ({f.name}): {e}"}
    return None
