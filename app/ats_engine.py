"""
Motor de Curaduría Ejecutiva — ATS DETERMINISTA (sin IA).
============================================================

Implementa la lógica de los documentos "Motor de Curaduría Ejecutiva" y
"Prompt Maestro" pero SIN modelos de lenguaje: todo el scoring se calcula
con reglas explícitas sobre los campos ESTRUCTURADOS que el candidato y la
oferta registran en la base de datos.

Por eso el formulario de hoja de vida captura señales estructuradas
(habilidades, idiomas con nivel, sectores, nivel jerárquico por
experiencia, liderazgo de equipo, manejo de P&L, etc.): son las entradas
que el motor necesita para puntuar de forma reproducible y auditable.

Salida: un diccionario con la misma forma del JSON del prompt maestro
(resumen_ejecutivo, puntuacion, nivel_recomendacion, score_detallado,
pesos_aplicados, eliminatorios, fortalezas, brechas, compensaciones, etc.).

Determinista = misma entrada → misma salida. Explicable = cada número se
justifica con evidencia tomada del CV.
"""
from __future__ import annotations

import json
import re
import unicodedata
from datetime import date
from typing import Optional


# ──────────────────────────────────────────────────────────────
# Constantes / léxicos
# ──────────────────────────────────────────────────────────────

# Jerarquía de cargos (mayor = más senior).
NIVELES_JERARQUICOS = {
    "operativo": 1, "coordinacion": 2, "jefatura": 3,
    "gerencia": 4, "direccion": 5, "alta_direccion": 6,
}
# Palabras clave para inferir nivel jerárquico desde el título del cargo.
LEXICO_JERARQUIA = [
    (6, ["ceo", "gerente general", "director general", "presidente", "country manager",
         "managing director", "vicepresidente ejecutivo", "socio director"]),
    (5, ["director", "directora", "vp ", "vicepresidente", "chief", "cfo", "coo",
         "cto", "chro", "cmo", "head of", "head ", "country head"]),
    (4, ["gerente", "manager", "subdirector", "subdirectora"]),
    (3, ["jefe", "jefa", "lider", "líder", "supervisor", "supervisora"]),
    (2, ["coordinador", "coordinadora", "analista senior", "especialista"]),
    (1, ["analista", "asistente", "auxiliar", "practicante", "junior"]),
]

# Jerarquía de formación.
PESO_FORMACION = {
    "bachiller": 1, "tecnico": 2, "tecnologo": 3, "pregrado": 4,
    "especializacion": 5, "maestria": 6, "mba": 6, "doctorado": 8,
}

# Niveles de idioma ordenados.
NIVEL_IDIOMA = {"basico": 1, "intermedio": 2, "avanzado": 3, "nativo": 4}

# Palabras clave temáticas para señales blandas (sobre funciones/resumen).
KW_LIDERAZGO = ["lider", "liderazgo", "equipo", "dirigi", "dirig", "gestione personal",
                "a cargo de", "supervis", "coordine", "coordin"]
KW_COMPLEJIDAD = ["p&l", "pyl", "presupuesto", "junta directiva", "comite directivo",
                  "comité directivo", "regional", "multinacional", "millones",
                  "filiales", "unidades de negocio", "crisis", "turnaround"]
KW_TRANSFORMACION = ["transformacion", "transformación", "cambio", "reestructur",
                     "turnaround", "digitaliza", "transformacion digital",
                     "expansion", "expansión", "escalamiento", "innovacion",
                     "innovación", "profesionalizacion", "profesionalización"]
KW_INTERNACIONAL = ["internacional", "regional", "latam", "global", "multinacional",
                    "exportacion", "exportación", "expatriad", "filial"]

# Escala de recomendación (paso 8 del documento).
ESCALA_RECOMENDACION = [
    (90, "Recomendado prioritario"),
    (80, "Recomendado"),
    (70, "Potencial alto"),
    (60, "Potencial con brechas"),
    (40, "Bajo ajuste"),
    (0,  "No recomendado"),
]

