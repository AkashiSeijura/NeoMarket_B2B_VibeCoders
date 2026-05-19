from pydantic import BaseModel, ConfigDict, field_serializer


class APIModel(BaseModel):
    model_config = ConfigDict(
        from_attributes=True,
        populate_by_name=True,
        str_strip_whitespace=True,
    )


class CategoryOut(APIModel):
    id: int
    name: str


class ImagePayload(APIModel):
    url: str
    ordering: int = 0


class ImageOut(ImagePayload):
    id: int

    @field_serializer("id")
    def serialize_id(self, value: int) -> str:
        return str(value)


class CharacteristicPayload(APIModel):
    name: str
    value: str


class CharacteristicOut(CharacteristicPayload):
    id: int

    @field_serializer("id")
    def serialize_id(self, value: int) -> str:
        return str(value)

