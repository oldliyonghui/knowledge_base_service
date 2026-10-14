import uuid
from datetime import datetime, timezone

from sqlalchemy import CHAR, DateTime, TypeDecorator, String


class UtcDateTime(TypeDecorator):
    """带时区的 UTC 时间列。

    MySQL 的 DATETIME 本身不存时区，即使写 DateTime(timezone=True)，
    驱动取出来的也是 naive datetime，接口就会返回不带 Z/+00:00 的时间字符串
    （api.md 约定的是 ISO 8601 UTC），前端按本地时间解析会整体偏 8 小时。

    这里统一约定：库里存的就是 UTC，写入时把 aware 转成 naive UTC，
    读出时补回 UTC 时区，这样 Pydantic 序列化出来就带 +00:00。
    """

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            return value
        return value.astimezone(timezone.utc).replace(tzinfo=None)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


class GUID(TypeDecorator):
    """跨库 UUID 类型。

    - PostgreSQL: 走原生 UUID
    - MySQL / SQLite: 走 CHAR(36)
    - Python 层始终是 uuid.UUID
    """

    impl = CHAR(36)
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            from sqlalchemy.dialects.postgresql import UUID as PG_UUID
            return dialect.type_descriptor(PG_UUID(as_uuid=True))
        # MySQL / SQLite：存 36 位带横线的字符串
        return dialect.type_descriptor(CHAR(36))

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if dialect.name == "postgresql":
            return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))
        if isinstance(value, uuid.UUID):
            return str(value)          # "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
        return str(uuid.UUID(str(value)))

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        if isinstance(value, uuid.UUID):
            return value
        return uuid.UUID(str(value))


class EnumStr(TypeDecorator):
    """把 Python 枚举存成 String，取出来自动还原成枚举成员。"""

    impl = String
    cache_ok = True

    def __init__(self, enum_cls, length: int = 32):
        self.enum_cls = enum_cls
        super().__init__(length=length)

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if isinstance(value, self.enum_cls):
            return value.value
        return str(value)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        try:
            return self.enum_cls(value)
        except ValueError:
            return value
