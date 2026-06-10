"""
Modelos de base de datos — INALDE · Motor de Curaduría Ejecutiva.
SQLAlchemy 2.0 con PostgreSQL (SQLite solo para pruebas locales).

Entidades principales:
  Candidato      → hoja de vida del alumni / postulante (con habilidades,
                   idiomas, sectores, formación y experiencia).
  OfertaLaboral  → vacante directiva/profesional con sus requisitos y la
                   configuración de búsqueda (modo, pesos, eliminatorios,
                   reglas de compensación). Reemplaza el antiguo "objeto
                   contractual".
  Evaluacion     → resultado de la curaduría de un Candidato contra una
                   OfertaLaboral, generado por el motor ATS determinista.
"""
import os
from datetime import datetime, date
from sqlalchemy import (
    create_engine, Column, Integer, String, Date, DateTime,
    ForeignKey, Boolean, Text, Table, inspect, text, UniqueConstraint
)
from sqlalchemy.orm import declarative_base, relationship, sessionmaker


def _build_database_url() -> str:
    url = os.getenv("DATABASE_URL")
    if url:
        return url
    user = os.getenv("POSTGRES_USER", "inalde")
    password = os.getenv("POSTGRES_PASSWORD", "inalde")
    host = os.getenv("POSTGRES_HOST", "localhost")
    port = os.getenv("POSTGRES_PORT", "5432")
    db = os.getenv("POSTGRES_DB", "curaduria_inalde")
    return f"postgresql+psycopg://{user}:{password}@{host}:{port}/{db}"


DATABASE_URL = _build_database_url()

engine_kwargs = {"pool_pre_ping": True}
if DATABASE_URL.startswith("sqlite"):
    engine_kwargs["connect_args"] = {"check_same_thread": False}
else:
    engine_kwargs["pool_size"] = int(os.getenv("DB_POOL_SIZE", "5"))
    engine_kwargs["max_overflow"] = int(os.getenv("DB_MAX_OVERFLOW", "10"))

engine = create_engine(DATABASE_URL, **engine_kwargs)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


# Alcance de revisores: a un revisor se le asignan ofertas y solo verá
# los candidatos/evaluaciones de esas ofertas. superadmin/admin ven todo.
usuario_oferta = Table(
    "usuario_oferta",
    Base.metadata,
    Column("usuario_id", ForeignKey("usuarios_admin.id", ondelete="CASCADE"), primary_key=True),
    Column("oferta_id", ForeignKey("ofertas_laborales.id", ondelete="CASCADE"), primary_key=True),
)


# ============================================================
# Catálogos parametrizables
# ============================================================
class TipoDocumento(Base):
    __tablename__ = "tipos_documento"
    id = Column(Integer, primary_key=True, index=True)
    codigo = Column(String(10), nullable=False, unique=True)
    nombre = Column(String(120), nullable=False)
    activo = Column(Boolean, default=True, nullable=False)
    orden = Column(Integer, default=0)


class Nacionalidad(Base):
    __tablename__ = "nacionalidades"
    id = Column(Integer, primary_key=True, index=True)
    codigo = Column(String(5), nullable=False, unique=True)
    nombre = Column(String(120), nullable=False, unique=True)
    activo = Column(Boolean, default=True, nullable=False)
    orden = Column(Integer, default=0)


class NivelFormacion(Base):
    """Niveles académicos. `peso` ordena la jerarquía para el ATS."""
    __tablename__ = "niveles_formacion"
    id = Column(Integer, primary_key=True, index=True)
    codigo = Column(String(30), nullable=False, unique=True)
    nombre = Column(String(120), nullable=False, unique=True)
    peso = Column(Integer, default=0)   # bachiller=1 ... doctorado=8
    activo = Column(Boolean, default=True, nullable=False)
    orden = Column(Integer, default=0)


