import asyncio
import requests
from slack_sdk.web.async_client import AsyncWebClient
from app.exception import BotException
from app.models import User
from app.slack.services.base import SlackService
from app.slack.services.point import PointService
from app.slack.types import (
    ActionBodyType,
    CommandBodyType,
    MessageBodyType,
    ViewBodyType,
)
from slack_bolt.async_app import AsyncAck, AsyncSay
from slack_sdk.models.views import View
from slack_sdk.models.blocks import (
    SectionBlock,
    InputBlock,
    UserMultiSelectElement,
    ActionsBlock,
    ContextBlock,
    ButtonElement,
    DividerBlock,
)
from app.config import settings
from app.utils import dict_to_json_str, json_str_to_dict


async def handle_coffee_chat_message(
    ack: AsyncAck,
    body: MessageBodyType,
    say: AsyncSay,
    client: AsyncWebClient,
    user: User,
    service: SlackService,
    point_service: PointService,
) -> None:
    """커피챗 인증 메시지인지 확인하고, 인증 모달을 전송합니다."""
    await ack()

    # 인증글에 답글로 커피챗 인증을 하는 경우
    if body["event"].get("thread_ts"):
        try:
            service.check_coffee_chat_proof(
                thread_ts=str(body["event"]["thread_ts"]),
                user_id=body["event"]["user"],
            )
        except BotException:
            # 인증 글에 대한 답글이 아니거나 이미 인증한 경우, 인증 대상이 아닌 경우이다.
            return

        service.create_coffee_chat_proof(
            ts=str(body["event"]["ts"]),
            thread_ts=str(body["event"]["thread_ts"]),
            user_id=body["event"]["user"],
            text=body["event"]["text"],
            files=body["event"].get("files", []),  # type: ignore
            selected_user_ids="",
        )

        await client.reactions_add(
            channel=body["event"]["channel"],
            timestamp=body["event"]["ts"],
            name="white_check_mark",
        )

        # 포인트 지급
        text = point_service.grant_if_coffee_chat_verified(
            user_id=body["event"]["user"]
        )
        await client.chat_postMessage(channel=body["event"]["user"], text=text)

        return

    # 1초 대기하는 이유는 메시지 보다 더 먼저 전송 될 수 있기 때문임
    await asyncio.sleep(1)
    text = f"☕ <@{user.user_id}> 님 커피챗 인증을 시작하려면 아래 [ 커피챗 인증 ] 버튼을 눌러주세요."
    await client.chat_postEphemeral(
        user=user.user_id,
        channel=body["event"]["channel"],
        text=text,
        blocks=[
            SectionBlock(text=text),
            ActionsBlock(
                elements=[
                    ButtonElement(
                        text="안내 닫기",
                        action_id="cancel_coffee_chat_proof_button",
                    ),
                    ButtonElement(
                        text="커피챗 인증",
                        action_id="submit_coffee_chat_proof_button",
                        value=body["event"]["ts"],
                        style="primary",
                    ),
                ]
            ),
        ],
    )


async def cancel_coffee_chat_proof_button(
    ack: AsyncAck,
    body: ActionBodyType,
    client: AsyncWebClient,
    user: User,
    service: SlackService,
    point_service: PointService,
) -> None:
    """커피챗 인증 안내를 닫습니다."""
    await ack()

    requests.post(
        body["response_url"],
        json={
            "response_type": "ephemeral",
            "delete_original": True,
        },
        timeout=5.0,
    )


async def submit_coffee_chat_proof_button(
    ack: AsyncAck,
    body: ActionBodyType,
    client: AsyncWebClient,
    user: User,
    service: SlackService,
    point_service: PointService,
) -> None:
    """커피챗 인증을 제출합니다."""
    await ack()

    private_metadata = dict_to_json_str(
        {
            "ephemeral_url": body["response_url"],
            "message_ts": body["actions"][0]["value"],
        }
    )

    await client.views_open(
        trigger_id=body["trigger_id"],
        view=View(
            type="modal",
            title="커피챗 인증",
            submit="커피챗 인증하기",
            callback_id="submit_coffee_chat_proof_view",
            private_metadata=private_metadata,
            blocks=[
                SectionBlock(text="커피챗에 참여한 멤버들을 모두 선택해주세요.😊"),
                InputBlock(
                    block_id="participant",
                    label="커피챗 참여 멤버",
                    optional=False,
                    element=UserMultiSelectElement(
                        action_id="select",
                        placeholder="참여한 멤버들을 모두 선택해주세요.",
                        initial_users=[user.user_id],
                    ),
                ),
            ],
        ),
    )


async def submit_coffee_chat_proof_view(
    ack: AsyncAck,
    body: ViewBodyType,
    client: AsyncWebClient,
    say: AsyncSay,
    user: User,
    service: SlackService,
    point_service: PointService,
) -> None:
    """커피챗 인증을 처리합니다."""
    await ack()

    private_metadata = json_str_to_dict(body["view"]["private_metadata"])
    ephemeral_url = private_metadata["ephemeral_url"]
    message_ts = private_metadata["message_ts"]

    history = await client.conversations_history(
        channel=settings.COFFEE_CHAT_PROOF_CHANNEL,
        latest=message_ts,
        limit=1,
        inclusive=True,
    )
    message = history["messages"][0]
    selected_users = body["view"]["state"]["values"]["participant"]["select"][
        "selected_users"
    ]

    service.create_coffee_chat_proof(
        ts=message_ts,
        thread_ts="",
        user_id=user.user_id,
        text=message["text"],
        files=message.get("files", []),
        selected_user_ids=",".join(
            selected_user
            for selected_user in selected_users
            if selected_user != user.user_id
        ),
    )

    await client.reactions_add(
        channel=settings.COFFEE_CHAT_PROOF_CHANNEL,
        timestamp=message_ts,
        name="white_check_mark",
    )

    # 포인트 지급
    text = point_service.grant_if_coffee_chat_verified(user_id=user.user_id)
    await client.chat_postMessage(channel=user.user_id, text=text)

    user_call_text = ",".join(
        f"<@{selected_user}>"
        for selected_user in selected_users
        if selected_user != user.user_id  # 본인 제외
    )

    if user_call_text:
        await client.chat_postMessage(
            channel=settings.COFFEE_CHAT_PROOF_CHANNEL,
            thread_ts=message_ts,
            text=f"{user_call_text} \n\n😊 커피챗 인증을 위해 꼭 후기를 남겨주세요. 인증이 확인된 멤버는 ✅가 표시돼요.",
        )

    # 나에게만 표시 메시지 수정하는 요청(slack bolt 에서는 지원하지 않음)
    requests.post(
        ephemeral_url,
        json={
            "response_type": "ephemeral",
            "delete_original": True,
        },
        timeout=5.0,
    )


