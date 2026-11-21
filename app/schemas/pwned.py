from pydantic import BaseModel

class StrengthCheckRequest(BaseModel):
    password: str

class StrengthCheckResponse(BaseModel):
    score: int
    es_fuerte: bool
    errores: list[str]

class PwnedRangeResponse(BaseModel):
    prefijo: str
    total_conocidas: int
    conteos: dict[str, int]
