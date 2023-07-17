import re
from typing import Any
from app import models
from app import config
from app.client import SpreadSheetClient
from app.config import PASS_VIEW, SUBMIT_VIEW, SEARCH_VIEW, settings
from slack_bolt.async_app import AsyncApp
from app.db import create_log_file, fetch_db, upload_logs

from app.services import user_content_service
from app.utils import print_log


slack = AsyncApp(token=settings.BOT_TOKEN)


@slack.event("message")
async def handle_message_event(ack, body) -> None:
    await ack()


def _start_log(body: dict[str, str], type: str) -> str:
    return f"{body.get('user_id')}({body.get('channel_id')}) 님이 {type} 를 시작합니다."


@slack.command("/제출")
async def submit_command(ack, body, logger, say, client) -> None:
    print_log(_start_log(body, "submit"))
    await ack()
    await user_content_service.open_submit_modal(body, client, SUBMIT_VIEW)


@slack.view(SUBMIT_VIEW)
async def submit_view(ack, body, client, view, logger, say) -> None:
    await ack()
    user_id = body["user"]["id"]
    channel_id = view["private_metadata"]

    try:
        user = user_content_service.get_user(user_id, channel_id)
        content = await user_content_service.create_submit_content(
            ack, body, view, user
        )
        text = user_content_service.get_chat_message(content)
        await client.chat_postMessage(
            channel=channel_id,
            blocks=[
                {
                    "type": "actions",
                    "elements": [
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "소개 보기"},
                            "action_id": "intro_modal",
                            "value": user.user_id,
                        },
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "이전 작성글 보기"},
                            "action_id": "contents_modal",
                            "value": user.user_id,
                        },
                    ],
                },
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": text,
                    },
                },
            ],
        )
    except Exception as e:
        message = f"{user.name}({user.channel_name}) 님의 제출이 실패하였습니다."
        print_log(message, str(e))
        return None


@slack.action("intro_modal")
async def open_intro_modal(ack, body, client, view, logger):
    await ack()

    user_body = {"user_id": body.get("user_id")}
    print_log(_start_log(user_body, "intro_modal"))

    user_id = body["actions"][0]["value"]
    user = user_content_service.get_user_not_valid(user_id)

    await client.views_open(
        trigger_id=body["trigger_id"],
        view={
            "type": "modal",
            "title": {"type": "plain_text", "text": f"{user.name}님의 소개"},
            "close": {"type": "plain_text", "text": "닫기"},
            "blocks": [
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": user.intro.replace("\\n", "\n")},
                }
            ],
        },
    )


@slack.action("contents_modal")
async def contents_modal(ack, body, client, view, logger):
    await ack()

    user_body = {"user_id": body.get("user_id")}
    print_log(_start_log(user_body, "contents_modal"))

    user_id = body["actions"][0]["value"]
    user = user_content_service.get_user_not_valid(user_id)

    await client.views_open(
        trigger_id=body["trigger_id"],
        view={
            "type": "modal",
            "title": {"type": "plain_text", "text": f"{user.name}님의 작성글"},
            "close": {"type": "plain_text", "text": "닫기"},
            "blocks": _fetch_blocks(user.contents),
        },
    )


@slack.command("/패스")
async def pass_command(ack, body, logger, say, client) -> None:
    print_log(_start_log(body, "pass"))
    await ack()
    await user_content_service.open_pass_modal(body, client, PASS_VIEW)


@slack.view(PASS_VIEW)
async def pass_view(ack, body, client, view, logger, say) -> None:
    await ack()
    user_id = body["user"]["id"]
    channel_id = view["private_metadata"]

    try:
        user = user_content_service.get_user(user_id, channel_id)
        content = await user_content_service.create_pass_content(ack, body, view, user)
        await client.chat_postMessage(
            channel=channel_id, text=user_content_service.get_chat_message(content)
        )
    except Exception as e:
        message = f"{user.name}({user.channel_name}) 님의 패스가 실패하였습니다."
        print_log(message, str(e))
        return None


