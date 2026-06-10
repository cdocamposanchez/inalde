"""
Módulo administrativo — INALDE · Motor de Curaduría Ejecutiva.

Rutas bajo /admin/*:
  - Autenticación (login/logout).
  - Dashboard con métricas.
  - Candidatos: listado, detalle, cambio de estado, descarga de CV.
  - Ofertas laborales: CRUD con la configuración de búsqueda (modo,
    pesos, requisitos eliminatorios, reglas de compensación).
  - Curaduría: ejecuta el motor ATS (determinista, sin IA) de un
    candidato contra una oferta y persiste la Evaluación.
  - Catálogos: gestión básica (API genérica).
"""
import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import List, Optional
from urllib.parse import quote

from fastapi import (
    APIRouter, Depends, Request, Form, HTTPException, Query,
)
from fastapi.responses import (
    HTMLResponse, RedirectResponse, JSONResponse, FileResponse, Response,
)
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import func

from app import config
from app.database import (
    get_db,
    UsuarioAdmin, Candidato, OfertaLaboral, Evaluacion,
    Habilidad, IdiomaCandidato, SectorCandidato, Formacion, Experiencia,
    TipoDocumento, Nacionalidad, NivelFormacion, Sector, Departamento,
    CambioEstadoAuditoria,
)
from app.security import (
    COOKIE_NAME, SESSION_MAX_AGE,
    verify_password, create_session_token, hash_password,
    get_current_admin, get_current_admin_or_redirect,
    require_superadmin, require_gestor_catalogos,
)
from app.workflows import CANDIDATO_WORKFLOW, segundos_transcurridos, formatear_duracion
from app.timezone import now_utc_naive, now_local, format_local
from app import ats_engine
from app.pdf_generator import generar_pdf_hoja_de_vida

log = logging.getLogger("inalde.admin")

BASE_DIR = Path(__file__).resolve().parent.parent
router = APIRouter(prefix="/admin", tags=["admin"])
templates = Jinja2Templates(directory=str(BASE_DIR / "app" / "templates"))
templates.env.filters["bogota"] = format_local
templates.env.filters["duracion"] = formatear_duracion


def _from_json_list(raw):
    if not raw:
        return []
    try:
        val = json.loads(raw)
        return val if isinstance(val, list) else []
    except (json.JSONDecodeError, TypeError):
        return []


def _from_json_dict(raw):
    if not raw:
        return {}
    try:
        val = json.loads(raw)
        return val if isinstance(val, dict) else {}
    except (json.JSONDecodeError, TypeError):
        return {}


templates.env.filters["from_json_list"] = _from_json_list
templates.env.filters["from_json_dict"] = _from_json_dict


# ============================================================
# Helpers
# ============================================================
def _ctx(request: Request, admin: UsuarioAdmin, **extra) -> dict:
    base = {
        "request": request,
        "admin": admin,
        "app_name": config.APP_NAME,
        "app_short_name": config.APP_SHORT_NAME,
        "anio_actual": now_local().year,
        "workflow": CANDIDATO_WORKFLOW,
        "estados": CANDIDATO_WORKFLOW.estados,
    }
    base.update(extra)
    return base


def _estado_info(codigo: Optional[str]) -> dict:
    return CANDIDATO_WORKFLOW.serializar_estado(codigo)


def _candidato_en_alcance(cand: Candidato, admin: UsuarioAdmin) -> bool:
    if admin.ve_todo():
        return True
    ofertas_admin = set(admin.ofertas_ids())
    ofertas_cand = {e.oferta_id for e in cand.evaluaciones}
    return bool(ofertas_admin & ofertas_cand)


def _oferta_en_alcance(oferta: OfertaLaboral, admin: UsuarioAdmin) -> bool:
    """Una oferta está en el alcance del usuario si lo ve todo (superadmin) o
    si la tiene asignada."""
    if admin.ve_todo():
        return True
    return oferta.id in set(admin.ofertas_ids())


def _ofertas_visibles_q(db: Session, admin: UsuarioAdmin, solo_activas: bool = False):
    """Query de ofertas acotada al alcance del usuario. Devuelve un Query para
    que cada vista aplique su propio order_by."""
    q = db.query(OfertaLaboral)
    if solo_activas:
        q = q.filter(OfertaLaboral.activo.is_(True))
    if not admin.ve_todo():
        ids = admin.ofertas_ids()
        # Lista vacía ⇒ no ve ninguna (el centinela -1 nunca existe).
        q = q.filter(OfertaLaboral.id.in_(ids if ids else [-1]))
    return q


def _candidato_a_datos(cand: Candidato) -> dict:
    """Arma el diccionario que espera generar_pdf_hoja_de_vida() a partir del
    candidato guardado (mismos campos que el formulario público)."""
    return {
        "consecutivo": cand.consecutivo or "",
        "nombres": cand.nombres or "",
        "apellidos": cand.apellidos or "",
        "tipo_documento": cand.tipo_documento or "",
        "numero_documento": cand.numero_documento or "",
        "fecha_nacimiento": cand.fecha_nacimiento,
        "nacionalidad": cand.nacionalidad or "",
        "correo": cand.correo or "",
        "telefono_celular": cand.telefono_celular or "",
        "linkedin": cand.linkedin or "",
        "ciudad": cand.ciudad or "",
        "pais": cand.pais or "",
        "titular": cand.titular or "",
        "resumen_profesional": cand.resumen_profesional or "",
        "anos_experiencia": cand.anos_experiencia,
        "pretension_salarial": cand.pretension_salarial or "",
        "es_alumni": cand.es_alumni,
        "programa_inalde": cand.programa_inalde or "",
        "disponibilidad_viaje": cand.disponibilidad_viaje,
        "disponibilidad_reubicacion": cand.disponibilidad_reubicacion,
        "habilidades": [{"nombre": h.nombre, "nivel": h.nivel} for h in cand.habilidades],
        "tecnologias": [{"nombre": t.nombre, "nivel": t.nivel} for t in cand.tecnologias],
        "idiomas": [{"idioma": i.idioma, "nivel": i.nivel} for i in cand.idiomas],
        "sectores": [s.sector for s in cand.sectores if s.sector],
        "experiencias": [{
            "cargo": e.cargo, "empresa": e.empresa,
            "fecha_inicio": e.fecha_inicio, "fecha_fin": e.fecha_fin, "actual": e.actual,
            "sector": e.sector, "pais": e.pais,
            "nivel_jerarquico": e.nivel_jerarquico, "lidero_equipo": e.lidero_equipo,
            "tam_equipo": e.tam_equipo, "manejo_pyl": e.manejo_pyl, "funciones": e.funciones,
        } for e in cand.experiencias],
        "formaciones": [{
            "nivel": f.nivel, "titulo": f.titulo, "institucion": f.institucion,
            "anio_inicio": f.anio_inicio, "anio_fin": f.anio_fin, "en_curso": f.en_curso,
        } for f in cand.formaciones],
    }


