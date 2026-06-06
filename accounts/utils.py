"""
Utilitaires : génération de PDFs et envoi d'emails SendGrid.
Toute la logique de génération d'identifiants est dans services.py.
"""
import io
import os
import math
import base64
import logging
from datetime import datetime
from django.conf import settings
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import (
    Mail, Attachment, FileContent, FileName, FileType, Disposition
)
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table,
    TableStyle, KeepTogether,
)
from reportlab.lib.enums import TA_CENTER, TA_RIGHT, TA_LEFT
from reportlab.lib.utils import ImageReader
import requests as _requests

logger = logging.getLogger('banking.utils')


# ── SendGrid ──────────────────────────────────────────────────────────────

def _send_email(from_name: str, to_email: str, subject: str, html_body: str,
                pdf_buffer: io.BytesIO = None, pdf_filename: str = None):
    sg = SendGridAPIClient(api_key=settings.SENDGRID_API_KEY)
    message = Mail(
        from_email=(settings.DEFAULT_FROM_EMAIL, from_name),
        to_emails=to_email,
        subject=subject,
        html_content=html_body,
    )
    if pdf_buffer and pdf_filename:
        pdf_buffer.seek(0)
        encoded = base64.b64encode(pdf_buffer.read()).decode()
        att = Attachment(
            FileContent(encoded),
            FileName(pdf_filename),
            FileType('application/pdf'),
            Disposition('attachment'),
        )
        message.attachment = att
    sg.send(message)


# ── Helpers style PayPal ──────────────────────────────────────────────────

def _email_header(bank) -> str:
    logo_html = ''
    if bank.logo:
        try:
            raw = bank.logo.url
            logo_url = raw if raw.startswith('http') else f"{settings.SITE_URL}{raw}"
            logo_html = f'<img src="{logo_url}" alt="{bank.name}" style="max-height:52px;max-width:150px;display:block;">'
        except Exception:
            pass

    if logo_html:
        content_cells = f'<td style="vertical-align:middle;">{logo_html}</td>'
    else:
        name_part = f'<span style="color:{bank.color_primary};font-size:17px;font-weight:700;font-family:Arial,Helvetica,sans-serif;">{bank.name}</span>'
        tagline_part = f'<br><span style="color:#888888;font-size:11px;font-family:Arial,Helvetica,sans-serif;">{bank.tagline}</span>' if bank.tagline else ''
        content_cells = f'<td style="vertical-align:middle;">{name_part}{tagline_part}</td>'

    return f"""
    <table width="100%" cellpadding="0" cellspacing="0" border="0" style="border-bottom:3px solid {bank.color_primary};">
      <tr>
        <td style="background:#ffffff;padding:18px 24px;">
          <table cellpadding="0" cellspacing="0" border="0">
            <tr>
              {content_cells}
            </tr>
          </table>
        </td>
      </tr>
    </table>"""


def _email_footer(bank) -> str:
    parts = [f'<strong style="color:#555555;">{bank.name}</strong>']
    if bank.address:
        parts.append(f'<span style="color:#888888;">{bank.address}</span>')
    if bank.phone:
        parts.append(f'<span style="color:#888888;">Tél&nbsp;: {bank.phone}</span>')
    if bank.email:
        parts.append(f'<a href="mailto:{bank.email}" style="color:#888888;text-decoration:none;">{bank.email}</a>')

    return f"""
    <table width="100%" cellpadding="0" cellspacing="0" border="0" style="margin-top:32px;border-top:1px solid #dddddd;">
      <tr>
        <td style="padding:20px 24px;text-align:center;">
          <p style="margin:0 0 6px;font-size:11px;font-family:Arial,Helvetica,sans-serif;color:#aaaaaa;line-height:1.7;">
            {' &nbsp;·&nbsp; '.join(parts)}
          </p>
          <p style="margin:0;font-size:11px;font-family:Arial,Helvetica,sans-serif;color:#aaaaaa;line-height:1.7;">
            Ce message est confidentiel et destiné uniquement à son destinataire.
          </p>
        </td>
      </tr>
    </table>"""


