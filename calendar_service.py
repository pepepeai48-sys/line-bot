"""
Googleカレンダーサービス - トドロミグラウンド専用
"""

import os
from datetime import datetime, timedelta
from google.oauth2 import service_account
from googleapiclient.discovery import build
import logging

logger = logging.getLogger(__name__)
SCOPES = ["https://www.googleapis.com/auth/calendar"]


class CalendarService:
    def __init__(self):
        creds = service_account.Credentials.from_service_account_file(
            os.environ.get("GOOGLE_SERVICE_ACCOUNT_FILE", "service_account.json"),
            scopes=SCOPES
        )
        self.service = build("calendar", "v3", credentials=creds)
        self.calendar_id = os.environ.get("GOOGLE_CALENDAR_ID", "primary")

    def check_conflict(self, date: str, start_time: str, end_time: str, court: str) -> bool:
        try:
            start_dt = datetime.fromisoformat(f"{date}T{start_time}:00+09:00")
            end_dt = datetime.fromisoformat(f"{date}T{end_time}:00+09:00")

            events = self.service.events().list(
                calendarId=self.calendar_id,
                timeMin=start_dt.isoformat(),
                timeMax=end_dt.isoformat(),
                q=court,
                singleEvents=True
            ).execute()

            for item in events.get("items", []):
                if court in item.get("summary", ""):
                    return True
            return False
        except Exception as e:
            logger.error(f"重複チェックエラー: {e}")
            return False

    def create_event(self, parsed: dict, fee: dict) -> dict:
        date = parsed["date"]
        start_time = parsed["start_time"]
        end_time = parsed["end_time"]
        name = parsed.get("name", "未記入")
        court = parsed.get("court", "人工芝")
        phone = parsed.get("phone", "")
        notes = parsed.get("notes", "")
        category = fee.get("category_label", "一般")
        day_type = "土日祝" if fee.get("is_weekend") else "平日"

        event = {
            "summary": f"【{court}】{name}様",
            "description": (
                f"お名前: {name}\n"
                f"連絡先: {phone}\n"
                f"グラウンド: {court}\n"
                f"利用者区分: {category}\n"
                f"料金: ¥{fee['total']:,}（{fee['rate_per_hour']:,}円/h × {fee['hours']}h / {day_type}）\n"
                f"支払い: 前払い（請求書）\n"
                f"備考: {notes}"
            ),
            "start": {
                "dateTime": f"{date}T{start_time}:00+09:00",
                "timeZone": "Asia/Tokyo"
            },
            "end": {
                "dateTime": f"{date}T{end_time}:00+09:00",
                "timeZone": "Asia/Tokyo"
            },
            "colorId": "9" if court == "人工芝" else "6",  # 人工芝=青緑, 天然芝=緑
        }

        result = self.service.events().insert(
            calendarId=self.calendar_id, body=event
        ).execute()
        logger.info(f"カレンダー登録: {result['id']}")
        return result

    def get_events_for_date(self, date: str) -> list:
        start = datetime.fromisoformat(f"{date}T00:00:00+09:00")
        end = start + timedelta(days=1)
        events = self.service.events().list(
            calendarId=self.calendar_id,
            timeMin=start.isoformat(),
            timeMax=end.isoformat(),
            singleEvents=True,
            orderBy="startTime"
        ).execute()
        return events.get("items", [])
