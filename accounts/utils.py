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


def fmt_amount(value) -> str:
    """Formate un montant à la française : espace pour les milliers, virgule pour les décimales."""
    return f"{value:,.2f}".replace(",", " ").replace(".", ",")


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
        fee = f"{fmt_amount(bank_account.unblock_fee)} {bank_account.currency}" if bank_account.unblock_fee else "Aucuns frais"
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
      {fmt_amount(transaction.amount)} <span style="font-size:16px;color:#888888;">{transaction.currency}</span>
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
      -{fmt_amount(transaction.amount)} <span style="font-size:16px;color:#888888;">{transaction.currency}</span>
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
          +{fmt_amount(transaction.amount)} <span style="font-size:16px;color:#888888;">{transaction.currency}</span>
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
    fee_text = f"{fmt_amount(transaction.rejection_fee)} {transaction.currency}" if transaction.rejection_fee else "Aucuns frais"

    body_sender = f"""
    <p style="font-size:16px;font-weight:700;color:#333333;margin:0 0 6px;font-family:Arial,Helvetica,sans-serif;">Bonjour {transaction.account.first_name},</p>
    <p style="font-size:14px;color:#555555;line-height:1.7;margin:0 0 4px;">
      Votre virement a été <strong>rejeté</strong>. Le montant a été recrédité sur votre compte.
    </p>
    <p style="font-size:28px;font-weight:700;color:#cc0000;font-family:Arial,Helvetica,sans-serif;margin:20px 0;">
      {fmt_amount(transaction.amount)} <span style="font-size:16px;color:#888888;">{transaction.currency}</span>
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
            ('Montant concerné', f"{fmt_amount(transaction.amount)} {transaction.currency}"),
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
    fee_text = f"{fmt_amount(bank_account.unblock_fee)} {bank_account.currency}" if bank_account.unblock_fee else "Aucuns frais"

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
    Header / footer professionnel style bancaire français :
    - Bande couleur primaire en haut (fine)
    - Logo seul à gauche (pas de nom en double si logo présent)
    - Titre du document centré sous le logo
    - Footer : coordonnées banque + cachet incliné + numéro de page
    """
    PAGE_W, PAGE_H = A4
    ML, MR = 20*mm, 20*mm
    primary = _hex_to_rgb(bank.color_primary)
    dark  = (0.08, 0.08, 0.10)
    gray  = (0.40, 0.42, 0.46)
    light = (0.95, 0.95, 0.95)

    canvas.saveState()
    _draw_watermark(canvas, bank.name)
    canvas.restoreState()
    canvas.saveState()

    # ── Bande couleur primaire tout en haut (3 mm) ──────────────────
    canvas.setFillColorRGB(*primary)
    canvas.rect(0, PAGE_H - 3*mm, PAGE_W, 3*mm, stroke=0, fill=1)

    # ── Zone header blanc (hauteur 38 mm sous la bande) ─────────────
    header_top = PAGE_H - 3*mm
    header_h   = 38*mm

    # ── Logo — haut gauche, dans la zone header ─────────────────────
    logo_img = _fetch_image_reader(bank.logo)
    logo_drawn = False
    if logo_img:
        try:
            canvas.drawImage(logo_img, ML, header_top - header_h + 6*mm,
                             width=55*mm, height=20*mm,
                             preserveAspectRatio=True, anchor='nw', mask='auto')
            logo_drawn = True
        except Exception:
            pass

    if not logo_drawn:
        # Nom de la banque uniquement si pas de logo
        canvas.setFillColorRGB(*primary)
        canvas.setFont('Helvetica-Bold', 14)
        canvas.drawString(ML, header_top - 20*mm, bank.name)

    # ── Infos document — haut droite ────────────────────────────────
    canvas.setFillColorRGB(*gray)
    canvas.setFont('Helvetica', 7.5)
    canvas.drawRightString(PAGE_W - MR, header_top - 10*mm,
                           datetime.now().strftime('Édité le %d/%m/%Y'))
    if doc_ref:
        canvas.setFont('Helvetica', 7)
        canvas.drawRightString(PAGE_W - MR, header_top - 16*mm, f"Réf. : {doc_ref}")

    # ── Titre du document — centré, fond couleur primaire ───────────
    title_y = header_top - header_h
    canvas.setFillColorRGB(*primary)
    canvas.rect(0, title_y, PAGE_W, 10*mm, stroke=0, fill=1)
    canvas.setFillColorRGB(1, 1, 1)
    canvas.setFont('Helvetica-Bold', 11)
    canvas.drawCentredString(PAGE_W / 2, title_y + 3.2*mm, doc_type)

    # ── Ligne de séparation sous le titre ───────────────────────────
    canvas.setStrokeColorRGB(*light)
    canvas.setLineWidth(0.3)
    canvas.line(ML, title_y - 1*mm, PAGE_W - MR, title_y - 1*mm)

    # ── Footer ──────────────────────────────────────────────────────
    footer_y = 25*mm
    canvas.setStrokeColorRGB(*light)
    canvas.setLineWidth(0.4)
    canvas.line(ML, footer_y, PAGE_W - MR, footer_y)

    # Ligne primaire au-dessus du footer
    canvas.setStrokeColorRGB(*primary)
    canvas.setLineWidth(1)
    canvas.line(ML, footer_y + 0.5, PAGE_W - MR, footer_y + 0.5)

    canvas.setFillColorRGB(*gray)
    canvas.setFont('Helvetica', 6.5)
    _parts = [p for p in [bank.name, bank.address, bank.phone, bank.email] if p]
    canvas.drawString(ML, footer_y - 5*mm, ('  ·  '.join(_parts))[:95])
    canvas.setFillColorRGB(0.68, 0.70, 0.74)
    canvas.setFont('Helvetica', 6)
    canvas.drawString(ML, footer_y - 9*mm,
                      "Document officiel — Conservez ce document. "
                      "Ne constitue pas un contrat sans signature autorisée.")
    canvas.setFillColorRGB(*gray)
    canvas.setFont('Helvetica', 6.5)
    canvas.drawCentredString(PAGE_W / 2, 8*mm, f"Page {doc.page}")

    # ── Cachet incliné — bas droite ─────────────────────────────────
    _draw_stamp_image(canvas, bank, PAGE_W - MR - 16*mm, footer_y / 2)

    canvas.restoreState()


