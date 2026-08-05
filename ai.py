import streamlit as st
import time
import json
import re
from datetime import date
import io
from PIL import Image, ImageOps, ImageEnhance
from google import genai
from google.genai import types
from config import KEY, GEMINI_MODELS

@st.cache_resource
def get_gemini_client():
    if not KEY: return None
    return genai.Client(api_key=KEY)

def call_gemini_with_fallback(prompt_text, image_part=None, ai_config=None):
    client = get_gemini_client()
    if not client: raise ValueError("GEMINI_API_KEY が設定されていません。")
    
    payload = [image_part, prompt_text] if image_part else prompt_text
    last_exception = None
    for idx, model in enumerate(GEMINI_MODELS):
        try: return client.models.generate_content(model=model, contents=payload, config=ai_config)
        except Exception as e:
            last_exception = e
            if idx < len(GEMINI_MODELS) - 1: time.sleep(0.5 * (idx + 1))
            else: raise last_exception
    return None

def clean_and_parse_json(text):
    clean_text = text.strip()
    clean_text = re.sub(r"^```(?:json)?\n?", "", clean_text)
    clean_text = re.sub(r"\n?```$", "", clean_text)
    return json.loads(clean_text)

def process_single_file(f, actual_idx, prompt_text, ai_config):
    try:
        if "pdf" in f.type: cp = types.Part.from_bytes(data=f.getvalue(), mime_type="application/pdf")
        else:
            img = Image.open(io.BytesIO(f.getvalue()))
            img = ImageOps.exif_transpose(img)
            img = ImageEnhance.Contrast(img).enhance(1.2)
            cp = img
        
        res = call_gemini_with_fallback(prompt_text=prompt_text, image_part=cp, ai_config=ai_config)
        if res and res.text:
            parsed = clean_and_parse_json(res.text) 
            if isinstance(parsed, dict): parsed = [parsed]
            
            for item in parsed:
                item["_f_idx"] = actual_idx
                # ブリッジ判定（※ここは後ほど修正しますが、今は構造を維持します）
                tp = str(item.get("tooth_position", ""))
                if re.search(r'\d{2,}', tp) or re.search(r'\d[-~]\d', tp) or re.search(r'\d\.\d', tp):
                    item["restoration_type"] = "ブリッジ"
                
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