@slack.command("/제출내역")
async def history_command(ack, body, logger, say, client) -> None:
    print_log(_start_log(body, "history"))
    await ack()
    submit_history = user_content_service.get_submit_history(body["user_id"])

    user = user_content_service.get_user_not_valid(body["user_id"])
    round, due_date = user.get_due_date()
    guide_message = f"\n*현재 회차는 {round}회차, 마감일은 {due_date} 이에요."

    await client.views_open(
        trigger_id=body["trigger_id"],
        view={
            "type": "modal",
            "title": {"type": "plain_text", "text": f"{user.name}님의 제출 내역"},
            "blocks": [
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": submit_history},
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


@slack.command("/예치금")
async def get_deposit(ack, body, logger, say, client) -> None:
    print_log(_start_log(body, "deposit"))
    await ack()

    user = user_content_service.get_user_not_valid(body["user_id"])

    await client.views_open(
        trigger_id=body["trigger_id"],
        view={
            "type": "modal",
            "title": {"type": "plain_text", "text": f"{user.name}님의 예치금 현황"},
            "blocks": [
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"현재 남은 예치금은 {format(user.deposit, ',d')} 원 입니다.\n\n*<{settings.DEPOSIT_SHEETS_URL}|{'예치금 현황 자세히 확인하기'}>*",
                    },
                },
            ],
        },
    )


@slack.command("/관리자")
async def admin_command(ack, body, logger, say, client) -> None:
    # TODO: 추후 관리자 메뉴 추가
    await ack()
    try:
        user_content_service.validate_admin_user(body["user_id"])
        sheet_client = SpreadSheetClient()
        sheet_client.push_backup()
        fetch_db(sheet_client)
        upload_logs(sheet_client)
        create_log_file(sheet_client)
        await client.chat_postMessage(channel=body["user_id"], text="DB sync 완료")
    except ValueError as e:
        await client.chat_postMessage(channel=body["user_id"], text=str(e))


@slack.command("/검색")
async def search_command(ack, body, logger, say, client) -> None:
    print_log(_start_log(body, "serach"))
    await ack()
    await user_content_service.open_search_modal(body, client, PASS_VIEW)


@slack.view("submit_search")
async def submit_search(ack, body, client, view, logger):
    # TODO: 로그 리팩터링하기
    user_body = {"user_id": body.get("user", {}).get("id")}
    print_log(_start_log(user_body, "submit_search"))
    await ack()

    name = _get_name(body)
    category = _get_category(body)
    keyword = _get_keyword(body)

    contents = user_content_service.fetch_contents(keyword, name, category)

    await client.views_open(
        trigger_id=body["trigger_id"],
        view={
            "type": "modal",
            "callback_id": "back_to_search_view",
            "title": {"type": "plain_text", "text": f"총 {len(contents)} 개의 글이 있습니다. 🔍"},
            "submit": {"type": "plain_text", "text": "다시 찾기"},
            "blocks": _fetch_blocks(contents),
        },
    )


def _fetch_blocks(contents: list[models.Content]) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    blocks.append(
        {
            "type": "section",
            "text": {"type": "plain_text", "text": "결과는 최대 20개까지만 표시합니다."},
        },
    )
    for content in contents:
        if content.content_url:
            blocks.append({"type": "divider"})
            blocks.append(
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"*<{content.content_url}|{re.sub('<|>', '', content.title)}>*",
                    },
                    "accessory": {
                        "type": "overflow",
                        "action_id": "overflow-action",
                        "options": [
                            {
                                "text": {
                                    "type": "plain_text",
                                    "text": "👍🏼 추천(추후 도입 예정)",
                                    "emoji": True,
                                },
                                "value": "like",
                            },
                        ],
                    },
                }
            )
            tags = f"> 태그: {' '.join(content.tags.split('#'))}" if content.tags else " "
            blocks.append(
                {
                    "type": "context",
                    "elements": [
                        {"type": "mrkdwn", "text": f"> 카테고리: {content.category}"},
                        {"type": "mrkdwn", "text": tags},
                    ],
                }
            )
        if len(blocks) > 60:
            return blocks
    return blocks


@slack.view("back_to_search_view")
async def back_to_search_view(ack, body, logger, say, client) -> None:
    # TODO: 로그 리팩터링하기
    user_body = {"user_id": body.get("user", {}).get("id")}
    print_log(_start_log(user_body, "back_to_search_view"))
    await ack()
    await user_content_service.open_search_modal(body, client, PASS_VIEW)


def _get_category(body):
    category = (
        body.get("view", {})
        .get("state", {})
        .get("values", {})
        .get("category_search", {})
        .get("chosen_category", {})
        .get("selected_option", {})
        .get("value", "전체")
    )
    return category


def _get_name(body):
    name = (
        body.get("view", {})
        .get("state", {})
        .get("values", {})
        .get("author_search", {})
        .get("author_name", {})
        .get("value", "")
    )
    return name


def _get_keyword(body):
    name = (
        body.get("view", {})
        .get("state", {})
        .get("values", {})
        .get("keyword_search", {})
        .get("keyword", {})
        .get("value", "")
    )
    return name
