"""
Seguridad: hashing de contraseñas + sesiones del módulo admin.

Decisiones:
- bcrypt como algoritmo de hashing (resistencia a fuerza bruta). passlib
  lo abstrae y permite migrar a argon2id cambiando solo el `schemes`.
- Sesiones basadas en cookies firmadas con itsdangerous. La cookie es
  HttpOnly para evitar lectura por JavaScript del navegador.
"""
from datetime import datetime
from typing import Optional

from fastapi import Request, HTTPException, status, Depends
from sqlalchemy.orm import Session
from passlib.context import CryptContext
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired

from app import config
from app.database import get_db, UsuarioAdmin


# ============================================================
# Hashing de contraseñas
# ============================================================
_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(plain: str) -> str:
    """Genera un hash bcrypt de la contraseña."""
    return _pwd_context.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    """Verifica si `plain` corresponde al hash `hashed`."""
    try:
        return _pwd_context.verify(plain, hashed)
    except Exception:
        return False


# ============================================================
# Sesiones (cookies firmadas)
# ============================================================
COOKIE_NAME = "inalde_admin_session"
SESSION_MAX_AGE = 8 * 60 * 60   # 8 horas

_serializer = URLSafeTimedSerializer(
    config.SESSION_SECRET, salt="inalde-admin-session-v1"
)


def create_session_token(user_id: int) -> str:
    return _serializer.dumps({"uid": user_id})


def read_session_token(token: str) -> Optional[int]:
    try:
        data = _serializer.loads(token, max_age=SESSION_MAX_AGE)
        return int(data.get("uid"))
    except (BadSignature, SignatureExpired, ValueError, TypeError):
        return None


# ============================================================
# Dependencies de FastAPI
# ============================================================
def get_current_admin(
    request: Request,
    db: Session = Depends(get_db),
) -> UsuarioAdmin:
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="No autenticado")
    user_id = read_session_token(token)
    if user_id is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Sesión inválida o expirada")
    user = db.query(UsuarioAdmin).filter(UsuarioAdmin.id == user_id).first()
    if not user or not user.activo:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Usuario no encontrado o inactivo")
    return user


def get_current_admin_or_redirect(request: Request, db: Session = Depends(get_db)):
    """Versión "soft" para vistas HTML: devuelve None en lugar de 401."""
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return None
    user_id = read_session_token(token)
    if user_id is None:
        return None
    user = db.query(UsuarioAdmin).filter(UsuarioAdmin.id == user_id).first()
    if not user or not user.activo:
        return None
    return user


# ============================================================
# Roles / permisos
#   superadmin → todo (usuarios + catálogos + ofertas + candidatos)
#   admin      → catálogos + ofertas + candidatos (NO usuarios)
#   revisor    → solo candidatos/curaduría de sus ofertas asignadas
# ============================================================
def require_superadmin(admin: UsuarioAdmin = Depends(get_current_admin)) -> UsuarioAdmin:
    if not admin.es_superadmin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Se requiere rol de superadministrador para esta acción",
        )
    return admin


def require_gestor_catalogos(admin: UsuarioAdmin = Depends(get_current_admin)) -> UsuarioAdmin:
    if not admin.puede_gestionar_catalogos():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Se requiere rol de administrador para gestionar catálogos",
        )
    return admin
