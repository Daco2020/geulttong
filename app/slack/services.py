import asyncio
import re
from typing import Any

import httpx
from app.constants import URL_REGEX
from app.logging import log_event, logger
from app.exception import BotException, ClientException
from app.slack.repositories import SlackRepository
from app.constants import remind_message
from app import models
from app import store

from bs4 import BeautifulSoup


from slack_bolt.async_app import AsyncApp


class SlackService:
    def __init__(self, user_repo: SlackRepository, user: models.User) -> None:
        self._user_repo = user_repo
        self._user = user

    def fetch_contents(
        self,
        keyword: str | None = None,
        name: str | None = None,
        category: str = "전체",
    ) -> list[models.Content]:
        """콘텐츠를 조건에 맞춰 가져옵니다."""
        if keyword:
            contents = self._user_repo.fetch_contents_by_keyword(keyword)
        else:
            contents = self._user_repo.fetch_contents()

        if name:
            user_ids = self._user_repo.fetch_user_ids_by_name(name)
            contents = [content for content in contents if content.user_id in user_ids]

        if category != "전체":
            contents = [content for content in contents if content.category == category]

        return contents

    def get_user(self, user_id) -> models.User:
        """유저 정보를 가져옵니다."""
        user = self._user_repo.get_user(user_id)
        if not user:
            raise BotException("해당 유저 정보가 없어요.")
        return user

    async def create_submit_content(
        self,
        title: str,
        content_url: str,
        username: str,
        view: dict[str, Any],
    ) -> models.Content:
        """제출 콘텐츠를 생성합니다."""
        content = models.Content(
            user_id=self._user.user_id,
            username=username,
            title=title,
            content_url=content_url,
            category=self._get_category(view),
            description=self._get_description(view),
            type="submit",
            tags=self._get_tags(view),
            # curation_flag=self._get_curation_flag(view), # TODO: 방학기간에는 제거, 10기에 활성화 필요
        )
        return content

    async def update_user_content(self, content: models.Content) -> None:
        """유저의 콘텐츠를 업데이트합니다."""
        self._user.contents.append(content)
        self._user_repo.update(self._user)

    async def create_pass_content(self, ack, body, view) -> models.Content:
        """패스 콘텐츠를 생성합니다."""
        content = models.Content(
            user_id=body["user"]["id"],
            username=body["user"]["username"],
            description=self._get_description(view),
            type="pass",
        )
        return content

    def get_chat_message(self, content: models.Content) -> str:
        if content.type == "submit":
            title = content.title.replace("\n", " ")
            message = f"\n>>>🎉 *<@{content.user_id}>님 제출 완료.*\
                {self._description_message(content.description)}\
                \n링크 : *<{content.content_url}|{re.sub('<|>', '', title if content.title != 'title unknown.' else content.content_url)}>*\
                \n카테고리 : {content.category}\
                {self._tag_message(content.tags)}"  # noqa E501
        else:
            message = f"\n>>>🙏🏼 *<@{content.user_id}>님 패스 완료.*\
                {self._description_message(content.description)}"
        return message

    def _get_description(self, view) -> str:
        description: str = view["state"]["values"]["description"]["text_input"]["value"]
        if not description:
            return ""
        return description

    def _get_tags(self, view) -> str:
        raw_tag: str = view["state"]["values"]["tag"]["tags_input"]["value"]
        if not raw_tag:
            return ""
        deduplication_tags = list(dict.fromkeys(raw_tag.split(",")))
        tags = ",".join(tag.strip() for tag in deduplication_tags if tag)
        return tags

    def _get_category(self, view) -> str:
        category: str = view["state"]["values"]["category"]["category_select"][
            "selected_option"
        ]["value"]
        return category

    def _get_curation_flag(self, view) -> str:
        curation_flag: str = view["state"]["values"]["curation"]["curation_select"][
            "selected_option"
        ]["value"]
        return curation_flag

    async def get_title(self, view, url: str) -> str:

        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(url)
                if response.status_code == 404:
                    raise ClientException("비공개 글이거나, url 를 찾을 수 없어요.")

            # 제목을 직접 입력한 경우에는 status_code만 확인 후에 return
            title_input = view["state"]["values"]["manual_title_input"]["title_input"][
                "value"
            ]
            if title_input:
                return title_input

            soup = BeautifulSoup(response.text, "html.parser")
            title = soup.find("title")
            if not title:
                raise ClientException(
                    "'글 제목'을 찾을 수 없습니다. 모달 하단에 직접 입력해주세요."
                )
            return title.text.strip()

        except ClientException as e:
            raise e
        except Exception as e:
            logger.debug(str(e))
            raise ClientException("url 에 문제가 있어요. 확인 후 다시 시도해주세요.")

    def _description_message(self, description: str) -> str:
        description_message = f"\n\n💬 '{description}'\n" if description else ""
        return description_message

    def _tag_message(self, tag: str) -> str:
        tag_message = (
            "\n태그 : " + " ".join([f"`{t.strip()}`" for t in tag.split(",")])
            if tag
            else ""
        )
        return tag_message

    def validate_url(self, view, content_url: str) -> None:
        if not re.match(URL_REGEX, content_url):
            raise ValueError("링크는 url 형식이어야 해요.")
        if content_url in self._user.content_urls:
            raise ValueError("이미 제출한 url 이에요.")
        if "tistory.com/manage/posts" in content_url:
            # 티스토리 posts 페이지는 글 링크가 아니므로 제외합니다.
            raise ValueError("잠깐! 입력한 링크가 '글 링크'가 맞는지 확인해주세요.")
        if (
            "notion." in content_url
            or "oopy.io" in content_url
            or ".site" in content_url
        ):
            # notion.so, notion.site, oopy.io 는 title 을 크롤링하지 못하므로 직접 입력을 받는다.
            # 글 제목을 입력한 경우 통과.
            if (
                view["state"]["values"]
                .get("manual_title_input", {})
                .get("title_input", {})
                .get("value")
            ):
                return None
            raise ValueError("노션은 하단의 '글 제목'을 필수로 입력해주세요.")

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

    def update_user_intro(
        self,
        user_id: str,
        new_intro: str,
    ) -> None:
        """사용자의 자기소개를 수정합니다."""
        if self._user.user_id != user_id:
            raise BotException("본인의 자기소개만 수정할 수 있습니다.")
        self._user_repo.update_user_intro(user_id, new_intro)

    def fetch_users(self) -> list[models.User]:
        users = [models.User(**user) for user in self._user_repo._fetch_users()]
        return users

    def get_content_by_ts(self, ts: str) -> models.Content:
        return self._user_repo.get_content_by_ts(ts)  # type: ignore


class SlackReminderService:
    def __init__(self, user_repo: SlackRepository) -> None:
        self._user_repo = user_repo

    async def send_reminder_message_to_user(self, slack_app: AsyncApp) -> None:
        """사용자에게 리마인드 메시지를 전송합니다."""
        users = self._user_repo.fetch_users()
        for user in users:
            if user.is_submit:
                continue
            if user.cohort == "8기":
                continue
            if user.cohort == "9기":
                continue
            if user.channel_name == "슬랙봇":
                continue

            log_event(
                actor="slack_reminder_service",
                event="send_reminder_message_to_user",
                type="reminder",
                description=f"{user.name} 님에게 리마인드 메시지를 전송합니다.",
            )

            await slack_app.client.chat_postMessage(
                channel=user.user_id,
                text=remind_message.format(user_name=user.name),
            )
            await asyncio.sleep(1)
            # 슬랙은 메시지 전송을 초당 1개를 권장하기 때문에 1초 대기합니다.
            # 참고문서: https://api.slack.com/methods/chat.postMessage#rate_limiting