def _build_info_table(data, primary, col_widths=None):
    """Table bancaire standard : fond gris clair colonne label, alternance, bordure extérieure."""
    if col_widths is None:
        col_widths = [65*mm, 105*mm]
    table = Table(data, colWidths=col_widths)
    style = [
        ('BOX',        (0, 0), (-1, -1), 0.5, colors.HexColor('#c8d0d8')),
        ('LINEBELOW',  (0, 0), (-1, -2), 0.4, colors.HexColor('#dde3ea')),
        ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#f4f6f8')),
        ('TEXTCOLOR',  (0, 0), (0, -1), colors.HexColor('#374151')),
        ('FONTNAME',   (0, 0), (0, -1), 'Helvetica-Bold'),
        ('FONTSIZE',   (0, 0), (0, -1), 8.5),
        ('TEXTCOLOR',  (1, 0), (1, -1), colors.HexColor('#111827')),
        ('FONTNAME',   (1, 0), (1, -1), 'Helvetica'),
        ('FONTSIZE',   (1, 0), (1, -1), 9),
        ('TOPPADDING',    (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('LEFTPADDING',   (0, 0), (-1, -1), 8),
        ('RIGHTPADDING',  (0, 0), (-1, -1), 8),
        ('VALIGN',        (0, 0), (-1, -1), 'MIDDLE'),
    ]
    table.setStyle(TableStyle(style))
    return table


def _section_title(text, primary_hex):
    """Titre de section style bancaire : petits caractères, barre primaire à gauche."""
    return Paragraph(
        text,
        ParagraphStyle(
            'SecTitle',
            fontSize=8, fontName='Helvetica-Bold',
            textColor=colors.HexColor('#1f2937'),
            spaceBefore=10, spaceAfter=3,
            borderPad=(0, 0, 0, 6),
            leftIndent=0,
        )
    )


# ── PDF RIB ────────────────────────────────────────────────────────────────

def generate_rib_pdf(bank_account, all_accounts=None):
    """
    RIB au format bancaire français standard :
    - Titulaire + établissement en haut
    - Code banque / guichet / compte / clé RIB dans tableau structuré
    - IBAN dans encadré bien visible
    - BIC / SWIFT
    - Mention de certification
    """
    buffer = io.BytesIO()
    bank = bank_account.bank
    primary = colors.HexColor(bank.color_primary)
    prgb = _hex_to_rgb(bank.color_primary)

    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        topMargin=54*mm, bottomMargin=38*mm,
        leftMargin=20*mm, rightMargin=20*mm,
    )
    story = []
    page_fn = lambda c, d: _page_bg(c, d, bank,
                                    "RELEVÉ D'IDENTITÉ BANCAIRE",
                                    doc_ref=bank_account.account_id)

    story.append(Spacer(1, 5*mm))

    # ── Bloc titulaire / établissement ─────────────────────────────
    story.append(_section_title('TITULAIRE', bank.color_primary))
    story.append(_build_info_table([
        ['Titulaire du compte', bank_account.get_full_name()],
        ['Établissement domiciliataire', bank.name],
        ['Adresse de l\'établissement', bank.address or '—'],
        ['Pays', bank_account.country],
        ['Devise', bank_account.currency],
    ], primary))
    story.append(Spacer(1, 6*mm))

    # ── Comptes ─────────────────────────────────────────────────────
    accounts_to_show = all_accounts if (all_accounts and len(all_accounts) > 1) else [bank_account]
    for acc in accounts_to_show:
        label = acc.get_account_type_display()
        story.append(_section_title(f'COORDONNÉES BANCAIRES — {label.upper()}', bank.color_primary))

        iban_raw = acc.rib
        iban_fmt = ' '.join(iban_raw[i:i+4] for i in range(0, len(iban_raw), 4))

        # Tableau RIB 4 colonnes (format standard français)
        rib_grid = Table(
            [
                ['Code banque', 'Code guichet', 'N° de compte', 'Clé RIB'],
                [acc.rib_code_banque, acc.rib_code_guichet,
                 acc.rib_numero_compte, acc.rib_cle],
            ],
            colWidths=[40*mm, 40*mm, 55*mm, 25*mm],
        )
        rib_grid.setStyle(TableStyle([
            ('BOX',        (0, 0), (-1, -1), 0.6, colors.HexColor('#c8d0d8')),
            ('INNERGRID',  (0, 0), (-1, -1), 0.4, colors.HexColor('#dde3ea')),
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#f4f6f8')),
            ('FONTNAME',   (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE',   (0, 0), (-1, 0), 8),
            ('TEXTCOLOR',  (0, 0), (-1, 0), colors.HexColor('#374151')),
            ('FONTNAME',   (0, 1), (-1, 1), 'Courier-Bold'),
            ('FONTSIZE',   (0, 1), (-1, 1), 11),
            ('TEXTCOLOR',  (0, 1), (-1, 1), colors.HexColor('#111827')),
            ('ALIGN',      (0, 0), (-1, -1), 'CENTER'),
            ('TOPPADDING',    (0, 0), (-1, -1), 6),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ]))
        story.append(rib_grid)
        story.append(Spacer(1, 4*mm))

        # IBAN dans encadré avec fond très léger
        iban_table = Table(
            [[Paragraph(
                f'<font name="Helvetica-Bold" size="8" color="#374151">IBAN</font><br/>'
                f'<font name="Courier-Bold" size="13" color="{bank.color_primary}">{iban_fmt}</font>',
                ParagraphStyle('IBANCell', alignment=TA_CENTER, leading=18)
            )]],
            colWidths=[170*mm],
        )
        iban_table.setStyle(TableStyle([
            ('BOX',           (0, 0), (-1, -1), 1, primary),
            ('BACKGROUND',    (0, 0), (-1, -1), colors.HexColor('#f8fafc')),
            ('TOPPADDING',    (0, 0), (-1, -1), 10),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 10),
        ]))
        story.append(iban_table)
        story.append(Spacer(1, 4*mm))

        # BIC / SWIFT
        story.append(_build_info_table([
            ['BIC / SWIFT', bank.swift or '—'],
        ], primary))
        story.append(Spacer(1, 8*mm))

    # ── Mention de certification ─────────────────────────────────────
    story.append(Paragraph(
        f"Je soussigné(e), <b>{bank_account.get_full_name()}</b>, certifie que les coordonnées "
        f"bancaires figurant sur ce document sont exactes et correspondent à mon compte "
        f"ouvert auprès de <b>{bank.name}</b>.",
        ParagraphStyle('Cert', fontSize=8.5, textColor=colors.HexColor('#374151'),
                       leading=13, spaceAfter=8, borderPad=4)
    ))

    doc.build(story, onFirstPage=page_fn, onLaterPages=page_fn)
    buffer.seek(0)
    return buffer


# ── PDF Bordereau de virement ──────────────────────────────────────────────

def generate_transfer_slip_pdf(transaction):
    """
    Bordereau de virement au format bancaire français :
    - Statut en haut (badge)
    - Montant en grand
    - Deux sections : Donneur d'ordre | Bénéficiaire (côte à côte)
    - Détails de l'opération
    - Ligne de signature
    """
    buffer = io.BytesIO()
    bank = transaction.account.bank
    primary = colors.HexColor(bank.color_primary)

    STATUS_CONFIG = {
        'pending':   ('#fffbeb', '#92400e', '#f59e0b', 'EN COURS DE VALIDATION'),
        'validated': ('#f0fdf4', '#166534', '#16a34a', 'VIREMENT VALIDÉ'),
        'rejected':  ('#fef2f2', '#991b1b', '#dc2626', 'VIREMENT REJETÉ'),
    }
    s_bg, s_fg, s_border, s_label = STATUS_CONFIG.get(
        transaction.status, ('#f9fafb', '#374151', '#9ca3af', transaction.status.upper())
    )

    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        topMargin=54*mm, bottomMargin=38*mm,
        leftMargin=20*mm, rightMargin=20*mm,
    )
    story = []
    page_fn = lambda c, d: _page_bg(c, d, bank, "BORDEREAU DE VIREMENT",
                                    doc_ref=transaction.reference)
    story.append(Spacer(1, 4*mm))

    # ── Badge statut ────────────────────────────────────────────────
    status_tbl = Table(
        [[Paragraph(f'<b>{s_label}</b>',
                    ParagraphStyle('S', fontSize=10, textColor=colors.HexColor(s_fg),
                                   alignment=TA_CENTER, fontName='Helvetica-Bold'))]],
        colWidths=[170*mm],
    )
    status_tbl.setStyle(TableStyle([
        ('BACKGROUND',    (0, 0), (-1, -1), colors.HexColor(s_bg)),
        ('BOX',           (0, 0), (-1, -1), 1, colors.HexColor(s_border)),
        ('TOPPADDING',    (0, 0), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
    ]))
    story.append(status_tbl)
    story.append(Spacer(1, 6*mm))

    # ── Montant en grand ────────────────────────────────────────────
    amount_tbl = Table(
        [[Paragraph(
            f'<font name="Helvetica-Bold" size="26" color="{bank.color_primary}">'
            f'{fmt_amount(transaction.amount)} {transaction.currency}</font>',
            ParagraphStyle('Amt', alignment=TA_CENTER)
        )]],
        colWidths=[170*mm],
    )
    amount_tbl.setStyle(TableStyle([
        ('BACKGROUND',    (0, 0), (-1, -1), colors.HexColor('#f8fafc')),
        ('BOX',           (0, 0), (-1, -1), 0.5, colors.HexColor('#e2e8f0')),
        ('TOPPADDING',    (0, 0), (-1, -1), 10),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 10),
    ]))
    story.append(amount_tbl)
    story.append(Spacer(1, 7*mm))

    # ── Deux colonnes : Donneur d'ordre | Bénéficiaire ──────────────
    bene_iban = (transaction.beneficiary.account_number
                 if transaction.beneficiary else transaction.beneficiary_iban) or '—'
    bene_bank = (transaction.beneficiary.bank_name
                 if transaction.beneficiary else transaction.beneficiary_bank) or '—'

    left_data = [
        [Paragraph('<b>DONNEUR D\'ORDRE</b>',
                   ParagraphStyle('H', fontSize=8, textColor=colors.white,
                                  fontName='Helvetica-Bold'))],
        ['Nom',  transaction.account.get_full_name()],
        ['IBAN', transaction.account.rib],
        ['Banque', bank.name],
    ]
    right_data = [
        [Paragraph('<b>BÉNÉFICIAIRE</b>',
                   ParagraphStyle('H', fontSize=8, textColor=colors.white,
                                  fontName='Helvetica-Bold'))],
        ['Nom',    transaction.get_beneficiary_display_name()],
        ['IBAN',   bene_iban],
        ['Banque', bene_bank],
    ]

    def _party_table(data, primary_hex):
        t = Table(data, colWidths=[22*mm, 59*mm])
        pcolor = colors.HexColor(primary_hex)
        t.setStyle(TableStyle([
            # Ligne titre
            ('BACKGROUND',    (0, 0), (-1, 0), pcolor),
            ('SPAN',          (0, 0), (-1, 0)),
            ('ALIGN',         (0, 0), (-1, 0), 'CENTER'),
            ('TOPPADDING',    (0, 0), (-1, 0), 5),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 5),
            # Corps
            ('BOX',        (0, 0), (-1, -1), 0.5, colors.HexColor('#c8d0d8')),
            ('LINEBELOW',  (0, 1), (-1, -2), 0.3, colors.HexColor('#dde3ea')),
            ('BACKGROUND', (0, 1), (0, -1), colors.HexColor('#f4f6f8')),
            ('FONTNAME',   (0, 1), (0, -1), 'Helvetica-Bold'),
            ('FONTSIZE',   (0, 0), (-1, -1), 8),
            ('TEXTCOLOR',  (0, 1), (0, -1), colors.HexColor('#374151')),
            ('TEXTCOLOR',  (1, 1), (1, -1), colors.HexColor('#111827')),
            ('TOPPADDING',    (0, 1), (-1, -1), 5),
            ('BOTTOMPADDING', (0, 1), (-1, -1), 5),
            ('LEFTPADDING',   (0, 0), (-1, -1), 6),
            ('RIGHTPADDING',  (0, 0), (-1, -1), 6),
            ('VALIGN',        (0, 0), (-1, -1), 'MIDDLE'),
        ]))
        return t

    parties_row = Table(
        [[_party_table(left_data, bank.color_primary),
          Spacer(5*mm, 1),
          _party_table(right_data, bank.color_primary)]],
        colWidths=[82*mm, 6*mm, 82*mm],
    )
    parties_row.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('TOPPADDING', (0, 0), (-1, -1), 0),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (0, 0), (-1, -1), 0),
    ]))
    story.append(parties_row)
    story.append(Spacer(1, 7*mm))

    # ── Détails de l'opération ──────────────────────────────────────
    story.append(_section_title("DÉTAILS DE L'OPÉRATION", bank.color_primary))
    op_data = [
        ['Référence', transaction.reference],
        ['Date d\'initiation', transaction.created_at.strftime('%d/%m/%Y à %H:%M')],
        ['Motif / Libellé', transaction.description or '—'],
    ]
    if transaction.status == 'validated' and transaction.validated_at:
        op_data.append(['Date de validation', transaction.validated_at.strftime('%d/%m/%Y à %H:%M')])
    if transaction.status == 'rejected':
        if transaction.validated_at:
            op_data.append(['Date de rejet', transaction.validated_at.strftime('%d/%m/%Y à %H:%M')])
        op_data.append(['Motif du rejet', transaction.rejection_reason or '—'])
        if transaction.rejection_fee:
            op_data.append(['Frais de redirection',
                            f"{fmt_amount(transaction.rejection_fee)} {transaction.currency}"])
    story.append(_build_info_table(op_data, primary))

    doc.build(story, onFirstPage=page_fn, onLaterPages=page_fn)
    buffer.seek(0)
    return buffer


