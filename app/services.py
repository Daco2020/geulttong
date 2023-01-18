import datetime
import re
from typing import Any
from app.client import SpreadSheetClient
from app import dto
from app.utils import now_dt


class SubmissionService:
    def __init__(self, sheets_client: SpreadSheetClient) -> None:
        self._sheets_client = sheets_client
        self._url_regex = r"((http|https):\/\/)?[a-zA-Z0-9.-]+(\.[a-zA-Z]{2,})"

    async def open_modal(self, body, client, view_name: str) -> None:
        await client.views_open(
            trigger_id=body["trigger_id"], view=self._get_modal_view(body, view_name)
        )

    async def get(self, ack, body, view) -> dto.Submission:
        content_url = self._get_content_url(view)
        await self._validate_url(ack, content_url)
        submission = dto.Submission(
            dt=datetime.datetime.strftime(now_dt(), "%Y-%m-%d %H:%M:%S"),
            user_id=body["user"]["id"],
            username=body["user"]["username"],
            content_url=self._get_content_url(view),
            category=self._get_category(view),
            description=self._get_description(view),
            tag=self._get_tag(view),
        )
        return submission

    def submit(self, submission: dto.Submission) -> None:
        self._sheets_client.submit(submission)

    async def send_chat_message(
        self, client, view, logger, submission: dto.Submission
    ) -> None:
        tag_msg = self._get_tag_msg(submission.tag)
        description_msg = self._get_description_msg(submission.description)
        channal = view["private_metadata"]
        try:
            msg = f"\n<@{submission.user_id}>님 제출 완료🎉{description_msg}\
                \ncategory : {submission.category}{tag_msg}\
                \nlink : {submission.content_url}"
            await client.chat_postMessage(channel=channal, text=msg)
        except Exception as e:
            logger.exception(f"Failed to post a message {str(e)}")

    def _get_modal_view(self, body, submit_view: str) -> dict[str, Any]:
        view = {
            "type": "modal",
            "private_metadata": body["channel_id"],
            "callback_id": submit_view,
            "title": {"type": "plain_text", "text": "글똥이"},
            "submit": {"type": "plain_text", "text": "제출"},
            "blocks": [
                {
                    "type": "section",
                    "block_id": "required_section",
                    "text": {
                        "type": "mrkdwn",
                        "text": "글 쓰느라 고생 많았어~ 👏🏼👏🏼👏🏼\n[글 링크]와 [카테고리]를 제출하면 끝! 🥳",
                    },
                },
                {
                    "type": "input",
                    "block_id": "content",
                    "element": {
                        "type": "url_text_input",
                        "action_id": "url_text_input-action",
                    },
                    "label": {"type": "plain_text", "text": "글 링크", "emoji": True},
                },
                {
                    "type": "input",
                    "block_id": "category",
                    "label": {"type": "plain_text", "text": "카테고리", "emoji": True},
                    "element": {
                        "type": "static_select",
                        "placeholder": {
                            "type": "plain_text",
                            "text": "카테고리 선택",
                            "emoji": True,
                        },
                        "options": [
                            {
                                "text": {
                                    "type": "plain_text",
                                    "text": "언어 & 기술",
                                    "emoji": True,
                                },
                                "value": "언어 & 기술",
                            },
                            {
                                "text": {
                                    "type": "plain_text",
                                    "text": "취준 & 이직",
                                    "emoji": True,
                                },
                                "value": "취준 & 이직",
                            },
                            {
                                "text": {
                                    "type": "plain_text",
                                    "text": "조직 & 문화",
                                    "emoji": True,
                                },
                                "value": "조직 & 문화",
                            },
                            {
                                "text": {
                                    "type": "plain_text",
                                    "text": "일상 & 관계",
                                    "emoji": True,
                                },
                                "value": "일상 & 생각",
                            },
                            {
                                "text": {
                                    "type": "plain_text",
                                    "text": "기타",
                                    "emoji": True,
                                },
                                "value": "기타",
                            },
                        ],
                        "action_id": "static_select-action",
                    },
                },
                {"type": "divider"},
                {
                    "type": "input",
                    "block_id": "description",
                    "optional": True,
                    "element": {
                        "type": "plain_text_input",
                        "action_id": "plain_text_input-action",
                        "placeholder": {
                            "type": "plain_text",
                            "text": "입력",
                        },
                        "multiline": True,
                    },
                    "label": {
                        "type": "plain_text",
                        "text": "하고 싶은 말",
                        "emoji": True,
                    },
                },
                {
                    "type": "input",
                    "block_id": "tag",
                    "label": {
                        "type": "plain_text",
                        "text": "태그",
                    },
                    "optional": True,
                    "element": {
                        "type": "plain_text_input",
                        "action_id": "dreamy_input",
                        "placeholder": {
                            "type": "plain_text",
                            "text": "태그1,태그2,태그3, ... ",
                        },
                        "multiline": False,
                    },
                },
            ],
        }
        return view

    def _get_description(self, view) -> str:
        description: str = view["state"]["values"]["description"][
            "plain_text_input-action"
        ]["value"]
        if not description:
            description = ""
        return description

    def _get_tag(self, view) -> str:
        tag = ""
        raw_tag: str = view["state"]["values"]["tag"]["dreamy_input"]["value"]
        if raw_tag:
            tag = ",".join(set(tag.strip() for tag in raw_tag.split(",") if tag))
        return tag

    def _get_category(self, view) -> str:
        category: str = view["state"]["values"]["category"]["static_select-action"][
            "selected_option"
        ]["value"]

        return category

    def _get_content_url(self, view) -> str:
        content_url: str = view["state"]["values"]["content"]["url_text_input-action"][
            "value"
        ]
        return content_url

    def _get_description_msg(self, description: str) -> str:
        description_msg = ""
        if description:
            description_msg = f"\n\n💬 '{description}'\n"
        return description_msg

    def _get_tag_msg(self, tag: str) -> str:
        tag_msg = ""
        if tag:
            tags = tag.split(",")
            tag_msg = "\ntag : #" + " #".join(set(tag.strip() for tag in tags))
        return tag_msg

    async def _validate_url(self, ack, content_url: str) -> None:
        if not re.match(self._url_regex, content_url):
            errors = {}
            errors["content"] = "링크는 url 주소여야 합니다."
            await ack(response_action="errors", errors=errors)
            raise ValueError