# Pesos por defecto según modo de búsqueda (del prompt maestro).
PESOS_DEFAULT = {
    "matching_exacto": {
        "experiencia_funcional": 25, "experiencia_sectorial": 20, "nivel_jerarquico": 15,
        "formacion_academica": 10, "liderazgo_equipos": 10, "complejidad_gestionada": 5,
        "idiomas": 5, "internacionalidad": 3, "transformacion_cambio": 2,
        "cultura_estilo_liderazgo": 2, "potencial_crecimiento": 2, "fit_alumni_comunidad": 1,
    },
    "potencial_exito": {
        "experiencia_funcional": 15, "experiencia_sectorial": 8, "nivel_jerarquico": 10,
        "formacion_academica": 7, "liderazgo_equipos": 15, "complejidad_gestionada": 15,
        "idiomas": 3, "internacionalidad": 7, "transformacion_cambio": 10,
        "cultura_estilo_liderazgo": 5, "potencial_crecimiento": 4, "fit_alumni_comunidad": 1,
    },
    "hibrido": {
        "experiencia_funcional": 20, "experiencia_sectorial": 15, "nivel_jerarquico": 12,
        "formacion_academica": 8, "liderazgo_equipos": 12, "complejidad_gestionada": 10,
        "idiomas": 5, "internacionalidad": 5, "transformacion_cambio": 5,
        "cultura_estilo_liderazgo": 4, "potencial_crecimiento": 3, "fit_alumni_comunidad": 1,
    },
}

CRITERIOS = list(PESOS_DEFAULT["hibrido"].keys())

STOPWORDS = set("""
de la el los las un una unos unas y o a en con por para del al lo su sus mi tu se que como
sobre entre desde hasta the of and to in for with por más mas e u
""".split())


# ──────────────────────────────────────────────────────────────
# Utilidades
# ──────────────────────────────────────────────────────────────
def _norm(s: Optional[str]) -> str:
    """minúsculas + sin tildes."""
    if not s:
        return ""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return s.lower().strip()


def _tokens(s: Optional[str]) -> set[str]:
    txt = _norm(s)
    palabras = re.findall(r"[a-z0-9&]{3,}", txt)
    return {p for p in palabras if p not in STOPWORDS}


def _contiene(texto: str, claves: list[str]) -> bool:
    t = _norm(texto)
    return any(_norm(k) in t for k in claves)


def _loads(raw, default):
    if not raw:
        return default
    if isinstance(raw, (list, dict)):
        return raw
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return default


def _anios_experiencia(cand) -> float:
    """Años de experiencia: declarados o calculados desde las experiencias."""
    if getattr(cand, "anos_experiencia", None):
        return float(cand.anos_experiencia)
    total_dias = 0
    hoy = date.today()
    for e in cand.experiencias:
        ini = e.fecha_inicio
        fin = e.fecha_fin or (hoy if e.actual else hoy)
        if ini and fin and fin >= ini:
            total_dias += (fin - ini).days
    return round(total_dias / 365.25, 1)


def _nivel_jerarquico_exp(e) -> int:
    if getattr(e, "nivel_jerarquico", None) in NIVELES_JERARQUICOS:
        return NIVELES_JERARQUICOS[e.nivel_jerarquico]
    cargo = _norm(e.cargo)
    for nivel, claves in LEXICO_JERARQUIA:
        if any(k in cargo for k in claves):
            return nivel
    return 1


def _max_jerarquia(cand) -> int:
    return max([_nivel_jerarquico_exp(e) for e in cand.experiencias], default=0)


def _max_formacion(cand) -> int:
    pesos = []
    for f in cand.formaciones:
        cod = _norm(f.nivel)
        if cod in PESO_FORMACION:
            pesos.append(PESO_FORMACION[cod])
        elif "mba" in _norm(f.titulo) or "master" in _norm(f.titulo):
            pesos.append(6)
    return max(pesos, default=0)


def _texto_candidato(cand) -> str:
    partes = [cand.titular or "", cand.resumen_profesional or ""]
    for e in cand.experiencias:
        partes += [e.cargo or "", e.funciones or ""]
    for h in cand.habilidades:
        partes.append(h.nombre or "")
    for t in getattr(cand, "tecnologias", []) or []:
        partes.append(t.nombre or "")
    return " ".join(partes)


def _sectores_candidato(cand) -> set[str]:
    secs = {_norm(s.sector) for s in cand.sectores if s.sector}
    secs |= {_norm(e.sector) for e in cand.experiencias if e.sector}
    return {s for s in secs if s}


def _clamp(x) -> int:
    return int(max(0, min(100, round(x))))


def _nivel_recomendacion(score: int) -> str:
    for umbral, etiqueta in ESCALA_RECOMENDACION:
        if score >= umbral:
            return etiqueta
    return "No recomendado"


# ──────────────────────────────────────────────────────────────
# Scores por criterio (cada uno 0-100, con evidencia)
# ──────────────────────────────────────────────────────────────
def _score_funcional(cand, oferta) -> tuple[int, str]:
    base_oferta = " ".join([
        oferta.titulo or "", oferta.area or "", oferta.descripcion or "",
        oferta.requisitos_tecnicos or "",
    ])
    toks_oferta = _tokens(base_oferta)
    if not toks_oferta:
        return 60, "Oferta sin requisitos técnicos detallados; puntaje neutro."
    toks_cand = _tokens(_texto_candidato(cand))
    interseccion = toks_oferta & toks_cand
    ratio = len(interseccion) / max(1, len(toks_oferta))
    score = _clamp(35 + ratio * 90)
    ev = f"{len(interseccion)} de {len(toks_oferta)} términos funcionales de la oferta presentes en el CV."
    return score, ev


