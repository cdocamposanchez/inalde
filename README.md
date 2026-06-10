# INALDE · Motor de Curaduría Ejecutiva

Sistema **ATS (Applicant Tracking System) determinista — sin IA** para curar hojas de vida de ejecutivos y alumni de INALDE frente a **ofertas laborales**, estimando la probabilidad de éxito de cada candidato mediante un motor de reglas transparente y auditable.

La aplicación consta de dos módulos:

- **Formulario público** (`/`): captura estructurada de la hoja de vida del candidato en 6 pasos (datos personales, perfil ejecutivo, habilidades/tecnologías/idiomas, formación, experiencia y envío), con sección de **habilidades** (no "dependencias"), **tecnologías/herramientas**, idiomas, sectores con autocompletado, formación y experiencia, más la carga del CV en PDF.
- **Módulo administrativo** (`/admin`): tablero, gestión de candidatos y ofertas, **gestión de usuarios** (con asignación de ofertas a revisores), catálogos individuales, ejecución de la curaduría ATS (individual y masiva) y ranking de candidatos por oferta. El análisis de cada candidato se presenta como un **dashboard interactivo** (medidor de puntuación, métricas, criterios y tarjetas de fortalezas/brechas).

---

## Motor de curaduría (ATS determinista)

El motor evalúa cada candidato contra una oferta con reglas explícitas, sin modelos generativos. Esto garantiza resultados **reproducibles, explicables y auditables**.

**Tres modos de búsqueda:**

| Modo | Enfoque |
|------|---------|
| `matching_exacto` | Prioriza el cumplimiento literal de requisitos técnicos y de experiencia. |
| `potencial_exito` | Pondera el potencial de crecimiento, liderazgo y complejidad gestionada. |
| `hibrido` | Equilibrio entre ajuste actual y proyección. |

**Doce criterios evaluados:** experiencia funcional, experiencia sectorial, nivel jerárquico, formación académica, liderazgo de equipos, complejidad gestionada, idiomas, internacionalidad, transformación/cambio, estilo de liderazgo, potencial de crecimiento y fit con la comunidad alumni.

**Características del motor:**

- Requisitos eliminatorios (derivados automáticamente de la configuración de la oferta).
- Pesos dinámicos por criterio (configurables por oferta; se normalizan a 100).
- Reglas de compensación entre criterios.
- Escala de recomendación de 0 a 100 (≥90 recomendado prioritario … <40 no recomendado).
- Salida estructurada por candidato: puntuación, recomendación, puntos fuertes y débiles, habilidades coincidentes y faltantes, complejidad, riesgos, preguntas de entrevista sugeridas y próximos pasos.

---

## Paleta de marca INALDE

| Uso | HEX |
|-----|-----|
| Rojo principal | `#E30613` |
| Rojo hover | `#E1010B` |
| Negro | `#000000` |
| Título | `#212529` |
| Subrayado | `#333333` |
| Gris medio | `#A6A6A6` |
| Gris barra | `#E4E4E4` |
| Gris fondo | `#F4F4F4` |
| Gris sección | `#F4F5FA` |
| Blanco | `#FFFFFF` |

Tipografías: **Fraunces** (títulos) y **DM Sans** (cuerpo).

---

## Stack técnico

- **FastAPI** + **Uvicorn**
- **SQLAlchemy 2.0** + **PostgreSQL** (vía `psycopg`)
- **Jinja2** para las plantillas server-side
- **ReportLab** para generar el PDF de la hoja de vida
- **passlib + bcrypt** para el hash de contraseñas; sesión por cookie firmada (`itsdangerous`)

---

## Puesta en marcha con Docker (recomendado)

Requisitos: Docker y Docker Compose.

```bash
cp .env.example .env          # ajuste credenciales y SESSION_SECRET
docker compose up --build
```

Al levantar, el contenedor crea el esquema, siembra los catálogos y dos ofertas de ejemplo, y expone:

- Formulario público: <http://localhost:7070>
- Módulo administrativo: <http://localhost:7070/admin>

---

## Puesta en marcha local (sin Docker)

Requisitos: Python 3.12 y un PostgreSQL accesible (o usar `DATABASE_URL` apuntando a SQLite para pruebas).

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env          # configure POSTGRES_* o DATABASE_URL

python -m app.seed            # crea esquema + catálogos + admin + ofertas demo
uvicorn app.main:app --host 0.0.0.0 --port 7070 --reload
```

---

## Acceso administrativo por defecto

| Usuario | Contraseña |
|---------|-----------|
| `admin` | `inalde1234` |

> Cambie estas credenciales y `SESSION_SECRET` antes de cualquier despliegue real.

**Roles disponibles:** `superadmin` (todo, incluida la gestión de usuarios), `admin` (catálogos, ofertas y candidatos; ve todas las ofertas) y `revisor` (solo los candidatos de las ofertas que el superadmin le asigne).

---

## Flujo de uso

1. El candidato completa el formulario público y adjunta su CV en PDF. Se genera un consecutivo (`INALDE-AÑO-00001`) y queda en estado **Recibido**.
2. El equipo crea o ajusta una **oferta laboral** en `/admin/ofertas`, definiendo el bloque descriptivo y la configuración del motor (modo, requisitos, pesos).
3. Desde el detalle del candidato se ejecuta la **curaduría** contra una oferta, o desde el ranking de la oferta se **curan todos** los candidatos de una vez.
4. El sistema produce la puntuación y el análisis estructurado; el candidato avanza por los estados **Recibido → En evaluación → Preseleccionado → Finalista → Contratado / Descartado**.
5. El **ranking** ordena a los candidatos evaluados por puntuación para cada oferta.

---

## Estructura del proyecto

```
inalde/
├─ app/
│  ├─ main.py            # App FastAPI, formulario público y APIs de catálogos
│  ├─ admin.py           # Router del módulo administrativo
│  ├─ ats_engine.py      # Motor de curaduría determinista (12 criterios)
│  ├─ database.py        # Modelos SQLAlchemy y sesión
│  ├─ workflows.py       # Estados del candidato
│  ├─ security.py        # Sesión, hash y control de roles
│  ├─ config.py          # Configuración por variables de entorno
│  ├─ pdf_generator.py   # Generación del PDF de hoja de vida
│  ├─ mailer.py          # Envío de correo (opcional)
│  ├─ seed.py            # Catálogos, usuario admin y ofertas de ejemplo
│  ├─ templates/         # Plantillas Jinja2 (público + admin/)
│  └─ static/            # CSS y JS
├─ uploads/              # Hojas de vida en PDF (persistente)
├─ requirements.txt
├─ Dockerfile
├─ docker-compose.yml
└─ .env.example
```

---
