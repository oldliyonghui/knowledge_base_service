from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class GoodsSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int | None = None
    name: str | None = None
    price: Decimal | None = None
    stock: int | None = None
    category_id: int | None = None
    category_name: str | None = None
