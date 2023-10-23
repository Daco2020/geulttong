import csv

from app.logging import log_event, logger
from app.config import (
    BACKUP_SHEET,
    BOOKMARK_SHEET,
    RAW_DATA_SHEET,
    LOG_SHEET,
    settings,
)

import gspread
from oauth2client.service_account import ServiceAccountCredentials
from app.models import Bookmark


credentials = ServiceAccountCredentials.from_json_keyfile_dict(
    settings.JSON_KEYFILE_DICT, settings.SCOPE
)
gc = gspread.authorize(credentials)
content_upload_queue: list[list[str]] = []
bookmark_upload_queue: list[list[str]] = []
bookmark_update_queue: list[Bookmark] = []  # TODO: 추후 타입 수정 필요

# TODO: 파일 시스템과 분리 필요


class SpreadSheetClient:
    def __init__(self) -> None:
        self._doc = gc.open_by_url(settings.SPREAD_SHEETS_URL)
        self._raw_data_sheet = self._doc.worksheet(RAW_DATA_SHEET)
        self._log_sheet = self._doc.worksheet(LOG_SHEET)
        self._backup_sheet = self._doc.worksheet(BACKUP_SHEET)
        self._bookmark_sheet = self._doc.worksheet(BOOKMARK_SHEET)

        self._sheets = {
            "raw_data": self._doc.worksheet("raw_data"),
            "users": self._doc.worksheet("users"),
            "log": self._doc.worksheet("log"),
            "backup": self._doc.worksheet("backup"),
            "bookmark": self._doc.worksheet("bookmark"),
        }

    def upload(self) -> None:
        """새로 추가된 queue 가 있다면 upload 합니다."""
        global content_upload_queue
        if content_upload_queue:
            try:
                cursor = len(self._raw_data_sheet.get_values("A:A")) + 1
                self._raw_data_sheet.update(f"A{cursor}", content_upload_queue)
            except Exception as e:
                logger.error(f"Failed to upload content: {str(e)}")
                return None
            log_event(
                actor="system",
                event="uploaded_contents",
                type="content",
                description=f"{len(content_upload_queue)}개 콘텐츠 업로드",
                body={"content_upload_queue": content_upload_queue},
            )
            content_upload_queue = []

        global bookmark_upload_queue
        if bookmark_upload_queue:
            try:
                cursor = len(self._bookmark_sheet.get_values("A:A")) + 1
                self._bookmark_sheet.update(f"A{cursor}", bookmark_upload_queue)
            except Exception as e:
                logger.error(f"Failed to upload bookmark: {str(e)}")
                return None
            log_event(
                actor="system",
                event="uploaded_bookmarks",
                type="content",
                description=f"{len(bookmark_upload_queue)}개 북마크 업로드",
                body={"bookmark_upload_queue": bookmark_upload_queue},
            )
            bookmark_upload_queue = []

        global bookmark_update_queue
        if bookmark_update_queue:
            for bookmark in bookmark_update_queue:
                self.update_bookmark(bookmark)
            log_event(
                actor="system",
                event="updated_bookmarks",
                type="content",
                description=f"{len(bookmark_update_queue)}개 북마크 업데이트",
                body={"bookmark_update_queue": bookmark_update_queue},
            )
            bookmark_update_queue = []

    def get_values(self, sheet_name: str, column: str = "") -> list[list[str]]:
        """스프레드 시트로 부터 값을 가져옵니다."""
        if column:
            return self._sheets[sheet_name].get_values(column)
        else:
            return self._sheets[sheet_name].get_all_values()

    def push_backup(self) -> None:
        """백업 시트에 contents.csv를 업로드합니다."""
        with open("store/contents.csv") as f:
            reader = csv.reader(f)
            contents = list(reader)
        self._backup_sheet.clear()  # 기존 데이터를 지웁니다.
        self._backup_sheet.append_rows(contents)  # 백업할 데이터를 업로드 합니다.

    # def _parse(self, contents: list[list[str]]) -> list[str]:
    #     """
    #     가져온 콘텐츠를 csv 포멧에 맞게 가공합니다.
    #     content[0]: user_id
    #     content[1]: username
    #     content[2]: title
    #     content[3]: content_url
    #     content[4]: dt
    #     content[5]: categor
    #     content[6]: description
    #     content[7]: type
    #     content[8]: tags
    #     """
    #     result = [",".join(contents[0]) + "\n"]
    #     for content in contents[1:]:
    #         content[2] = f'"{content[2]}"'
    #         content[3] = f'"{content[3]}"'
    #         content[6] = content[6].replace(",", "")
    #         content[8] = content[8].replace(",", "#")
    #         result.append(",".join(content).replace("\n", " ") + "\n")
    #     return result

    def create_log_file(self) -> None:
        """로그 파일을 생성합니다."""
        open("store/logs.csv", "w").close()

    def upload_logs(self) -> None:
        """로그 파일을 업로드합니다."""
        with open("store/logs.csv") as f:
            reader = csv.reader(f)
            logs = list(reader)
        cursor = len(self._log_sheet.get_values("A:A")) + 1
        self._log_sheet.update(f"A{cursor}", logs)
        logger.info("Uploaded logs")

    def update_bookmark(self, bookmark: Bookmark) -> None:
        """북마크를 업데이트합니다."""
        records = self._bookmark_sheet.get_all_records()
        target_record = dict()
        row_number = 2  # +1은 enumerate이 0부터 시작하기 때문, +1은 헤더 행 때문
        for idx, record in enumerate(records):
            if (
                bookmark.user_id == record["user_id"]
                and bookmark.content_id == record["content_id"]
            ):
                target_record = record
                row_number += idx
                break

        values = bookmark.to_list_for_sheet()

        if not target_record:
            logger.error(f"시트에 해당 북마크가 존재하지 않습니다. {values}")

        self._bookmark_sheet.update(f"A{row_number}:F{row_number}", [values])
