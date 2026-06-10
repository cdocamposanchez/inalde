"""
INALDE · Motor de Curaduría Ejecutiva
Backend FastAPI — formulario público de hojas de vida + APIs de catálogos.

El análisis de las hojas de vida NO usa IA: la curaduría se ejecuta con un
motor ATS determinista (app/ats_engine.py) desde el módulo administrativo.
"""
import json
import logging
import re
import uuid
from datetime import datetime, date
from pathlib import Path
from typing import List, Optional

from fastapi import (
    FastAPI, Depends, Request, Form, File, UploadFile, HTTPException,
)
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import JSONResponse, HTMLResponse
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field, field_validator

from app import config
from app.database import (
    get_db, init_db,
    TipoDocumento, Nacionalidad, NivelFormacion, Sector, Departamento,
    Candidato, Habilidad, Tecnologia, IdiomaCandidato, SectorCandidato,
    Formacion, Experiencia, CambioEstadoAuditoria,
)
from app.admin import router as admin_router
from app.pdf_generator import generar_pdf_hoja_de_vida
from app.mailer import enviar_candidato, EmailSendError
from app.workflows import CANDIDATO_WORKFLOW
from app.timezone import now_utc_naive, now_local, format_local, APP_TZ_NAME


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("inalde.main")


BASE_DIR = Path(__file__).resolve().parent.parent
UPLOAD_DIR = config.UPLOAD_DIR
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
MAX_PDF_SIZE = config.MAX_PDF_SIZE


app = FastAPI(
    title=config.APP_NAME,
    description=(
        "Captación de hojas de vida ejecutivas y curaduría por motor ATS — "
        "INALDE Business School."
    ),
    version=config.APP_VERSION,
    debug=config.DEBUG,
)

templates = Jinja2Templates(directory=str(BASE_DIR / "app" / "templates"))
templates.env.filters["bogota"] = format_local

app.mount(
    "/static",
    StaticFiles(directory=str(BASE_DIR / "app" / "static")),
    name="static",
)

app.include_router(admin_router)


@app.on_event("startup")
def on_startup():
    config.assert_config_coherente()
    init_db()
    log.info("Aplicación iniciada (%s). Zona horaria: %s", config.APP_NAME, APP_TZ_NAME)


# ============================================================
# Esquemas Pydantic del formulario público
# ============================================================
class FormacionIn(BaseModel):
    nivel: str
    titulo: str
    institucion: str
    anio_inicio: Optional[int] = None
    anio_fin: Optional[int] = None
    en_curso: bool = False

    @field_validator("anio_inicio", "anio_fin", mode="before")
    @classmethod
    def _empty_to_none_int(cls, v):
        if v in ("", None):
            return None
        return int(v)


class ExperienciaIn(BaseModel):
    empresa: str
    cargo: str
    sector: Optional[str] = None
    pais: Optional[str] = None
    fecha_inicio: date
    fecha_fin: Optional[date] = None
    actual: bool = False
    funciones: Optional[str] = None
    nivel_jerarquico: Optional[str] = None
    lidero_equipo: bool = False
    tam_equipo: Optional[int] = None
    manejo_pyl: bool = False

    @field_validator("fecha_fin", mode="before")
    @classmethod
    def _empty_to_none_date(cls, v):
        if v in ("", None):
            return None
        return v

    @field_validator("tam_equipo", mode="before")
    @classmethod
    def _empty_to_none_int(cls, v):
        if v in ("", None):
            return None
        return int(v)


class HabilidadIn(BaseModel):
    nombre: str
    nivel: Optional[str] = None


class TecnologiaIn(BaseModel):
    nombre: str
    nivel: Optional[str] = None


class IdiomaIn(BaseModel):
    idioma: str
    nivel: Optional[str] = None


class CandidatoIn(BaseModel):
    # Datos personales
    nombres: str
    apellidos: str
    tipo_documento: str
    numero_documento: str
    fecha_nacimiento: Optional[date] = None
    nacionalidad: Optional[str] = None
    correo: str
    telefono_celular: str
    linkedin: Optional[str] = None
    ciudad: Optional[str] = None
    pais: Optional[str] = "Colombia"

    # Perfil ejecutivo
    titular: Optional[str] = None
    resumen_profesional: Optional[str] = None
    anos_experiencia: Optional[int] = None
    pretension_salarial: Optional[str] = None
    disponibilidad_viaje: bool = False
    disponibilidad_reubicacion: bool = False
    es_alumni: bool = False
    programa_inalde: Optional[str] = None

    # Colecciones
    habilidades: List[HabilidadIn] = Field(default_factory=list)
    tecnologias: List[TecnologiaIn] = Field(default_factory=list)
    idiomas: List[IdiomaIn] = Field(default_factory=list)
    sectores: List[str] = Field(default_factory=list)
    formaciones: List[FormacionIn] = Field(default_factory=list)
    experiencias: List[ExperienciaIn] = Field(default_factory=list)

    @field_validator("fecha_nacimiento", mode="before")
    @classmethod
    def _empty_to_none_date(cls, v):
        if v in ("", None):
            return None
        return v

    @field_validator("anos_experiencia", mode="before")
    @classmethod
    def _empty_to_none_int(cls, v):
        if v in ("", None):
            return None
        return int(v)

    @field_validator("correo")
    @classmethod
    def validar_correo(cls, v):
        if "@" not in v or "." not in v.split("@")[-1]:
            raise ValueError("Correo electrónico inválido.")
        return v.strip().lower()

    @field_validator("habilidades")
    @classmethod
    def al_menos_una_habilidad(cls, v):
        if not v:
            raise ValueError("Debe registrar al menos una habilidad.")
        return v


