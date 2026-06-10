"""
Configuración central de la aplicación — INALDE · Motor de Curaduría Ejecutiva.

Estrategia de carga:
1. En desarrollo local, `python-dotenv` carga el archivo `.env` del
   directorio del proyecto si existe (en el import de este módulo).
2. En Docker, `docker-compose.yml` referencia el mismo `.env` vía
   `env_file:`, así que las variables ya están en el ambiente del
   contenedor. `load_dotenv()` es idempotente.
"""
import os
from pathlib import Path
from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent.parent
ENV_FILE = BASE_DIR / ".env"
load_dotenv(ENV_FILE, override=False)


def _bool_env(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).lower() in ("1", "true", "yes", "on")


# ─── Aplicación ──────────────────────────────────────────────
APP_NAME = os.getenv("APP_NAME", "INALDE · Motor de Curaduría Ejecutiva")
APP_SHORT_NAME = os.getenv("APP_SHORT_NAME", "Motor de Curaduría")
APP_VERSION = os.getenv("APP_VERSION", "1.0.0")
ENVIRONMENT = os.getenv("ENVIRONMENT", "development")
DEBUG = _bool_env("DEBUG", False)


# ─── Servidor ────────────────────────────────────────────────
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "7070"))


# ─── Base de datos ───────────────────────────────────────────
POSTGRES_USER = os.getenv("POSTGRES_USER", "inalde")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "inalde")
POSTGRES_DB = os.getenv("POSTGRES_DB", "curaduria_inalde")
POSTGRES_HOST = os.getenv("POSTGRES_HOST", "localhost")
POSTGRES_PORT = int(os.getenv("POSTGRES_PORT", "5432"))


# ─── Almacenamiento ──────────────────────────────────────────
UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", str(BASE_DIR / "uploads")))
MAX_PDF_SIZE_MB = int(os.getenv("MAX_PDF_SIZE_MB", "10"))
MAX_PDF_SIZE = MAX_PDF_SIZE_MB * 1024 * 1024


# ─── Reglas de negocio del formulario de hoja de vida ────────
MAX_FORMACIONES = int(os.getenv("MAX_FORMACIONES", "5"))
MAX_EXPERIENCIAS = int(os.getenv("MAX_EXPERIENCIAS", "10"))
MAX_HABILIDADES = int(os.getenv("MAX_HABILIDADES", "20"))
MAX_IDIOMAS = int(os.getenv("MAX_IDIOMAS", "6"))


# ─── Módulo administrativo ───────────────────────────────────
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "inalde1234")
SESSION_SECRET = os.getenv(
    "SESSION_SECRET",
    "CAMBIAR-EN-PRODUCCION-este-valor-no-es-seguro-solo-dev",
)


# ─── Persistencia / correo ───────────────────────────────────
# Por defecto las hojas de vida se almacenan para curaduría posterior.
STORE_HOJAS_VIDA = _bool_env("STORE_HOJAS_VIDA", True)

EMAIL_ENABLED = _bool_env("EMAIL_ENABLED", False)
EMAIL_DESTINO = os.getenv("EMAIL_DESTINO", "")
EMAIL_FROM_NAME = os.getenv("EMAIL_FROM_NAME", APP_NAME)
EMAIL_FROM = os.getenv("EMAIL_FROM", "")

SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
SMTP_USE_TLS = _bool_env("SMTP_USE_TLS", True)
SMTP_USE_SSL = _bool_env("SMTP_USE_SSL", False)


def assert_config_coherente() -> None:
    """Lanza si la configuración deja al sistema sin ningún destino."""
    if not STORE_HOJAS_VIDA and not EMAIL_ENABLED:
        raise RuntimeError(
            "Configuración inválida: STORE_HOJAS_VIDA=false y EMAIL_ENABLED=false "
            "simultáneamente. Sin base de datos ni correo, las hojas de vida se "
            "perderían. Activa al menos uno de los dos."
        )
    if EMAIL_ENABLED and not EMAIL_DESTINO:
        raise RuntimeError(
            "Configuración inválida: EMAIL_ENABLED=true pero EMAIL_DESTINO está vacío."
        )
    if EMAIL_ENABLED:
        if not SMTP_HOST or "@" in SMTP_HOST:
            raise RuntimeError(
                "Configuración inválida: SMTP_HOST debe ser el servidor (ej. smtp.gmail.com)."
            )
        if SMTP_USE_TLS and SMTP_USE_SSL:
            raise RuntimeError(
                "Configuración inválida: SMTP_USE_TLS y SMTP_USE_SSL no pueden estar ambos en true."
            )
        if not SMTP_USER or not SMTP_PASSWORD:
            raise RuntimeError(
                "Configuración inválida: faltan SMTP_USER o SMTP_PASSWORD."
            )
