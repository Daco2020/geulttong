import re
from typing import Any

from app.logging import logger
from app.config import MAX_PASS_COUNT, URL_REGEX
from app.slack.exception import BotException
from app.slack.repositories import SlackRepository
from app import store


import requests
from bs4 import BeautifulSoup

from app import models


class SlackService:
    def __init__(self, user_repo: SlackRepository, user: models.User) -> None:
        self._user_repo = user_repo
        self._user = user

    @property
    def user(self) -> models.User:
        """유저를 가져옵니다."""
        return self._user

    def fetch_contents(
        self, keyword: str | None = None, name: str | None = None, category: str = "전체"
    ) -> list[models.Content]:
        """콘텐츠를 조건에 맞춰 가져옵니다."""
        if keyword:
            contents = self._user_repo.fetch_contents_by_keyword(keyword)
        else:
            contents = self._user_repo.fetch_contents()

        if name:
            user_id = self._user_repo.get_user_id_by_name(name)
            contents = [content for content in contents if content.user_id == user_id]

        if category != "전체":
            contents = [content for content in contents if content.category == category]

        return contents

    def get_other_user(self, user_id) -> models.User:
        """다른 유저를 가져옵니다."""
        user = self._user_repo.get_user(user_id)
        return user  # type: ignore

    async def create_submit_content(self, ack, body, view) -> models.Content:
        """제출 콘텐츠를 생성합니다."""
        content_url = self._get_content_url(view)
        await self._validate_url(ack, content_url, self._user)
        content = models.Content(
            user_id=body["user"]["id"],
            username=body["user"]["username"],
            title=self._get_title(content_url),
            content_url=content_url,
            category=self._get_category(view),
            description=self._get_description(view),
            type="submit",
            tags=self._get_tags(view),
            curation_flag=self._get_curation_flag(view),
        )
        self._user.contents.append(content)
        self._user_repo.update(self._user)
        return content

    async def create_pass_content(self, ack, body, view) -> models.Content:
        """패스 콘텐츠를 생성합니다."""
        await self._validate_pass(ack, self._user)
        content = models.Content(
            user_id=body["user"]["id"],
            username=body["user"]["username"],
            description=self._get_description(view),
            type="pass",
        )
        self._user.contents.append(content)
        self._user_repo.update(self._user)
        return content

    def get_chat_message(self, content: models.Content) -> str:
        if content.type == "submit":
            message = f"\n>>>🎉 *<@{content.user_id}>님 제출 완료.*\
                {self._description_message(content.description)}\
                \ncategory : {content.category}\
                {self._tag_message(content.tags)}\
                \nlink : {content.content_url}"
        else:
            message = f"\n>>>🙏🏼 *<@{content.user_id}>님 패스 완료.*\
                {self._description_message(content.description)}"
        return message

    def get_submit_history(self) -> str:
        message = ""
        for content in self._user.fetch_contents():
            round = content.get_round()
            sumit_head = f"✅  {round}회차 제출"
            pass_head = f"▶️  {round}회차 패스"
            message += f"\n{sumit_head if content.type == 'submit' else pass_head}  |  "
            message += f"{content.dt}  |  "
            message += f"{content.content_url}"
        return message or "제출 내역이 없어요."

    async def open_error_modal(
        self, body: dict[str, str], client, view_name: str, message: str
    ) -> None:
        message = (
            "예기치 못한 오류가 발생했어요.\n[글또봇질문] 채널로 문의해주세요."
            if "Content" in message
            else message
        )
        await client.views_open(
            trigger_id=body["trigger_id"],
            view={
                "type": "modal",
                "private_metadata": body["channel_id"],
                "callback_id": view_name,
                "title": {"type": "plain_text", "text": "또봇"},
                "close": {"type": "plain_text", "text": "닫기"},
                "blocks": [
                    {
                        "type": "section",
                        "text": {
                            "type": "plain_text",
                            "text": message,
                        },
                    }
                ],
            },
        )

    async def open_submit_modal(self, body, client, view_name: str) -> None:
        """제출 모달을 띄웁니다."""
        self._check_channel(body["channel_id"])

        try:
            round, due_date = self._user.get_due_date()
            guide_message = f"\n\n현재 회차는 {round}회차, 마감일은 {due_date} 이에요."
            guide_message += f"\n({self._user.name} 님은 아직 {round}회차 글을 제출하지 않았어요)"
            if self._user.is_submit:
                guide_message += f"\n({self._user.name} 님은 이미 {round}회차 글을 제출했어요)"
        except BotException:
            guide_message = ""
        await client.views_open(
            trigger_id=body["trigger_id"],
            view={
                "type": "modal",
                "private_metadata": body["channel_id"],
                "callback_id": view_name,
                "title": {"type": "plain_text", "text": "또봇"},
                "submit": {"type": "plain_text", "text": "제출"},
                "blocks": [
                    {
                        "type": "section",
                        "block_id": "required_section",
                        "text": {
                            "type": "mrkdwn",
                            "text": guide_message,
                        },
                    },
                    {
                        "type": "input",
                        "block_id": "content_url",
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
                                "text": "글의 카테고리를 선택해주세요.",
                                "emoji": True,
                            },
                            "options": [
                                {
                                    "text": {
                                        "type": "plain_text",
                                        "text": "프로젝트",
                                        "emoji": True,
                                    },
                                    "value": "프로젝트",
                                },
                                {
                                    "text": {
                                        "type": "plain_text",
                                        "text": "기술 & 언어",
                                        "emoji": True,
                                    },
                                    "value": "기술 & 언어",
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
                                        "text": "취준 & 이직",
                                        "emoji": True,
                                    },
                                    "value": "취준 & 이직",
                                },
                                {
                                    "text": {
                                        "type": "plain_text",
                                        "text": "일상 & 생각",
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
                            "action_id": "static_select-category",
                        },
                    },
                    {
                        "type": "input",
                        "block_id": "curation",
                        "label": {"type": "plain_text", "text": "큐레이션", "emoji": True},
                        "element": {
                            "type": "static_select",
                            "placeholder": {
                                "type": "plain_text",
                                "text": "글을 큐레이션 대상에 포함할까요?",
                                "emoji": True,
                            },
                            "options": [
                                {
                                    "text": {
                                        "type": "plain_text",
                                        "text": "큐레이션 대상이 되고 싶어요!",
                                        "emoji": True,
                                    },
                                    "value": "Y",  # str만 반환할 수 있음
                                },
                                {
                                    "text": {
                                        "type": "plain_text",
                                        "text": "아직은 부끄러워요~",
                                        "emoji": True,
                                    },
                                    "value": "N",
                                },
                            ],
                            "action_id": "static_select-curation",
                        },
                    },
                    {"type": "divider"},
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
                    {
                        "type": "input",
                        "block_id": "description",
                        "optional": True,
                        "element": {
                            "type": "plain_text_input",
                            "action_id": "plain_text_input-action",
                            "placeholder": {
                                "type": "plain_text",
                                "text": "하고 싶은 말이 있다면 남겨주세요.",
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
            },
        )

    async def open_pass_modal(self, body, client, view_name: str) -> None:
        """패스 모달을 띄웁니다."""
        self._check_channel(body["channel_id"])

        pass_count = self._user.pass_count
        try:
            round, due_date = self._user.get_due_date()
            guide_message = f"\n- 현재 회차는 {round}회차, 마감일은 {due_date} 이에요."
        except BotException:
            guide_message = ""
        await client.views_open(
            trigger_id=body["trigger_id"],
            view={
                "type": "modal",
                "private_metadata": body["channel_id"],
                "callback_id": view_name,
                "title": {"type": "plain_text", "text": "또봇"},
                "submit": {"type": "plain_text", "text": "패스"},
                "blocks": [
                    {
                        "type": "section",
                        "block_id": "required_section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f"패스 하려면 아래 '패스' 버튼을 눌러주세요.\
                            \n\n아래 유의사항을 확인해주세요.{guide_message}\
                            \n- 패스는 연속으로 사용할 수 없어요.\
                            \n- 남은 패스는 {MAX_PASS_COUNT - pass_count}번 이에요.",
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
                                "text": "하고 싶은 말이 있다면 남겨주세요.",
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
            },
        )

    async def open_search_modal(self, body, client) -> dict[str, Any]:
        return await client.views_open(
            trigger_id=body["trigger_id"],
            view={
                "type": "modal",
                "callback_id": "submit_search",
                "title": {"type": "plain_text", "text": "글 검색 🔍"},
                "submit": {"type": "plain_text", "text": "검색"},
                "blocks": [
                    {
                        "type": "section",
                        "block_id": "description_section",
                        "text": {"type": "mrkdwn", "text": "조건에 맞는 글을 검색합니다."},
                    },
                    {
                        "type": "input",
                        "block_id": "keyword_search",
                        "optional": True,
                        "element": {
                            "type": "plain_text_input",
                            "action_id": "keyword",
                            "placeholder": {
                                "type": "plain_text",
                                "text": "검색어를 입력해주세요.",
                            },
                            "multiline": False,
                        },
                        "label": {
                            "type": "plain_text",
                            "text": "검색어",
                            "emoji": True,
                        },
                    },
                    {
                        "type": "input",
                        "block_id": "author_search",
                        "optional": True,
                        "element": {
                            "type": "plain_text_input",
                            "action_id": "author_name",
                            "placeholder": {
                                "type": "plain_text",
                                "text": "이름을 입력해주세요.",
                            },
                            "multiline": False,
                        },
                        "label": {
                            "type": "plain_text",
                            "text": "글 작성자",
                            "emoji": False,
                        },
                    },
                    {
                        "type": "input",
                        "block_id": "category_search",
                        "label": {"type": "plain_text", "text": "카테고리", "emoji": True},
                        "element": {
                            "type": "static_select",
                            "action_id": "chosen_category",
                            "placeholder": {"type": "plain_text", "text": "카테고리 선택"},
                            "initial_option": {
                                "text": {"type": "plain_text", "text": "전체"},
                                "value": "전체",
                            },
                            "options": [
                                {
                                    "text": {"type": "plain_text", "text": "전체"},
                                    "value": "전체",
                                },
                                {
                                    "text": {"type": "plain_text", "text": "프로젝트"},
                                    "value": "프로젝트",
                                },
                                {
                                    "text": {"type": "plain_text", "text": "기술 & 언어"},
                                    "value": "기술 & 언어",
                                },
                                {
                                    "text": {"type": "plain_text", "text": "조직 & 문화"},
                                    "value": "조직 & 문화",
                                },
                                {
                                    "text": {"type": "plain_text", "text": "취준 & 이직"},
                                    "value": "취준 & 이직",
                                },
                                {
                                    "text": {"type": "plain_text", "text": "일상 & 생각"},
                                    "value": "일상 & 생각",
                                },
                                {
                                    "text": {"type": "plain_text", "text": "기타"},
                                    "value": "기타",
                                },
                            ],
                        },
                    },
                ],
            },
        )

    def _get_description(self, view) -> str:
        description: str = view["state"]["values"]["description"][
            "plain_text_input-action"
        ]["value"]
        if not description:
            return ""
        return description

    def _get_tags(self, view) -> str:
        raw_tag: str = view["state"]["values"]["tag"]["dreamy_input"]["value"]
        if not raw_tag:
            return ""
        deduplication_tags = list(dict.fromkeys(raw_tag.split(",")))
        tags = ",".join(tag.strip() for tag in deduplication_tags if tag)
        return tags

    def _get_category(self, view) -> str:
        category: str = view["state"]["values"]["category"]["static_select-category"][
            "selected_option"
        ]["value"]
        return category

    def _get_curation_flag(self, view) -> str:
        curation_flag: str = view["state"]["values"]["curation"][
            "static_select-curation"
        ]["selected_option"]["value"]
        return curation_flag

    def _get_content_url(self, view) -> str:
        # 슬랙 앱이 구 버전일 경우 일부 block 이 사라져 키에러가 발생할 수 있음
        content_url: str = view["state"]["values"]["content_url"][
            "url_text_input-action"
        ]["value"]
        return content_url

    def _get_title(self, url: str) -> str:
        try:
            response = requests.get(url)
            soup = BeautifulSoup(response.text, "html.parser")
            # TODO: title 태그가 없는 경우 핸들링 필요
            title = soup.find("title").text  # type: ignore
            result = title.strip()
            return result
        except Exception as e:
            logger.debug(str(e))
            return "title unknown."

    def _description_message(self, description: str) -> str:
        description_message = f"\n\n💬 '{description}'\n" if description else ""
        return description_message

    def _tag_message(self, tag: str) -> str:
        tag_message = (
            "\ntag : " + " ".join([f"`{t.strip()}`" for t in tag.split(",")])
            if tag
            else ""
        )
        return tag_message

    def _check_channel(self, channel_id) -> None:
        if self._user.channel_id == "ALL":
            return
        if self._user.channel_id != channel_id:
            raise BotException(
                f"{self._user.name} 님의 코어 채널은 [{self._user.channel_name}] 이에요.\
                             \n코어 채널에서 다시 시도해주세요."
            )

    async def _validate_url(self, ack, content_url: str, user: models.User) -> None:
        if not re.match(URL_REGEX, content_url):
            block_id = "content_url"
            message = "링크는 url 형식이어야 해요."
            await ack(response_action="errors", errors={block_id: message})
            raise BotException(message)
        if content_url in user.content_urls:
            block_id = "content_url"
            message = "이미 제출한 url 이에요."
            await ack(response_action="errors", errors={block_id: message})
            raise BotException(message)

    async def _validate_pass(self, ack, user: models.User) -> None:
        if user.pass_count >= MAX_PASS_COUNT:
            block_id = "description"
            message = "사용할 수 있는 pass 가 없어요."
            await ack(response_action="errors", errors={block_id: message})
            raise BotException(message)
        if user.is_prev_pass:
            block_id = "description"
            message = "연속으로 pass 를 사용할 수 없어요."
            await ack(response_action="errors", errors={block_id: message})
            raise BotException(message)

    def create_bookmark(
        self, user_id: str, content_id: str, note: str = ""
    ) -> models.Bookmark:
        """북마크를 생성합니다."""
        bookmark = models.Bookmark(user_id=user_id, content_id=content_id, note=note)
        self._user_repo.create_bookmark(bookmark)
        store.bookmark_upload_queue.append(bookmark.to_list_for_sheet())
        return bookmark

    def get_bookmark(self, user_id: str, content_id: str) -> models.Bookmark | None:
        """북마크를 가져옵니다."""
        bookmark = self._user_repo.get_bookmark(user_id, content_id)
        return bookmark

    def fetch_bookmarks(self, user_id: str) -> list[models.Bookmark]:
        """유저의 북마크를 모두 가져옵니다."""
        # TODO: 키워드로 검색 기능 추가
        bookmarks = self._user_repo.fetch_bookmarks(user_id)
        return bookmarks

    def fetch_contents_by_ids(
        self, content_ids: list[str], keyword: str = ""
    ) -> list[models.Content]:
        """컨텐츠 아이디로 Contents 를 가져옵니다."""
        if keyword:
            contents = self._user_repo.fetch_contents_by_keyword(keyword)
        else:
            contents = self._user_repo.fetch_contents()
        return [content for content in contents if content.content_id in content_ids]

    def update_bookmark(
        self,
        user_id: str,
        content_id: str,
        new_note: str = "",
        new_status: models.BookmarkStatusEnum = models.BookmarkStatusEnum.ACTIVE,
    ) -> None:
        """북마크를 업데이트합니다."""
        # TODO: 북마크 삭제와 수정 분리할 것
        self._user_repo.update_bookmark(content_id, new_note, new_status)
        bookmark = self._user_repo.get_bookmark(user_id, content_id, status=new_status)
        if bookmark:
            store.bookmark_update_queue.append(bookmark)