class Sector(Base):
    """Sectores económicos (catálogo para ofertas y candidatos)."""
    __tablename__ = "sectores"
    id = Column(Integer, primary_key=True, index=True)
    codigo = Column(String(40), nullable=False, unique=True)
    nombre = Column(String(160), nullable=False, unique=True)
    activo = Column(Boolean, default=True, nullable=False)
    orden = Column(Integer, default=0)


class Departamento(Base):
    __tablename__ = "departamentos"
    id = Column(Integer, primary_key=True, index=True)
    codigo_dane = Column(String(5), nullable=True, unique=True)
    nombre = Column(String(120), nullable=False, unique=True)
    activo = Column(Boolean, default=True, nullable=False)
    orden = Column(Integer, default=0)


# ============================================================
# Usuarios admin
# ============================================================
class UsuarioAdmin(Base):
    __tablename__ = "usuarios_admin"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(60), nullable=False, unique=True, index=True)
    password_hash = Column(String(200), nullable=False)
    nombre_completo = Column(String(200), nullable=True)
    rol = Column(String(20), nullable=False, default="superadmin")
    activo = Column(Boolean, default=True, nullable=False)
    fecha_creacion = Column(DateTime, default=datetime.utcnow, nullable=False)
    ultimo_acceso = Column(DateTime, nullable=True)

    ofertas = relationship("OfertaLaboral", secondary=usuario_oferta, back_populates="usuarios")

    @property
    def es_superadmin(self) -> bool:
        return (self.rol or "").lower() == "superadmin"

    @property
    def es_admin(self) -> bool:
        return (self.rol or "").lower() == "admin"

    @property
    def es_revisor(self) -> bool:
        return (self.rol or "").lower() == "revisor"

    def puede_gestionar_usuarios(self) -> bool:
        return self.es_superadmin

    def puede_gestionar_catalogos(self) -> bool:
        return self.es_superadmin or self.es_admin

    def puede_administrar(self) -> bool:
        return self.puede_gestionar_catalogos()

    def ve_todo(self) -> bool:
        # Solo el superadministrador ve todo el sistema. Los administradores y
        # los revisores quedan acotados a las ofertas que tengan asignadas.
        return self.es_superadmin

    def ofertas_ids(self) -> list[int]:
        return [o.id for o in self.ofertas]


# ============================================================
# Candidato (hoja de vida)
# ============================================================
class Candidato(Base):
    __tablename__ = "candidatos"

    id = Column(Integer, primary_key=True, index=True)
    consecutivo = Column(String(30), unique=True, index=True, nullable=True)

    # Datos personales / contacto
    nombres = Column(String(120), nullable=False)
    apellidos = Column(String(120), nullable=False)
    tipo_documento = Column(String(20), nullable=False)
    numero_documento = Column(String(40), nullable=False, index=True)
    fecha_nacimiento = Column(Date, nullable=True)
    nacionalidad = Column(String(80), nullable=True)
    correo = Column(String(160), nullable=False, index=True)
    telefono_celular = Column(String(40), nullable=False)
    linkedin = Column(String(255), nullable=True)
    ciudad = Column(String(120), nullable=True)
    pais = Column(String(120), nullable=True, default="Colombia")

    # Perfil ejecutivo
    titular = Column(String(200), nullable=True)          # headline / cargo actual
    resumen_profesional = Column(Text, nullable=True)
    anos_experiencia = Column(Integer, nullable=True)     # declarados
    pretension_salarial = Column(String(80), nullable=True)
    disponibilidad_viaje = Column(Boolean, default=False)
    disponibilidad_reubicacion = Column(Boolean, default=False)

    # Fit alumni / comunidad INALDE
    es_alumni = Column(Boolean, default=False)
    programa_inalde = Column(String(160), nullable=True)

    # Archivo
    cv_archivo = Column(String(300), nullable=True)
    cv_archivo_original = Column(String(300), nullable=True)

    # Auditoría / estado
    fecha_registro = Column(DateTime, default=datetime.utcnow, nullable=False)
    estado = Column(String(40), default="recibido", nullable=False, index=True)
    fecha_estado_actual = Column(DateTime, default=datetime.utcnow, nullable=True)
    fecha_actualizacion_estado = Column(DateTime, nullable=True)
    fecha_finalizacion_estado = Column(DateTime, nullable=True)

    # Relaciones
    formaciones = relationship("Formacion", back_populates="candidato", cascade="all, delete-orphan")
    experiencias = relationship("Experiencia", back_populates="candidato", cascade="all, delete-orphan")
    habilidades = relationship("Habilidad", back_populates="candidato", cascade="all, delete-orphan")
    tecnologias = relationship("Tecnologia", back_populates="candidato", cascade="all, delete-orphan")
    idiomas = relationship("IdiomaCandidato", back_populates="candidato", cascade="all, delete-orphan")
    sectores = relationship("SectorCandidato", back_populates="candidato", cascade="all, delete-orphan")
    evaluaciones = relationship("Evaluacion", back_populates="candidato", cascade="all, delete-orphan")

    @property
    def nombre_completo(self) -> str:
        return f"{self.nombres} {self.apellidos}".strip()


