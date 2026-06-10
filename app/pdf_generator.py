"""
Generador de PDF de hoja de vida — INALDE · Motor de Curaduría.

Genera una hoja de vida estructurada y legible a partir de los datos del
formulario (no extrae texto del PDF original que sube el candidato; ese se
adjunta aparte). Paleta institucional INALDE (rojo / negro / grises).
"""
from __future__ import annotations

from datetime import date, datetime
from html import escape
from io import BytesIO
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import (
    BaseDocTemplate, Frame, HRFlowable, KeepTogether, PageTemplate,
    Paragraph, Spacer, Table, TableStyle,
)

PAGE_W, PAGE_H = letter
MARGIN_X = 1.5 * cm
MARGIN_TOP = 1.3 * cm
MARGIN_BOTTOM = 1.4 * cm
CONTENT_W = PAGE_W - (MARGIN_X * 2)

# Paleta INALDE
C_RED = colors.HexColor("#E30613")
C_RED_DARK = colors.HexColor("#E1010B")
C_BLACK = colors.HexColor("#000000")
C_TEXT = colors.HexColor("#212529")
C_DARK = colors.HexColor("#333333")
C_MUTED = colors.HexColor("#A6A6A6")
C_LINE = colors.HexColor("#E4E4E4")
C_SOFT = colors.HexColor("#F4F5FA")
C_SOFT2 = colors.HexColor("#F4F4F4")
C_WHITE = colors.white


def _safe(v: Any, default: str = "") -> str:
    if v is None:
        return default
    t = str(v).strip()
    if not t:
        return default
    return escape(t, quote=False).replace("\n", "<br/>")


def _fecha(d: Any) -> str:
    if d is None or d == "":
        return ""
    if isinstance(d, str):
        try:
            d = date.fromisoformat(d[:10])
        except ValueError:
            return d
    if isinstance(d, datetime):
        d = d.date()
    return d.strftime("%d/%m/%Y") if hasattr(d, "strftime") else str(d)


def _styles():
    return {
        "h1": ParagraphStyle("h1", fontName="Helvetica-Bold", fontSize=20,
                             textColor=C_BLACK, leading=23),
        "sub": ParagraphStyle("sub", fontName="Helvetica", fontSize=10.5,
                              textColor=C_RED, leading=14),
        "meta": ParagraphStyle("meta", fontName="Helvetica", fontSize=8.5,
                               textColor=C_MUTED, leading=12),
        "section": ParagraphStyle("section", fontName="Helvetica-Bold", fontSize=10.5,
                                  textColor=C_RED, leading=14, spaceBefore=4, spaceAfter=2),
        "label": ParagraphStyle("label", fontName="Helvetica-Bold", fontSize=8,
                                textColor=C_MUTED, leading=11),
        "value": ParagraphStyle("value", fontName="Helvetica", fontSize=9.5,
                                textColor=C_TEXT, leading=13),
        "body": ParagraphStyle("body", fontName="Helvetica", fontSize=9.5,
                              textColor=C_DARK, leading=14),
        "item_t": ParagraphStyle("item_t", fontName="Helvetica-Bold", fontSize=10,
                                textColor=C_TEXT, leading=13),
        "item_s": ParagraphStyle("item_s", fontName="Helvetica", fontSize=9,
                                textColor=C_MUTED, leading=12),
        "chip": ParagraphStyle("chip", fontName="Helvetica", fontSize=8.5,
                              textColor=C_DARK, leading=12),
    }


def _header_footer(consecutivo: str):
    def draw(canvas, doc):
        canvas.saveState()
        # Banda superior roja
        canvas.setFillColor(C_RED)
        canvas.rect(0, PAGE_H - 0.35 * cm, PAGE_W, 0.35 * cm, fill=1, stroke=0)
        # Pie
        canvas.setFillColor(C_MUTED)
        canvas.setFont("Helvetica", 7.5)
        canvas.drawString(MARGIN_X, 0.7 * cm,
                          "INALDE · Motor de Curaduría Ejecutiva")
        canvas.drawRightString(PAGE_W - MARGIN_X, 0.7 * cm,
                               f"Radicado {consecutivo} · pág. {doc.page}")
        canvas.setStrokeColor(C_LINE)
        canvas.line(MARGIN_X, 1.0 * cm, PAGE_W - MARGIN_X, 1.0 * cm)
        canvas.restoreState()
    return draw