def _score_sectorial(cand, oferta) -> tuple[int, str]:
    sec_oferta = _norm(oferta.sector)
    importancia = (oferta.importancia_sector or "medio").lower()
    if not sec_oferta:
        return 60, "La oferta no especifica sector; criterio poco determinante."
    secs_cand = _sectores_candidato(cand)
    transferibles = {_norm(s) for s in _loads(oferta.sectores_transferibles, [])}

    if any(sec_oferta in s or s in sec_oferta for s in secs_cand):
        return 100, f"El candidato tiene experiencia directa en el sector '{oferta.sector}'."
    if secs_cand & transferibles:
        compartidos = ", ".join(sorted(secs_cand & transferibles))
        base = {"critico": 30, "alto": 80, "medio": 75, "bajo": 85}.get(importancia, 75)
        return base, f"Sin sector exacto, pero viene de sectores transferibles ({compartidos})."
    # Sin coincidencia: depende de qué tan crítico sea el sector.
    base = {"critico": 5, "alto": 35, "medio": 55, "bajo": 70}.get(importancia, 55)
    return base, f"No registra experiencia en el sector ni en sectores transferibles (importancia: {importancia})."


def _score_jerarquico(cand, oferta) -> tuple[int, str]:
    cand_nivel = _max_jerarquia(cand)
    req = NIVELES_JERARQUICOS.get(_norm(oferta.nivel_jerarquico_min), 0)
    nombre_max = next((k for k, v in NIVELES_JERARQUICOS.items() if v == cand_nivel), "—")
    if req == 0:
        score = _clamp(cand_nivel / 6 * 100)
        return score, f"Nivel jerárquico alcanzado: {nombre_max}."
    if cand_nivel >= req:
        return 100, f"Alcanza o supera el nivel requerido ({nombre_max})."
    brecha = req - cand_nivel
    score = _clamp(100 - brecha * 30)
    return score, f"Nivel actual ({nombre_max}) está {brecha} escalón(es) por debajo del requerido."


def _score_formacion(cand, oferta) -> tuple[int, str]:
    cand_f = _max_formacion(cand)
    req = PESO_FORMACION.get(_norm(oferta.formacion_min), 0)
    nombre = next((k for k, v in PESO_FORMACION.items() if v == cand_f), "sin registro")
    if req == 0:
        return _clamp(cand_f / 8 * 100) if cand_f else 50, f"Formación máxima: {nombre}."
    if cand_f >= req:
        return 100, f"Cumple el nivel de formación requerido (máximo: {nombre})."
    brecha = req - cand_f
    return _clamp(100 - brecha * 25), f"Formación ({nombre}) por debajo del nivel exigido."


def _score_liderazgo(cand) -> tuple[int, str]:
    lidero = any(e.lidero_equipo for e in cand.experiencias)
    max_equipo = max([e.tam_equipo or 0 for e in cand.experiencias], default=0)
    kw = _contiene(_texto_candidato(cand), KW_LIDERAZGO)
    if not lidero and not kw:
        return 25, "No hay evidencia explícita de liderazgo de equipos."
    score = 55
    if lidero:
        score += 20
    if max_equipo >= 50:
        score += 25
    elif max_equipo >= 10:
        score += 15
    elif max_equipo >= 1:
        score += 8
    ev = f"Liderazgo de equipos evidenciado" + (f" (hasta {max_equipo} personas)." if max_equipo else ".")
    return _clamp(score), ev


def _complejidad(cand) -> tuple[int, str, str]:
    texto = _texto_candidato(cand)
    pyl = any(e.manejo_pyl for e in cand.experiencias) or _contiene(texto, ["p&l", "pyl", "presupuesto"])
    internacional = _contiene(texto, KW_INTERNACIONAL) or any(
        _norm(e.pais) not in ("", "colombia") for e in cand.experiencias)
    alta_jerarquia = _max_jerarquia(cand) >= 5
    equipo_grande = max([e.tam_equipo or 0 for e in cand.experiencias], default=0) >= 20
    otros = _contiene(texto, KW_COMPLEJIDAD)
    señales = sum([pyl, internacional, alta_jerarquia, equipo_grande, otros])
    evid = []
    if pyl: evid.append("gestión de P&L/presupuesto")
    if internacional: evid.append("exposición internacional/regional")
    if alta_jerarquia: evid.append("nivel de dirección")
    if equipo_grande: evid.append("equipos grandes")
    if otros: evid.append("entornos de alta complejidad")
    if señales >= 3:
        return 90, "alta", "Complejidad alta: " + ", ".join(evid) + "."
    if señales >= 1:
        return 60, "media", "Complejidad media: " + ", ".join(evid) + "."
    return 30, "baja", "Sin evidencia clara de complejidad ejecutiva gestionada."


