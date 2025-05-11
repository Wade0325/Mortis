# backend/app/services/config_service.py
import json
import os
from typing import Dict, List, Optional, Any
CONFIG_FILE_PATH = "config.json" # Relative to backend directory root
# 從原專案 config.py 移植並調整以下常量和函式
SUPPORTED_PROVIDERS = ["Google"] # 目前只專注 Google 可用功能
API_KEY_FIELDS = {"Google": "google_api_key"}
AVAILABLE_MODELS_FIELD = "available_models"
SELECTED_MODELS_FIELD = "selected_models"
PROMPT_FIELD = "prompt"
# 預設的 Google 模型 (如果設定檔中沒有)
DEFAULT_GOOGLE_AVAILABLE_MODELS = [
    "gemini-1.5-flash-latest", # 範例, 請根據實際 Gemini 可用模型調整
    "gemini-1.0-pro",
    "gemini-pro-vision" # 如果也想測試 vision
]
def _load_or_create_config() -> Dict[str, Any]:
    default_structure = {
        "api_key": {API_KEY_FIELDS["Google"]: ""},
        AVAILABLE_MODELS_FIELD: {"Google": DEFAULT_GOOGLE_AVAILABLE_MODELS},
        PROMPT_FIELD: 
        "請將音訊檔案轉錄成日文，使用 SRT (SubRip Text) 字幕格式回覆我，只要給我SRT格式以及轉錄內容，不要給我其他文字",
        SELECTED_MODELS_FIELD: {"Google": DEFAULT_GOOGLE_AVAILABLE_MODELS[0] if DEFAULT_GOOGLE_AVAILABLE_MODELS else None}
    }
    if not os.path.exists(CONFIG_FILE_PATH):
        with open(CONFIG_FILE_PATH, 'w', encoding='utf-8') as f:
            json.dump(default_structure, f, indent=2, ensure_ascii=False)
        return default_structure
    try:
        with open(CONFIG_FILE_PATH, 'r', encoding='utf-8') as f:
            config_data = json.load(f)
        # 基本驗證與合併缺失鍵
        updated = False
        for key, value in default_structure.items():
            if key not in config_data:
                config_data[key] = value
                updated = True
            elif isinstance(value, dict) and isinstance(config_data[key], dict):
                for sub_key, sub_value in value.items():
                    if sub_key not in config_data[key]:
                        config_data[key][sub_key] = sub_value
                        updated = True
                    elif isinstance(sub_value, dict) and isinstance(config_data[key][sub_key], dict): # For nested dict like 'api_key'
                         for provider_key, provider_val in sub_value.items():
                             if provider_key not in config_data[key][sub_key]:
                                 config_data[key][sub_key][provider_key] = provider_val
                                 updated = True
        # Ensure Google models list exists
        if AVAILABLE_MODELS_FIELD not in config_data or "Google" not in config_data[AVAILABLE_MODELS_FIELD]:
            config_data.setdefault(AVAILABLE_MODELS_FIELD, {})["Google"] = DEFAULT_GOOGLE_AVAILABLE_MODELS
            updated = True
        if SELECTED_MODELS_FIELD not in config_data or "Google" not in config_data[SELECTED_MODELS_FIELD]:
            config_data.setdefault(SELECTED_MODELS_FIELD, {})["Google"] = DEFAULT_GOOGLE_AVAILABLE_MODELS[0] if DEFAULT_GOOGLE_AVAILABLE_MODELS else None
            updated = True
        if updated:
            with open(CONFIG_FILE_PATH, 'w', encoding='utf-8') as f:
                json.dump(config_data, f, indent=2, ensure_ascii=False)
        return config_data
    except (json.JSONDecodeError, IOError) as e:
        print(f"Error loading or creating config file: {e}. Returning default structure.")
        # If error, overwrite with default to ensure app can run
        with open(CONFIG_FILE_PATH, 'w', encoding='utf-8') as f:
            json.dump(default_structure, f, indent=2, ensure_ascii=False)
        return default_structure
def get_all_settings() -> Dict[str, Any]:
    config = _load_or_create_config()
    return {
        "google_api_key": config.get("api_key", {}).get(API_KEY_FIELDS["Google"], ""),
        "google_selected_model": config.get(SELECTED_MODELS_FIELD, {}).get("Google"),
        "google_available_models": config.get(AVAILABLE_MODELS_FIELD, {}).get("Google", []),
        "prompt": config.get(PROMPT_FIELD, "")
    }
def update_settings(
    google_api_key: Optional[str] = None,
    google_selected_model: Optional[str] = None,
    prompt: Optional[str] = None
) -> Dict[str, Any]:
    config = _load_or_create_config()
    if google_api_key is not None:
        config["api_key"][API_KEY_FIELDS["Google"]] = google_api_key
    if google_selected_model is not None:
        # Ensure model is in available list before setting? For now, just set.
        config[SELECTED_MODELS_FIELD]["Google"] = google_selected_model
    if prompt is not None:
        config[PROMPT_FIELD] = prompt
    with open(CONFIG_FILE_PATH, 'w', encoding='utf-8') as f:
        json.dump(config, f, indent=2, ensure_ascii=False)
    return get_all_settings()
# 從原專案 app.py 移植 test_api_key_model，簡化為只測 Google
# 需要 google-generativeai
import google.generativeai as genai
def test_google_api(api_key: str, model_name: str) -> Dict[str, Any]:
    if not api_key:
        return {"success": False, "message": "請提供 Google API Key。"}
    if not model_name:
        return {"success": False, "message": "請提供 Google 模型名稱。"}
    try:
        genai.configure(api_key=api_key)
        # Check if model exists by trying to get it.
        # The format for get_model might be just model_name, or "models/model_name"
        # Let's assume `model_name` is directly usable.
        # If Gemini SDK provides a list_models or check_model_availability that's better.
        # For now, trying to get it is a common pattern.
        model_to_test = genai.GenerativeModel(model_name) # This might not raise error until first call
        # Let's try a minimal call if model instantiation doesn't validate
        # response = model_to_test.generate_content("test", generation_config=genai.types.GenerationConfig(max_output_tokens=1))
        # A safer check might be to list models if API supports it and see if model_name is present
        # For simplicity, we'll assume genai.GenerativeModel(model_name) is enough or try a quick generation.
        # Let's just try to initialize. Actual API call test might be too slow for UI feedback.
        # Or, the SDK might have a specific validation method.
        # Referencing `genai.get_model(f'models/{model_name}')` from original `app.py`
        genai.get_model(f'models/{model_name}') # This seems to be the intended check
        return {"success": True, "message": f"Google API Key 和模型 '{model_name}' 測試成功！"}
    except Exception as e:
        return {"success": False, "message": f"Google API 測試失敗 (模型: {model_name}): {str(e)}"}