CATALOGOS = {
    "tipos-documento": (TipoDocumento, ["codigo", "nombre", "activo", "orden"]),
    "nacionalidades": (Nacionalidad, ["codigo", "nombre", "activo", "orden"]),
    "niveles-formacion": (NivelFormacion, ["codigo", "nombre", "peso", "activo", "orden"]),
    "sectores": (Sector, ["codigo", "nombre", "activo", "orden"]),
    "departamentos": (Departamento, ["nombre", "codigo_dane", "activo", "orden"]),
}


# ============================================================
# Autenticación
# ============================================================
@router.get("/login", response_class=HTMLResponse)
def login_view(request: Request, db: Session = Depends(get_db)):
    if get_current_admin_or_redirect(request, db):
        return RedirectResponse("/admin", status_code=303)
    return templates.TemplateResponse(
        "admin/login.html",
        {"request": request, "anio_actual": now_local().year, "app_name": config.APP_NAME},
    )


@router.post("/login")
def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    user = db.query(UsuarioAdmin).filter(UsuarioAdmin.username == username.strip()).first()
    if not user or not user.activo or not verify_password(password, user.password_hash):
        return templates.TemplateResponse(
            "admin/login.html",
            {
                "request": request, "error": "Credenciales inválidas",
                "username": username, "anio_actual": now_local().year,
                "app_name": config.APP_NAME,
            },
            status_code=401,
        )
    user.ultimo_acceso = now_utc_naive()
    db.commit()
    token = create_session_token(user.id)
    resp = RedirectResponse("/admin", status_code=303)
    resp.set_cookie(
        key=COOKIE_NAME, value=token, max_age=SESSION_MAX_AGE,
        httponly=True, samesite="lax", secure=False,
    )
    return resp


@router.post("/logout")
def logout():
    resp = RedirectResponse("/admin/login", status_code=303)
    resp.delete_cookie(COOKIE_NAME)
    return resp


# ============================================================
# Dashboard
# ============================================================
@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(get_db)):
    admin = get_current_admin_or_redirect(request, db)
    if not admin:
        return RedirectResponse("/admin/login", status_code=303)

    ve_todo = admin.ve_todo()
    oferta_ids = None if ve_todo else (admin.ofertas_ids() or [])

    if not ve_todo and not oferta_ids:
        # Usuario acotado sin ofertas asignadas: aún no ve nada.
        total_candidatos = total_ofertas = ofertas_abiertas = total_evaluaciones = 0
        recomendados = 0
        conteo_estados = [{"estado": est, "n": 0} for est in CANDIDATO_WORKFLOW.estados]
        ult_eval = []
    else:
        cand_count_q = db.query(func.count(Candidato.id))
        eval_count_q = db.query(func.count(Evaluacion.id))
        eval_list_q = db.query(Evaluacion)
        if not ve_todo:
            # Candidatos en alcance = los que tienen alguna evaluación contra
            # una de las ofertas asignadas.
            cand_in = Candidato.id.in_(
                db.query(Evaluacion.candidato_id).filter(Evaluacion.oferta_id.in_(oferta_ids))
            )
            cand_count_q = cand_count_q.filter(cand_in)
            eval_count_q = eval_count_q.filter(Evaluacion.oferta_id.in_(oferta_ids))
            eval_list_q = eval_list_q.filter(Evaluacion.oferta_id.in_(oferta_ids))

        total_candidatos = cand_count_q.scalar() or 0
        if ve_todo:
            total_ofertas = db.query(func.count(OfertaLaboral.id)).scalar() or 0
            ofertas_abiertas = db.query(func.count(OfertaLaboral.id)).filter(
                OfertaLaboral.estado == "abierta"
            ).scalar() or 0
        else:
            total_ofertas = len(oferta_ids)
            ofertas_abiertas = db.query(func.count(OfertaLaboral.id)).filter(
                OfertaLaboral.id.in_(oferta_ids), OfertaLaboral.estado == "abierta"
            ).scalar() or 0
        total_evaluaciones = eval_count_q.scalar() or 0

        conteo_estados = []
        for est in CANDIDATO_WORKFLOW.estados:
            n = cand_count_q.filter(Candidato.estado == est.codigo).scalar() or 0
            conteo_estados.append({"estado": est, "n": n})

        recomendados = eval_count_q.filter(
            Evaluacion.puntuacion >= 80, Evaluacion.resultado_eliminatorio == "cumple"
        ).scalar() or 0

        ult_eval = eval_list_q.order_by(Evaluacion.fecha_evaluacion.desc()).limit(8).all()

    return templates.TemplateResponse(
        "admin/dashboard.html",
        _ctx(
            request, admin,
            total_candidatos=total_candidatos,
            total_ofertas=total_ofertas,
            ofertas_abiertas=ofertas_abiertas,
            total_evaluaciones=total_evaluaciones,
            recomendados=recomendados,
            conteo_estados=conteo_estados,
            ultimas_evaluaciones=ult_eval,
        ),
    )