def _score_idiomas(cand, oferta) -> tuple[int, str]:
    req_idioma = _norm(oferta.idioma_requerido)
    req_nivel = NIVEL_IDIOMA.get(_norm(oferta.idioma_nivel_min), 0)
    if not req_idioma:
        n = len(cand.idiomas)
        return _clamp(50 + n * 20), f"Maneja {n} idioma(s) registrado(s)."
    for idi in cand.idiomas:
        if _norm(idi.idioma) == req_idioma or req_idioma in _norm(idi.idioma):
            nivel_c = NIVEL_IDIOMA.get(_norm(idi.nivel), 2)
            if nivel_c >= req_nivel:
                return 100, f"Cumple el idioma requerido ({oferta.idioma_requerido})."
            return _clamp(100 - (req_nivel - nivel_c) * 30), \
                f"Tiene {oferta.idioma_requerido} pero por debajo del nivel exigido."
    return 0, f"No registra el idioma requerido ({oferta.idioma_requerido})."


def _score_internacionalidad(cand) -> tuple[int, str]:
    paises = {_norm(e.pais) for e in cand.experiencias if e.pais and _norm(e.pais) != "colombia"}
    kw = _contiene(_texto_candidato(cand), KW_INTERNACIONAL)
    if paises:
        return _clamp(70 + len(paises) * 10), f"Experiencia fuera de Colombia: {', '.join(sorted(paises))}."
    if kw:
        return 60, "Exposición regional/internacional mencionada en la trayectoria."
    return 25, "Sin evidencia de experiencia internacional."


def _score_transformacion(cand) -> tuple[int, str]:
    if _contiene(_texto_candidato(cand), KW_TRANSFORMACION):
        return 80, "Evidencia de transformación / cambio / crecimiento en la trayectoria."
    return 40, "Sin evidencia explícita de proyectos de transformación."


def _score_cultura(cand) -> tuple[int, str]:
    tiene_resumen = bool((cand.resumen_profesional or "").strip())
    lidero = any(e.lidero_equipo for e in cand.experiencias)
    base = 50 + (15 if tiene_resumen else 0) + (15 if lidero else 0)
    return _clamp(base), "Estilo de liderazgo inferido del perfil declarado (señal blanda)."


def _score_potencial(cand) -> tuple[int, str]:
    exps = sorted([e for e in cand.experiencias if e.fecha_inicio],
                  key=lambda e: e.fecha_inicio)
    niveles = [_nivel_jerarquico_exp(e) for e in exps]
    progresiones = sum(1 for i in range(1, len(niveles)) if niveles[i] > niveles[i - 1])
    if progresiones >= 2:
        return 85, f"Progresión ascendente clara ({progresiones} ascensos de nivel)."
    if progresiones == 1 or _max_jerarquia(cand) >= 4:
        return 65, "Trayectoria con crecimiento profesional."
    return 45, "Crecimiento profesional limitado o no evidente en los datos."


def _score_fit_alumni(cand) -> tuple[int, str]:
    if cand.es_alumni:
        prog = f" ({cand.programa_inalde})" if cand.programa_inalde else ""
        return 100, f"Alumni INALDE{prog}."
    return 20, "No se registra pertenencia a la comunidad alumni."