def _traducir_msg_pydantic(err: dict) -> str:
    t = err.get("type", "")
    msg = err.get("msg", "")
    if t in ("missing", "value_error.missing"):
        return "Este campo es obligatorio."
    if "date" in t:
        return "Fecha inválida."
    if "int" in t:
        return "Debe ser un número entero."
    return msg or "Valor inválido."


# ============================================================
# Página pública
# ============================================================
@app.get("/", response_class=HTMLResponse)
def index(request: Request, db: Session = Depends(get_db)):
    contexto = {
        "request": request,
        "app_name": config.APP_NAME,
        "app_short_name": config.APP_SHORT_NAME,
        "max_formaciones": config.MAX_FORMACIONES,
        "max_experiencias": config.MAX_EXPERIENCIAS,
        "max_habilidades": config.MAX_HABILIDADES,
        "max_idiomas": config.MAX_IDIOMAS,
        "anio": now_local().year,
    }
    return templates.TemplateResponse("index.html", contexto)


# ============================================================
# APIs de catálogos
# ============================================================
@app.get("/api/tipos-documento")
def api_tipos_documento(db: Session = Depends(get_db)):
    items = (
        db.query(TipoDocumento)
        .filter(TipoDocumento.activo.is_(True))
        .order_by(TipoDocumento.orden, TipoDocumento.nombre)
        .all()
    )
    return [{"codigo": i.codigo, "nombre": i.nombre} for i in items]


@app.get("/api/nacionalidades")
def api_nacionalidades(db: Session = Depends(get_db)):
    items = (
        db.query(Nacionalidad)
        .filter(Nacionalidad.activo.is_(True))
        .order_by(Nacionalidad.orden, Nacionalidad.nombre)
        .all()
    )
    return [{"codigo": i.codigo, "nombre": i.nombre} for i in items]


@app.get("/api/niveles-formacion")
def api_niveles_formacion(db: Session = Depends(get_db)):
    items = (
        db.query(NivelFormacion)
        .filter(NivelFormacion.activo.is_(True))
        .order_by(NivelFormacion.peso, NivelFormacion.orden)
        .all()
    )
    return [{"codigo": i.codigo, "nombre": i.nombre} for i in items]


@app.get("/api/sectores")
def api_sectores(db: Session = Depends(get_db)):
    items = (
        db.query(Sector)
        .filter(Sector.activo.is_(True))
        .order_by(Sector.orden, Sector.nombre)
        .all()
    )
    return [{"codigo": i.codigo, "nombre": i.nombre} for i in items]


@app.get("/api/departamentos")
def api_departamentos(db: Session = Depends(get_db)):
    items = (
        db.query(Departamento)
        .filter(Departamento.activo.is_(True))
        .order_by(Departamento.orden, Departamento.nombre)
        .all()
    )
    return [{"nombre": i.nombre} for i in items]


