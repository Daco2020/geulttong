from app.client import SpreadSheetClient
from app.config import settings
from app.constants import HELP_TEXT
from app.slack.services import SlackService
from app.store import Store


async def handle_mention(ack, body, say, client) -> None:
    """앱 멘션 호출 시 도움말 메시지를 전송합니다."""
    await client.chat_postEphemeral(
        channel=body["event"]["channel"],
        user=body["event"]["user"],
        text=HELP_TEXT,
    )
    await ack()


async def get_deposit(
    ack, body, say, client, user_id: str, service: SlackService
) -> None:
    """예치금을 조회합니다."""
    await ack()

    await client.views_open(
        trigger_id=body["trigger_id"],
        view={
            "type": "modal",
            "title": {"type": "plain_text", "text": f"{service.user.name}님의 예치금 현황"},
            "blocks": [
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"현재 남은 예치금은 {format(service.user.deposit, ',d')} 원 이에요.\n\n*<{settings.DEPOSIT_SHEETS_URL}|{'예치금 현황 자세히 확인하기'}>*",  # noqa E501
                    },
                },
            ],
        },
    )


async def history_command(
    ack, body, say, client, user_id: str, service: SlackService
) -> None:
    """제출 내역을 조회합니다."""
    await ack()

    round, due_date = service.user.get_due_date()
    guide_message = f"\n*현재 회차는 {round}회차, 마감일은 {due_date} 이에요."

    await client.views_open(
        trigger_id=body["trigger_id"],
        view={
            "type": "modal",
            "title": {"type": "plain_text", "text": f"{service.user.name}님의 제출 내역"},
            "blocks": [
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": service.get_submit_history()},
                },
                {
                    "type": "divider",
                },
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": guide_message},
                },
            ],
        },
    )


async def admin_command(
    ack, body, say, client, user_id: str, service: SlackService
) -> None:
    """관리자 메뉴를 조회합니다."""
    await ack()
    # TODO: 추후 관리자 메뉴 추가

    if user_id not in settings.ADMIN_IDS:
        raise PermissionError("관리자만 호출할 수 있어요. 히힛 :)")
    try:
        await client.chat_postMessage(channel=body["user_id"], text="store pull 완료")
        sheet_client = SpreadSheetClient()
        store = Store(client=sheet_client)
        store.upload("logs")
        store.backup("contents")
        store.initialize_logs()
        store.pull()
    except Exception as e:
        await client.chat_postMessage(channel=body["user_id"], text=str(e))