# ──────────────────────────────────────────────────────────────
# Requisitos eliminatorios
# ──────────────────────────────────────────────────────────────
def _evaluar_eliminatorios(cand, oferta) -> list[dict]:
    """Evalúa cada requisito eliminatorio configurado en la oferta.
    Cada item: {criterio, descripcion, cumple: True|False|None, evidencia}.
    cumple=None ⇒ información insuficiente (no se asume cumplimiento)."""
    reqs = _loads(oferta.requisitos_eliminatorios, [])
    resultados = []
    anios = _anios_experiencia(cand)
    secs_cand = _sectores_candidato(cand)

    for r in reqs:
        criterio = _norm(r.get("criterio", ""))
        desc = r.get("descripcion", r.get("criterio", ""))
        cumple, evidencia = None, "Información insuficiente en el CV."

        if "experiencia" in criterio and ("año" in criterio or "anos" in criterio or "minim" in criterio or "exp" in criterio):
            req = oferta.anos_experiencia_min or 0
            cumple = anios >= req
            evidencia = f"{anios} años de experiencia (requeridos: {req})."
        elif "idioma" in criterio:
            req_idioma = _norm(oferta.idioma_requerido)
            req_nivel = NIVEL_IDIOMA.get(_norm(oferta.idioma_nivel_min), 1)
            match = next((i for i in cand.idiomas if req_idioma and req_idioma in _norm(i.idioma)), None)
            if match:
                cumple = NIVEL_IDIOMA.get(_norm(match.nivel), 2) >= req_nivel
                evidencia = f"{match.idioma} nivel {match.nivel or 'no especificado'}."
            elif req_idioma:
                cumple = False
                evidencia = f"No registra el idioma requerido ({oferta.idioma_requerido})."
        elif "sector" in criterio:
            sec = _norm(oferta.sector)
            cumple = bool(sec and any(sec in s or s in sec for s in secs_cand))
            evidencia = ("Tiene experiencia en el sector." if cumple
                         else f"No registra experiencia en el sector '{oferta.sector}'.")
        elif "formacion" in criterio or "educacion" in criterio:
            req = PESO_FORMACION.get(_norm(oferta.formacion_min), 0)
            cumple = _max_formacion(cand) >= req if req else None
            evidencia = "Nivel de formación verificado contra el mínimo." if req else evidencia
        elif "jerarqu" in criterio or "cargo" in criterio or "nivel" in criterio:
            req = NIVELES_JERARQUICOS.get(_norm(oferta.nivel_jerarquico_min), 0)
            cumple = _max_jerarquia(cand) >= req if req else None
        elif "pais" in criterio or "ciudad" in criterio or "geograf" in criterio or "ubicaci" in criterio:
            objetivo = _norm(oferta.ciudad_requerida) or _norm(oferta.pais_requerido)
            ubic_cand = _norm(cand.ciudad) + " " + _norm(cand.pais)
            if objetivo:
                cumple = objetivo in ubic_cand or cand.disponibilidad_reubicacion
                evidencia = (f"Ubicación/disponibilidad compatible con {objetivo}." if cumple
                             else f"Ubicación del candidato no coincide con {objetivo}.")
        elif "internacional" in criterio:
            paises = {_norm(e.pais) for e in cand.experiencias if e.pais and _norm(e.pais) != "colombia"}
            cumple = bool(paises)
            evidencia = ("Experiencia internacional evidenciada." if cumple
                         else "Sin experiencia internacional registrada.")
        elif "lider" in criterio or "equipo" in criterio:
            cumple = any(e.lidero_equipo for e in cand.experiencias)
            evidencia = "Liderazgo de equipos evidenciado." if cumple else "Sin liderazgo de equipos registrado."
        elif "p&l" in criterio or "pyl" in criterio or "presupuesto" in criterio:
            cumple = any(e.manejo_pyl for e in cand.experiencias)
            evidencia = "Manejo de P&L evidenciado." if cumple else "Sin manejo de P&L registrado."
        elif "viaje" in criterio or "disponibil" in criterio:
            cumple = bool(cand.disponibilidad_viaje)
            evidencia = "Disponibilidad de viaje declarada." if cumple else "No declara disponibilidad de viaje."
        elif "certific" in criterio:
            # No verificable desde datos estructurados → información insuficiente.
            cumple = None
            evidencia = "Certificación no verificable desde el CV estructurado; requiere validación manual."

        resultados.append({
            "criterio": r.get("criterio", criterio),
            "descripcion": desc,
            "cumple": cumple,
            "evidencia": evidencia,
        })
    return resultados