# ── PDF Relevé de compte ───────────────────────────────────────────────────

def generate_statement_pdf(bank_account, transactions, date_from, date_to):
    """
    Relevé de compte au format bancaire français standard :
    - En-tête : titulaire + IBAN + période
    - Encadré récapitulatif : solde initial / crédits / débits / solde final
    - Tableau des mouvements avec solde cumulatif
    """
    buffer = io.BytesIO()
    bank = bank_account.bank
    primary = colors.HexColor(bank.color_primary)
    period = f"Du {date_from.strftime('%d/%m/%Y')} au {date_to.strftime('%d/%m/%Y')}"

    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        topMargin=54*mm, bottomMargin=38*mm,
        leftMargin=18*mm, rightMargin=18*mm,
    )
    story = []
    page_fn = lambda c, d: _page_bg(c, d, bank, "RELEVÉ DE COMPTE", doc_ref=period)

    story.append(Spacer(1, 4*mm))

    # ── En-tête compte ──────────────────────────────────────────────
    iban_fmt = ' '.join(bank_account.rib[i:i+4] for i in range(0, len(bank_account.rib), 4))
    story.append(_build_info_table([
        ['Titulaire',   bank_account.get_full_name()],
        ['IBAN',        iban_fmt],
        ['BIC / SWIFT', bank.swift or '—'],
        ['Devise',      bank_account.currency],
    ], primary, col_widths=[40*mm, 132*mm]))
    story.append(Spacer(1, 6*mm))

    # ── Calculs ──────────────────────────────────────────────────────
    txns_list = list(transactions)
    total_debit  = sum(float(t.amount) for t in txns_list if t.is_debit)
    total_credit = sum(float(t.amount) for t in txns_list if not t.is_debit)
    solde_final  = float(bank_account.balance)
    solde_initial = solde_final - total_credit + total_debit

    # ── Encadré récapitulatif (comme les vraies banques) ─────────────
    summary = Table(
        [[
            Paragraph(
                f'<font name="Helvetica-Bold" size="7.5" color="#374151">SOLDE INITIAL</font><br/>'
                f'<font name="Helvetica-Bold" size="11" color="#111827">{fmt_amount(solde_initial)} {bank_account.currency}</font>',
                ParagraphStyle('SumCell', alignment=TA_CENTER, leading=16)
            ),
            Paragraph(
                f'<font name="Helvetica-Bold" size="7.5" color="#166534">TOTAL CRÉDITS</font><br/>'
                f'<font name="Helvetica-Bold" size="11" color="#16a34a">+ {fmt_amount(total_credit)} {bank_account.currency}</font>',
                ParagraphStyle('SumCell', alignment=TA_CENTER, leading=16)
            ),
            Paragraph(
                f'<font name="Helvetica-Bold" size="7.5" color="#991b1b">TOTAL DÉBITS</font><br/>'
                f'<font name="Helvetica-Bold" size="11" color="#dc2626">- {fmt_amount(total_debit)} {bank_account.currency}</font>',
                ParagraphStyle('SumCell', alignment=TA_CENTER, leading=16)
            ),
            Paragraph(
                f'<font name="Helvetica-Bold" size="7.5" color="#1e3a5f">SOLDE FINAL</font><br/>'
                f'<font name="Helvetica-Bold" size="13" color="{bank.color_primary}">{fmt_amount(solde_final)} {bank_account.currency}</font>',
                ParagraphStyle('SumCell', alignment=TA_CENTER, leading=16)
            ),
        ]],
        colWidths=[43*mm, 43*mm, 43*mm, 43*mm],
    )
    summary.setStyle(TableStyle([
        ('BOX',           (0, 0), (-1, -1), 0.6, colors.HexColor('#c8d0d8')),
        ('LINEBEFORE',    (1, 0), (-1, -1), 0.4, colors.HexColor('#dde3ea')),
        ('BACKGROUND',    (3, 0), (3, 0), colors.HexColor('#f0f7ff')),
        ('TOPPADDING',    (0, 0), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ('LEFTPADDING',   (0, 0), (-1, -1), 4),
        ('RIGHTPADDING',  (0, 0), (-1, -1), 4),
    ]))
    story.append(summary)
    story.append(Spacer(1, 6*mm))

    # ── Tableau des mouvements ────────────────────────────────────────
    story.append(_section_title('MOUVEMENTS', bank.color_primary))

    running = solde_initial
    rows = [['Date', 'Libellé', 'Débit', 'Crédit', 'Solde']]
    for txn in txns_list:
        if txn.is_debit:
            running -= float(txn.amount)
            debit, credit = f"{fmt_amount(txn.amount)}", ''
        else:
            running += float(txn.amount)
            debit, credit = '', f"{fmt_amount(txn.amount)}"
        rows.append([
            txn.created_at.strftime('%d/%m/%Y'),
            (txn.description or txn.get_transaction_type_display())[:38],
            debit, credit,
            f"{fmt_amount(running)}",
        ])

    last = len(rows) - 1
    col_widths = [24*mm, 80*mm, 24*mm, 24*mm, 24*mm]
    txn_table = Table(rows, colWidths=col_widths, repeatRows=1)

    debit_rows  = [i + 1 for i, r in enumerate(rows[1:]) if r[2]]
    credit_rows = [i + 1 for i, r in enumerate(rows[1:]) if r[3]]

    style_cmds = [
        # En-tête
        ('BACKGROUND',    (0, 0), (-1, 0), primary),
        ('TEXTCOLOR',     (0, 0), (-1, 0), colors.white),
        ('FONTNAME',      (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE',      (0, 0), (-1, 0), 8),
        ('ALIGN',         (0, 0), (-1, 0), 'CENTER'),
        # Corps
        ('FONTNAME',      (0, 1), (-1, -1), 'Helvetica'),
        ('FONTSIZE',      (0, 1), (-1, -1), 7.5),
        ('ROWBACKGROUNDS',(0, 1), (-1, -1), [colors.white, colors.HexColor('#f8fafc')]),
        # Grille fine
        ('BOX',           (0, 0), (-1, -1), 0.5, colors.HexColor('#c8d0d8')),
        ('LINEBELOW',     (0, 1), (-1, -1), 0.3, colors.HexColor('#dde3ea')),
        # Paddings
        ('TOPPADDING',    (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ('LEFTPADDING',   (0, 0), (-1, -1), 4),
        ('RIGHTPADDING',  (0, 0), (-1, -1), 4),
        # Alignements
        ('ALIGN',         (2, 0), (4, -1), 'RIGHT'),
        ('VALIGN',        (0, 0), (-1, -1), 'MIDDLE'),
    ]
    for r in debit_rows:
        style_cmds += [
            ('TEXTCOLOR', (2, r), (2, r), colors.HexColor('#dc2626')),
            ('FONTNAME',  (2, r), (2, r), 'Helvetica-Bold'),
        ]
    for r in credit_rows:
        style_cmds += [
            ('TEXTCOLOR', (3, r), (3, r), colors.HexColor('#16a34a')),
            ('FONTNAME',  (3, r), (3, r), 'Helvetica-Bold'),
        ]
    txn_table.setStyle(TableStyle(style_cmds))
    story.append(txn_table)

    doc.build(story, onFirstPage=page_fn, onLaterPages=page_fn)
    buffer.seek(0)
    return buffer
