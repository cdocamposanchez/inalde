"""
Carga de datos iniciales — INALDE · Motor de Curaduría Ejecutiva.

Crea catálogos (tipos de documento, nacionalidades, niveles de formación
con su peso jerárquico, sectores económicos, departamentos), un par de
ofertas laborales de ejemplo con su configuración de búsqueda completa, y
el usuario administrador inicial.

Uso:
    python -m app.seed
Idempotente: no duplica registros existentes (se identifica por código /
username / título).
"""
import json
import logging

from app.database import (
    SessionLocal, init_db,
    TipoDocumento, Nacionalidad, NivelFormacion, Sector, Departamento,
    UsuarioAdmin, OfertaLaboral,
)
from app.security import hash_password
from app import config

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger("inalde.seed")


TIPOS_DOCUMENTO = [
    ("CC", "Cédula de ciudadanía"),
    ("CE", "Cédula de extranjería"),
    ("PA", "Pasaporte"),
    ("PEP", "Permiso especial de permanencia"),
    ("NIT", "NIT"),
]

NACIONALIDADES = [
    ("CO", "Colombiana"), ("VE", "Venezolana"), ("EC", "Ecuatoriana"),
    ("PE", "Peruana"), ("MX", "Mexicana"), ("AR", "Argentina"),
    ("CL", "Chilena"), ("ES", "Española"), ("US", "Estadounidense"),
    ("BR", "Brasileña"), ("OT", "Otra"),
]

# (codigo, nombre, peso jerárquico para el ATS)
NIVELES_FORMACION = [
    ("bachiller", "Bachillerato", 1),
    ("tecnico", "Técnico", 2),
    ("tecnologo", "Tecnólogo", 3),
    ("profesional", "Profesional / Pregrado", 4),
    ("especializacion", "Especialización", 5),
    ("maestria", "Maestría / MBA", 6),
    ("doctorado", "Doctorado / PhD", 7),
    ("posdoctorado", "Posdoctorado", 8),
]

SECTORES = [
    ("financiero", "Financiero y bancario"),
    ("consumo_masivo", "Consumo masivo / Retail"),
    ("industrial", "Industrial / Manufactura"),
    ("tecnologia", "Tecnología / Software"),
    ("salud", "Salud / Farmacéutico"),
    ("energia", "Energía y servicios públicos"),
    ("construccion", "Construcción / Infraestructura"),
    ("agroindustria", "Agroindustria"),
    ("educacion", "Educación"),
    ("consultoria", "Consultoría / Servicios profesionales"),
    ("telecomunicaciones", "Telecomunicaciones"),
    ("logistica", "Logística y transporte"),
    ("publico", "Sector público / Gobierno"),
    ("hidrocarburos", "Hidrocarburos / Minería"),
    ("seguros", "Seguros"),
]

DEPARTAMENTOS = [
    "Bogotá D.C.", "Antioquia", "Valle del Cauca", "Atlántico", "Santander",
    "Cundinamarca", "Bolívar", "Caldas", "Risaralda", "Norte de Santander",
    "Tolima", "Boyacá", "Nariño", "Córdoba", "Magdalena", "Otro",
]


def _seed_catalogo(db, Model, registros, by="codigo"):
    creados = 0
    for orden, item in enumerate(registros, start=1):
        if Model is TipoDocumento or Model is Nacionalidad or Model is Sector:
            codigo, nombre = item
            existe = db.query(Model).filter(Model.codigo == codigo).first()
            if existe:
                continue
            db.add(Model(codigo=codigo, nombre=nombre, orden=orden, activo=True))
            creados += 1
        elif Model is NivelFormacion:
            codigo, nombre, peso = item
            if db.query(Model).filter(Model.codigo == codigo).first():
                continue
            db.add(Model(codigo=codigo, nombre=nombre, peso=peso, orden=orden, activo=True))
            creados += 1
        elif Model is Departamento:
            nombre = item
            if db.query(Model).filter(Model.nombre == nombre).first():
                continue
            db.add(Model(nombre=nombre, orden=orden, activo=True))
            creados += 1
    db.commit()
    log.info("%s: %d nuevos.", Model.__tablename__, creados)