class PassService:
    def __init__(self, sheets_client: SpreadSheetClient) -> None:
        self._sheets_client = sheets_client

    async def open_modal(self, body, client, view_name: str) -> None:
        await client.views_open(
            trigger_id=body["trigger_id"], view=self._get_modal_view(body, view_name)
        )

    async def get(self, ack, body, view) -> dto.Pass:
        username = body["user"]["username"]
        await self._validate_passable(ack, username)
        pass_ = dto.Pass(
            dt=datetime.datetime.strftime(now_dt(), "%Y-%m-%d %H:%M:%S"),
            user_id=body["user"]["id"],
            username=username,
            description=self._get_description(view),
        )
        return pass_

    def submit(self, pass_: dto.Pass) -> None:
        self._sheets_client.submit(pass_)

    async def send_chat_message(self, client, view, logger, pass_: dto.Pass) -> None:
        description_msg = self._get_description_msg(pass_.description)
        channal = view["private_metadata"]
        try:
            msg = f"\n<@{pass_.user_id}>님 패스 완료🙏🏼{description_msg}"
            await client.chat_postMessage(channel=channal, text=msg)
        except Exception as e:
            logger.exception(f"Failed to post a message {str(e)}")

    def _get_modal_view(self, body, view_name: str) -> dict[str, Any]:
        count = self._sheets_client.get_passed_count(body["user_name"])
        view = {
            "type": "modal",
            "private_metadata": body["channel_id"],
            "callback_id": view_name,
            "title": {"type": "plain_text", "text": "글똥이"},
            "submit": {"type": "plain_text", "text": "패스"},
            "blocks": [
                {
                    "type": "section",
                    "block_id": "required_section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"패스 하려면 아래 '패스' 버튼을 눌러주세요.\n(패스 가능 횟수 {2-count}회)",
                    },
                },
                {
                    "type": "input",
                    "block_id": "description",
                    "optional": True,
                    "element": {
                        "type": "plain_text_input",
                        "action_id": "plain_text_input-action",
                        "placeholder": {
                            "type": "plain_text",
                            "text": "입력",
                        },
                        "multiline": True,
                    },
                    "label": {
                        "type": "plain_text",
                        "text": "하고 싶은 말",
                        "emoji": True,
                    },
                },
            ],
        }
        return view

    def _get_description(self, view) -> str:
        description: str = view["state"]["values"]["description"][
            "plain_text_input-action"
        ]["value"]
        if not description:
            description = ""
        return description

    def _get_description_msg(self, description: str) -> str:
        description_msg = ""
        if description:
            description_msg = f"\n\n💬 '{description}'\n"
        return description_msg

    async def _validate_passable(self, ack, username: str) -> None:
        count = self._sheets_client.get_passed_count(username)
        if count >= 2:
            errors = {}
            errors["description"] = "pass는 2회 까지만 가능합니다."
            await ack(response_action="errors", errors=errors)
            raise ValueError


submission_service = SubmissionService(SpreadSheetClient())
pass_service = PassService(SpreadSheetClient())
