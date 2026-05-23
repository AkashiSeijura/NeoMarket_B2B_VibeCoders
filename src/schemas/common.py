import uuid

from pydantic import BaseModel, ConfigDict


class APIModel(BaseModel):
    model_config = ConfigDict(
        from_attributes=True,
        populate_by_name=True,
        str_strip_whitespace=True,
    )


class CategoryOut(APIModel):
    id: uuid.UUID
    name: str


class ImagePayload(APIModel):
    url: str
    ordering: int = 0


class ImageOut(ImagePayload):
    id: uuid.UUID


class CharacteristicPayload(APIModel):
    name: str
    value: str


class CharacteristicOut(CharacteristicPayload):
    id: uuid.UUID

