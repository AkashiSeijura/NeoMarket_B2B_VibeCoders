from pydantic import BaseModel, ConfigDict


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
    pass


class CharacteristicPayload(APIModel):
    name: str
    value: str


class CharacteristicOut(CharacteristicPayload):
    pass