def _seed_usuario_admin(db):
    username = config.ADMIN_USERNAME
    if db.query(UsuarioAdmin).filter(UsuarioAdmin.username == username).first():
        log.info("Usuario admin '%s' ya existe.", username)
        return
    db.add(UsuarioAdmin(
        username=username,
        password_hash=hash_password(config.ADMIN_PASSWORD),
        nombre_completo="Administrador INALDE",
        rol="superadmin",
        activo=True,
    ))
    db.commit()
    log.info("Usuario admin '%s' creado (rol superadmin).", username)


def _seed_ofertas(db):
    ofertas = [
        dict(
            codigo="OFE-00000001",
            titulo="Director(a) Comercial",
            area="Comercial / Ventas",
            descripcion=("Liderar la estrategia comercial nacional, equipos de ventas "
                         "y la relación con clientes clave de la compañía."),
            requisitos_tecnicos="Gestión comercial, manejo de P&L, CRM, planeación estratégica.",
            requisitos_experiencia="Más de 10 años en áreas comerciales, 5 en cargos de dirección.",
            requisitos_educacion="Profesional con MBA o especialización en mercadeo/ventas.",
            area_estudio="Administración, Mercadeo, Ingeniería Industrial o afines",
            sector="consumo_masivo",
            ubicacion="Bogotá, Colombia",
            tipo_empresa="Multinacional de consumo masivo",
            contexto_organizacional="Compañía en expansión regional con presencia en 4 países.",
            reto_principal="Duplicar la facturación en 3 años y consolidar el canal moderno.",
            modo_busqueda="hibrido",
            importancia_sector="alto",
            sectores_transferibles=["retail", "farmaceutico", "telecomunicaciones"],
            anos_experiencia_min=10,
            nivel_jerarquico_min="direccion",
            idioma_requerido="ingles",
            idioma_nivel_min="avanzado",
            pais_requerido="Colombia",
            ciudad_requerida="Bogotá",
            requiere_internacional=False,
            requiere_liderazgo=True,
            requiere_pyl=True,
            formacion_min="maestria",
            skills_requeridos=["liderazgo comercial", "manejo de P&L", "negociacion", "canal moderno"],
            tecnologias_requeridas=["Salesforce", "SAP", "Power BI", "Excel avanzado"],
            pesos=None,
            estado="abierta",
        ),
        dict(
            codigo="OFE-00000002",
            titulo="Gerente de Transformación Digital",
            area="Tecnología / Estrategia",
            descripcion=("Diseñar y ejecutar la hoja de ruta de transformación digital "
                         "de la organización, integrando procesos, datos y cultura."),
            requisitos_tecnicos="Gestión de proyectos ágiles, analítica de datos, gestión del cambio.",
            requisitos_experiencia="8+ años en tecnología/estrategia, liderando transformaciones.",
            requisitos_educacion="Profesional en ingeniería/administración con posgrado.",
            area_estudio="Ingeniería de Sistemas, Industrial, Administración o afines",
            sector="tecnologia",
            ubicacion="Medellín, Colombia",
            tipo_empresa="Empresa industrial en proceso de modernización",
            contexto_organizacional="Organización tradicional iniciando su digitalización.",
            reto_principal="Liderar el cambio cultural y tecnológico en 18 meses.",
            modo_busqueda="potencial_exito",
            importancia_sector="medio",
            sectores_transferibles=["consultoria", "financiero", "telecomunicaciones"],
            anos_experiencia_min=8,
            nivel_jerarquico_min="gerencia",
            idioma_requerido="ingles",
            idioma_nivel_min="intermedio",
            pais_requerido="Colombia",
            ciudad_requerida=None,
            requiere_internacional=False,
            requiere_liderazgo=True,
            requiere_pyl=False,
            formacion_min="especializacion",
            skills_requeridos=["transformacion digital", "gestion del cambio", "metodologias agiles", "analitica"],
            tecnologias_requeridas=["Jira", "Power BI", "Azure", "SQL"],
            pesos=None,
            estado="abierta",
        ),
    ]
    creados = 0
    for o in ofertas:
        if db.query(OfertaLaboral).filter(OfertaLaboral.codigo == o["codigo"]).first():
            continue
        oferta = OfertaLaboral(
            codigo=o["codigo"], titulo=o["titulo"], area=o["area"],
            descripcion=o["descripcion"],
            requisitos_tecnicos=o["requisitos_tecnicos"],
            requisitos_experiencia=o["requisitos_experiencia"],
            requisitos_educacion=o["requisitos_educacion"],
            sector=o["sector"], ubicacion=o["ubicacion"], tipo_empresa=o["tipo_empresa"],
            contexto_organizacional=o["contexto_organizacional"],
            reto_principal=o["reto_principal"],
            modo_busqueda=o["modo_busqueda"], importancia_sector=o["importancia_sector"],
            sectores_transferibles=json.dumps(o["sectores_transferibles"], ensure_ascii=False),
            anos_experiencia_min=o["anos_experiencia_min"],
            nivel_jerarquico_min=o["nivel_jerarquico_min"],
            idioma_requerido=o["idioma_requerido"], idioma_nivel_min=o["idioma_nivel_min"],
            pais_requerido=o["pais_requerido"], ciudad_requerida=o["ciudad_requerida"],
            requiere_internacional=o["requiere_internacional"],
            requiere_liderazgo=o["requiere_liderazgo"], requiere_pyl=o["requiere_pyl"],
            formacion_min=o["formacion_min"],
            skills_requeridos=json.dumps(o["skills_requeridos"], ensure_ascii=False),
            tecnologias_requeridas=json.dumps(o.get("tecnologias_requeridas") or [], ensure_ascii=False),
            area_estudio=o.get("area_estudio"),
            pesos=o["pesos"],
            estado=o["estado"], activo=(o["estado"] == "abierta"),
        )
        # requisitos eliminatorios derivados
        elim = []
        if o["anos_experiencia_min"]:
            elim.append({"criterio": "experiencia", "valor": o["anos_experiencia_min"],
                         "descripcion": f"Mínimo {o['anos_experiencia_min']} años de experiencia"})
        if o["idioma_requerido"]:
            elim.append({"criterio": "idioma", "valor": o["idioma_requerido"],
                         "nivel": o["idioma_nivel_min"],
                         "descripcion": f"{o['idioma_requerido']} nivel {o['idioma_nivel_min']}"})
        if o["formacion_min"]:
            elim.append({"criterio": "formacion", "valor": o["formacion_min"],
                         "descripcion": f"Formación mínima: {o['formacion_min']}"})
        if o["requiere_liderazgo"]:
            elim.append({"criterio": "liderazgo", "descripcion": "Experiencia liderando equipos"})
        if o["requiere_pyl"]:
            elim.append({"criterio": "pyl", "descripcion": "Responsabilidad sobre P&L"})
        oferta.requisitos_eliminatorios = json.dumps(elim, ensure_ascii=False)
        oferta.reglas_compensacion = json.dumps({}, ensure_ascii=False)
        db.add(oferta)
        creados += 1
    db.commit()
    log.info("ofertas_laborales: %d nuevas.", creados)


def run():
    init_db()
    db = SessionLocal()
    try:
        _seed_catalogo(db, TipoDocumento, TIPOS_DOCUMENTO)
        _seed_catalogo(db, Nacionalidad, NACIONALIDADES)
        _seed_catalogo(db, NivelFormacion, NIVELES_FORMACION)
        _seed_catalogo(db, Sector, SECTORES)
        _seed_catalogo(db, Departamento, DEPARTAMENTOS)
        _seed_usuario_admin(db)
        _seed_ofertas(db)
        log.info("Seed completado.")
    finally:
        db.close()


if __name__ == "__main__":
    run()