class Habilidad(Base):
    """Habilidad / competencia del candidato. Reemplaza las antiguas
    'áreas de interés / dependencias'."""
    __tablename__ = "habilidades"
    id = Column(Integer, primary_key=True, index=True)
    candidato_id = Column(Integer, ForeignKey("candidatos.id", ondelete="CASCADE"), nullable=False)
    nombre = Column(String(120), nullable=False)
    nivel = Column(String(30), nullable=True)   # basico | intermedio | avanzado | experto
    candidato = relationship("Candidato", back_populates="habilidades")


class Tecnologia(Base):
    """Tecnología / herramienta que domina el candidato (software,
    plataformas, lenguajes, ERPs, etc.). Complementa las habilidades
    y también alimenta el match de skills del motor."""
    __tablename__ = "tecnologias"
    id = Column(Integer, primary_key=True, index=True)
    candidato_id = Column(Integer, ForeignKey("candidatos.id", ondelete="CASCADE"), nullable=False)
    nombre = Column(String(120), nullable=False)
    nivel = Column(String(30), nullable=True)   # basico | intermedio | avanzado | experto
    candidato = relationship("Candidato", back_populates="tecnologias")


class IdiomaCandidato(Base):
    __tablename__ = "idiomas_candidato"
    id = Column(Integer, primary_key=True, index=True)
    candidato_id = Column(Integer, ForeignKey("candidatos.id", ondelete="CASCADE"), nullable=False)
    idioma = Column(String(60), nullable=False)
    nivel = Column(String(30), nullable=True)   # basico | intermedio | avanzado | nativo
    candidato = relationship("Candidato", back_populates="idiomas")


class SectorCandidato(Base):
    __tablename__ = "sectores_candidato"
    id = Column(Integer, primary_key=True, index=True)
    candidato_id = Column(Integer, ForeignKey("candidatos.id", ondelete="CASCADE"), nullable=False)
    sector = Column(String(160), nullable=False)
    candidato = relationship("Candidato", back_populates="sectores")


class Formacion(Base):
    __tablename__ = "formaciones"
    id = Column(Integer, primary_key=True, index=True)
    candidato_id = Column(Integer, ForeignKey("candidatos.id", ondelete="CASCADE"), nullable=False)
    nivel = Column(String(60), nullable=False)   # codigo de NivelFormacion
    titulo = Column(String(200), nullable=False)
    institucion = Column(String(200), nullable=False)
    anio_inicio = Column(Integer, nullable=True)
    anio_fin = Column(Integer, nullable=True)
    en_curso = Column(Boolean, default=False)
    candidato = relationship("Candidato", back_populates="formaciones")


