import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel

class HistorialItem(BaseModel):
    campana_id: Optional[uuid.UUID] = None
    puntaje_phishing: float
    nivel: str
    creado_en: datetime

class HistorialResponse(BaseModel):
    destinatario_id: uuid.UUID
    items: list[HistorialItem]

class TrendItem(BaseModel):
    campana_id: uuid.UUID
    nombre: str
    finalizada_en: Optional[datetime] = None
    promedio: float
    n_destinatarios: int

class TrendResponse(BaseModel):
    grupo_id: uuid.UUID
    items: list[TrendItem]

class Distribucion(BaseModel):
    bajo: int = 0
    medio: int = 0
    alto: int = 0
    critico: int = 0

class CampanasResumen(BaseModel):
    total: int = 0
    completadas: int = 0

class ResumenResponse(BaseModel):
    destinatarios_activos: int
    indice_promedio: Optional[float] = None
    distribucion: Distribucion
    campanas: CampanasResumen
    ultima_finalizacion: Optional[datetime] = None
