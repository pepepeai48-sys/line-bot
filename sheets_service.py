"""
Googleスプレッドシートサービス
トドロミグラウンド専用 予約台帳管理
"""

import os
from datetime import date, datetime
from google.oauth2 import service_account
from googleapiclient.discovery import build
import logging

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

HEADERS = [
    "予約ID", "受付日時", "利用日", "曜日", "開始時間", "終了時間",
    "グラウンド", "お名前", "連絡先", "利用者区分",
    "利用時間(h)", "単価(円/h)", "料金(円)", "平日/土日祝",
    "ステータス", "カレンダーID", "備考"
]


class SheetsService:
    def __init__(self):
        creds = service_account.Credentials.from_service_account_file(
            os.environ.get("GOOGLE_SERVICE_ACCOUNT_FILE", "service_account.json"),
            scopes=SCOPES
        )
        self.service = build("sheets", "v4", credentials=creds)
        self.spreadsheet_id = os.environ["GOOGLE_SPREADSHEET_ID"]
        self.sheet_name = os.environ.get("SHEET_NAME", "予約台帳")
        self._ensure_headers()

    def _ensure_headers(self):
        try:
            result = self.service.spreadsheets().values().get(
                spreadsheetId=self.spreadsheet_id,
                range=f"{self.sheet_name}!A1:Q1"
            ).execute()
            if not result.get("values"):
                self._write_headers()
        except Exception as e:
            logger.warning(f"ヘッダー確認エラー: {e}")

    def _write_headers(self):
        self.service.spreadsheets().values().update(
            spreadsheetId=self.spreadsheet_id,
            range=f"{self.sheet_name}!A1",
            valueInputOption="RAW",
            body={"values": [HEADERS]}
        ).execute()
        self._format_header()

    def append_reservation(self, parsed: dict, fee: dict, calendar_event_id: str) -> int:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        reservation_id = f"R{datetime.now().strftime('%Y%m%d%H%M%S')}"

        date_str = parsed.get("date", "")
        dow = self._get_dow(date_str)

        row = [
            reservation_id,
            now,
            date_str,
            dow,
            parsed.get("start_time", ""),
            parsed.get("end_time", ""),
            parsed.get("court", "人工芝"),
            parsed.get("name", ""),
            parsed.get("phone", ""),
            fee.get("category_label", "一般"),
            fee.get("hours", 2),
            fee.get("rate_per_hour", 0),
            fee.get("total", 0),
            "土日祝" if fee.get("is_weekend") else "平日",
            "確定",
            calendar_event_id,
            parsed.get("notes", "")
        ]

        result = self.service.spreadsheets().values().append(
            spreadsheetId=self.spreadsheet_id,
            range=f"{self.sheet_name}!A1",
            valueInputOption="USER_ENTERED",
            insertDataOption="INSERT_ROWS",
            body={"values": [row]}
        ).execute()

        updated_range = result["updates"]["updatedRange"]
        row_num = int(updated_range.split("!")[1].split(":")[0][1:])
        logger.info(f"スプレッドシート追記: 行{row_num} {reservation_id}")
        return row_num

    def get_today_reservations(self) -> list:
        today = date.today().strftime("%Y-%m-%d")
        result = self.service.spreadsheets().values().get(
            spreadsheetId=self.spreadsheet_id,
            range=f"{self.sheet_name}!A2:Q1000"
        ).execute()

        rows = result.get("values", [])
        reservations = []
        for row in rows:
            if len(row) > 2 and row[2] == today:
                status = row[14] if len(row) > 14 else ""
                if status != "キャンセル":
                    reservations.append({
                        "id": row[0] if row else "",
                        "date": row[2] if len(row) > 2 else "",
                        "time": f"{row[4]}〜{row[5]}" if len(row) > 5 else "",
                        "court": row[6] if len(row) > 6 else "",
                        "name": row[7] if len(row) > 7 else "",
                        "phone": row[8] if len(row) > 8 else "",
                        "category": row[9] if len(row) > 9 else "",
                        "fee": row[12] if len(row) > 12 else ""
                    })
        return sorted(reservations, key=lambda x: x.get("time", ""))

    def get_monthly_summary(self, year: int, month: int) -> dict:
        result = self.service.spreadsheets().values().get(
            spreadsheetId=self.spreadsheet_id,
            range=f"{self.sheet_name}!A2:Q1000"
        ).execute()

        rows = result.get("values", [])
        prefix = f"{year}-{month:02d}"
        total_fee = 0
        count = 0
        cancelled = 0

        for row in rows:
            if len(row) > 2 and row[2].startswith(prefix):
                status = row[14] if len(row) > 14 else ""
                if status == "キャンセル":
                    cancelled += 1
                else:
                    count += 1
                    try:
                        total_fee += int(row[12]) if len(row) > 12 else 0
                    except (ValueError, IndexError):
                        pass

        return {"year": year, "month": month, "count": count, "cancelled": cancelled, "total_fee": total_fee}

    def _get_dow(self, date_str: str) -> str:
        try:
            d = datetime.strptime(date_str, "%Y-%m-%d")
            return ["月", "火", "水", "木", "金", "土", "日"][d.weekday()]
        except Exception:
            return ""

    def _format_header(self):
        try:
            meta = self.service.spreadsheets().get(spreadsheetId=self.spreadsheet_id).execute()
            sheet_id = None
            for s in meta["sheets"]:
                if s["properties"]["title"] == self.sheet_name:
                    sheet_id = s["properties"]["sheetId"]
                    break
            if sheet_id is None:
                return
            requests = [{
                "repeatCell": {
                    "range": {"sheetId": sheet_id, "startRowIndex": 0, "endRowIndex": 1},
                    "cell": {
                        "userEnteredFormat": {
                            "backgroundColor": {"red": 0.1, "green": 0.4, "blue": 0.7},
                            "textFormat": {"bold": True, "foregroundColor": {"red": 1, "green": 1, "blue": 1}}
                        }
                    },
                    "fields": "userEnteredFormat(backgroundColor,textFormat)"
                }
            }]
            self.service.spreadsheets().batchUpdate(
                spreadsheetId=self.spreadsheet_id,
                body={"requests": requests}
            ).execute()
        except Exception as e:
            logger.warning(f"ヘッダーフォーマット失敗: {e}")