def _email_wrap(bank, body: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1.0">
</head>
<body style="margin:0;padding:0;background:#f5f5f5;">
  <table width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#f5f5f5;">
    <tr>
      <td align="center" style="padding:32px 16px;">
        <table width="600" cellpadding="0" cellspacing="0" border="0" style="max-width:600px;width:100%;background:#ffffff;border:1px solid #dddddd;">
          <tr><td>{_email_header(bank)}</td></tr>
          <tr>
            <td style="padding:32px 24px;font-family:Arial,Helvetica,sans-serif;color:#333333;">
              {body}
              {_email_footer(bank)}
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""


def _info_table(rows: list) -> str:
    html = '<table width="100%" cellpadding="0" cellspacing="0" border="0" style="margin:24px 0;border-top:1px solid #dddddd;">'
    for label, value in rows:
        html += f"""
        <tr>
          <td style="padding:12px 0;border-bottom:1px solid #dddddd;font-size:13px;color:#888888;font-family:Arial,Helvetica,sans-serif;width:45%;vertical-align:top;">{label}</td>
          <td style="padding:12px 0;border-bottom:1px solid #dddddd;font-size:13px;color:#333333;font-family:Arial,Helvetica,sans-serif;font-weight:700;text-align:right;vertical-align:top;">{value}</td>
        </tr>"""
    html += '</table>'
    return html


def _btn(label: str, url: str, color: str, text_color: str = '#ffffff') -> str:
    return f"""
    <table cellpadding="0" cellspacing="0" border="0" style="margin:28px 0;">
      <tr>
        <td style="background:{color};padding:14px 32px;">
          <a href="{url}" style="color:{text_color};font-size:14px;font-weight:700;font-family:Arial,Helvetica,sans-serif;text-decoration:none;display:block;">{label}</a>
        </td>
      </tr>
    </table>"""


def _alert(text: str, border_color: str, bg_color: str, text_color: str) -> str:
    return f"""
    <table width="100%" cellpadding="0" cellspacing="0" border="0" style="margin:24px 0;">
      <tr>
        <td style="border-left:4px solid {border_color};background:{bg_color};padding:14px 18px;">
          <p style="margin:0;font-size:13px;font-family:Arial,Helvetica,sans-serif;color:{text_color};line-height:1.6;">{text}</p>
        </td>
      </tr>
    </table>"""


# ── Email : ouverture de compte ───────────────────────────────────────────

def send_account_creation_email(bank_account):
    bank = bank_account.bank

    if bank_account.is_blocked:
        fee = f"{bank_account.unblock_fee:,.2f} {bank_account.currency}" if bank_account.unblock_fee else "Aucuns frais"
        status_html = _alert(
            f'<strong>Compte temporairement bloqué</strong><br>'
            f'Motif&nbsp;: {bank_account.block_reason}<br>'
            f'Frais de déblocage&nbsp;: {fee}',
            '#cc0000', '#fff8f8', '#cc0000'
        )
        status_html += '<p style="font-size:14px;color:#555555;line-height:1.7;margin:0;">Votre gestionnaire vous contactera pour la procédure de déblocage.</p>'
    else:
        status_html = _alert(
            'Votre compte est <strong>actif et opérationnel</strong>. Vous pouvez vous connecter dès maintenant.',
            '#2ea44f', '#f6fff9', '#1a7a38'
        )

    body = f"""
    <p style="font-size:16px;font-weight:700;color:#333333;margin:0 0 6px;font-family:Arial,Helvetica,sans-serif;">Bonjour {bank_account.first_name},</p>
    <p style="font-size:14px;color:#555555;line-height:1.7;margin:0 0 24px;">
      Votre compte bancaire a été ouvert avec succès auprès de <strong>{bank.name}</strong>.
    </p>
    {status_html}
    <p style="font-size:12px;font-weight:700;color:#888888;letter-spacing:0.8px;text-transform:uppercase;margin:28px 0 0;font-family:Arial,Helvetica,sans-serif;">Détails du compte</p>
    {_info_table([
        ('Titulaire', bank_account.get_full_name()),
        ('Banque', bank.name),
        ('Devise', bank_account.currency),
        ('Gestionnaire', bank_account.manager_name),
    ])}
    {_btn('Se connecter à mon espace', bank_account.get_login_url(), bank.color_primary, bank.color_text_on_primary)}
    {_alert(
        f'Votre gestionnaire <strong>{bank_account.manager_name}</strong> vous communiquera vos identifiants de connexion par voie sécurisée. Ne les partagez jamais avec quiconque.',
        '#f0a500', '#fffdf0', '#7a5c00'
    )}
    """

    try:
        rib_pdf = generate_rib_pdf(bank_account)
    except Exception:
        rib_pdf = None

    _send_email(
        from_name=bank.name,
        to_email=bank_account.email,
        subject=f"{bank.name} — Ouverture de votre compte bancaire",
        html_body=_email_wrap(bank, body),
        pdf_buffer=rib_pdf,
        pdf_filename=f"RIB_{bank_account.account_id}.pdf",
    )


# ── Email : virement initié (bénéficiaire) ────────────────────────────────

def send_transfer_initiated_email_to_beneficiary(transaction):
    beneficiary_email = transaction.get_beneficiary_display_email()
    if not beneficiary_email:
        return

    bank = transaction.account.bank

    body = f"""
    <p style="font-size:16px;font-weight:700;color:#333333;margin:0 0 6px;font-family:Arial,Helvetica,sans-serif;">Bonjour,</p>
    <p style="font-size:14px;color:#555555;line-height:1.7;margin:0 0 4px;">
      Un virement a été initié en votre faveur depuis <strong>{bank.name}</strong>.
    </p>
    <p style="font-size:28px;font-weight:700;color:#333333;font-family:Arial,Helvetica,sans-serif;margin:20px 0;">
      {transaction.amount:,.2f} <span style="font-size:16px;color:#888888;">{transaction.currency}</span>
    </p>
    {_info_table([
        ('Référence', transaction.reference),
        ("Donneur d'ordre", transaction.account.get_full_name()),
        ('Banque émettrice', bank.name),
        ('Motif', transaction.description or '—'),
    ])}
    {_alert(
        'Ce virement est en cours de validation. Vous recevrez la confirmation définitive sous <strong>48 heures ouvrées</strong>.',
        '#f0a500', '#fffdf0', '#7a5c00'
    )}
    """

    try:
        slip_pdf = generate_transfer_slip_pdf(transaction)
    except Exception:
        slip_pdf = None

    _send_email(
        from_name=bank.name,
        to_email=beneficiary_email,
        subject=f"Virement entrant en attente — Réf. {transaction.reference}",
        html_body=_email_wrap(bank, body),
        pdf_buffer=slip_pdf,
        pdf_filename=f"bordereau_{transaction.reference}.pdf",
    )


# ── Email : virement validé ───────────────────────────────────────────────

def send_transfer_validated_email(transaction):
    bank = transaction.account.bank
    validated_at = transaction.validated_at.strftime('%d/%m/%Y à %H:%M') if transaction.validated_at else '—'
    iban_bene = transaction.beneficiary.account_number if transaction.beneficiary else transaction.beneficiary_iban or '—'

    body_sender = f"""
    <p style="font-size:16px;font-weight:700;color:#333333;margin:0 0 6px;font-family:Arial,Helvetica,sans-serif;">Bonjour {transaction.account.first_name},</p>
    <p style="font-size:14px;color:#555555;line-height:1.7;margin:0 0 4px;">
      Votre virement a été <strong>validé avec succès</strong>.
    </p>
    <p style="font-size:28px;font-weight:700;color:#333333;font-family:Arial,Helvetica,sans-serif;margin:20px 0;">
      -{transaction.amount:,.2f} <span style="font-size:16px;color:#888888;">{transaction.currency}</span>
    </p>
    {_info_table([
        ('Référence', transaction.reference),
        ('Bénéficiaire', transaction.get_beneficiary_display_name()),
        ('IBAN bénéficiaire', iban_bene),
        ('Motif', transaction.description or '—'),
        ('Validé le', validated_at),
    ])}
    """

    try:
        slip_pdf = generate_transfer_slip_pdf(transaction)
    except Exception:
        slip_pdf = None

    _send_email(
        from_name=bank.name,
        to_email=transaction.account.email,
        subject=f"Virement validé — Réf. {transaction.reference}",
        html_body=_email_wrap(bank, body_sender),
        pdf_buffer=slip_pdf,
        pdf_filename=f"bordereau_{transaction.reference}.pdf",
    )

    beneficiary_email = transaction.get_beneficiary_display_email()
    if beneficiary_email:
        body_bene = f"""
        <p style="font-size:16px;font-weight:700;color:#333333;margin:0 0 6px;font-family:Arial,Helvetica,sans-serif;">Bonjour,</p>
        <p style="font-size:14px;color:#555555;line-height:1.7;margin:0 0 4px;">
          Un virement a été <strong>validé</strong> en votre faveur.
        </p>
        <p style="font-size:28px;font-weight:700;color:#2ea44f;font-family:Arial,Helvetica,sans-serif;margin:20px 0;">
          +{transaction.amount:,.2f} <span style="font-size:16px;color:#888888;">{transaction.currency}</span>
        </p>
        {_info_table([
            ('Référence', transaction.reference),
            ('Émetteur', transaction.account.get_full_name()),
            ('Banque émettrice', bank.name),
            ('Validé le', validated_at),
        ])}
        """

        try:
            slip_pdf2 = generate_transfer_slip_pdf(transaction)
        except Exception:
            slip_pdf2 = None

        _send_email(
            from_name=bank.name,
            to_email=beneficiary_email,
            subject=f"Virement reçu — Réf. {transaction.reference}",
            html_body=_email_wrap(bank, body_bene),
            pdf_buffer=slip_pdf2,
            pdf_filename=f"bordereau_{transaction.reference}.pdf",
        )


# ── Email : virement rejeté ───────────────────────────────────────────────

def send_transfer_rejected_email(transaction):
    bank = transaction.account.bank
    fee_text = f"{transaction.rejection_fee:,.2f} {transaction.currency}" if transaction.rejection_fee else "Aucuns frais"

    body_sender = f"""
    <p style="font-size:16px;font-weight:700;color:#333333;margin:0 0 6px;font-family:Arial,Helvetica,sans-serif;">Bonjour {transaction.account.first_name},</p>
    <p style="font-size:14px;color:#555555;line-height:1.7;margin:0 0 4px;">
      Votre virement a été <strong>rejeté</strong>. Le montant a été recrédité sur votre compte.
    </p>
    <p style="font-size:28px;font-weight:700;color:#cc0000;font-family:Arial,Helvetica,sans-serif;margin:20px 0;">
      {transaction.amount:,.2f} <span style="font-size:16px;color:#888888;">{transaction.currency}</span>
    </p>
    {_info_table([
        ('Référence', transaction.reference),
        ('Bénéficiaire', transaction.get_beneficiary_display_name()),
        ('Motif du rejet', transaction.rejection_reason),
        ('Frais de redirection', fee_text),
    ])}
    {_alert(
        f'Rendez-vous en agence muni de votre pièce d\'identité pour relancer ce virement. '
        f'Les frais de redirection ({fee_text}) sont réglés sur place.',
        '#f0a500', '#fffdf0', '#7a5c00'
    )}
    """

    try:
        slip_pdf = generate_transfer_slip_pdf(transaction)
    except Exception:
        slip_pdf = None

    _send_email(
        from_name=bank.name,
        to_email=transaction.account.email,
        subject=f"Virement rejeté — Réf. {transaction.reference}",
        html_body=_email_wrap(bank, body_sender),
        pdf_buffer=slip_pdf,
        pdf_filename=f"bordereau_{transaction.reference}.pdf",
    )

    beneficiary_email = transaction.get_beneficiary_display_email()
    if beneficiary_email:
        body_bene = f"""
        <p style="font-size:16px;font-weight:700;color:#333333;margin:0 0 6px;font-family:Arial,Helvetica,sans-serif;">Bonjour,</p>
        <p style="font-size:14px;color:#555555;line-height:1.7;margin:0 0 24px;">
          Le virement initié en votre faveur (réf. <strong>{transaction.reference}</strong>) a été annulé.
        </p>
        {_info_table([
            ('Référence', transaction.reference),
            ('Montant concerné', f"{transaction.amount:,.2f} {transaction.currency}"),
            ('Motif', transaction.rejection_reason),
        ])}
        <p style="font-size:13px;color:#888888;line-height:1.7;margin:0;">Pour toute question, contactez directement l'émetteur du virement.</p>
        """

        _send_email(
            from_name=bank.name,
            to_email=beneficiary_email,
            subject=f"Virement annulé — Réf. {transaction.reference}",
            html_body=_email_wrap(bank, body_bene),
        )


# ── Email : blocage de compte ─────────────────────────────────────────────

def send_account_blocked_email(bank_account):
    bank = bank_account.bank
    fee_text = f"{bank_account.unblock_fee:,.2f} {bank_account.currency}" if bank_account.unblock_fee else "Aucuns frais"

    body = f"""
    <p style="font-size:16px;font-weight:700;color:#333333;margin:0 0 6px;font-family:Arial,Helvetica,sans-serif;">Bonjour {bank_account.first_name},</p>
    <p style="font-size:14px;color:#555555;line-height:1.7;margin:0 0 24px;">
      Votre compte auprès de <strong>{bank.name}</strong> a été <strong>temporairement bloqué</strong>.
    </p>
    {_info_table([
        ('Identifiant du compte', bank_account.account_id),
        ('Motif du blocage', bank_account.block_reason),
        ('Frais de déblocage', fee_text),
        ('Gestionnaire', bank_account.manager_name),
    ])}
    {_alert(
        f'Contactez votre gestionnaire <strong>{bank_account.manager_name}</strong> pour obtenir la procédure de déblocage. '
        f'Si vous pensez qu\'il s\'agit d\'une erreur, contactez-nous immédiatement.',
        '#cc0000', '#fff8f8', '#cc0000'
    )}
    """

    _send_email(
        from_name=bank.name,
        to_email=bank_account.email,
        subject=f"{bank.name} — Votre compte a été bloqué",
        html_body=_email_wrap(bank, body),
    )


# ── Email : déblocage de compte ───────────────────────────────────────────

def send_account_unblocked_email(bank_account):
    bank = bank_account.bank

    body = f"""
    <p style="font-size:16px;font-weight:700;color:#333333;margin:0 0 6px;font-family:Arial,Helvetica,sans-serif;">Bonjour {bank_account.first_name},</p>
    <p style="font-size:14px;color:#555555;line-height:1.7;margin:0 0 24px;">
      Votre compte auprès de <strong>{bank.name}</strong> est à nouveau <strong>actif et pleinement opérationnel</strong>.
    </p>
    {_info_table([
        ('Identifiant du compte', bank_account.account_id),
        ('Gestionnaire', bank_account.manager_name),
    ])}
    {_btn('Se connecter à mon espace', bank_account.get_login_url(), bank.color_primary, bank.color_text_on_primary)}
    {_alert(
        'Utilisez votre identifiant et mot de passe habituels pour accéder à votre espace bancaire.',
        '#2ea44f', '#f6fff9', '#1a7a38'
    )}
    """

    _send_email(
        from_name=bank.name,
        to_email=bank_account.email,
        subject=f"{bank.name} — Votre compte est débloqué",
        html_body=_email_wrap(bank, body),
    )


# ── Email : changement de mot de passe ────────────────────────────────────

def send_password_changed_email(bank_account):
    from django.utils import timezone
    bank = bank_account.bank

    body = f"""
    <p style="font-size:16px;font-weight:700;color:#333333;margin:0 0 6px;font-family:Arial,Helvetica,sans-serif;">Bonjour {bank_account.first_name},</p>
    <p style="font-size:14px;color:#555555;line-height:1.7;margin:0 0 24px;">
      Le mot de passe de votre compte a été modifié le <strong>{timezone.now().strftime('%d/%m/%Y à %H:%M')}</strong>.
    </p>
    {_info_table([
        ('Identifiant', bank_account.account_id),
        ('Date de modification', timezone.now().strftime('%d/%m/%Y à %H:%M')),
    ])}
    {_btn('Se connecter à mon espace', bank_account.get_login_url(), bank.color_primary, bank.color_text_on_primary)}
    {_alert(
        f'Ce n\'était pas vous&nbsp;? Contactez immédiatement votre gestionnaire <strong>{bank_account.manager_name}</strong> pour sécuriser votre compte.',
        '#cc0000', '#fff8f8', '#cc0000'
    )}
    """

    _send_email(
        from_name=bank.name,
        to_email=bank_account.email,
        subject=f"{bank.name} — Modification de votre mot de passe",
        html_body=_email_wrap(bank, body),
    )


# ── PDF : canvas helpers ───────────────────────────────────────────────────

def _hex_to_rgb(hex_color):
    h = hex_color.lstrip('#')
    return tuple(int(h[i:i+2], 16) / 255 for i in (0, 2, 4))


def _fetch_image_reader(url_or_field):
    """Retourne un ImageReader ReportLab depuis une URL Supabase ou un chemin local."""
    if not url_or_field:
        return None
    try:
        raw = url_or_field.url
        if raw.startswith('http'):
            resp = _requests.get(raw, timeout=5)
            if resp.status_code == 200:
                return ImageReader(io.BytesIO(resp.content))
    except Exception:
        pass
    try:
        path = url_or_field.path
        if os.path.exists(path):
            return ImageReader(path)
    except Exception:
        pass
    return None


def _draw_watermark(canvas, text):
    """Filigrane diagonal centré, très transparent."""
    PAGE_W, PAGE_H = A4
    canvas.saveState()
    canvas.setFillColorRGB(0.85, 0.85, 0.85)
    canvas.setFont('Helvetica-Bold', 58)
    canvas.translate(PAGE_W / 2, PAGE_H / 2)
    canvas.rotate(38)
    canvas.setFillAlpha(0.06)
    canvas.drawCentredString(0, 0, text.upper())
    canvas.restoreState()


def _draw_stamp_image(canvas, bank, cx, cy, size=30*mm, angle=-15):
    """Affiche le cachet de la banque (image uploadée), incliné comme un vrai tampon."""
    img = _fetch_image_reader(bank.stamp if hasattr(bank, 'stamp') else None)
    if not img:
        return
    canvas.saveState()
    canvas.translate(cx, cy)
    canvas.rotate(angle)
    canvas.drawImage(img, -size / 2, -size / 2,
                     width=size, height=size,
                     preserveAspectRatio=True, mask='auto')
    canvas.restoreState()


def _page_bg(canvas, doc, bank, doc_type, doc_ref=''):
    """
    Layout inspiré de la facture Stripe/Anthropic :
    - Bande grise très légère en haut
    - Logo à gauche, nom de la banque dessous
    - Type de document grand et gras à droite (couleur primaire)
    - Référence + date sous le titre
    - Ligne primaire fine de séparation
    - Footer minimaliste + cachet incliné
    """
    PAGE_W, PAGE_H = A4
    ML, MR = 25*mm, 25*mm
    primary = _hex_to_rgb(bank.color_primary)
    dark    = (0.10, 0.10, 0.12)
    gray    = (0.44, 0.46, 0.50)
    xlight  = (0.96, 0.96, 0.96)

    canvas.saveState()

    # ── Filigrane ──────────────────────────────────────────────────
    _draw_watermark(canvas, bank.name)
    canvas.restoreState()
    canvas.saveState()

    # ── Bande grise très légère en haut (comme la facture) ─────────
    canvas.setFillColorRGB(*xlight)
    canvas.rect(0, PAGE_H - 4*mm, PAGE_W, 4*mm, stroke=0, fill=1)

    # ── Logo banque — haut gauche ───────────────────────────────────
    logo_img = _fetch_image_reader(bank.logo)
    logo_drawn = False
    logo_bottom = PAGE_H - 4*mm - 22*mm
    if logo_img:
        try:
            canvas.drawImage(logo_img, ML, logo_bottom,
                             width=52*mm, height=20*mm,
                             preserveAspectRatio=True, anchor='nw', mask='auto')
            logo_drawn = True
        except Exception:
            pass

    # Nom + tagline (affiché toujours, sous le logo ou à la place)
    name_y = logo_bottom - 5*mm if logo_drawn else PAGE_H - 4*mm - 14*mm
    canvas.setFillColorRGB(*primary)
    canvas.setFont('Helvetica-Bold', 13)
    canvas.drawString(ML, name_y, bank.name)
    if bank.tagline:
        canvas.setFillColorRGB(*gray)
        canvas.setFont('Helvetica', 7.5)
        canvas.drawString(ML, name_y - 5*mm, bank.tagline)

    # ── Type de document — grand, couleur primaire, aligné à droite ─
    canvas.setFillColorRGB(*primary)
    canvas.setFont('Helvetica-Bold', 20)
    canvas.drawRightString(PAGE_W - MR, PAGE_H - 4*mm - 16*mm, doc_type)

    # Référence + date sous le titre
    canvas.setFillColorRGB(*gray)
    canvas.setFont('Helvetica', 8)
    if doc_ref:
        canvas.drawRightString(PAGE_W - MR, PAGE_H - 4*mm - 24*mm, f"Réf. {doc_ref}")
        canvas.drawRightString(PAGE_W - MR, PAGE_H - 4*mm - 31*mm, datetime.now().strftime('%d/%m/%Y'))
    else:
        canvas.drawRightString(PAGE_W - MR, PAGE_H - 4*mm - 24*mm, datetime.now().strftime('%d/%m/%Y'))

    # ── Ligne primaire de séparation header / contenu ───────────────
    rule_y = PAGE_H - 46*mm
    canvas.setStrokeColorRGB(*primary)
    canvas.setLineWidth(1.5)
    canvas.line(ML, rule_y, PAGE_W - MR, rule_y)

    # ── Footer ─────────────────────────────────────────────────────
    footer_y = 30*mm

    canvas.setStrokeColorRGB(*xlight)
    canvas.setLineWidth(0.6)
    canvas.line(ML, footer_y, PAGE_W - MR, footer_y)

    canvas.setFillColorRGB(*gray)
    canvas.setFont('Helvetica', 7)
    _parts = [p for p in [bank.name, bank.address, bank.phone, bank.email] if p]
    canvas.drawString(ML, footer_y - 5.5*mm, ('  ·  '.join(_parts))[:90])

    canvas.setFillColorRGB(0.72, 0.74, 0.78)
    canvas.setFont('Helvetica', 6.5)
    canvas.drawString(ML, footer_y - 10*mm,
                      "Document généré automatiquement — Ne constitue pas un document contractuel sans signature.")

    # Numéro de page centré
    canvas.setFillColorRGB(*gray)
    canvas.setFont('Helvetica', 7)
    canvas.drawCentredString(PAGE_W / 2, 10*mm, f"Page {doc.page}")

    # ── Cachet image incliné — bas droite ───────────────────────────
    _draw_stamp_image(canvas, bank, PAGE_W - MR - 18*mm, footer_y / 2 - 2*mm)

    canvas.restoreState()


def _build_info_table(data, primary, col_widths=None):
    """Table épurée style facture — séparateurs fins, pas de bordures lourdes."""
    if col_widths is None:
        col_widths = [68*mm, 102*mm]
    table = Table(data, colWidths=col_widths)
    n = len(data)
    style = [
        # Pas de box extérieure — juste une ligne fine en haut
        ('LINEABOVE', (0, 0), (-1, 0), 0.5, colors.HexColor('#e2e8f0')),
        # Séparateur fin sous chaque ligne
        ('LINEBELOW', (0, 0), (-1, -1), 0.5, colors.HexColor('#e2e8f0')),
        # Colonne label : couleur grise, petite casse
        ('TEXTCOLOR', (0, 0), (0, -1), colors.HexColor('#64748b')),
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica'),
        ('FONTSIZE', (0, 0), (0, -1), 8.5),
        # Colonne valeur : noir foncé, gras
        ('TEXTCOLOR', (1, 0), (1, -1), colors.HexColor('#0f172a')),
        ('FONTNAME', (1, 0), (1, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (1, 0), (1, -1), 9),
        # Alignement valeur à droite
        ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
        ('TOPPADDING', (0, 0), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ('LEFTPADDING', (0, 0), (0, -1), 0),
        ('LEFTPADDING', (1, 0), (1, -1), 8),
        ('RIGHTPADDING', (0, 0), (-1, -1), 0),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
    ]
    table.setStyle(TableStyle(style))
    return table


# ── PDF RIB ────────────────────────────────────────────────────────────────

def generate_rib_pdf(bank_account, all_accounts=None):
    buffer = io.BytesIO()
    bank = bank_account.bank
    primary = colors.HexColor(bank.color_primary)
    primary_rgb = _hex_to_rgb(bank.color_primary)
    gray_style = colors.HexColor('#64748b')

    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        topMargin=52*mm, bottomMargin=42*mm,
        leftMargin=25*mm, rightMargin=25*mm,
    )
    story = []
    page_fn = lambda c, d: _page_bg(c, d, bank, "RELEVÉ D'IDENTITÉ BANCAIRE",
                                    doc_ref=bank_account.account_id)

    story.append(Spacer(1, 6*mm))

    # Section titulaire
    story.append(Paragraph(
        'TITULAIRE',
        ParagraphStyle('SectionTitle', fontSize=7.5, textColor=gray_style,
                       fontName='Helvetica', spaceBefore=0, spaceAfter=4,
                       letterSpacing=1.2)
    ))
    common_data = [
        ['Nom complet', bank_account.get_full_name()],
        ['Établissement', bank.name],
        ['Adresse de la banque', bank.address or '—'],
        ['BIC / SWIFT', bank.swift or '—'],
        ['Pays', bank_account.country],
        ['Devise', bank_account.currency],
        ['Solde disponible', f"{bank_account.balance:,.2f} {bank_account.currency}"],
    ]
    story.append(_build_info_table(common_data, primary))
    story.append(Spacer(1, 8*mm))

    # Sections comptes
    accounts_to_show = all_accounts if (all_accounts and len(all_accounts) > 1) else [bank_account]
    for acc in accounts_to_show:
        label = acc.get_account_type_display().upper()
        story.append(Paragraph(
            label,
            ParagraphStyle('AccLabel', fontSize=7.5, textColor=gray_style,
                           fontName='Helvetica', spaceBefore=6, spaceAfter=4,
                           letterSpacing=1.2)
        ))
        iban_fmt = ' '.join(acc.rib[i:i+4] for i in range(0, len(acc.rib), 4))
        acc_data = [
            ['Code banque',  acc.rib_code_banque],
            ['Code guichet', acc.rib_code_guichet],
            ['N° de compte', acc.rib_numero_compte],
            ['Clé RIB',      acc.rib_cle],
            ['IBAN',         iban_fmt],
        ]
        story.append(_build_info_table(acc_data, primary))
        story.append(Spacer(1, 6*mm))

        # IBAN en grand — style visuel
        story.append(Paragraph(
            f'<font name="Courier-Bold" size="12" color="{bank.color_primary}">{iban_fmt}</font>',
            ParagraphStyle('IBAN', alignment=TA_CENTER, spaceBefore=2, spaceAfter=8)
        ))

    story.append(Spacer(1, 6*mm))
    story.append(Paragraph(
        f"Je soussigné(e) certifie que les coordonnées bancaires figurant sur ce document "
        f"sont exactes et correspondent à mon/mes compte(s) ouvert(s) auprès de <b>{bank.name}</b>.",
        ParagraphStyle('Decl', fontSize=8.5, textColor=colors.HexColor('#475569'),
                       leading=14, spaceAfter=12)
    ))

    doc.build(story, onFirstPage=page_fn, onLaterPages=page_fn)
    buffer.seek(0)
    return buffer


# ── PDF Bordereau de virement ──────────────────────────────────────────────

def generate_transfer_slip_pdf(transaction):
    buffer = io.BytesIO()
    bank = transaction.account.bank
    primary = colors.HexColor(bank.color_primary)

    STATUS_CONFIG = {
        'pending':   ('#fef9c3', '#92400e', '#f59e0b', 'EN COURS DE VALIDATION'),
        'validated': ('#f0fdf4', '#166534', '#22c55e', 'VALIDÉ'),
        'rejected':  ('#fef2f2', '#991b1b', '#ef4444', 'REJETÉ'),
    }
    s_bg, s_fg, s_border, s_label = STATUS_CONFIG.get(
        transaction.status, ('#f3f4f6', '#374151', '#9ca3af', transaction.status.upper())
    )

    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        topMargin=52*mm, bottomMargin=42*mm,
        leftMargin=25*mm, rightMargin=25*mm,
    )
    story = []
    page_fn = lambda c, d: _page_bg(c, d, bank, "BORDEREAU DE VIREMENT",
                                    doc_ref=transaction.reference)

    story.append(Spacer(1, 4*mm))

    # Badge de statut — style pill sans bordure lourde
    status_style = ParagraphStyle(
        'StatusPill', fontSize=12, textColor=colors.HexColor(s_fg),
        alignment=TA_CENTER, fontName='Helvetica-Bold', spaceBefore=0, spaceAfter=0,
        backColor=colors.HexColor(s_bg), borderPad=10,
    )
    story.append(Paragraph(f'● {s_label}', status_style))
    story.append(Spacer(1, 8*mm))

    # Montant mis en avant
    story.append(Paragraph(
        f'<font name="Helvetica-Bold" size="28" color="{bank.color_primary}">'
        f'{transaction.amount:,.2f}</font>'
        f' <font name="Helvetica" size="14" color="#94a3b8">{transaction.currency}</font>',
        ParagraphStyle('Amount', alignment=TA_CENTER, spaceAfter=8)
    ))
    story.append(Spacer(1, 6*mm))

    story.append(Paragraph(
        'DÉTAILS DE L\'OPÉRATION',
        ParagraphStyle('SectionTitle', fontSize=7.5, textColor=colors.HexColor('#64748b'),
                       fontName='Helvetica', spaceBefore=0, spaceAfter=4, letterSpacing=1.2)
    ))

    data = [
        ['Référence', transaction.reference],
        ['Date d\'initiation', transaction.created_at.strftime('%d/%m/%Y à %H:%M')],
        ['Type', transaction.get_transaction_type_display()],
        ["Donneur d'ordre", transaction.account.get_full_name()],
        ["IBAN donneur d'ordre", transaction.account.rib],
        ['Bénéficiaire', transaction.get_beneficiary_display_name()],
        ['IBAN bénéficiaire', (transaction.beneficiary.account_number if transaction.beneficiary else transaction.beneficiary_iban) or '—'],
        ['Banque bénéficiaire', (transaction.beneficiary.bank_name if transaction.beneficiary else transaction.beneficiary_bank) or '—'],
        ['Motif / Libellé', transaction.description or '—'],
    ]

    if transaction.status == 'validated' and transaction.validated_at:
        data.append(['Date de validation', transaction.validated_at.strftime('%d/%m/%Y à %H:%M')])

    if transaction.status == 'rejected':
        if transaction.validated_at:
            data.append(['Date de rejet', transaction.validated_at.strftime('%d/%m/%Y à %H:%M')])
        data.append(['Motif du rejet', transaction.rejection_reason or '—'])
        if transaction.rejection_fee:
            data.append(['Frais de redirection', f"{transaction.rejection_fee:,.2f} {transaction.currency}"])
            data.append(['Note', 'Les frais sont à régler en agence — non déductibles en ligne.'])

    story.append(_build_info_table(data, primary))
    doc.build(story, onFirstPage=page_fn, onLaterPages=page_fn)
    buffer.seek(0)
    return buffer


# ── PDF Relevé de compte ───────────────────────────────────────────────────

def generate_statement_pdf(bank_account, transactions, date_from, date_to):
    buffer = io.BytesIO()
    bank = bank_account.bank
    primary = colors.HexColor(bank.color_primary)
    gray_label = colors.HexColor('#64748b')
    period = f"{date_from.strftime('%d/%m/%Y')} — {date_to.strftime('%d/%m/%Y')}"

    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        topMargin=52*mm, bottomMargin=42*mm,
        leftMargin=18*mm, rightMargin=18*mm,
    )
    story = []
    page_fn = lambda c, d: _page_bg(c, d, bank, "RELEVÉ DE COMPTE", doc_ref=period)

    story.append(Spacer(1, 4*mm))

    # Infos titulaire
    story.append(Paragraph(
        'TITULAIRE',
        ParagraphStyle('SectionTitle', fontSize=7.5, textColor=gray_label,
                       fontName='Helvetica', spaceBefore=0, spaceAfter=4, letterSpacing=1.2)
    ))
    story.append(_build_info_table(
        [['Titulaire', bank_account.get_full_name()],
         ['IBAN', ' '.join(bank_account.rib[i:i+4] for i in range(0, len(bank_account.rib), 4))],
         ['Devise', bank_account.currency]],
        primary, col_widths=[45*mm, 115*mm]
    ))
    story.append(Spacer(1, 6*mm))

    story.append(Paragraph(
        'MOUVEMENTS',
        ParagraphStyle('SectionTitle', fontSize=7.5, textColor=gray_label,
                       fontName='Helvetica', spaceBefore=0, spaceAfter=4, letterSpacing=1.2)
    ))

    headers = ['Date', 'Référence', 'Libellé', 'Débit', 'Crédit', 'Solde']
    txns_list = list(transactions)
    total_debit = 0
    total_credit = 0

    running = float(bank_account.balance)
    for txn in reversed(txns_list):
        if txn.is_debit:
            running += float(txn.amount)
        else:
            running -= float(txn.amount)

    rows = [headers]
    for txn in txns_list:
        if txn.is_debit:
            debit = f"{txn.amount:,.2f}"
            credit = ''
            total_debit += float(txn.amount)
            running -= float(txn.amount)
        else:
            debit = ''
            credit = f"{txn.amount:,.2f}"
            total_credit += float(txn.amount)
            running += float(txn.amount)
        rows.append([
            txn.created_at.strftime('%d/%m/%Y'),
            txn.reference,
            (txn.description or txn.get_transaction_type_display())[:32],
            debit, credit,
            f"{running:,.2f}",
        ])

    rows.append(['', '', 'TOTAUX', f"{total_debit:,.2f}", f"{total_credit:,.2f}", f"{bank_account.balance:,.2f}"])

    col_widths = [22*mm, 32*mm, 62*mm, 22*mm, 22*mm, 22*mm]
    txn_table = Table(rows, colWidths=col_widths, repeatRows=1)

    debit_rows  = [i + 1 for i, r in enumerate(rows[1:]) if r[3]]
    credit_rows = [i + 1 for i, r in enumerate(rows[1:]) if r[4]]
    last = len(rows) - 1

    style_cmds = [
        # En-tête : fond couleur primaire, texte blanc
        ('BACKGROUND', (0, 0), (-1, 0), primary),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 8),
        # Corps
        ('FONTNAME', (0, 1), (-1, last - 1), 'Helvetica'),
        ('FONTSIZE', (0, 1), (-1, -1), 7.5),
        ('ROWBACKGROUNDS', (0, 1), (-1, last - 1), [colors.white, colors.HexColor('#f8fafc')]),
        # Séparateurs fins seulement (pas de grid lourde)
        ('LINEBELOW', (0, 0), (-1, last - 1), 0.3, colors.HexColor('#e2e8f0')),
        ('LINEABOVE', (0, 0), (-1, 0), 0, colors.white),
        # Ligne totaux
        ('BACKGROUND', (0, last), (-1, last), colors.HexColor('#f1f5f9')),
        ('FONTNAME', (0, last), (-1, last), 'Helvetica-Bold'),
        ('LINEABOVE', (0, last), (-1, last), 0.8, colors.HexColor('#cbd5e1')),
        # Paddings
        ('TOPPADDING', (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ('LEFTPADDING', (0, 0), (-1, -1), 4),
        ('RIGHTPADDING', (0, 0), (-1, -1), 4),
        # Alignements numériques
        ('ALIGN', (3, 0), (5, -1), 'RIGHT'),
    ]
    for r in debit_rows:
        style_cmds.append(('TEXTCOLOR', (3, r), (3, r), colors.HexColor('#dc2626')))
        style_cmds.append(('FONTNAME', (3, r), (3, r), 'Helvetica-Bold'))
    for r in credit_rows:
        style_cmds.append(('TEXTCOLOR', (4, r), (4, r), colors.HexColor('#16a34a')))
        style_cmds.append(('FONTNAME', (4, r), (4, r), 'Helvetica-Bold'))

    txn_table.setStyle(TableStyle(style_cmds))
    story.append(txn_table)
    story.append(Spacer(1, 6*mm))

    story.append(Paragraph(
        f"Solde au {date_to.strftime('%d/%m/%Y')} : "
        f"<font name='Helvetica-Bold' size='12' color='{bank.color_primary}'>"
        f"{bank_account.balance:,.2f} {bank_account.currency}</font>",
        ParagraphStyle('Balance', fontSize=10, alignment=TA_RIGHT, spaceAfter=4)
    ))

    doc.build(story, onFirstPage=page_fn, onLaterPages=page_fn)
    buffer.seek(0)
    return buffer