class Experiencia(Base):
    """Experiencia profesional enriquecida con campos estructurados que
    alimentan el motor ATS (sin necesidad de IA)."""
    __tablename__ = "experiencias"
    id = Column(Integer, primary_key=True, index=True)
    candidato_id = Column(Integer, ForeignKey("candidatos.id", ondelete="CASCADE"), nullable=False)
    empresa = Column(String(200), nullable=False)
    cargo = Column(String(200), nullable=False)
    sector = Column(String(160), nullable=True)
    pais = Column(String(120), nullable=True)
    fecha_inicio = Column(Date, nullable=False)
    fecha_fin = Column(Date, nullable=True)
    actual = Column(Boolean, default=False)
    funciones = Column(Text, nullable=True)
    # Señales estructuradas para el scoring ejecutivo:
    nivel_jerarquico = Column(String(40), nullable=True)   # operativo|coordinacion|jefatura|gerencia|direccion|alta_direccion
    lidero_equipo = Column(Boolean, default=False)
    tam_equipo = Column(Integer, nullable=True)
    manejo_pyl = Column(Boolean, default=False)
    candidato = relationship("Candidato", back_populates="experiencias")


# ============================================================
# Oferta laboral (vacante)  — reemplaza "Objeto contractual"
# ============================================================
class OfertaLaboral(Base):
    __tablename__ = "ofertas_laborales"

    id = Column(Integer, primary_key=True, index=True)
    codigo = Column(String(40), unique=True, index=True, nullable=True)

    # Descripción de la vacante (bloque A del prompt maestro)
    titulo = Column(String(300), nullable=False)              # Cargo
    area = Column(String(160), nullable=True)
    descripcion = Column(Text, nullable=True)
    requisitos_tecnicos = Column(Text, nullable=True)
    requisitos_experiencia = Column(Text, nullable=True)
    requisitos_educacion = Column(Text, nullable=True)
    area_estudio = Column(String(200), nullable=True)         # área/campo de estudio requerido (parámetro de educación)
    sector = Column(String(160), nullable=True)
    ubicacion = Column(String(160), nullable=True)
    tipo_empresa = Column(String(160), nullable=True)
    contexto_organizacional = Column(Text, nullable=True)
    reto_principal = Column(Text, nullable=True)

    # Configuración de búsqueda (bloque B)
    modo_busqueda = Column(String(30), default="hibrido")     # matching_exacto|potencial_exito|hibrido
    importancia_sector = Column(String(20), default="medio")  # critico|alto|medio|bajo
    sectores_transferibles = Column(Text, nullable=True)      # JSON list[str]

    anos_experiencia_min = Column(Integer, default=0)
    nivel_jerarquico_min = Column(String(40), nullable=True)
    idioma_requerido = Column(String(60), nullable=True)
    idioma_nivel_min = Column(String(30), nullable=True)
    pais_requerido = Column(String(120), nullable=True)
    ciudad_requerida = Column(String(120), nullable=True)
    requiere_internacional = Column(Boolean, default=False)
    requiere_liderazgo = Column(Boolean, default=False)
    requiere_pyl = Column(Boolean, default=False)
    formacion_min = Column(String(60), nullable=True)         # codigo NivelFormacion

    skills_requeridos = Column(Text, nullable=True)           # JSON list[str]
    tecnologias_requeridas = Column(Text, nullable=True)      # JSON list[str] (herramientas/tecnologías exigidas)
    pesos = Column(Text, nullable=True)                       # JSON dict (12 criterios)
    requisitos_eliminatorios = Column(Text, nullable=True)    # JSON list[{criterio, descripcion}]
    reglas_compensacion = Column(Text, nullable=True)         # JSON dict

    activo = Column(Boolean, default=True, nullable=False)
    estado = Column(String(30), default="abierta")            # abierta|cerrada|pausada
    orden = Column(Integer, default=0)
    fecha_creacion = Column(DateTime, default=datetime.utcnow, nullable=False)

    evaluaciones = relationship("Evaluacion", back_populates="oferta", cascade="all, delete-orphan")
    usuarios = relationship("UsuarioAdmin", secondary=usuario_oferta, back_populates="ofertas")


