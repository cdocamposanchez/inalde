"""
Envío de correo (opcional) — INALDE · Motor de Curaduría Ejecutiva.

Por defecto EMAIL_ENABLED=False y la app opera solo con persistencia en
base de datos. Si se habilita, al recibir una hoja de vida se notifica a
EMAIL_DESTINO con el PDF estructurado y el CV original adjuntos.

El envío NUNCA debe romper la respuesta al candidato: quien llama debe
capturar EmailSendError y continuar.
"""
import smtplib
import logging
from email.message import EmailMessage
from email.utils import formataddr
from typing import Optional, Tuple

from . import config

log = logging.getLogger("inalde.mailer")


class EmailSendError(RuntimeError):
    """Error controlado durante el envío de correo."""


def _construir_mensaje(
    asunto: str,
    cuerpo_html: str,
    cuerpo_texto: str,
    adjuntos: Optional[list[Tuple[str, bytes]]] = None,
) -> EmailMessage:
    msg = EmailMessage()
    msg["Subject"] = asunto
    msg["From"] = formataddr((config.EMAIL_FROM_NAME, config.EMAIL_FROM or config.SMTP_USER))
    msg["To"] = config.EMAIL_DESTINO
    msg.set_content(cuerpo_texto)
    msg.add_alternative(cuerpo_html, subtype="html")

    for nombre, contenido in (adjuntos or []):
        msg.add_attachment(
            contenido,
            maintype="application",
            subtype="pdf",
            filename=nombre,
        )
    return msg


def enviar_correo(
    asunto: str,
    cuerpo_html: str,
    cuerpo_texto: str,
    adjuntos: Optional[list[Tuple[str, bytes]]] = None,
) -> None:
    if not config.EMAIL_ENABLED:
        log.info("EMAIL_ENABLED=false; se omite el envío de correo.")
        return

    msg = _construir_mensaje(asunto, cuerpo_html, cuerpo_texto, adjuntos)
    try:
        if config.SMTP_USE_SSL:
            server = smtplib.SMTP_SSL(config.SMTP_HOST, config.SMTP_PORT, timeout=30)
        else:
            server = smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=30)
        with server:
            server.ehlo()
            if config.SMTP_USE_TLS and not config.SMTP_USE_SSL:
                server.starttls()
                server.ehlo()
            if config.SMTP_USER:
                server.login(config.SMTP_USER, config.SMTP_PASSWORD)
            server.send_message(msg)
        log.info("Correo enviado a %s (asunto=%s).", config.EMAIL_DESTINO, asunto)
    except Exception as e:  # noqa: BLE001
        log.exception("Fallo enviando correo: %s", e)
        raise EmailSendError(str(e)) from e


def enviar_candidato(
    datos: dict,
    pdf_generado: Optional[bytes] = None,
    pdf_usuario: Optional[Tuple[str, bytes]] = None,
) -> None:
    """Notifica la recepción de una hoja de vida para curaduría."""
    consecutivo = datos.get("consecutivo", "—")
    nombre = f"{datos.get('nombres', '')} {datos.get('apellidos', '')}".strip()
    asunto = f"[Curaduría INALDE] Nueva hoja de vida {consecutivo} — {nombre}"

    cuerpo_texto = (
        f"Se recibió una nueva hoja de vida para curaduría ejecutiva.\n\n"
        f"Radicado: {consecutivo}\n"
        f"Candidato: {nombre}\n"
        f"Correo: {datos.get('correo', '')}\n"
        f"Teléfono: {datos.get('telefono_celular', '')}\n"
        f"Ciudad/País: {datos.get('ciudad', '')} / {datos.get('pais', '')}\n"
    )
    cuerpo_html = f"""
    <div style="font-family:Arial,Helvetica,sans-serif;color:#212529">
      <div style="background:#E30613;color:#fff;padding:16px 20px;font-size:18px">
        INALDE · Motor de Curaduría Ejecutiva
      </div>
      <div style="padding:20px">
        <p>Se recibió una nueva hoja de vida para curaduría.</p>
        <table style="border-collapse:collapse">
          <tr><td style="padding:4px 12px;color:#A6A6A6">Radicado</td><td style="padding:4px 12px"><b>{consecutivo}</b></td></tr>
          <tr><td style="padding:4px 12px;color:#A6A6A6">Candidato</td><td style="padding:4px 12px">{nombre}</td></tr>
          <tr><td style="padding:4px 12px;color:#A6A6A6">Correo</td><td style="padding:4px 12px">{datos.get('correo','')}</td></tr>
          <tr><td style="padding:4px 12px;color:#A6A6A6">Teléfono</td><td style="padding:4px 12px">{datos.get('telefono_celular','')}</td></tr>
        </table>
        <p style="color:#A6A6A6;font-size:12px;margin-top:24px">
          Mensaje automático del Motor de Curaduría. No responda a este correo.
        </p>
      </div>
    </div>
    """

    adjuntos: list[Tuple[str, bytes]] = []
    if pdf_generado:
        adjuntos.append((f"{consecutivo}_estructurada.pdf", pdf_generado))
    if pdf_usuario and pdf_usuario[1]:
        nombre_arch = pdf_usuario[0] or "cv.pdf"
        adjuntos.append((nombre_arch, pdf_usuario[1]))

    enviar_correo(asunto, cuerpo_html, cuerpo_texto, adjuntos)
