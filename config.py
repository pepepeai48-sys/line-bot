"""設定ファイル読み込み"""
import os
import yaml
import logging

logger = logging.getLogger(__name__)

def load_config() -> dict:
    config_path = os.environ.get("CONFIG_PATH", "config/settings.yaml")
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)
    except FileNotFoundError:
        logger.warning(f"設定ファイルが見つかりません: {config_path}。デフォルト設定を使用します。")
        return get_default_config()

def get_default_config() -> dict:
    return {
        "ground": {
            "name": "トドロミグラウンド",
            "courts": [
                {"id": "人工芝", "name": "人工芝グラウンド"},
                {"id": "天然芝", "name": "天然芝グラウンド"}
            ]
        },
        "pricing": {
            "min_booking_hours": 2,
            "unit_hours": 2,
            "categories": {
                "elementary":  {"label": "小学生",    "weekday": 6000, "weekend": 7000},
                "middle_high": {"label": "中・高校生", "weekday": 7000, "weekend": 8000},
                "general":     {"label": "一般",      "weekday": 12000, "weekend": 13000}
            },
            "payment": {"method": "前払い（請求書）"}
        },
        "business_hours": {"open": "07:00", "close": "21:00"},
        "notifications": {"discord_enabled": True}
    }
