"""
トドロミグラウンド 予約自動管理システム
LINE → AI解析 → Googleカレンダー / スプレッドシート / Discord通知
"""

import os
import logging
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, ImageMessage, TextSendMessage
from datetime import date, datetime

from .reservation_parser import ReservationParser
from .calendar_service import CalendarService
from .sheets_service import SheetsService
from .discord_service import DiscordService
from .config import load_config

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
config = load_config()

line_bot_api = LineBotApi(os.environ["LINE_CHANNEL_ACCESS_TOKEN"])
handler = WebhookHandler(os.environ["LINE_CHANNEL_SECRET"])

parser = ReservationParser(os.environ["ANTHROPIC_API_KEY"])
calendar_svc = CalendarService()
sheets_svc = SheetsService()
discord_svc = DiscordService(os.environ.get("DISCORD_WEBHOOK_URL"))


@app.route("/webhook", methods=["POST"])
def webhook():
    signature = request.headers["X-Line-Signature"]
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return "OK"


@handler.add(MessageEvent, message=TextMessage)
def handle_text(event):
    text = event.message.text

    if text.startswith("/予約一覧"):
        handle_list_command(event)
        return
    if text.startswith("/キャンセル"):
        handle_cancel_command(event, text)
        return
    if text in ["/ヘルプ", "ヘルプ", "使い方"]:
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=get_help_message()))
        return

    result = parser.parse_text(text)
    if result.get("is_reservation"):
        process_reservation(event, result)
    else:
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=get_help_message()))


@handler.add(MessageEvent, message=ImageMessage)
def handle_image(event):
    message_content = line_bot_api.get_message_content(event.message.id)
    image_bytes = b"".join(chunk for chunk in message_content.iter_content())
    result = parser.parse_image(image_bytes)
    if result.get("is_reservation"):
        process_reservation(event, result)
    else:
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="画像から予約情報を読み取れませんでした。\nテキストでご連絡ください。")
        )


def process_reservation(event, parsed: dict):
    """予約処理メイン"""
    try:
        # 必須情報チェック
        missing = []
        if not parsed.get("date"):
            missing.append("ご利用日")
        if not parsed.get("start_time"):
            missing.append("開始時間")
        if not parsed.get("name"):
            missing.append("お名前")
        if missing:
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(
                    text=f"以下の情報が不足しています。再度ご連絡ください。\n\n"
                         + "\n".join(f"・{m}" for m in missing)
                )
            )
            return

        court = parsed.get("court", "人工芝")

        # 重複チェック
        conflict = calendar_svc.check_conflict(
            parsed["date"], parsed["start_time"], parsed["end_time"], court
        )
        if conflict:
            discord_svc.notify_conflict(parsed)
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(
                    text=f"⚠️ 申し訳ございません。\n"
                         f"{parsed['date']} {parsed['start_time']}〜{parsed['end_time']}は"
                         f"すでに予約が入っております。\n別の日時でご検討ください。"
                )
            )
            return

        # 料金計算
        fee = calculate_fee(parsed)

        # カレンダー登録
        calendar_event = calendar_svc.create_event(parsed, fee)

        # スプレッドシート記録
        row = sheets_svc.append_reservation(parsed, fee, calendar_event["id"])

        # Discord通知
        discord_svc.notify_new_reservation(parsed, fee, row)

        # LINE返信
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=build_confirmation_text(parsed, fee))
        )

        logger.info(f"予約完了: {parsed['date']} {parsed.get('name')}")

    except Exception as e:
        logger.error(f"予約処理エラー: {e}", exc_info=True)
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="システムエラーが発生しました。お手数ですが直接ご連絡ください。")
        )


def calculate_fee(parsed: dict) -> dict:
    """トドロミグラウンドの料金体系で計算"""
    cfg = config["pricing"]
    hours = parsed.get("hours", 2)
    category = parsed.get("category", "general")
    is_weekend = parsed.get("is_weekend", False)

    cat_cfg = cfg["categories"].get(category, cfg["categories"]["general"])
    rate_per_hour = cat_cfg["weekend"] if is_weekend else cat_cfg["weekday"]
    total = rate_per_hour * hours

    return {
        "category": category,
        "category_label": parsed.get("category_label", cat_cfg["label"]),
        "rate_per_hour": rate_per_hour,
        "hours": hours,
        "total": int(total),
        "is_weekend": is_weekend,
        "payment_method": cfg["payment"]["method"]
    }


def build_confirmation_text(parsed: dict, fee: dict) -> str:
    date_str = parsed.get("date", "")
    dow = get_japanese_dow(date_str)
    return (
        f"✅ 予約を受け付けました！\n\n"
        f"📅 {date_str}（{dow}） {parsed.get('start_time')}〜{parsed.get('end_time')}\n"
        f"🏟️ グラウンド：{parsed.get('court', '人工芝')}\n"
        f"👤 お名前：{parsed.get('name', '未記入')}\n"
        f"📞 連絡先：{parsed.get('phone', '未記入')}\n"
        f"👥 区分：{fee['category_label']}\n"
        f"⏱️ 利用時間：{fee['hours']}時間\n"
        f"💰 料金：¥{fee['total']:,}（{fee['payment_method']}）\n\n"
        f"後ほど請求書をお送りします。\nご利用ありがとうございます🙏"
    )


def get_japanese_dow(date_str: str) -> str:
    try:
        d = datetime.strptime(date_str, "%Y-%m-%d")
        return ["月", "火", "水", "木", "金", "土", "日"][d.weekday()]
    except Exception:
        return ""


def handle_list_command(event):
    reservations = sheets_svc.get_today_reservations()
    today = date.today().strftime("%Y-%m-%d")
    if not reservations:
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=f"本日（{today}）の予約はありません。")
        )
        return
    text = f"📋 本日の予約一覧（{today}）\n\n"
    for r in reservations:
        text += f"・{r['time']} {r['name']}様 [{r['court']}]\n"
    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=text))


def handle_cancel_command(event, text):
    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text="キャンセルのご連絡ありがとうございます。管理者が確認の上、折り返しご連絡します。")
    )
    discord_svc.notify_cancel_request(text)


def get_help_message():
    return (
        "トドロミグラウンド予約窓口です。\n\n"
        "【予約方法】\n"
        "以下をテキストで送ってください：\n"
        "・ご利用日\n"
        "・時間（2時間単位）\n"
        "・グラウンド種別（人工芝 or 天然芝）\n"
        "・お名前\n"
        "・連絡先（電話番号）\n"
        "・利用者区分（小学生 / 中高生 / 一般）\n\n"
        "【例】\n"
        "6月7日 9時〜11時、人工芝、田中太郎、\n"
        "090-1234-5678、一般\n\n"
        "【管理者コマンド】\n"
        "/予約一覧 → 本日の予約確認\n"
        "/キャンセル [日付] [名前] → キャンセル申請"
    )


if __name__ == "__main__":
    app.run(debug=True, port=5000)
