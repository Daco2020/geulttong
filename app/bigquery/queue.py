import asyncio
from datetime import date, datetime
from typing import TypedDict

import pandas as pd

from app.bigquery.client import BigqueryClient, TableNameEnum


class CommentDataType(TypedDict):
    user_id: str
    channel_id: str
    ts: str  # 상위 메시지 timestamp
    comment_ts: str  # 댓글 timestamp
    tddate: date
    createtime: datetime
    text: str


class EmojiDataType(TypedDict):
    user_id: str
    channel_id: str
    ts: str
    reactions_ts: str
    tddate: date
    createtime: datetime
    reaction: str


class PostDataType(TypedDict):
    user_id: str
    channel_id: str
    ts: str
    tddate: date
    createtime: datetime
    text: str


queue_lock = asyncio.Lock()

comments_upload_queue: list[CommentDataType] = []
emojis_upload_queue: list[EmojiDataType] = []
posts_upload_queue: list[PostDataType] = []


class BigqueryQueue:
    def __init__(self, client: BigqueryClient) -> None:
        self._client = client

    async def upload(self) -> None:
        global comments_upload_queue, emojis_upload_queue, posts_upload_queue

        async with queue_lock:
            temp_comments_queue = list(comments_upload_queue)
            if temp_comments_queue:
                await asyncio.to_thread(
                    self._client.update_table,
                    pd.DataFrame(temp_comments_queue),
                    TableNameEnum.COMMENTS_LOG,
                    "append",
                )
                comments_upload_queue = [
                    entry
                    for entry in comments_upload_queue
                    if entry not in temp_comments_queue
                ]

            temp_emojis_queue = list(emojis_upload_queue)
            if temp_emojis_queue:
                await asyncio.to_thread(
                    self._client.update_table,
                    pd.DataFrame(temp_emojis_queue),
                    TableNameEnum.EMOJIS_LOG,
                    "append",
                )
                emojis_upload_queue = [
                    entry
                    for entry in emojis_upload_queue
                    if entry not in temp_emojis_queue
                ]

            temp_posts_queue = list(posts_upload_queue)
            if temp_posts_queue:
                await asyncio.to_thread(
                    self._client.update_table,
                    pd.DataFrame(temp_posts_queue),
                    TableNameEnum.POSTS_LOG,
                    "append",
                )
                posts_upload_queue = [
                    entry
                    for entry in posts_upload_queue
                    if entry not in temp_posts_queue
                ]
