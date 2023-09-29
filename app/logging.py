import datetime
import decimal
import uuid
import orjson
import inspect

from typing import Any
from app.utils import now_dt_to_str
from loguru import logger

logger.add("store/logs.csv", format="{time},{level},{message}")


def default(obj: Any) -> str | list[Any]:
    if isinstance(obj, (decimal.Decimal, uuid.UUID)):
        return str(obj)
    elif isinstance(obj, set):
        return list(obj)
    elif isinstance(obj, datetime.datetime):
        return obj.isoformat()
    elif isinstance(obj, datetime.date):
        return obj.isoformat()
    elif isinstance(obj, bytes):
        return obj.decode("utf-8")
    else:
        return "This object cannot be serialized."


def event_log(user_id: str, event: str) -> None:
    try:
        data = dict(
            event=event,
            user_id=user_id,
            caller=inspect.stack()[1].function,
            timestamp=now_dt_to_str(),
        )
        logger.info(orjson.dumps(data, default=default).decode("utf-8"))
    except Exception as e:
        logger.debug(f"Failed to log event: {str(e)}")