# ============================================================
# Registro de candidato (hoja de vida)
# ============================================================
@app.post("/api/candidatos")
async def crear_candidato(
    payload: str = Form(...),
    cv: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """Recibe el formulario completo + un PDF (la hoja de vida)."""
    try:
        payload_dict = json.loads(payload)
    except json.JSONDecodeError:
        raise HTTPException(
            status_code=400,
            detail="El formulario está mal formado. Recarga la página e intenta de nuevo.",
        )

    from pydantic import ValidationError
    try:
        data = CandidatoIn(**payload_dict)
    except ValidationError as e:
        errores = [{
            "loc": list(err.get("loc", [])),
            "msg": _traducir_msg_pydantic(err),
            "type": err.get("type", ""),
        } for err in e.errors()]
        raise HTTPException(status_code=422, detail=errores)
    except Exception as e:  # noqa: BLE001
        log.exception("Error parseando payload: %s", e)
        raise HTTPException(status_code=400, detail="No se pudieron procesar los datos.")

    # Validación del archivo
    if cv.content_type != "application/pdf":
        raise HTTPException(status_code=400, detail="Solo se permiten archivos PDF.")
    contenido = await cv.read()
    if len(contenido) > MAX_PDF_SIZE:
        raise HTTPException(
            status_code=400,
            detail=f"El archivo supera el límite de {config.MAX_PDF_SIZE_MB} MB.",
        )

    ahora_utc = now_utc_naive()
    ahora_local = now_local()
    if config.STORE_HOJAS_VIDA:
        secuencia = db.query(Candidato).count() + 1
        consecutivo = f"INALDE-{ahora_local.year}-{secuencia:05d}"
    else:
        consecutivo = f"INALDE-{ahora_local.strftime('%Y%m%d-%H%M%S')}"

    datos_completos = {
        "consecutivo": consecutivo,
        "nombres": data.nombres.strip(),
        "apellidos": data.apellidos.strip(),
        "tipo_documento": data.tipo_documento,
        "numero_documento": data.numero_documento.strip(),
        "fecha_nacimiento": data.fecha_nacimiento,
        "nacionalidad": data.nacionalidad,
        "correo": data.correo,
        "telefono_celular": data.telefono_celular,
        "linkedin": data.linkedin,
        "ciudad": data.ciudad,
        "pais": data.pais,
        "titular": data.titular,
        "resumen_profesional": data.resumen_profesional,
        "anos_experiencia": data.anos_experiencia,
        "es_alumni": data.es_alumni,
        "programa_inalde": data.programa_inalde,
        "habilidades": [h.model_dump() for h in data.habilidades],
        "tecnologias": [t.model_dump() for t in data.tecnologias],
        "idiomas": [i.model_dump() for i in data.idiomas],
        "sectores": data.sectores,
        "formaciones": [f.model_dump() for f in data.formaciones],
        "experiencias": [e.model_dump() for e in data.experiencias],
        "fecha_registro": ahora_utc,
    }

    try:
        pdf_generado = generar_pdf_hoja_de_vida(datos_completos)
    except Exception as e:  # noqa: BLE001
        log.exception("Error generando PDF estructurado: %s", e)
        pdf_generado = None

    if config.STORE_HOJAS_VIDA:
        nombre_seguro = f"{uuid.uuid4().hex}.pdf"
        ruta = UPLOAD_DIR / nombre_seguro
        with open(ruta, "wb") as f:
            f.write(contenido)

        cand = Candidato(
            consecutivo=consecutivo,
            nombres=datos_completos["nombres"],
            apellidos=datos_completos["apellidos"],
            tipo_documento=data.tipo_documento,
            numero_documento=datos_completos["numero_documento"],
            fecha_nacimiento=data.fecha_nacimiento,
            nacionalidad=data.nacionalidad,
            correo=data.correo,
            telefono_celular=data.telefono_celular,
            linkedin=data.linkedin,
            ciudad=data.ciudad,
            pais=data.pais,
            titular=data.titular,
            resumen_profesional=data.resumen_profesional,
            anos_experiencia=data.anos_experiencia,
            pretension_salarial=data.pretension_salarial,
            disponibilidad_viaje=data.disponibilidad_viaje,
            disponibilidad_reubicacion=data.disponibilidad_reubicacion,
            es_alumni=data.es_alumni,
            programa_inalde=data.programa_inalde,
            cv_archivo=nombre_seguro,
            cv_archivo_original=cv.filename,
            estado=CANDIDATO_WORKFLOW.initial_state,
            fecha_estado_actual=ahora_utc,
            fecha_actualizacion_estado=ahora_utc,
        )
        for h in data.habilidades:
            cand.habilidades.append(Habilidad(**h.model_dump()))
        for t in data.tecnologias:
            cand.tecnologias.append(Tecnologia(**t.model_dump()))
        for i in data.idiomas:
            cand.idiomas.append(IdiomaCandidato(**i.model_dump()))
        for s in data.sectores:
            if s:
                cand.sectores.append(SectorCandidato(sector=s))
        for f in data.formaciones:
            cand.formaciones.append(Formacion(**f.model_dump()))
        for e in data.experiencias:
            cand.experiencias.append(Experiencia(**e.model_dump()))

        db.add(cand)
        db.flush()
        db.add(CambioEstadoAuditoria(
            entity_type=CANDIDATO_WORKFLOW.entity_type,
            entity_id=cand.id,
            estado_anterior=None,
            estado_nuevo=CANDIDATO_WORKFLOW.initial_state,
            comentario="Hoja de vida recibida por el formulario público.",
            usuario_admin_id=None,
            fecha_cambio=ahora_utc,
            duracion_estado_segundos=0,
        ))
        db.commit()

    if config.EMAIL_ENABLED and pdf_generado:
        try:
            enviar_candidato(
                datos=datos_completos,
                pdf_generado=pdf_generado,
                pdf_usuario=(cv.filename or "cv.pdf", contenido),
            )
        except EmailSendError as e:
            log.error("Error enviando correo (consecutivo=%s): %s", consecutivo, e)

    return JSONResponse({
        "ok": True,
        "consecutivo": consecutivo,
        "mensaje": (
            "Tu hoja de vida fue registrada correctamente. "
            "Conserva tu número de radicado."
        ),
    })