# ============================================================
# Candidatos
# ============================================================
@router.get("/candidatos", response_class=HTMLResponse)
def candidatos_view(
    request: Request,
    estado: Optional[str] = Query(None),
    q: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    admin = get_current_admin_or_redirect(request, db)
    if not admin:
        return RedirectResponse("/admin/login", status_code=303)

    query = db.query(Candidato)
    if estado:
        query = query.filter(Candidato.estado == estado)
    if q:
        like = f"%{q.strip()}%"
        query = query.filter(
            (Candidato.nombres.ilike(like))
            | (Candidato.apellidos.ilike(like))
            | (Candidato.numero_documento.ilike(like))
            | (Candidato.correo.ilike(like))
            | (Candidato.consecutivo.ilike(like))
        )
    candidatos = query.order_by(Candidato.fecha_registro.desc()).all()
    if not admin.ve_todo():
        candidatos = [c for c in candidatos if _candidato_en_alcance(c, admin)]

    return templates.TemplateResponse(
        "admin/candidatos.html",
        _ctx(
            request, admin,
            candidatos=candidatos,
            filtro_estado=estado or "",
            filtro_q=q or "",
            estado_info=_estado_info,
        ),
    )


@router.get("/candidatos/{cand_id}", response_class=HTMLResponse)
def candidato_detalle(request: Request, cand_id: int, db: Session = Depends(get_db)):
    admin = get_current_admin_or_redirect(request, db)
    if not admin:
        return RedirectResponse("/admin/login", status_code=303)
    cand = db.query(Candidato).filter(Candidato.id == cand_id).first()
    if not cand:
        raise HTTPException(status_code=404, detail="Candidato no encontrado")
    if not _candidato_en_alcance(cand, admin):
        raise HTTPException(status_code=403, detail="Fuera de su alcance")

    ofertas = _ofertas_visibles_q(db, admin, solo_activas=True).order_by(
        OfertaLaboral.orden, OfertaLaboral.titulo
    ).all()
    evaluaciones = (
        db.query(Evaluacion).filter(Evaluacion.candidato_id == cand_id)
        .order_by(Evaluacion.puntuacion.desc()).all()
    )
    eval_por_oferta = {}
    for ev in evaluaciones:
        eval_por_oferta[ev.oferta_id] = json.loads(ev.resultado_json) if ev.resultado_json else {}

    # Historial de estados y comentarios (auditoría). Incluye el alta por el
    # formulario público, los cambios de estado y los comentarios sueltos.
    historial = (
        db.query(CambioEstadoAuditoria)
        .filter(
            CambioEstadoAuditoria.entity_type == CANDIDATO_WORKFLOW.entity_type,
            CambioEstadoAuditoria.entity_id == cand_id,
        )
        .order_by(CambioEstadoAuditoria.fecha_cambio.desc(), CambioEstadoAuditoria.id.desc())
        .all()
    )

    return templates.TemplateResponse(
        "admin/candidato_detalle.html",
        _ctx(
            request, admin,
            cand=cand,
            ofertas=ofertas,
            evaluaciones=evaluaciones,
            eval_por_oferta=eval_por_oferta,
            estado_info=_estado_info,
            historial=historial,
        ),
    )


@router.get("/candidatos/{cand_id}/cv")
def descargar_cv(
    request: Request, cand_id: int,
    inline: bool = Query(False),
    db: Session = Depends(get_db),
):
    admin = get_current_admin_or_redirect(request, db)
    if not admin:
        return RedirectResponse("/admin/login", status_code=303)
    cand = db.query(Candidato).filter(Candidato.id == cand_id).first()
    if not cand or not cand.cv_archivo:
        raise HTTPException(status_code=404, detail="CV no disponible")
    if not _candidato_en_alcance(cand, admin):
        raise HTTPException(status_code=403, detail="Fuera de su alcance")
    ruta = config.UPLOAD_DIR / cand.cv_archivo
    if not ruta.exists():
        raise HTTPException(status_code=404, detail="Archivo no encontrado en disco")
    # inline=1 ⇒ el navegador lo muestra en el visor (modal); por defecto se descarga.
    return FileResponse(
        str(ruta), media_type="application/pdf",
        filename=cand.cv_archivo_original or f"{cand.consecutivo}.pdf",
        content_disposition_type="inline" if inline else "attachment",
    )


@router.get("/candidatos/{cand_id}/hoja-de-vida")
def descargar_hoja_de_vida(
    request: Request, cand_id: int,
    db: Session = Depends(get_db),
):
    """Genera y descarga una hoja de vida con formato INALDE a partir de los
    datos que el candidato ingresó en el formulario (no del PDF que adjuntó)."""
    admin = get_current_admin_or_redirect(request, db)
    if not admin:
        return RedirectResponse("/admin/login", status_code=303)
    cand = db.query(Candidato).filter(Candidato.id == cand_id).first()
    if not cand:
        raise HTTPException(status_code=404, detail="Candidato no encontrado")
    if not _candidato_en_alcance(cand, admin):
        raise HTTPException(status_code=403, detail="Fuera de su alcance")
    try:
        pdf = generar_pdf_hoja_de_vida(_candidato_a_datos(cand))
    except Exception as e:  # noqa: BLE001
        log.exception("Error generando hoja de vida (cand=%s): %s", cand_id, e)
        raise HTTPException(status_code=500, detail="No se pudo generar la hoja de vida.")
    nombre = f"{cand.nombres} {cand.apellidos}".strip() or (cand.consecutivo or "candidato")
    base = f"Hoja de vida - {nombre}"
    # Las cabeceras HTTP no admiten UTF-8 directo (un nombre con tildes como
    # "José Peña" rompía la descarga). RFC 5987/6266: nombre ASCII de respaldo
    # + filename* en UTF-8 percent-encoded para los navegadores modernos.
    ascii_fallback = (base.encode("ascii", "ignore").decode("ascii").strip() or "Hoja de vida")
    disposition = (
        f"attachment; filename=\"{ascii_fallback}.pdf\"; "
        f"filename*=UTF-8''{quote(base + '.pdf')}"
    )
    return Response(
        content=pdf, media_type="application/pdf",
        headers={"Content-Disposition": disposition},
    )


@router.post("/candidatos/{cand_id}/estado")
def cambiar_estado(
    request: Request, cand_id: int,
    nuevo_estado: str = Form(...),
    comentario: str = Form(""),
    db: Session = Depends(get_db),
    admin: UsuarioAdmin = Depends(get_current_admin),
):
    cand = db.query(Candidato).filter(Candidato.id == cand_id).first()
    if not cand:
        raise HTTPException(status_code=404, detail="Candidato no encontrado")
    if not _candidato_en_alcance(cand, admin):
        raise HTTPException(status_code=403, detail="Fuera de su alcance")
    try:
        nuevo = CANDIDATO_WORKFLOW.validar(nuevo_estado)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    ahora = now_utc_naive()
    anterior = cand.estado
    dur = segundos_transcurridos(cand.fecha_estado_actual, ahora)
    cand.estado = nuevo
    cand.fecha_estado_actual = ahora
    cand.fecha_actualizacion_estado = ahora
    if CANDIDATO_WORKFLOW.es_terminal(nuevo):
        cand.fecha_finalizacion_estado = ahora
    db.add(CambioEstadoAuditoria(
        entity_type=CANDIDATO_WORKFLOW.entity_type, entity_id=cand.id,
        estado_anterior=anterior, estado_nuevo=nuevo, comentario=comentario or None,
        usuario_admin_id=admin.id, fecha_cambio=ahora, duracion_estado_segundos=dur,
    ))
    db.commit()
    return RedirectResponse(f"/admin/candidatos/{cand_id}", status_code=303)


@router.post("/candidatos/{cand_id}/comentar")
def comentar_candidato(
    request: Request, cand_id: int,
    comentario: str = Form(...),
    db: Session = Depends(get_db),
    admin: UsuarioAdmin = Depends(get_current_admin),
):
    """Registra un comentario SIN cambiar el estado del candidato. Queda
    visible en el historial junto con quién lo dejó y cuándo."""
    cand = db.query(Candidato).filter(Candidato.id == cand_id).first()
    if not cand:
        raise HTTPException(status_code=404, detail="Candidato no encontrado")
    if not _candidato_en_alcance(cand, admin):
        raise HTTPException(status_code=403, detail="Fuera de su alcance")
    texto = (comentario or "").strip()
    if not texto:
        # Nada que registrar; volvemos sin crear ruido en la auditoría.
        return RedirectResponse(f"/admin/candidatos/{cand_id}", status_code=303)
    ahora = now_utc_naive()
    db.add(CambioEstadoAuditoria(
        entity_type=CANDIDATO_WORKFLOW.entity_type, entity_id=cand.id,
        estado_anterior=cand.estado, estado_nuevo=cand.estado, comentario=texto,
        usuario_admin_id=admin.id, fecha_cambio=ahora, duracion_estado_segundos=None,
        metadata_json=json.dumps({"solo_comentario": True}, ensure_ascii=False),
    ))
    db.commit()
    return RedirectResponse(f"/admin/candidatos/{cand_id}", status_code=303)


# ============================================================
# Curaduría (motor ATS determinista)
# ============================================================
@router.post("/candidatos/{cand_id}/curar")
def ejecutar_curaduria(
    request: Request, cand_id: int,
    oferta_id: int = Form(...),
    db: Session = Depends(get_db),
    admin: UsuarioAdmin = Depends(get_current_admin),
):
    cand = db.query(Candidato).filter(Candidato.id == cand_id).first()
    oferta = db.query(OfertaLaboral).filter(OfertaLaboral.id == oferta_id).first()
    if not cand or not oferta:
        raise HTTPException(status_code=404, detail="Candidato u oferta no encontrados")
    if not _oferta_en_alcance(oferta, admin):
        raise HTTPException(status_code=403, detail="Fuera de su alcance")

    resultado = ats_engine.evaluar(cand, oferta)

    ev = (
        db.query(Evaluacion)
        .filter(Evaluacion.candidato_id == cand_id, Evaluacion.oferta_id == oferta_id)
        .first()
    )
    if not ev:
        ev = Evaluacion(candidato_id=cand_id, oferta_id=oferta_id)
        db.add(ev)
    ev.puntuacion = resultado["puntuacion"]
    ev.nivel_recomendacion = resultado["nivel_recomendacion"]
    ev.resultado_eliminatorio = resultado["resultado_eliminatorio"]
    ev.modo_busqueda_aplicado = resultado["modo_busqueda_aplicado"]
    ev.complejidad_nivel = resultado["complejidad_gestionada"]["nivel"]
    ev.resumen_ejecutivo = resultado["resumen_ejecutivo_match"]
    ev.resultado_json = json.dumps(resultado, ensure_ascii=False)
    ev.fecha_evaluacion = now_utc_naive()
    ev.evaluado_por = admin.id

    # Si estaba 'recibido', avanza a 'en_evaluacion'.
    if cand.estado == "recibido":
        cand.estado = "en_evaluacion"
        cand.fecha_estado_actual = now_utc_naive()
    db.commit()
    return RedirectResponse(f"/admin/candidatos/{cand_id}#oferta-{oferta_id}", status_code=303)


@router.post("/ofertas/{oferta_id}/curar-todos")
def curar_todos(
    request: Request, oferta_id: int,
    db: Session = Depends(get_db),
    admin: UsuarioAdmin = Depends(get_current_admin),
):
    """Evalúa todos los candidatos contra una oferta (curaduría masiva)."""
    oferta = db.query(OfertaLaboral).filter(OfertaLaboral.id == oferta_id).first()
    if not oferta:
        raise HTTPException(status_code=404, detail="Oferta no encontrada")
    if not _oferta_en_alcance(oferta, admin):
        raise HTTPException(status_code=403, detail="Fuera de su alcance")
    candidatos = db.query(Candidato).all()
    for cand in candidatos:
        resultado = ats_engine.evaluar(cand, oferta)
        ev = (
            db.query(Evaluacion)
            .filter(Evaluacion.candidato_id == cand.id, Evaluacion.oferta_id == oferta_id)
            .first()
        )
        if not ev:
            ev = Evaluacion(candidato_id=cand.id, oferta_id=oferta_id)
            db.add(ev)
        ev.puntuacion = resultado["puntuacion"]
        ev.nivel_recomendacion = resultado["nivel_recomendacion"]
        ev.resultado_eliminatorio = resultado["resultado_eliminatorio"]
        ev.modo_busqueda_aplicado = resultado["modo_busqueda_aplicado"]
        ev.complejidad_nivel = resultado["complejidad_gestionada"]["nivel"]
        ev.resumen_ejecutivo = resultado["resumen_ejecutivo_match"]
        ev.resultado_json = json.dumps(resultado, ensure_ascii=False)
        ev.fecha_evaluacion = now_utc_naive()
        ev.evaluado_por = admin.id
    db.commit()
    return RedirectResponse(f"/admin/ofertas/{oferta_id}/ranking", status_code=303)


# ============================================================
# Ofertas laborales
# ============================================================
def _parse_json_field(raw: str, default):
    raw = (raw or "").strip()
    if not raw:
        return default
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        # admitir listas separadas por comas / saltos de línea
        items = [x.strip() for x in raw.replace("\n", ",").split(",") if x.strip()]
        return items if items else default


CODIGO_OFERTA_PREFIJO = "OFE-"
CODIGO_OFERTA_DIGITOS = 8


def _siguiente_codigo_oferta(db: Session) -> str:
    """Genera el siguiente código de oferta con la nomenclatura
    `OFE-00000000` (prefijo + 8 dígitos). Toma el mayor consecutivo
    numérico existente y suma 1, ignorando códigos que no sigan el
    patrón. Verifica unicidad por si quedaran códigos heredados.
    """
    patron = re.compile(rf"^{re.escape(CODIGO_OFERTA_PREFIJO)}(\d+)$")
    maximo = 0
    for (codigo,) in db.query(OfertaLaboral.codigo).all():
        if not codigo:
            continue
        m = patron.match(codigo.strip())
        if m:
            maximo = max(maximo, int(m.group(1)))
    siguiente = maximo + 1
    # Bucle defensivo de unicidad.
    while True:
        candidato = f"{CODIGO_OFERTA_PREFIJO}{siguiente:0{CODIGO_OFERTA_DIGITOS}d}"
        existe = db.query(OfertaLaboral.id).filter(OfertaLaboral.codigo == candidato).first()
        if not existe:
            return candidato
        siguiente += 1


@router.get("/ofertas", response_class=HTMLResponse)
def ofertas_view(request: Request, db: Session = Depends(get_db)):
    admin = get_current_admin_or_redirect(request, db)
    if not admin:
        return RedirectResponse("/admin/login", status_code=303)
    ofertas = db.query(OfertaLaboral).order_by(OfertaLaboral.orden, OfertaLaboral.fecha_creacion.desc()).all()
    if not admin.ve_todo():
        ids = set(admin.ofertas_ids())
        ofertas = [o for o in ofertas if o.id in ids]
    conteos = {}
    for o in ofertas:
        conteos[o.id] = db.query(func.count(Evaluacion.id)).filter(Evaluacion.oferta_id == o.id).scalar() or 0
    return templates.TemplateResponse(
        "admin/ofertas.html",
        _ctx(request, admin, ofertas=ofertas, conteos=conteos),
    )


@router.get("/ofertas/nueva", response_class=HTMLResponse)
def oferta_nueva(request: Request, db: Session = Depends(get_db)):
    admin = get_current_admin_or_redirect(request, db)
    if not admin:
        return RedirectResponse("/admin/login", status_code=303)
    sectores = db.query(Sector).filter(Sector.activo.is_(True)).order_by(Sector.nombre).all()
    niveles = db.query(NivelFormacion).filter(NivelFormacion.activo.is_(True)).order_by(NivelFormacion.peso).all()
    return templates.TemplateResponse(
        "admin/oferta_form.html",
        _ctx(
            request, admin, oferta=None, sectores=sectores, niveles=niveles,
            criterios=ats_engine.CRITERIOS, pesos_default=ats_engine.PESOS_DEFAULT,
        ),
    )


@router.get("/ofertas/{oferta_id}/editar", response_class=HTMLResponse)
def oferta_editar(request: Request, oferta_id: int, db: Session = Depends(get_db)):
    admin = get_current_admin_or_redirect(request, db)
    if not admin:
        return RedirectResponse("/admin/login", status_code=303)
    oferta = db.query(OfertaLaboral).filter(OfertaLaboral.id == oferta_id).first()
    if not oferta:
        raise HTTPException(status_code=404, detail="Oferta no encontrada")
    if not _oferta_en_alcance(oferta, admin):
        raise HTTPException(status_code=403, detail="Fuera de su alcance")
    sectores = db.query(Sector).filter(Sector.activo.is_(True)).order_by(Sector.nombre).all()
    niveles = db.query(NivelFormacion).filter(NivelFormacion.activo.is_(True)).order_by(NivelFormacion.peso).all()
    return templates.TemplateResponse(
        "admin/oferta_form.html",
        _ctx(
            request, admin, oferta=oferta, sectores=sectores, niveles=niveles,
            criterios=ats_engine.CRITERIOS, pesos_default=ats_engine.PESOS_DEFAULT,
        ),
    )


async def _leer_form_oferta(request: Request) -> dict:
    form = await request.form()
    return {k: (v if isinstance(v, str) else v) for k, v in form.items()}


@router.post("/ofertas/guardar")
async def oferta_guardar(
    request: Request,
    db: Session = Depends(get_db),
    admin: UsuarioAdmin = Depends(get_current_admin),
):
    f = await request.form()

    def g(name, default=""):
        return (f.get(name) or default).strip() if isinstance(f.get(name), str) else f.get(name, default)

    def gi(name, default=0):
        v = (f.get(name) or "").strip()
        return int(v) if v else default

    def gb(name):
        return (f.get(name) or "") in ("1", "true", "on", "yes")

    oferta_id = g("id")
    if oferta_id:
        oferta = db.query(OfertaLaboral).filter(OfertaLaboral.id == int(oferta_id)).first()
        if not oferta:
            raise HTTPException(status_code=404, detail="Oferta no encontrada")
        if not _oferta_en_alcance(oferta, admin):
            raise HTTPException(status_code=403, detail="Fuera de su alcance")
    else:
        oferta = OfertaLaboral()
        db.add(oferta)

    # El código se asigna automáticamente (OFE-00000000) al crear y no se
    # edita después; ignoramos cualquier valor enviado desde el formulario.
    if not oferta_id:
        oferta.codigo = _siguiente_codigo_oferta(db)
    oferta.titulo = g("titulo")
    oferta.area = g("area") or None
    oferta.descripcion = g("descripcion") or None
    oferta.requisitos_tecnicos = g("requisitos_tecnicos") or None
    oferta.requisitos_experiencia = g("requisitos_experiencia") or None
    oferta.requisitos_educacion = g("requisitos_educacion") or None
    oferta.area_estudio = g("area_estudio") or None
    oferta.sector = g("sector") or None
    oferta.ubicacion = g("ubicacion") or None
    oferta.tipo_empresa = g("tipo_empresa") or None
    oferta.contexto_organizacional = g("contexto_organizacional") or None
    oferta.reto_principal = g("reto_principal") or None

    oferta.modo_busqueda = g("modo_busqueda", "hibrido") or "hibrido"
    oferta.importancia_sector = g("importancia_sector", "medio") or "medio"
    oferta.sectores_transferibles = json.dumps(
        _parse_json_field(g("sectores_transferibles"), []), ensure_ascii=False
    )
    oferta.anos_experiencia_min = gi("anos_experiencia_min", 0)
    oferta.nivel_jerarquico_min = g("nivel_jerarquico_min") or None
    oferta.idioma_requerido = g("idioma_requerido") or None
    oferta.idioma_nivel_min = g("idioma_nivel_min") or None
    oferta.pais_requerido = g("pais_requerido") or None
    oferta.ciudad_requerida = g("ciudad_requerida") or None
    oferta.requiere_internacional = gb("requiere_internacional")
    oferta.requiere_liderazgo = gb("requiere_liderazgo")
    oferta.requiere_pyl = gb("requiere_pyl")
    oferta.formacion_min = g("formacion_min") or None
    oferta.skills_requeridos = json.dumps(
        _parse_json_field(g("skills_requeridos"), []), ensure_ascii=False
    )
    oferta.tecnologias_requeridas = json.dumps(
        _parse_json_field(g("tecnologias_requeridas"), []), ensure_ascii=False
    )

    # Pesos: tomar pesos_<criterio> si vienen; si no, default del modo.
    pesos = {}
    for c in ats_engine.CRITERIOS:
        val = (f.get(f"peso_{c}") or "").strip()
        if val:
            pesos[c] = int(val)
    if pesos:
        oferta.pesos = json.dumps(pesos, ensure_ascii=False)
    else:
        oferta.pesos = None  # usará el default del modo en el motor

    # Requisitos eliminatorios derivados de los checkboxes/campos.
    eliminatorios = []
    if oferta.anos_experiencia_min:
        eliminatorios.append({"criterio": "experiencia", "valor": oferta.anos_experiencia_min,
                              "descripcion": f"Mínimo {oferta.anos_experiencia_min} años de experiencia"})
    if oferta.idioma_requerido:
        eliminatorios.append({"criterio": "idioma", "valor": oferta.idioma_requerido,
                              "nivel": oferta.idioma_nivel_min,
                              "descripcion": f"{oferta.idioma_requerido} nivel {oferta.idioma_nivel_min or 'requerido'}"})
    if oferta.formacion_min:
        _desc_form = f"Formación mínima: {oferta.formacion_min}"
        if oferta.area_estudio:
            _desc_form += f" · Área: {oferta.area_estudio}"
        eliminatorios.append({"criterio": "formacion", "valor": oferta.formacion_min,
                              "area_estudio": oferta.area_estudio,
                              "descripcion": _desc_form})
    if oferta.requiere_liderazgo:
        eliminatorios.append({"criterio": "liderazgo", "descripcion": "Experiencia liderando equipos"})
    if oferta.requiere_pyl:
        eliminatorios.append({"criterio": "pyl", "descripcion": "Responsabilidad sobre P&L"})
    if oferta.requiere_internacional:
        eliminatorios.append({"criterio": "internacional", "descripcion": "Experiencia internacional"})
    if oferta.pais_requerido or oferta.ciudad_requerida:
        eliminatorios.append({"criterio": "geografia",
                              "pais": oferta.pais_requerido, "ciudad": oferta.ciudad_requerida,
                              "descripcion": f"Ubicación: {oferta.ciudad_requerida or ''} {oferta.pais_requerido or ''}".strip()})
    # Permitir override manual por JSON.
    manual = _parse_json_field(g("requisitos_eliminatorios"), None)
    if isinstance(manual, list) and manual:
        eliminatorios = manual
    oferta.requisitos_eliminatorios = json.dumps(eliminatorios, ensure_ascii=False)

    oferta.reglas_compensacion = json.dumps(
        _parse_json_field(g("reglas_compensacion"), {}), ensure_ascii=False
    )
    oferta.estado = g("estado", "abierta") or "abierta"
    oferta.activo = oferta.estado == "abierta"
    if not oferta_id:
        oferta.fecha_creacion = now_utc_naive()

    # Si quien crea la oferta es un usuario acotado (administrador o revisor),
    # se la asignamos para que no la pierda de vista apenas la guarda.
    if not oferta_id and not admin.es_superadmin:
        creador = db.get(UsuarioAdmin, admin.id)
        if creador is not None and creador not in oferta.usuarios:
            oferta.usuarios.append(creador)

    db.commit()
    db.refresh(oferta)
    return RedirectResponse(f"/admin/ofertas/{oferta.id}/ranking", status_code=303)


@router.post("/ofertas/{oferta_id}/eliminar")
def oferta_eliminar(
    oferta_id: int,
    db: Session = Depends(get_db),
    admin: UsuarioAdmin = Depends(require_gestor_catalogos),
):
    oferta = db.query(OfertaLaboral).filter(OfertaLaboral.id == oferta_id).first()
    if oferta:
        if not _oferta_en_alcance(oferta, admin):
            raise HTTPException(status_code=403, detail="Fuera de su alcance")
        db.delete(oferta)
        db.commit()
    return RedirectResponse("/admin/ofertas", status_code=303)


@router.get("/ofertas/{oferta_id}/ranking", response_class=HTMLResponse)
def oferta_ranking(request: Request, oferta_id: int, db: Session = Depends(get_db)):
    admin = get_current_admin_or_redirect(request, db)
    if not admin:
        return RedirectResponse("/admin/login", status_code=303)
    oferta = db.query(OfertaLaboral).filter(OfertaLaboral.id == oferta_id).first()
    if not oferta:
        raise HTTPException(status_code=404, detail="Oferta no encontrada")
    if not _oferta_en_alcance(oferta, admin):
        raise HTTPException(status_code=403, detail="Fuera de su alcance")
    evaluaciones = (
        db.query(Evaluacion)
        .filter(Evaluacion.oferta_id == oferta_id)
        .order_by(Evaluacion.puntuacion.desc())
        .all()
    )
    total_candidatos = db.query(func.count(Candidato.id)).scalar() or 0
    return templates.TemplateResponse(
        "admin/oferta_ranking.html",
        _ctx(
            request, admin, oferta=oferta, evaluaciones=evaluaciones,
            total_candidatos=total_candidatos, estado_info=_estado_info,
        ),
    )


# ============================================================
# Catálogos (vista individual por catálogo + CRUD server-side)
# ============================================================
CATALOGOS_META = {
    "tipos-documento": {"label": "Tipos de documento", "campos": ["codigo", "nombre"]},
    "nacionalidades": {"label": "Nacionalidades", "campos": ["codigo", "nombre"]},
    "niveles-formacion": {"label": "Niveles de formación", "campos": ["codigo", "nombre", "peso"]},
    "sectores": {"label": "Sectores", "campos": ["codigo", "nombre"]},
    "departamentos": {"label": "Departamentos", "campos": ["codigo_dane", "nombre"]},
}


@router.get("/catalogos", response_class=HTMLResponse)
def catalogos_index(request: Request, db: Session = Depends(get_db)):
    # Redirige al primer catálogo individual.
    return RedirectResponse("/admin/catalogos/tipos-documento", status_code=303)


@router.get("/catalogos/{nombre}", response_class=HTMLResponse)
def catalogo_view(request: Request, nombre: str, db: Session = Depends(get_db)):
    admin = get_current_admin_or_redirect(request, db)
    if not admin:
        return RedirectResponse("/admin/login", status_code=303)
    if not admin.puede_gestionar_catalogos():
        return RedirectResponse("/admin", status_code=303)
    if nombre not in CATALOGOS:
        raise HTTPException(status_code=404, detail="Catálogo no existe")
    Model, _ = CATALOGOS[nombre]
    items = db.query(Model).order_by(getattr(Model, "orden", Model.id)).all()
    meta = CATALOGOS_META.get(nombre, {"label": nombre, "campos": ["codigo", "nombre"]})
    return templates.TemplateResponse(
        "admin/catalogo.html",
        _ctx(
            request, admin, nombre=nombre, items=items,
            meta=meta, total=len(items),
        ),
    )


@router.post("/catalogos/{nombre}/crear")
async def catalogo_crear_form(
    nombre: str, request: Request,
    db: Session = Depends(get_db),
    admin: UsuarioAdmin = Depends(require_gestor_catalogos),
):
    if nombre not in CATALOGOS:
        raise HTTPException(status_code=404, detail="Catálogo no existe")
    Model, _ = CATALOGOS[nombre]
    meta = CATALOGOS_META.get(nombre, {"campos": ["codigo", "nombre"]})
    form = await request.form()
    obj = Model()
    for fld in meta["campos"]:
        val = (form.get(fld) or "").strip()
        if fld == "peso":
            setattr(obj, fld, int(val) if val else 0)
        else:
            setattr(obj, fld, val or None)
    # Orden automático al final.
    if hasattr(obj, "orden"):
        ult = db.query(func.max(Model.orden)).scalar() or 0
        obj.orden = ult + 1
    if hasattr(obj, "activo"):
        obj.activo = True
    db.add(obj)
    db.commit()
    return RedirectResponse(f"/admin/catalogos/{nombre}", status_code=303)


@router.post("/catalogos/{nombre}/{item_id}/actualizar")
async def catalogo_actualizar_form(
    nombre: str, item_id: int, request: Request,
    db: Session = Depends(get_db),
    admin: UsuarioAdmin = Depends(require_gestor_catalogos),
):
    """Edita un registro de catálogo: campos del catálogo + activo + orden."""
    if nombre not in CATALOGOS:
        raise HTTPException(status_code=404, detail="Catálogo no existe")
    Model, _ = CATALOGOS[nombre]
    meta = CATALOGOS_META.get(nombre, {"campos": ["codigo", "nombre"]})
    obj = db.query(Model).filter(Model.id == item_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Registro no encontrado")
    form = await request.form()
    for fld in meta["campos"]:
        if fld not in form:
            continue
        val = (form.get(fld) or "").strip()
        if fld == "peso":
            setattr(obj, fld, int(val) if val else 0)
        else:
            setattr(obj, fld, val or None)
    if hasattr(obj, "orden") and "orden" in form:
        val = (form.get("orden") or "").strip()
        if val:
            obj.orden = int(val)
    if hasattr(obj, "activo"):
        obj.activo = (form.get("activo") or "") in ("1", "true", "on", "yes")
    db.commit()
    return RedirectResponse(f"/admin/catalogos/{nombre}", status_code=303)


@router.post("/catalogos/{nombre}/{item_id}/eliminar")
def catalogo_eliminar_form(
    nombre: str, item_id: int,
    db: Session = Depends(get_db),
    admin: UsuarioAdmin = Depends(require_gestor_catalogos),
):
    if nombre not in CATALOGOS:
        raise HTTPException(status_code=404, detail="Catálogo no existe")
    Model, _ = CATALOGOS[nombre]
    obj = db.query(Model).filter(Model.id == item_id).first()
    if obj:
        db.delete(obj)
        db.commit()
    return RedirectResponse(f"/admin/catalogos/{nombre}", status_code=303)


def _serialize(obj, fields: List[str]) -> dict:
    return {f: getattr(obj, f, None) for f in fields} | {"id": obj.id}


@router.post("/api/catalogos/{nombre}")
async def catalogo_crear(
    nombre: str, request: Request,
    db: Session = Depends(get_db),
    admin: UsuarioAdmin = Depends(require_gestor_catalogos),
):
    if nombre not in CATALOGOS:
        raise HTTPException(status_code=404, detail="Catálogo no existe")
    Model, fields = CATALOGOS[nombre]
    try:
        data = await request.json()
    except Exception:
        data = {}
    obj = Model()
    for fld in fields:
        if fld in data:
            setattr(obj, fld, data[fld])
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return JSONResponse(_serialize(obj, fields))


@router.delete("/api/catalogos/{nombre}/{item_id}")
def catalogo_eliminar(
    nombre: str, item_id: int,
    db: Session = Depends(get_db),
    admin: UsuarioAdmin = Depends(require_gestor_catalogos),
):
    if nombre not in CATALOGOS:
        raise HTTPException(status_code=404, detail="Catálogo no existe")
    Model, _ = CATALOGOS[nombre]
    obj = db.query(Model).filter(Model.id == item_id).first()
    if obj:
        db.delete(obj)
        db.commit()
    return JSONResponse({"ok": True})


# ============================================================
# Gestión de usuarios (solo superadmin)
# ============================================================
ROLES_ASIGNABLES = [
    ("admin", "Administrador", "Gestiona candidatos, ofertas y catálogos de las ofertas que tenga asignadas. No administra usuarios."),
    ("revisor", "Revisor", "Solo ve y evalúa los candidatos de las ofertas que tenga asignadas."),
]
_ROLES_ASIGNABLES = {r[0] for r in ROLES_ASIGNABLES}


def _contar_superadmins_activos(db: Session, excluir_id: Optional[int] = None) -> int:
    q = db.query(UsuarioAdmin).filter(
        UsuarioAdmin.rol == "superadmin", UsuarioAdmin.activo.is_(True)
    )
    if excluir_id is not None:
        q = q.filter(UsuarioAdmin.id != excluir_id)
    return q.count()


def _asignar_ofertas(db: Session, u: UsuarioAdmin, ids: List[int]) -> None:
    """Asigna ofertas (alcance) a un rol acotado (administrador o revisor).
    El superadministrador ve todo, así que nunca se le asignan ofertas."""
    if u.es_superadmin:
        u.ofertas = []
        return
    ids = [int(i) for i in ids if str(i).strip().isdigit()]
    ids = list(dict.fromkeys(ids))
    if not ids:
        u.ofertas = []
        return
    ofertas = db.query(OfertaLaboral).filter(OfertaLaboral.id.in_(ids)).all()
    u.ofertas = ofertas


@router.get("/usuarios", response_class=HTMLResponse)
def usuarios_view(request: Request, db: Session = Depends(get_db)):
    admin = get_current_admin_or_redirect(request, db)
    if not admin:
        return RedirectResponse("/admin/login", status_code=303)
    if not admin.es_superadmin:
        return RedirectResponse("/admin", status_code=303)
    usuarios = (
        db.query(UsuarioAdmin)
        .order_by(UsuarioAdmin.activo.desc(), UsuarioAdmin.username)
        .all()
    )
    ofertas = db.query(OfertaLaboral).order_by(OfertaLaboral.titulo).all()
    return templates.TemplateResponse(
        "admin/usuarios.html",
        _ctx(
            request, admin, usuarios=usuarios, ofertas=ofertas,
            roles_asignables=ROLES_ASIGNABLES,
        ),
    )


@router.post("/usuarios/crear")
async def usuarios_crear(
    request: Request,
    db: Session = Depends(get_db),
    admin: UsuarioAdmin = Depends(require_superadmin),
):
    form = await request.form()
    username = (form.get("username") or "").strip().lower()
    password = (form.get("password") or "").strip()
    nombre = (form.get("nombre_completo") or "").strip()
    rol = (form.get("rol") or "revisor").strip().lower()
    ofertas_ids = form.getlist("ofertas") if hasattr(form, "getlist") else []

    if rol not in _ROLES_ASIGNABLES:
        raise HTTPException(422, f"Rol no asignable: {rol}")
    if len(username) < 3:
        raise HTTPException(422, "El usuario debe tener al menos 3 caracteres.")
    if len(password) < 8:
        raise HTTPException(422, "La contraseña debe tener al menos 8 caracteres.")
    if db.query(UsuarioAdmin).filter(UsuarioAdmin.username == username).first():
        raise HTTPException(409, f"Ya existe el usuario '{username}'.")

    u = UsuarioAdmin(
        username=username, password_hash=hash_password(password),
        nombre_completo=nombre or None, rol=rol, activo=True,
    )
    db.add(u)
    db.flush()
    _asignar_ofertas(db, u, list(ofertas_ids))
    db.commit()
    return RedirectResponse("/admin/usuarios", status_code=303)


@router.post("/usuarios/{user_id}/actualizar")
async def usuarios_actualizar(
    user_id: int, request: Request,
    db: Session = Depends(get_db),
    admin: UsuarioAdmin = Depends(require_superadmin),
):
    u = db.query(UsuarioAdmin).filter(UsuarioAdmin.id == user_id).first()
    if not u:
        raise HTTPException(404, "Usuario no encontrado")
    form = await request.form()
    nombre = (form.get("nombre_completo") or "").strip()
    rol = (form.get("rol") or "").strip().lower()
    activo = (form.get("activo") or "") in ("1", "true", "on", "yes")
    ofertas_ids = form.getlist("ofertas") if hasattr(form, "getlist") else []

    # Reglas defensivas
    if u.id == admin.id and not activo:
        raise HTTPException(422, "No puedes desactivarte a ti mismo.")
    if u.id == admin.id and rol and rol != (u.rol or "").lower():
        raise HTTPException(422, "No puedes cambiar tu propio rol.")
    if u.es_superadmin and not activo and _contar_superadmins_activos(db, excluir_id=u.id) == 0:
        raise HTTPException(422, "No puedes dejar el sistema sin superadministradores activos.")

    u.nombre_completo = nombre or None
    # El superadmin no se reasigna por la UI; solo se tocan roles asignables.
    if rol in _ROLES_ASIGNABLES and not u.es_superadmin:
        u.rol = rol
    u.activo = activo
    _asignar_ofertas(db, u, list(ofertas_ids))
    db.commit()
    return RedirectResponse("/admin/usuarios", status_code=303)


@router.post("/usuarios/{user_id}/password")
async def usuarios_password(
    user_id: int, request: Request,
    db: Session = Depends(get_db),
    admin: UsuarioAdmin = Depends(require_superadmin),
):
    u = db.query(UsuarioAdmin).filter(UsuarioAdmin.id == user_id).first()
    if not u:
        raise HTTPException(404, "Usuario no encontrado")
    form = await request.form()
    password = (form.get("password") or "").strip()
    if len(password) < 8:
        raise HTTPException(422, "La contraseña debe tener al menos 8 caracteres.")
    u.password_hash = hash_password(password)
    db.commit()
    return RedirectResponse("/admin/usuarios", status_code=303)
