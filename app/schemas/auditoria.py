import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel

class AuditoriaResponse(BaseModel):
    id_eventos_auditoria: uuid.UUID
    tipo: str
    actor_id: Optional[uuid.UUID] = None
    actor_tipo: str
    actor_correo: Optional[str] = None
    detalle: str
    creado_en: datetime

class AuditoriaListResponse(BaseModel):
    total: int
    items: list[AuditoriaResponse]
    limit: int
    offset: int
