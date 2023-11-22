import traceback
from app.config import settings
from slack_bolt.async_app import AsyncApp
from app.logging import log_event
from loguru import logger
from slack_bolt.request import BoltRequest
from slack_bolt.response import BoltResponse
from typing import Callable, cast

from app.slack.contents import events as contents_events
from app.slack.core import events as core_events
from app.slack.repositories import SlackRepository
from app.slack.services import SlackService

app = AsyncApp(token=settings.BOT_TOKEN)


@app.middleware
async def log_event_middleware(
    req: BoltRequest, resp: BoltResponse, next: Callable
) -> None:
    """이벤트를 로그로 남깁니다."""
    body = req.body
    if body.get("command"):
        event = body.get("command")
        type = "command"
    elif body.get("type") == "view_submission":
        event = body.get("view", {}).get("callback_id")
        type = "view_submission"
    elif body.get("type") == "block_actions":
        event = body.get("actions", [{}])[0].get("action_id")
        type = "block_actions"
    elif body.get("event"):
        event = body.get("event", {}).get("type")
        type = "event"
    else:
        event = "unknown"
        type = "unknown"

    if event != "message":  # 일반 메시지는 로그를 수집하지 않는다.
        description = event_descriptions.get(str(event), "알 수 없는 이벤트")
        log_event(
            actor=req.context.user_id,
            event=event,  # type: ignore
            type=type,
            description=description,
            body=body,
        )

    req.context["event"] = event
    await next()


@app.middleware
async def inject_service_middleware(
    req: BoltRequest, resp: BoltResponse, next: Callable
) -> None:
    """서비스 객체를 주입합니다."""
    if req.context.get("event") in ["app_mention", "message"]:
        await next()
        return

    user_repo = SlackRepository()
    user = user_repo.get_user(cast(str, req.context.user_id))
    if user:
        req.context["service"] = SlackService(user_repo=user_repo, user=user)
        await next()
        return

    # 사용자 정보가 없으면 안내 문구를 전송하고 관리자에게 알립니다.
    await app.client.chat_postEphemeral(
        channel=cast(str, req.context.channel_id),
        user=cast(str, req.context.user_id),
        text=f"🥲 아직 사용자 정보가 없어요...\
            \n👉🏼 <#{settings.SUPPORT_CHANNEL}> 채널로 요청해주시면 빠르게 도와드릴게요!",
    )
    message = f"🥲 사용자 정보를 추가해주세요. 👉🏼 {req.context.user_id=}"
    await app.client.chat_postMessage(channel=settings.ADMIN_CHANNEL, text=message)
    logger.error(message)


@app.error
async def handle_error(error, body):
    """이벤트 핸들러에서 발생한 에러를 처리합니다."""
    logger.error(f'"{str(error)}"')
    trace = traceback.format_exc()
    logger.debug(dict(body=body, error=trace))
    await app.client.chat_postMessage(
        channel=settings.ADMIN_CHANNEL, text=f"🕊️: {trace=} 👉🏼 💌: {body=}"
    )


# community
@app.event("message")
async def handle_message_event(ack, body) -> None:
    await ack()


# contents
app.command("/제출")(contents_events.submit_command)
app.view("submit_view")(contents_events.submit_view)
app.action("intro_modal")(contents_events.open_intro_modal)
app.action("contents_modal")(contents_events.contents_modal)
app.action("bookmark_modal")(contents_events.bookmark_modal)
app.view("bookmark_view")(contents_events.bookmark_view)
app.command("/패스")(contents_events.pass_command)
app.view("pass_view")(contents_events.pass_view)
app.command("/검색")(contents_events.search_command)
app.view("submit_search")(contents_events.submit_search)
app.view("back_to_search_view")(contents_events.back_to_search_view)
app.command("/북마크")(contents_events.bookmark_command)
app.view("bookmark_search_view")(contents_events.bookmark_search_view)
app.action("bookmark_overflow_action")(contents_events.open_overflow_action)
app.view("bookmark_submit_search_view")(contents_events.bookmark_submit_search_view)

# core
# TODO: 도움말 명령어 추가
app.event("app_mention")(core_events.handle_mention)
app.command("/예치금")(core_events.get_deposit)
app.command("/제출내역")(core_events.history_command)
app.command("/관리자")(core_events.admin_command)


event_descriptions = {
    "/제출": "글 제출 시작",
    "submit_view": "글 제출 완료",
    "intro_modal": "다른 유저의 자기소개 확인",
    "contents_modal": "다른 유저의 제출한 글 목록 확인",
    "bookmark_modal": "북마크 저장 시작",
    "bookmark_view": "북마크 저장 완료",
    "/패스": "글 패스 시작",
    "pass_view": "글 패스 완료",
    "/검색": "글 검색 시작",
    "submit_search": "글 검색 완료",
    "back_to_search_view": "글 검색 다시 시작",
    "/북마크": "북마크 조회",
    "bookmark_search_view": "북마크 검색 시작",
    "bookmark_overflow_action": "북마크 메뉴 선택",
    "bookmark_submit_search_view": "북마크 검색 완료",
    "app_mention": "앱 멘션",
    "/예치금": "예치금 조회",
    "/제출내역": "제출내역 조회",
    "/관리자": "관리자 메뉴 조회",
}