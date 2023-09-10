import csv
from typing import Any

from app import models, client


class UserRepository:
    def __init__(self) -> None:
        ...

    def get_user(self, user_id: str) -> models.User | None:
        """유저와 콘텐츠를 가져옵니다."""
        if user := self._get_user(user_id):
            user.contents = self._fetch_contents(user_id)
            return user
        return None

    def _get_user(self, user_id: str) -> models.User | None:
        """유저를 가져옵니다."""
        users = self._fetch_users()
        for user in users:
            if user["user_id"] == user_id:
                return models.User(**user)
        return None

    def _fetch_users(self) -> list[dict[str, Any]]:
        """모든 유저를 가져옵니다."""
        with open("store/users.csv", "r") as f:
            reader = csv.DictReader(f)
            users = [dict(row) for row in reader]
            return users

    def _fetch_contents(self, user_id: str) -> list[models.Content]:
        """유저의 콘텐츠를 오름차순(날짜)으로 정렬하여 가져옵니다."""
        with open("store/contents.csv", "r") as f:
            reader = csv.DictReader(f)
            contents = [
                models.Content(**content)
                for content in reader
                if content["user_id"] == user_id
            ]
            return sorted(contents, key=lambda content: content.dt_)

    def update(self, user: models.User) -> None:
        """유저의 콘텐츠를 업데이트합니다."""
        if not user.contents:
            raise ValueError("업데이트 대상 content 가 없습니다.")
        client.upload_queue.append(user.recent_content.to_list_for_sheet())
        line = user.recent_content.to_line_for_csv()
        with open("store/contents.csv", "a") as f:
            f.write(line + "\n")

    def fetch_contents(self) -> list[models.Content]:
        """모든 콘텐츠를 가져옵니다."""
        with open("store/contents.csv", "r") as f:
            reader = csv.DictReader(f)
            contents = [
                models.Content(**content)
                for content in reader
                if content["type"] == "submit"
            ]
            return sorted(contents, key=lambda content: content.dt_, reverse=True)

    def fetch_contents_by_keyword(self, keyword: str) -> list[models.Content]:
        """키워드가 포함된 콘텐츠를 가져옵니다."""
        with open("store/contents.csv", "r") as f:
            reader = csv.DictReader(f)
            contents = [
                models.Content(**content)
                for content in reader
                if keyword.lower()
                in (content["title"] + content["description"] + content["tags"]).lower()
                and content["type"] == "submit"
            ]
            return sorted(contents, key=lambda content: content.dt_, reverse=True)

    def get_user_id_by_name(self, name: str) -> str | None:
        """이름으로 user_id를 가져옵니다."""
        with open("store/users.csv", "r") as f:
            reader = csv.DictReader(f)
            matching_users = [user for user in reader if name in user["name"]]

        if len(matching_users) == 1:  # 이름 부분 일치가 하나인 경우에만 반환
            return matching_users[0]["user_id"]
        elif len(matching_users) > 1:
            for user in matching_users:
                if user["name"] == name:
                    return user["user_id"]
        return None

    def create_bookmark(self, bookmark: models.Bookmark) -> None:
        """북마크를 생성합니다."""
        with open("store/bookmark.csv", "a") as f:
            f.write(bookmark.to_line_for_csv() + "\n")

    def get_bookmark(self, user_id: str, content_id: str) -> models.Bookmark | None:
        bookmarks = self.fetch_bookmarks(user_id)
        for bookmark in bookmarks:
            if bookmark.content_id == content_id:
                return bookmark
        return None

    def fetch_bookmarks(self, user_id: str) -> list[models.Bookmark]:
        """유저의 삭제되지 않은 북마크를 내림차순으로 가져옵니다."""
        with open("store/bookmark.csv", "r") as f:
            reader = csv.DictReader(f)
            bookmarks = [
                models.Bookmark(**bookmark)  # type: ignore
                for bookmark in reader
                if bookmark["is_deleted"] and bookmark["user_id"] == user_id
            ]

        return sorted(bookmarks, key=lambda bookmark: bookmark.created_at, reverse=True)
