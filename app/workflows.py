"""
Flujos de estados reutilizables.

El control de estados no queda amarrado a una sola entidad: la tabla
genérica de auditoría (`cambios_estado_auditoria`) permite definir otro
EstadoWorkflow para otro modelo en el futuro.
"""
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, Iterable, Optional


@dataclass(frozen=True)
class EstadoConfig:
    codigo: str
    etiqueta: str
    descripcion: str
    color: str
    terminal: bool = False


class EstadoWorkflow:
    def __init__(self, entity_type: str, initial_state: str, estados: Iterable[EstadoConfig]):
        self.entity_type = entity_type
        self.initial_state = initial_state
        self._estados: Dict[str, EstadoConfig] = {e.codigo: e for e in estados}
        if initial_state not in self._estados:
            raise ValueError("El estado inicial debe existir dentro del flujo")

    @property
    def estados(self) -> list[EstadoConfig]:
        return list(self._estados.values())

    def get(self, codigo: Optional[str]) -> EstadoConfig:
        return self._estados.get(codigo or self.initial_state, self._estados[self.initial_state])

    def validar(self, codigo: str) -> str:
        codigo = (codigo or "").strip().lower()
        if codigo not in self._estados:
            raise ValueError(f"Estado no permitido: {codigo}")
        return codigo

    def es_terminal(self, codigo: Optional[str]) -> bool:
        return self.get(codigo).terminal

    def serializar_estado(self, codigo: Optional[str]) -> dict:
        e = self.get(codigo)
        return {
            "codigo": e.codigo, "etiqueta": e.etiqueta,
            "descripcion": e.descripcion, "color": e.color, "terminal": e.terminal,
        }


# Flujo del candidato dentro del proceso de curaduría ejecutiva.
CANDIDATO_WORKFLOW = EstadoWorkflow(
    entity_type="candidato",
    initial_state="recibido",
    estados=[
        EstadoConfig(
            "recibido", "Recibido",
            "Hoja de vida nueva en el banco, pendiente de curaduría.",
            "bg-slate-100 text-slate-700 border-slate-200",
        ),
        EstadoConfig(
            "en_evaluacion", "En evaluación",
            "Perfil siendo evaluado contra una o más ofertas laborales.",
            "bg-amber-100 text-amber-800 border-amber-200",
        ),
        EstadoConfig(
            "preseleccionado", "Preseleccionado",
            "Perfil que superó el filtro de curaduría para una oferta.",
            "bg-sky-100 text-sky-800 border-sky-200",
        ),
        EstadoConfig(
            "finalista", "Finalista",
            "Perfil enviado al headhunter o empresa alumni como prioritario.",
            "bg-emerald-100 text-emerald-800 border-emerald-200",
        ),
        EstadoConfig(
            "descartado", "Descartado",
            "Perfil descartado para los procesos actuales.",
            "bg-rose-100 text-rose-800 border-rose-200",
            terminal=True,
        ),
        EstadoConfig(
            "contratado", "Contratado",
            "Proceso cerrado con vinculación del candidato.",
            "bg-[#fde2e4] text-[#E30613] border-[#f5b8bd]",
            terminal=True,
        ),
    ],
)


def segundos_transcurridos(desde: Optional[datetime], hasta: Optional[datetime] = None) -> int:
    if not desde:
        return 0
    hasta = hasta or datetime.utcnow()
    return max(0, int((hasta - desde).total_seconds()))


def formatear_duracion(segundos: Optional[int]) -> str:
    segundos = max(0, int(segundos or 0))
    if segundos < 60:
        return f"{segundos}s"
    minutos = segundos // 60
    if minutos < 60:
        return f"{minutos} min"
    horas = minutos // 60
    if horas < 24:
        resto_min = minutos % 60
        return f"{horas} h" if resto_min == 0 else f"{horas} h {resto_min} min"
    dias = horas // 24
    resto_h = horas % 24
    return f"{dias} d" if resto_h == 0 else f"{dias} d {resto_h} h"
