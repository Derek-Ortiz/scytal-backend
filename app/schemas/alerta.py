import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel

class AlertaResponse(BaseModel):
    id_alertas: uuid.UUID
    tipo: str
    referencia_tipo: Optional[str] = None
    referencia_id: Optional[uuid.UUID] = None
    resuelto: bool
    resuelto_en: Optional[datetime] = None
    creado_en: datetime

class AlertaListResponse(BaseModel):
    total: int
    items: list[AlertaResponse]
    limit: int
    offset: int