async def paper_plane_command(
    ack: AsyncAck,
    body: CommandBodyType,
    client: AsyncWebClient,
    user: User,
    service: SlackService,
    point_service: PointService,
) -> None:
    """종이비행기 명령을 처리합니다."""
    await ack()

    paper_planes = service.fetch_current_week_paper_planes(user_id=user.user_id)
    remain_paper_planes = 7 - len(paper_planes) if len(paper_planes) < 7 else 0

    await client.views_open(
        trigger_id=body["trigger_id"],
        view=View(
            type="modal",
            callback_id="paper_plane_command",
            title={"type": "plain_text", "text": "종이비행기"},
            blocks=[
                SectionBlock(text="✈️ *종이비행기란?*"),
                ContextBlock(
                    elements=[
                        {
                            "type": "mrkdwn",
                            "text": (
                                "종이비행기는 글또 멤버에게 따뜻한 감사나 응원의 메시지를 보낼 수 있는 기능이에요.\n"
                                "매주 토요일 0시에 7개가 충전되며, 한 주 동안 자유롭게 원하는 분께 보낼 수 있어요.\n"
                                f"*{user.name[1:]}* 님이 이번 주에 보낼 수 있는 종이비행기 수는 현재 *{remain_paper_planes}개* 입니다."
                            ),
                        }
                    ]
                ),
                DividerBlock(),
                ActionsBlock(
                    elements=[
                        ButtonElement(
                            text="종이비행기 보내기",
                            action_id="send_paper_plane_message",
                            value="send_paper_plane_message",
                            style="primary",
                        ),
                        ButtonElement(
                            text="주고받은 종이비행기 보기",
                            action_id="open_paper_plane_url",
                            url="https://geultto-paper-plane.vercel.app",
                        ),
                    ]
                ),
                DividerBlock(),
                # 사용 방법 안내
                SectionBlock(
                    text={
                        "type": "mrkdwn",
                        "text": "*✍️ 어떤 내용을 보내면 좋을까요?*",
                    }
                ),
                ContextBlock(
                    elements=[
                        {
                            "type": "mrkdwn",
                            "text": "종이비행기 메시지를 작성할 때는 아래 내용을 참고해보세요. 😉\n\n"
                            "*`구체적인 상황`* - 어떤 활동이나 대화에서 고마움을 느꼈는지 이야기해요.\n"
                            "*`구체적인 내용`* - 그 사람이 어떤 도움을 줬거나, 어떤 말을 해줬는지 적어보세요.\n"
                            "*`효과와 감사 표현`* - 그 행동이 나에게 어떤 영향을 주었는지, 얼마나 감사한지 표현해요.\n"
                            "*`앞으로의 기대`* - 앞으로도 계속 함께해주길 바라는 마음을 전해보세요!",
                        }
                    ]
                ),
                DividerBlock(),
                # 예시 메시지
                SectionBlock(
                    text={
                        "type": "mrkdwn",
                        "text": "*💌 종이비행기 메시지 예시*\n",
                    }
                ),
                # 예시 1: 스터디 활동
                ContextBlock(
                    elements=[
                        {
                            "type": "mrkdwn",
                            "text": '예시 1: 스터디 활동\n>"00 스터디에서 항상 열정적으로 참여해주셔서 정말 감사해요! 덕분에 저도 더 열심히 하게 되고, 많은 배움을 얻고 있어요. 앞으로도 함께 성장해나갈 수 있으면 좋겠어요! 😊"',
                        }
                    ]
                ),
                # 예시 2: 커피챗 대화
                ContextBlock(
                    elements=[
                        {
                            "type": "mrkdwn",
                            "text": '예시 2: 커피챗 대화\n>"지난번 커피챗에서 나눈 대화가 정말 인상 깊었어요. 개발에 대한 생각을 나누고 조언을 주셔서 고맙습니다! 다음에도 또 이런 기회가 있으면 좋겠네요!"',
                        }
                    ]
                ),
                # 예시 3: 반상회 발표
                ContextBlock(
                    elements=[
                        {
                            "type": "mrkdwn",
                            "text": '예시 3: 반상회 발표\n>"최근 반상회에서 발표하신 모습이 인상적이었어요! 멀리서 지켜보면서 많은 영감을 받았답니다. 😊 나중에 기회가 된다면 커피챗으로 더 깊게 이야기를 나눌 수 있으면 좋겠어요!"',
                        }
                    ]
                ),
                DividerBlock(),
                # 가이드 마무리
                ContextBlock(
                    elements=[
                        {
                            "type": "mrkdwn",
                            "text": "이제 진심을 담은 메시지를 종이비행기에 담아 전달해보세요! ✈️",
                        }
                    ]
                ),
            ],
        ),
    )
