"""
Zona horaria de la aplicación: America/Bogota (GMT-5).

Decisión:
-----------------------------------------------------------------
- Almacenamos timestamps como "naive UTC" en Postgres (sin tzinfo).
  Es la forma más portable: cualquier consulta SQL, cualquier
  herramienta de BI y cualquier replicación entiende UTC como
  referencia única. NO depende del TZ del servidor donde corre
  Postgres ni del de la app.

- En la capa de presentación (templates Jinja, JSON que va al
  navegador) convertimos a America/Bogota. Así el operador en
  Colombia ve "hoy a las 09:14" y no "hoy a las 14:14 UTC".

- Para que el navegador haga la conversión bien, exponemos los
  ISO strings con sufijo `Z` (UTC explícito). Luego en JS usamos
  `toLocaleString("es-CO", { timeZone: "America/Bogota", ... })`.

Si en el futuro la UBPD necesita operación multi-país, basta con
cambiar el TZ por defecto sin tocar la DB ni los modelos.
"""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from typing import Optional


# Zona horaria de operación. Configurable vía env por si en testing
# se quiere usar otra (por ejemplo "UTC" para tests deterministas).
import os
APP_TZ_NAME = os.getenv("APP_TZ", "America/Bogota")
APP_TZ = ZoneInfo(APP_TZ_NAME)
UTC = timezone.utc


def now_utc_naive() -> datetime:
    """Timestamp actual en UTC, sin tzinfo. Usado para columnas DateTime
    naive de SQLAlchemy. Reemplaza a `datetime.utcnow()` que está
    deprecado en Python 3.12+."""
    return datetime.now(UTC).replace(tzinfo=None)


def now_local() -> datetime:
    """Timestamp actual con tzinfo de la app (America/Bogota por
    defecto). Útil para etiquetas en plantillas y nombres de archivo."""
    return datetime.now(APP_TZ)


def to_local(dt) -> Optional[datetime]:
    """Convierte un datetime (naive-UTC o aware) a la zona horaria de
    la app. None pasa de largo para que los templates no exploten.

    Si recibe un objeto `date` (sin componente de hora), lo deja como
    está: las fechas calendario no tienen zona horaria. Esto permite
    usar el filtro `bogota` sin riesgo desde templates que mezclen
    columnas Date y DateTime."""
    if dt is None:
        return None
    # `date` puro: no tiene `tzinfo`. Lo devolvemos sin tocarlo para que
    # el `strftime` posterior funcione normal.
    if not isinstance(dt, datetime):
        return dt
    if dt.tzinfo is None:
        # Convención del proyecto: naive = UTC.
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(APP_TZ)


def format_local(dt, fmt: str = "%d/%m/%Y · %H:%M") -> str:
    """Filtro de Jinja: convierte a TZ local y formatea. Falsy → '—'.

    Acepta tanto `datetime` como `date`. Para `datetime` aware/naive
    aplica la conversión a la TZ de la app. Para `date` puro
    (calendar day) hace strftime directo: las fechas no se convierten."""
    local = to_local(dt)
    if local is None:
        return "—"
    return local.strftime(fmt)


def iso_utc(dt: Optional[datetime]) -> Optional[str]:
    """Serializa un datetime a ISO 8601 con sufijo Z explícito.

    Para que el navegador interprete correctamente el timestamp como
    UTC al hacer `new Date(...)`. Si pasamos un ISO sin tz, los
    browsers asumen "hora local del cliente" y la conversión sale mal.
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    # `isoformat()` de un aware en UTC da "...+00:00". Lo normalizamos
    # a "Z" porque es más corto y universalmente reconocido por JS.
    s = dt.astimezone(UTC).isoformat()
    return s.replace("+00:00", "Z")