# ──────────────────────────────────────────────────────────────
# Compensaciones (reglas no-eliminatorias)
# ──────────────────────────────────────────────────────────────
def _aplicar_compensaciones(scores: dict, complejidad_nivel: str, cand, oferta) -> list[dict]:
    """Ajusta scores de brechas compensables y devuelve la lista de
    compensaciones aplicadas (paso 4 del documento)."""
    reglas = _loads(oferta.reglas_compensacion, {}) or {}
    aplicadas = []

    fuerte_experiencia = scores["experiencia_funcional"] >= 70 or _anios_experiencia(cand) >= 12
    fuerte_complejidad = complejidad_nivel == "alta"
    fuerte_liderazgo = scores["liderazgo_equipos"] >= 70

    # Educación compensable por experiencia/liderazgo.
    if reglas.get("educacion_compensable_por_experiencia") and scores["formacion_academica"] < 70 \
            and (fuerte_experiencia or fuerte_complejidad or fuerte_liderazgo):
        antes = scores["formacion_academica"]
        scores["formacion_academica"] = _clamp(antes + 25)
        aplicadas.append({
            "brecha": "Formación académica por debajo del nivel ideal",
            "compensacion": "Experiencia directiva / liderazgo / alta complejidad",
            "justificacion": f"Score de formación ajustado de {antes} a {scores['formacion_academica']} por trayectoria ejecutiva.",
        })

    # Sector compensable por función / complejidad.
    if scores["experiencia_sectorial"] < 70 and (
            (reglas.get("sector_compensable_por_funcion") and scores["experiencia_funcional"] >= 70) or
            (reglas.get("sector_compensable_por_complejidad") and fuerte_complejidad)):
        antes = scores["experiencia_sectorial"]
        scores["experiencia_sectorial"] = _clamp(antes + 20)
        aplicadas.append({
            "brecha": "Sector distinto al de la oferta",
            "compensacion": "Función equivalente / complejidad comparable",
            "justificacion": f"Score sectorial ajustado de {antes} a {scores['experiencia_sectorial']} por transferibilidad funcional.",
        })

    # Nivel jerárquico compensable.
    if reglas.get("nivel_jerarquico_compensable") and scores["nivel_jerarquico"] < 70 \
            and (fuerte_complejidad or fuerte_liderazgo):
        antes = scores["nivel_jerarquico"]
        scores["nivel_jerarquico"] = _clamp(antes + 15)
        aplicadas.append({
            "brecha": "Nivel jerárquico previo inferior al requerido",
            "compensacion": "Responsabilidades equivalentes / alta complejidad gestionada",
            "justificacion": f"Score jerárquico ajustado de {antes} a {scores['nivel_jerarquico']} por alcance de responsabilidades.",
        })

    return aplicadas


# ──────────────────────────────────────────────────────────────
# Skills match
# ──────────────────────────────────────────────────────────────
def _skills_match(cand, oferta) -> tuple[list[str], list[str]]:
    # Las habilidades requeridas y las tecnologías/herramientas exigidas
    # se evalúan juntas como "requisitos técnicos" parametrizados.
    requeridos = list(_loads(oferta.skills_requeridos, []))
    for t in _loads(getattr(oferta, "tecnologias_requeridas", None), []):
        if _norm(t) not in {_norm(r) for r in requeridos}:
            requeridos.append(t)
    tecnos = getattr(cand, "tecnologias", []) or []
    if not requeridos:
        base = [h.nombre for h in cand.habilidades] + [t.nombre for t in tecnos]
        return base[:10], []
    texto_cand = (_norm(_texto_candidato(cand)) + " "
                  + " ".join(_norm(h.nombre) for h in cand.habilidades) + " "
                  + " ".join(_norm(t.nombre) for t in tecnos) + " "
                  + " ".join(_norm(i.idioma) for i in cand.idiomas))
    match, faltan = [], []
    for s in requeridos:
        if _norm(s) in texto_cand:
            match.append(s)
        else:
            faltan.append(s)
    return match, faltan


# ──────────────────────────────────────────────────────────────
# Pesos
# ──────────────────────────────────────────────────────────────
def _resolver_pesos(oferta) -> dict:
    pesos = _loads(oferta.pesos, None)
    modo = (oferta.modo_busqueda or "hibrido").lower()
    if not pesos:
        pesos = dict(PESOS_DEFAULT.get(modo, PESOS_DEFAULT["hibrido"]))
    # Normalizar: asegurar las 12 claves y que sumen 100.
    pesos = {k: float(pesos.get(k, 0)) for k in CRITERIOS}
    total = sum(pesos.values()) or 1
    return {k: round(v * 100 / total, 2) for k, v in pesos.items()}


# ──────────────────────────────────────────────────────────────
# Generación de texto (plantillas deterministas, NO IA)
# ──────────────────────────────────────────────────────────────
def _resumen_ejecutivo(cand, oferta, score, nivel_rec, resultado_elim,
                       fuertes, brechas, compensaciones) -> str:
    nombre = cand.nombre_completo
    p1 = (f"{nombre} obtiene un ajuste de {score}/100 frente a la vacante "
          f"«{oferta.titulo}» bajo el modo de búsqueda "
          f"{(oferta.modo_busqueda or 'hibrido').replace('_', ' ')}, "
          f"con una recomendación de «{nivel_rec}».")
    if resultado_elim == "no_cumple":
        p1 += (" El candidato NO cumple uno o más requisitos eliminatorios "
               "definidos como no compensables, por lo que no debe avanzar para esta vacante.")
    p2 = ("Fortalezas principales: " + "; ".join(fuertes[:4]) + ".") if fuertes else \
         "No se identifican fortalezas destacadas frente a los criterios definidos."
    p3 = ("Brechas o riesgos a revisar: " + "; ".join(brechas[:4]) + ".") if brechas else \
         "No se identifican brechas relevantes frente a los criterios definidos."
    if compensaciones:
        p3 += " Se aplicaron compensaciones por trayectoria ejecutiva sobre brechas no críticas."
    return f"{p1}\n\n{p2}\n\n{p3}"


