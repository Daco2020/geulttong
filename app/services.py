import re
from typing import Any
from app.config import MAX_PASS_COUNT, URL_REGEX
from app.repositories import UserRepository
from app import models
from app.utils import print_log


import requests
from bs4 import BeautifulSoup


class UserContentService:
    def __init__(self, user_repo: UserRepository) -> None:
        self._user_repo = user_repo

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

    def get_user(self, user_id, channel_id) -> models.User:
        user = self._user_repo.get_user(user_id)

        # TODO: validate 분리
        self._validate_user(channel_id, user)
        return user  # type: ignore

    def get_user_not_valid(self, user_id) -> models.User:
        # TODO: 임시로 사용, 추후 제거
        user = self._user_repo.get_user(user_id)
        return user  # type: ignore

    def update_user(self, user: models.User, content: models.Content):
        user.contents.append(content)
        self._user_repo.update(user)

    async def open_submit_modal(self, body, client, view_name: str) -> None:
        try:
            user = self.get_user(body["user_id"], body["channel_id"])
        except ValueError as e:
            await self._open_error_modal(client, body, view_name, str(e))
            return None
        await self._open_submit_modal(client, body, view_name, user)

    async def create_submit_content(
        self, ack, body, view, user: models.User
    ) -> models.Content:
        content_url = self._get_content_url(view)
        await self._validate_url(ack, content_url, user)
        content = models.Content(
            user_id=body["user"]["id"],
            username=body["user"]["username"],
            title=self._get_title(content_url),
            content_url=content_url,
            category=self._get_category(view),
            description=self._get_description(view),
            tags=self._get_tags(view),
            type="submit",
        )
        self.update_user(user, content)
        return content

    async def open_pass_modal(self, body, client, view_name: str) -> None:
        try:
            user = self.get_user(body["user_id"], body["channel_id"])
        except ValueError as e:
            await self._open_error_modal(client, body, view_name, str(e))
            return None
        await self._open_pass_modal(client, body, view_name, user)

    async def create_pass_content(
        self, ack, body, view, user: models.User
    ) -> models.Content:
        await self._validate_pass(ack, user)
        content = models.Content(
            user_id=body["user"]["id"],
            username=body["user"]["username"],
            description=self._get_description(view),
            type="pass",
        )
        self.update_user(user, content)
        return content

    async def open_search_modal(self, body, client) -> None:
        await self._open_search_modal(client, body)

    def get_chat_message(self, content: models.Content, animal: dict[str, str]) -> str:
        if content.type == "submit":
            message = f"\n>>>{animal['emoji']} *<@{content.user_id}>님 제출 완료.*\
                {self._description_message(content.description)}\
                \ncategory : {content.category}\
                {self._tag_message(content.tags)}\
                \nlink : {content.content_url}"
        else:
            message = f"\n>>>{animal['emoji']} *<@{content.user_id}>님 패스 완료.*\
                {self._description_message(content.description)}"
        return message

    def get_submit_history(self, user_id: str) -> str:
        user = self._user_repo.get_user(user_id)
        if user is None:
            return "사용자 정보가 없습니다. [글또봇질문]채널로 문의해주세요."
        return self._history_message(user)

    def validate_admin_user(self, user_id: str) -> None:
        if user_id not in ["U02HPESDZT3", "U04KVHPMQQ6"]:
            raise ValueError("관리자 계정이 아닙니다.")

    def _history_message(self, user: models.User) -> str:
        message = ""
        for content in user.fetch_contents():
            round = content.get_round()
            sumit_head = f"✅  {round}회차 제출"
            pass_head = f"▶️  {round}회차 패스"
            message += f"\n{sumit_head if content.type == 'submit' else pass_head}  |  "
            message += f"{content.dt}  |  "
            message += f"{content.content_url}"
        return message or "제출 내역이 없습니다."

    async def _open_error_modal(
        self, client, body: dict[str, str], view_name: str, e: str
    ) -> None:
        message = (
            f"{body.get('user_id')}({body.get('channel_id')}) 님의 {view_name} 가 실패하였습니다."
        )
        print_log(message, e)
        e = "예기치 못한 오류가 발생하였습니다.\n[글또봇질문] 채널로 문의해주세요." if "Content" in e else e
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
                            "text": f"🥲 \n{e}",
                        },
                    }
                ],
            },
        )

    async def _open_submit_modal(
        self, client, body, view_name: str, user: models.User
    ) -> None:
        try:
            round, due_date = user.get_due_date()
            guide_message = f"\n\n현재 회차는 {round}회차, 마감일은 {due_date} 이에요."
            if user.is_submit:
                guide_message += f"\n({user.name} 님은 이미 {round}회차 글을 제출하셨어요)"
        except ValueError:
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
                            "text": f"\n[글 링크]와 [카테고리]를 제출해주세요. 🥳{guide_message}",
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
                                "text": "카테고리 선택",
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
            },
        )

    async def _open_pass_modal(
        self, client, body, view_name: str, user: models.User
    ) -> None:
        pass_count = user.pass_count
        try:
            round, due_date = user.get_due_date()
            guide_message = f"\n- 현재 회차는 {round}회차, 마감일은 {due_date} 이에요."
        except ValueError:
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

    async def _open_search_modal(self, client, body) -> dict[str, Any]:
        return await client.views_open(
            trigger_id=body["trigger_id"],
            view={
                "type": "modal",
                "callback_id": "submit_search",
                "title": {"type": "plain_text", "text": "글 검색 🔍"},
                "submit": {"type": "plain_text", "text": "찾기"},
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
        deduplication_tags = list(dict.fromkeys(raw_tag.replace("#", "").split(",")))
        tags = ",".join(tag.strip() for tag in deduplication_tags if tag)
        return tags

    def _get_category(self, view) -> str:
        category: str = view["state"]["values"]["category"]["static_select-action"][
            "selected_option"
        ]["value"]
        return category

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
            print_log(str(e))
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

    def _validate_user(self, channel_id, user: models.User | None) -> None:
        if not user:
            raise ValueError("사용자 정보가 등록되어 있지 않습니다.\n[글또봇질문] 채널로 문의해주세요.")
        if user.channel_id == "ALL":  # 관리자는 모든 채널에서 사용 가능
            return
        if user.channel_id != channel_id:
            raise ValueError(
                f"{user.name} 님의 코어 채널은 [{user.channel_name}] 입니다.\
                             \n코어 채널에서 다시 시도해주세요."
            )

    async def _validate_url(self, ack, content_url: str, user: models.User) -> None:
        if not re.match(URL_REGEX, content_url):
            block_id = "content_url"
            message = "링크는 url 형식이어야 합니다."
            await ack(response_action="errors", errors={block_id: message})
            raise ValueError(message)
        if content_url in user.content_urls:
            block_id = "content_url"
            message = "이미 제출한 url 입니다."
            await ack(response_action="errors", errors={block_id: message})
            raise ValueError(message)

    async def _validate_pass(self, ack, user: models.User) -> None:
        if user.pass_count >= MAX_PASS_COUNT:
            block_id = "description"
            message = "사용할 수 있는 pass 가 없습니다."
            await ack(response_action="errors", errors={block_id: message})
            raise ValueError(message)
        if user.is_prev_pass:
            block_id = "description"
            message = "연속으로 pass 를 사용할 수 없습니다."
            await ack(response_action="errors", errors={block_id: message})
            raise ValueError(message)

    def create_bookmark(
        self, user_id: str, content_id: str, note: str = ""
    ) -> models.Bookmark:
        """북마크를 생성합니다."""
        bookmark = models.Bookmark(user_id=user_id, content_id=content_id, note=note)
        self._user_repo.create_bookmark(bookmark)
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
        """unique_id 를 확인하여 Contents 를 가져옵니다."""
        if keyword:
            contents = self._user_repo.fetch_contents_by_keyword(keyword)
        else:
            contents = self._user_repo.fetch_contents()
        return [content for content in contents if content.unique_id in content_ids]


user_content_service = UserContentService(user_repo=UserRepository())
