"""
予約情報パーサー
テキスト・画像からClaude APIを使って予約情報を抽出する
トドロミグラウンド専用設定
"""

import anthropic
import base64
import json
import re
from datetime import datetime, date
import logging

logger = logging.getLogger(__name__)


class ReservationParser:
    def __init__(self, api_key: str):
        self.client = anthropic.Anthropic(api_key=api_key)
        self.model = "claude-opus-4-6"

        self.system_prompt = """
あなたはトドロミグラウンド（大阪）の予約管理AIです。
ユーザーのメッセージや画像から予約情報を抽出してください。

【グラウンド情報】
コート種類: 人工芝 / 天然芝（どちらも同一料金）
予約単位: 2時間単位（例：9:00〜11:00、11:00〜13:00）

【料金体系】
利用者区分:
- 小学生: 平日6,000円/h、土日祝7,000円/h
- 中・高校生: 平日7,000円/h、土日祝8,000円/h
- 一般: 平日12,000円/h、土日祝13,000円/h
※長期休暇中の平日は土日祝料金

以下のJSON形式のみで返答してください（余計なテキスト不要）：
{
  "is_reservation": true/false,
  "date": "YYYY-MM-DD",
  "start_time": "HH:MM",
  "end_time": "HH:MM",
  "hours": 2,
  "court": "人工芝" or "天然芝",
  "category": "elementary" or "middle_high" or "general",
  "category_label": "小学生" or "中・高校生" or "一般",
  "is_weekend": true/false,
  "name": "氏名",
  "phone": "電話番号",
  "email": "メールアドレス",
  "team_name": "チーム名（あれば）",
  "num_people": 人数（数字）,
  "notes": "その他の要望",
  "confidence": 0.0〜1.0
}

ルール：
- is_reservation: 予約・使用希望ならtrue、雑談・問い合わせはfalse
- date: 今日を基準に具体的な日付に変換（「今週の土曜」→「2025-05-24」など）
- hours: 最低2時間、2時間単位（3時間なら4時間に切り上げ）
- end_timeがなければstart_timeから2時間後を設定
- court: 記載なければ"人工芝"
- category: 記載なければ"general"
- is_weekend: 土日祝ならtrue（土=土曜、日=日曜）
- confidence: 日時・氏名がそろっていれば0.9以上
"""

    def parse_text(self, text: str) -> dict:
        """テキストメッセージから予約情報を抽出"""
        today = date.today().strftime("%Y-%m-%d")
        weekday = date.today().strftime("%A")

        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=600,
                system=self.system_prompt,
                messages=[{
                    "role": "user",
                    "content": f"今日の日付: {today}（{weekday}）\n\nメッセージ: {text}"
                }]
            )
            return self._parse_response(response.content[0].text)
        except Exception as e:
            logger.error(f"テキスト解析エラー: {e}")
            return {"is_reservation": False, "error": str(e)}

    def parse_image(self, image_bytes: bytes) -> dict:
        """画像から予約情報を抽出"""
        today = date.today().strftime("%Y-%m-%d")
        b64 = base64.standard_b64encode(image_bytes).decode("utf-8")

        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=600,
                system=self.system_prompt,
                messages=[{
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {"type": "base64", "media_type": "image/jpeg", "data": b64}
                        },
                        {
                            "type": "text",
                            "text": f"今日の日付: {today}\n\nこの画像から予約情報を抽出してください。"
                        }
                    ]
                }]
            )
            result = self._parse_response(response.content[0].text)
            result["source"] = "image"
            return result
        except Exception as e:
            logger.error(f"画像解析エラー: {e}")
            return {"is_reservation": False, "error": str(e)}

    def _parse_response(self, text: str) -> dict:
        text = re.sub(r"```json\s*", "", text)
        text = re.sub(r"```\s*", "", text)
        text = text.strip()

        try:
            data = json.loads(text)
            # hours を2時間単位に補正
            if data.get("is_reservation"):
                h = data.get("hours", 2)
                if h < 2:
                    h = 2
                elif h % 2 != 0:
                    h = h + 1  # 切り上げ
                data["hours"] = h

                # end_time が未設定なら計算
                if data.get("start_time") and not data.get("end_time"):
                    s = datetime.strptime(data["start_time"], "%H:%M")
                    from datetime import timedelta
                    e = s + timedelta(hours=h)
                    data["end_time"] = e.strftime("%H:%M")
            return data
        except json.JSONDecodeError as e:
            logger.error(f"JSON解析失敗: {text[:200]}")
            return {"is_reservation": False, "error": f"JSON parse error: {e}"}
