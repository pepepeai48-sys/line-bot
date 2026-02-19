"""
Discord通知サービス - トドロミグラウンド専用
"""

import requests
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

DOW_JP = ["月", "火", "水", "木", "金", "土", "日"]


class DiscordService:
    def __init__(self, webhook_url: str = None):
        self.webhook_url = webhook_url
        self.enabled = bool(webhook_url)

    def _send(self, payload: dict):
        if not self.enabled:
            logger.info("Discord無効（DISCORD_WEBHOOK_URL未設定）")
            return
        try:
            resp = requests.post(self.webhook_url, json=payload, timeout=10)
            resp.raise_for_status()
        except Exception as e:
            logger.error(f"Discord送信エラー: {e}")

    def _get_dow(self, date_str: str) -> str:
        try:
            d = datetime.strptime(date_str, "%Y-%m-%d")
            return DOW_JP[d.weekday()]
        except Exception:
            return ""

    def notify_new_reservation(self, parsed: dict, fee: dict, row_num: int):
        """新規予約通知"""
        date_str = parsed.get("date", "")
        dow = self._get_dow(date_str)
        day_type = "🟡 土日祝料金" if fee.get("is_weekend") else "🔵 平日料金"

        embed = {
            "title": "✅ 新規予約",
            "color": 0x2ECC71,
            "fields": [
                {
                    "name": "📅 日時",
                    "value": f"{date_str}（{dow}） {parsed.get('start_time')}〜{parsed.get('end_time')}",
                    "inline": False
                },
                {
                    "name": "🏟️ グラウンド",
                    "value": parsed.get("court", "人工芝"),
                    "inline": True
                },
                {
                    "name": "👤 お名前",
                    "value": parsed.get("name", "未記入"),
                    "inline": True
                },
                {
                    "name": "📞 連絡先",
                    "value": parsed.get("phone", "未記入"),
                    "inline": True
                },
                {
                    "name": "👥 利用者区分",
                    "value": fee.get("category_label", "一般"),
                    "inline": True
                },
                {
                    "name": "⏱️ 利用時間",
                    "value": f"{fee.get('hours', 2)}時間",
                    "inline": True
                },
                {
                    "name": "💰 料金",
                    "value": f"¥{fee.get('total', 0):,}\n（{fee.get('rate_per_hour', 0):,}円/h × {fee.get('hours', 2)}h）\n{day_type}",
                    "inline": True
                },
            ],
            "footer": {
                "text": f"台帳 行{row_num} | 支払い：前払い（請求書） | {datetime.now().strftime('%Y-%m-%d %H:%M')}"
            }
        }

        if parsed.get("notes"):
            embed["fields"].append({"name": "📝 備考", "value": parsed["notes"], "inline": False})

        self._send({"embeds": [embed]})

    def notify_cancel_request(self, raw_text: str):
        """キャンセル申請通知"""
        embed = {
            "title": "⚠️ キャンセル申請",
            "color": 0xE74C3C,
            "description": raw_text,
            "footer": {"text": datetime.now().strftime("%Y-%m-%d %H:%M")}
        }
        self._send({"embeds": [embed]})

    def notify_conflict(self, parsed: dict):
        """重複予約通知"""
        date_str = parsed.get("date", "")
        dow = self._get_dow(date_str)
        embed = {
            "title": "🔴 重複予約リクエスト",
            "color": 0xF39C12,
            "description": (
                f"**{date_str}（{dow}） {parsed.get('start_time')}〜{parsed.get('end_time')}**\n"
                f"グラウンド：{parsed.get('court', '人工芝')}\n"
                f"申請者：{parsed.get('name', '未記入')} / {parsed.get('phone', '未記入')}"
            ),
            "footer": {"text": "すでに予約済みのため自動でブロックしました"}
        }
        self._send({"embeds": [embed]})

    def notify_daily_summary(self, date_str: str, reservations: list, total_fee: int):
        """日次サマリー通知"""
        dow = self._get_dow(date_str)
        embed = {
            "title": f"📊 本日の予約サマリー　{date_str}（{dow}）",
            "color": 0x3498DB,
            "fields": [
                {"name": "予約件数", "value": f"{len(reservations)}件", "inline": True},
                {"name": "売上合計", "value": f"¥{total_fee:,}", "inline": True},
            ],
            "footer": {"text": "トドロミグラウンド 自動集計"}
        }
        if reservations:
            lines = []
            for r in reservations:
                lines.append(f"・{r['time']}　{r['name']}様　[{r['court']}]　¥{r.get('fee', '?')}")
            embed["fields"].append({
                "name": "予約一覧",
                "value": "\n".join(lines) or "なし",
                "inline": False
            })
        self._send({"embeds": [embed]})