def _proximos_pasos(nivel_rec, resultado_elim, riesgos) -> str:
    if resultado_elim == "no_cumple":
        return "No enviar para esta vacante: no cumple requisitos eliminatorios. Mantener en base para futuras búsquedas."
    if nivel_rec in ("Recomendado prioritario", "Recomendado") and not riesgos:
        return "Enviar como perfil prioritario al headhunter o empresa alumni."
    if nivel_rec in ("Recomendado prioritario", "Recomendado", "Potencial alto"):
        return "Enviar como perfil alternativo: el headhunter debe revisar las brechas señaladas."
    if nivel_rec in ("Potencial con brechas", "Bajo ajuste"):
        return "Mantener en base para futuras búsquedas con mejor ajuste."
    return "No enviar para esta vacante."


# ──────────────────────────────────────────────────────────────
# API principal
# ──────────────────────────────────────────────────────────────
def evaluar(cand, oferta) -> dict:
    """Evalúa un Candidato contra una OfertaLaboral y devuelve el dict de
    resultado con la misma forma del JSON del prompt maestro."""

    # 1. Scores por criterio.
    s_func, ev_func = _score_funcional(cand, oferta)
    s_sect, ev_sect = _score_sectorial(cand, oferta)
    s_jer, ev_jer = _score_jerarquico(cand, oferta)
    s_form, ev_form = _score_formacion(cand, oferta)
    s_lid, ev_lid = _score_liderazgo(cand)
    s_comp, complejidad_nivel, ev_comp = _complejidad(cand)
    s_idi, ev_idi = _score_idiomas(cand, oferta)
    s_int, ev_int = _score_internacionalidad(cand)
    s_trans, ev_trans = _score_transformacion(cand)
    s_cult, ev_cult = _score_cultura(cand)
    s_pot, ev_pot = _score_potencial(cand)
    s_fit, ev_fit = _score_fit_alumni(cand)

    scores = {
        "experiencia_funcional": s_func, "experiencia_sectorial": s_sect,
        "nivel_jerarquico": s_jer, "formacion_academica": s_form,
        "liderazgo_equipos": s_lid, "complejidad_gestionada": s_comp,
        "idiomas": s_idi, "internacionalidad": s_int,
        "transformacion_cambio": s_trans, "cultura_estilo_liderazgo": s_cult,
        "potencial_crecimiento": s_pot, "fit_alumni_comunidad": s_fit,
    }
    evidencias = {
        "experiencia_funcional": ev_func, "experiencia_sectorial": ev_sect,
        "nivel_jerarquico": ev_jer, "formacion_academica": ev_form,
        "liderazgo_equipos": ev_lid, "complejidad_gestionada": ev_comp,
        "idiomas": ev_idi, "internacionalidad": ev_int,
        "transformacion_cambio": ev_trans, "cultura_estilo_liderazgo": ev_cult,
        "potencial_crecimiento": ev_pot, "fit_alumni_comunidad": ev_fit,
    }

    # 2. Compensaciones (ajustan scores no-eliminatorios).
    compensaciones = _aplicar_compensaciones(scores, complejidad_nivel, cand, oferta)

    # 3. Pesos y score ponderado.
    pesos = _resolver_pesos(oferta)
    score_final = _clamp(sum(scores[k] * pesos[k] for k in CRITERIOS) / 100)

    # 4. Eliminatorios.
    elim = _evaluar_eliminatorios(cand, oferta)
    no_cumplidos = [e for e in elim if e["cumple"] is False]
    insuficientes = [e for e in elim if e["cumple"] is None]
    if no_cumplidos:
        resultado_elim = "no_cumple"
    elif insuficientes:
        resultado_elim = "informacion_insuficiente"
    else:
        resultado_elim = "cumple"

    # 5. Nivel de recomendación (con override por eliminatorio).
    if resultado_elim == "no_cumple":
        nivel_rec = "No recomendado por requisito eliminatorio"
    else:
        nivel_rec = _nivel_recomendacion(score_final)

    # 6. Fortalezas, debilidades, skills, riesgos.
    etiquetas = {
        "experiencia_funcional": "experiencia funcional", "experiencia_sectorial": "experiencia sectorial",
        "nivel_jerarquico": "nivel jerárquico", "formacion_academica": "formación académica",
        "liderazgo_equipos": "liderazgo de equipos", "complejidad_gestionada": "complejidad gestionada",
        "idiomas": "idiomas", "internacionalidad": "internacionalidad",
        "transformacion_cambio": "transformación/cambio", "cultura_estilo_liderazgo": "estilo de liderazgo",
        "potencial_crecimiento": "potencial de crecimiento", "fit_alumni_comunidad": "fit alumni",
    }
    fuertes = [f"{etiquetas[k]}: {evidencias[k]}" for k in CRITERIOS if scores[k] >= 75]
    brechas = [f"{etiquetas[k]}: {evidencias[k]}" for k in CRITERIOS if scores[k] < 50]
    skills_match, skills_faltan = _skills_match(cand, oferta)

    riesgos = []
    for e in no_cumplidos:
        riesgos.append(f"Requisito eliminatorio no cumplido: {e['descripcion']} ({e['evidencia']})")
    for e in insuficientes:
        riesgos.append(f"Información insuficiente para validar: {e['descripcion']}")
    if skills_faltan:
        riesgos.append("Skills requeridas no evidenciadas: " + ", ".join(skills_faltan))

    # 7. Logros (líneas de funciones con cifras/%).
    logros = []
    for e in cand.experiencias:
        for linea in re.split(r"[\n;•·]+", e.funciones or ""):
            linea = linea.strip()
            if linea and re.search(r"\d", linea) and len(linea) > 12:
                logros.append(f"{e.cargo} @ {e.empresa}: {linea}")
    logros = logros[:6]

    # 8. Preguntas sugeridas (derivadas de las brechas, plantillas).
    preguntas = []
    for e in (no_cumplidos + insuficientes)[:3]:
        preguntas.append(f"¿Cómo aborda el requisito '{e['descripcion']}' que no se evidencia en su CV?")
    if skills_faltan:
        preguntas.append("¿Qué experiencia tiene con: " + ", ".join(skills_faltan[:4]) + "?")
    if complejidad_nivel != "alta":
        preguntas.append("¿Qué es lo más complejo que ha gestionado (presupuesto, equipos, países)?")

    resumen_ejecutivo = _resumen_ejecutivo(cand, oferta, score_final, nivel_rec,
                                           resultado_elim, fuertes, brechas, compensaciones)
    proximos = _proximos_pasos(nivel_rec, resultado_elim, riesgos)

    resumen_eval = (
        f"Evaluación bajo modo {(oferta.modo_busqueda or 'hibrido').replace('_', ' ')}. "
        f"El criterio de mayor peso ({max(pesos, key=pesos.get).replace('_', ' ')}, "
        f"{pesos[max(pesos, key=pesos.get)]}%) obtuvo "
        f"{scores[max(pesos, key=pesos.get)]}/100. "
        f"Complejidad gestionada estimada: {complejidad_nivel}. "
        f"Años de experiencia: {_anios_experiencia(cand)}."
    )

    return {
        "resumen_ejecutivo_match": resumen_ejecutivo,
        "nombre_postulado": cand.nombre_completo,
        "email_postulado": cand.correo,
        "telefono": cand.telefono_celular,
        "linkedin": cand.linkedin,
        "ciudad": cand.ciudad,
        "pais": cand.pais,
        "anos_experiencia_total": _anios_experiencia(cand),
        "nivel_educacion": next((k for k, v in PESO_FORMACION.items() if v == _max_formacion(cand)), None),
        "instituciones_academicas": [f.institucion for f in cand.formaciones],
        "sector_experiencia": sorted(_sectores_candidato(cand)),
        "modo_busqueda_aplicado": (oferta.modo_busqueda or "hibrido"),
        "resultado_eliminatorio": resultado_elim,
        "criterios_eliminatorios_evaluados": elim,
        "criterios_eliminatorios_no_cumplidos": [e["descripcion"] for e in no_cumplidos],
        "puntuacion": score_final,
        "nivel_recomendacion": nivel_rec,
        "score_detallado": scores,
        "pesos_aplicados": pesos,
        "puntos_fuertes": fuertes,
        "debilidades": brechas,
        "skills_match": skills_match,
        "skills_faltantes": skills_faltan,
        "logros_destacados": logros,
        "complejidad_gestionada": {"nivel": complejidad_nivel, "evidencia": [evidencias["complejidad_gestionada"]]},
        "compensaciones_aplicadas": compensaciones,
        "riesgos_de_contratacion": riesgos,
        "evidencias_por_criterio": evidencias,
        "resumen_evaluacion": resumen_eval,
        "preguntas_sugeridas_para_entrevista": preguntas,
        "proximos_pasos": proximos,
    }