def generar_pdf_hoja_de_vida(datos: dict) -> bytes:
    st = _styles()
    buff = BytesIO()
    doc = BaseDocTemplate(
        buff, pagesize=letter,
        leftMargin=MARGIN_X, rightMargin=MARGIN_X,
        topMargin=MARGIN_TOP, bottomMargin=MARGIN_BOTTOM,
        title=f"Hoja de vida — {datos.get('nombres','')} {datos.get('apellidos','')}",
    )
    frame = Frame(MARGIN_X, MARGIN_BOTTOM, CONTENT_W,
                  PAGE_H - MARGIN_TOP - MARGIN_BOTTOM, id="main")
    doc.addPageTemplates([PageTemplate(id="base", frames=[frame],
                          onPage=_header_footer(datos.get("consecutivo", "")))])

    el = []
    nombre = f"{datos.get('nombres','')} {datos.get('apellidos','')}".strip()
    el.append(Paragraph(_safe(nombre), st["h1"]))
    if datos.get("titular"):
        el.append(Paragraph(_safe(datos["titular"]), st["sub"]))
    contacto = " · ".join(filter(None, [
        datos.get("correo"), datos.get("telefono_celular"),
        f"{datos.get('ciudad','')}{', ' + datos['pais'] if datos.get('pais') else ''}".strip(", "),
        datos.get("linkedin"),
    ]))
    el.append(Paragraph(_safe(contacto), st["meta"]))
    el.append(Spacer(1, 0.25 * cm))
    el.append(HRFlowable(width="100%", thickness=1.4, color=C_RED, spaceAfter=8))

    # Resumen profesional
    if datos.get("resumen_profesional"):
        el.append(Paragraph("PERFIL PROFESIONAL", st["section"]))
        el.append(Paragraph(_safe(datos["resumen_profesional"]), st["body"]))
        el.append(Spacer(1, 0.2 * cm))

    # Datos básicos
    el.append(Paragraph("DATOS PERSONALES", st["section"]))
    pares = [
        ("Documento", f"{datos.get('tipo_documento','')} {datos.get('numero_documento','')}".strip()),
        ("Nacimiento", _fecha(datos.get("fecha_nacimiento"))),
        ("Nacionalidad", datos.get("nacionalidad", "")),
        ("Años de experiencia", str(datos.get("anos_experiencia") or "—")),
        ("Pretensión salarial", datos.get("pretension_salarial", "")),
        ("Alumni INALDE", ("Sí — " + datos["programa_inalde"]) if datos.get("es_alumni") and datos.get("programa_inalde")
                          else ("Sí" if datos.get("es_alumni") else "No")),
        ("Disponibilidad", ", ".join(filter(None, [
            "viaje" if datos.get("disponibilidad_viaje") else "",
            "reubicación" if datos.get("disponibilidad_reubicacion") else "",
        ])) or "—"),
    ]
    filas = []
    for i in range(0, len(pares), 2):
        fila = []
        for j in (i, i + 1):
            if j < len(pares):
                k, v = pares[j]
                fila.append(Paragraph(f"<font color='#A6A6A6'>{escape(k)}</font><br/>{_safe(v,'—')}", st["value"]))
            else:
                fila.append("")
        filas.append(fila)
    t = Table(filas, colWidths=[CONTENT_W / 2] * 2)
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    el.append(t)
    el.append(Spacer(1, 0.15 * cm))

    # Habilidades
    habilidades = datos.get("habilidades") or []
    if habilidades:
        el.append(Paragraph("HABILIDADES", st["section"]))
        chips = []
        for h in habilidades:
            nom = h.get("nombre") if isinstance(h, dict) else str(h)
            niv = h.get("nivel") if isinstance(h, dict) else None
            chips.append(f"{escape(str(nom))}" + (f" ({escape(str(niv))})" if niv else ""))
        el.append(Paragraph("  •  ".join(chips), st["body"]))
        el.append(Spacer(1, 0.2 * cm))

    tecnologias = datos.get("tecnologias") or []
    if tecnologias:
        el.append(Paragraph("TECNOLOGÍAS Y HERRAMIENTAS", st["section"]))
        chips = []
        for t in tecnologias:
            nom = t.get("nombre") if isinstance(t, dict) else str(t)
            niv = t.get("nivel") if isinstance(t, dict) else None
            chips.append(f"{escape(str(nom))}" + (f" ({escape(str(niv))})" if niv else ""))
        el.append(Paragraph("  •  ".join(chips), st["body"]))
        el.append(Spacer(1, 0.2 * cm))
    idiomas = datos.get("idiomas") or []
    sectores = datos.get("sectores") or []
    cols = []
    if idiomas:
        txt = "<br/>".join(
            f"• {escape(str(i.get('idioma') if isinstance(i,dict) else i))}"
            + (f" — {escape(str(i.get('nivel')))}" if isinstance(i, dict) and i.get('nivel') else "")
            for i in idiomas)
        cols.append(Paragraph("<font color='#E30613'><b>IDIOMAS</b></font><br/>" + txt, st["body"]))
    if sectores:
        txt = "<br/>".join(f"• {escape(str(s))}" for s in sectores)
        cols.append(Paragraph("<font color='#E30613'><b>SECTORES</b></font><br/>" + txt, st["body"]))
    if cols:
        while len(cols) < 2:
            cols.append("")
        t2 = Table([cols], colWidths=[CONTENT_W / 2] * 2)
        t2.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
                                ("BOTTOMPADDING", (0, 0), (-1, -1), 6)]))
        el.append(t2)
        el.append(Spacer(1, 0.15 * cm))

    # Experiencia
    experiencias = datos.get("experiencias") or []
    if experiencias:
        el.append(Paragraph("EXPERIENCIA PROFESIONAL", st["section"]))
        for e in experiencias:
            ini = _fecha(e.get("fecha_inicio"))
            fin = "Actualidad" if e.get("actual") else _fecha(e.get("fecha_fin"))
            periodo = " — ".join(filter(None, [ini, fin]))
            if e.get("lidero_equipo") and e.get("tam_equipo"):
                equipo_txt = f"lideró equipo de {e.get('tam_equipo')}"
            elif e.get("lidero_equipo"):
                equipo_txt = "lideró equipo"
            elif e.get("tam_equipo"):
                equipo_txt = f"equipo: {e.get('tam_equipo')}"
            else:
                equipo_txt = ""
            extra = " · ".join(filter(None, [
                e.get("sector"), e.get("pais"),
                (str(e.get("nivel_jerarquico")).replace("_", " ") if e.get("nivel_jerarquico") else ""),
                equipo_txt,
                "Manejo P&L" if e.get("manejo_pyl") else "",
            ]))
            bloque = [
                Paragraph(_safe(e.get("cargo")), st["item_t"]),
                Paragraph(f"{_safe(e.get('empresa'))} · {escape(periodo)}", st["item_s"]),
            ]
            if extra:
                bloque.append(Paragraph(_safe(extra), st["item_s"]))
            if e.get("funciones"):
                bloque.append(Paragraph(_safe(e.get("funciones")), st["body"]))
            bloque.append(Spacer(1, 0.18 * cm))
            el.append(KeepTogether(bloque))

    # Formación
    formaciones = datos.get("formaciones") or []
    if formaciones:
        el.append(Paragraph("FORMACIÓN ACADÉMICA", st["section"]))
        for f in formaciones:
            ini = f.get("anio_inicio") or ""
            fin = "En curso" if f.get("en_curso") else (f.get("anio_fin") or "")
            periodo = " — ".join(str(x) for x in [ini, fin] if x)
            nivel_txt = str(f.get("nivel")).replace("_", " ").capitalize() if f.get("nivel") else ""
            subpartes = [_safe(f.get("institucion"))]
            if periodo:
                subpartes.append(escape(periodo))
            if nivel_txt:
                subpartes.append(escape(nivel_txt))
            el.append(KeepTogether([
                Paragraph(_safe(f.get("titulo")), st["item_t"]),
                Paragraph(" · ".join(p for p in subpartes if p), st["item_s"]),
                Spacer(1, 0.12 * cm),
            ]))

    doc.build(el)
    return buff.getvalue()