# ============================================================
# Evaluación (resultado del motor de curaduría / ATS)
# ============================================================
class Evaluacion(Base):
    __tablename__ = "evaluaciones"
    __table_args__ = (
        UniqueConstraint("candidato_id", "oferta_id", name="uq_eval_candidato_oferta"),
    )

    id = Column(Integer, primary_key=True, index=True)
    candidato_id = Column(Integer, ForeignKey("candidatos.id", ondelete="CASCADE"), nullable=False, index=True)
    oferta_id = Column(Integer, ForeignKey("ofertas_laborales.id", ondelete="CASCADE"), nullable=False, index=True)

    # Campos escalares (para filtrar/ordenar el tablero)
    puntuacion = Column(Integer, default=0, index=True)
    nivel_recomendacion = Column(String(60), nullable=True, index=True)
    resultado_eliminatorio = Column(String(30), nullable=True)   # cumple|no_cumple|informacion_insuficiente
    modo_busqueda_aplicado = Column(String(30), nullable=True)
    complejidad_nivel = Column(String(20), nullable=True)        # alta|media|baja|no_evidente

    # Salida estructurada completa del motor (igual al JSON del prompt maestro)
    resultado_json = Column(Text, nullable=True)
    resumen_ejecutivo = Column(Text, nullable=True)

    fecha_evaluacion = Column(DateTime, default=datetime.utcnow, nullable=False)
    evaluado_por = Column(Integer, ForeignKey("usuarios_admin.id", ondelete="SET NULL"), nullable=True)

    candidato = relationship("Candidato", back_populates="evaluaciones")
    oferta = relationship("OfertaLaboral", back_populates="evaluaciones")


class CambioEstadoAuditoria(Base):
    """Auditoría genérica de cambios de estado (reutilizable por entidad)."""
    __tablename__ = "cambios_estado_auditoria"
    id = Column(Integer, primary_key=True, index=True)
    entity_type = Column(String(80), nullable=False, index=True)
    entity_id = Column(Integer, nullable=False, index=True)
    estado_anterior = Column(String(40), nullable=True)
    estado_nuevo = Column(String(40), nullable=False, index=True)
    comentario = Column(Text, nullable=True)
    usuario_admin_id = Column(Integer, ForeignKey("usuarios_admin.id", ondelete="SET NULL"), nullable=True)
    fecha_cambio = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    duracion_estado_segundos = Column(Integer, nullable=True)
    metadata_json = Column(Text, nullable=True)
    usuario_admin = relationship("UsuarioAdmin")


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _ensure_columns() -> None:
    """Migración ligera e idempotente: agrega columnas nuevas a tablas
    ya existentes sin necesidad de Alembic. `create_all` solo crea
    tablas faltantes, no columnas, así que esto evita errores
    («column does not exist») al desplegar sobre una base ya creada.

    Compatible con PostgreSQL y SQLite (ambos aceptan
    `ALTER TABLE ... ADD COLUMN`). Solo añade; nunca elimina ni altera
    tipos para no arriesgar datos existentes.
    """
    columnas_nuevas = {
        "ofertas_laborales": [
            ("area_estudio", "VARCHAR(200)"),
            ("tecnologias_requeridas", "TEXT"),
        ],
    }
    insp = inspect(engine)
    existentes_tablas = set(insp.get_table_names())
    with engine.begin() as conn:
        for tabla, columnas in columnas_nuevas.items():
            if tabla not in existentes_tablas:
                continue  # la creará create_all con el esquema completo
            cols_actuales = {c["name"] for c in insp.get_columns(tabla)}
            for nombre_col, tipo_sql in columnas:
                if nombre_col in cols_actuales:
                    continue
                conn.execute(text(f'ALTER TABLE {tabla} ADD COLUMN {nombre_col} {tipo_sql}'))


def init_db():
    """Crea las tablas si no existen y aplica migraciones ligeras."""
    Base.metadata.create_all(bind=engine)
    _ensure_columns()
