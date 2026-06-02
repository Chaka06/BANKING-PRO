"""
Utilitaires : génération de PDFs et envoi d'emails Postmark.
Toute la logique de génération d'identifiants est dans services.py.
"""
import io
import os
import math
import logging
from datetime import datetime
from django.conf import settings
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table,
    TableStyle, KeepTogether,
)
from reportlab.lib.enums import TA_CENTER, TA_RIGHT, TA_LEFT

logger = logging.getLogger('banking.utils')


# ── SendGrid ──────────────────────────────────────────────────────────────

def _send_email(from_name: str, to_email: str, subject: str, html_body: str):
    sg = SendGridAPIClient(api_key=settings.SENDGRID_API_KEY)
    message = Mail(
        from_email=(settings.DEFAULT_FROM_EMAIL, from_name),
        to_emails=to_email,
        subject=subject,
        html_content=html_body,
    )
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

    logo_cell = f'<td style="vertical-align:middle;">{logo_html}</td>' if logo_html else ''

    name_part = f'<span style="color:{bank.color_primary};font-size:17px;font-weight:700;font-family:Arial,Helvetica,sans-serif;">{bank.name}</span>'
    tagline_part = f'<br><span style="color:#888888;font-size:11px;font-family:Arial,Helvetica,sans-serif;">{bank.tagline}</span>' if bank.tagline else ''
    padding_left = '12px' if logo_html else '0'
    name_cell = f'<td style="vertical-align:middle;padding-left:{padding_left};">{name_part}{tagline_part}</td>'

    return f"""
    <table width="100%" cellpadding="0" cellspacing="0" border="0" style="border-bottom:3px solid {bank.color_primary};">
      <tr>
        <td style="background:#ffffff;padding:18px 24px;">
          <table cellpadding="0" cellspacing="0" border="0">
            <tr>
              {logo_cell}
              {name_cell}
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

    _send_email(
        from_name=bank.name,
        to_email=bank_account.email,
        subject=f"{bank.name} — Ouverture de votre compte bancaire",
        html_body=_email_wrap(bank, body),
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

    _send_email(
        from_name=bank.name,
        to_email=beneficiary_email,
        subject=f"Virement entrant en attente — Réf. {transaction.reference}",
        html_body=_email_wrap(bank, body),
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

    _send_email(
        from_name=bank.name,
        to_email=transaction.account.email,
        subject=f"Virement validé — Réf. {transaction.reference}",
        html_body=_email_wrap(bank, body_sender),
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

        _send_email(
            from_name=bank.name,
            to_email=beneficiary_email,
            subject=f"Virement reçu — Réf. {transaction.reference}",
            html_body=_email_wrap(bank, body_bene),
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

    _send_email(
        from_name=bank.name,
        to_email=transaction.account.email,
        subject=f"Virement rejeté — Réf. {transaction.reference}",
        html_body=_email_wrap(bank, body_sender),
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


def _draw_arc_text(canvas, text, cx, cy, radius, angle_start, angle_end,
                   font_name='Helvetica-Bold', font_size=6, top_arc=True):
    """Place each character individually along a circular arc.
    angle_start/end in degrees (math convention: 0=right, CCW positive).
    top_arc=True  → char tops face outward (top half text).
    top_arc=False → char bottoms face outward (bottom half text).
    """
    n = len(text)
    if n == 0:
        return
    span = angle_end - angle_start
    canvas.setFont(font_name, font_size)
    for i, char in enumerate(text):
        t = i / max(n - 1, 1)
        angle_deg = angle_start + t * span
        angle_rad = math.radians(angle_deg)
        x = cx + radius * math.cos(angle_rad)
        y = cy + radius * math.sin(angle_rad)
        rotate = angle_deg - 90 if top_arc else angle_deg + 90
        canvas.saveState()
        canvas.translate(x, y)
        canvas.rotate(rotate)
        canvas.drawCentredString(0, 0, char)
        canvas.restoreState()


def _draw_5star(canvas, cx, cy, outer_r):
    """Draw a filled 5-pointed star."""
    inner_r = outer_r * 0.40
    path = canvas.beginPath()
    for i in range(10):
        angle = math.radians(90 + i * 36)
        r = outer_r if i % 2 == 0 else inner_r
        x = cx + r * math.cos(angle)
        y = cy + r * math.sin(angle)
        if i == 0:
            path.moveTo(x, y)
        else:
            path.lineTo(x, y)
    path.close()
    canvas.drawPath(path, fill=1, stroke=0)


def _stamp_initials(bank_name):
    """'BCG Banque' → 'BCG',  'Crédit Agricole' → 'CA'."""
    words = bank_name.split()
    if words and words[0].isupper() and len(words[0]) <= 5:
        return words[0]
    return ''.join(w[0].upper() for w in words if w)[:3]


def _draw_stamp(canvas, bank, cx, cy, radius=15*mm):
    """Professional three-ring bank seal with curved arc text, star separators
    and a monogram centre emblem."""
    primary = _hex_to_rgb(bank.color_primary)

    canvas.saveState()
    canvas.setStrokeColorRGB(*primary)
    canvas.setFillColorRGB(*primary)

    # ── Three concentric rings ─────────────────────────────────────
    # 1. Outer border (thick)
    canvas.setLineWidth(2.4)
    canvas.circle(cx, cy, radius, stroke=1, fill=0)

    # 2. Inner edge of text band
    band_r = radius - 3*mm
    canvas.setLineWidth(0.7)
    canvas.circle(cx, cy, band_r, stroke=1, fill=0)

    # 3. Centre zone border
    zone_r = radius - 5.2*mm
    canvas.setLineWidth(0.7)
    canvas.circle(cx, cy, zone_r, stroke=1, fill=0)

    # ── 5-pointed star separators (left ~10° and right ~170°) ─────
    star_mid_r = (radius + band_r) / 2
    for angle_deg in (10, 170):
        a = math.radians(angle_deg)
        _draw_5star(canvas,
                    cx + star_mid_r * math.cos(a),
                    cy + star_mid_r * math.sin(a),
                    outer_r=1.4)

    # ── Curved bank name — top arc (148° → 32°, left to right) ────
    arc_r = radius - 1.55*mm
    bank_name = bank.name.upper()[:22]
    _draw_arc_text(canvas, bank_name, cx, cy, arc_r,
                   148, 32, 'Helvetica-Bold', 5.5, top_arc=True)

    # ── Curved label — bottom arc (212° → 328°, left to right) ────
    _draw_arc_text(canvas, 'CERTIFIÉ CONFORME', cx, cy, arc_r,
                   212, 328, 'Helvetica', 4.8, top_arc=False)

    # ── Centre emblem ──────────────────────────────────────────────
    initials = _stamp_initials(bank.name)

    # Large initials
    canvas.setFont('Helvetica-Bold', 12)
    canvas.drawCentredString(cx, cy + 1.8*mm, initials)

    # Thin horizontal rule below initials
    rule_w = zone_r * 0.70
    canvas.setLineWidth(0.5)
    canvas.line(cx - rule_w, cy + 0.8*mm, cx + rule_w, cy + 0.8*mm)

    # SWIFT / BIC
    canvas.setFont('Helvetica', 6.5)
    canvas.drawCentredString(cx, cy - 2.5*mm, bank.swift or '')

    # Date
    canvas.setFont('Helvetica', 5)
    canvas.drawCentredString(cx, cy - 5*mm, datetime.now().strftime('%d/%m/%Y'))

    canvas.restoreState()


def _page_bg(canvas, doc, bank, doc_type):
    """Header (logo, bank name, rule, doc type, date) + footer (HR, info, stamp) on every page."""
    PAGE_W, PAGE_H = A4
    ML, MR = 22*mm, 22*mm
    primary = _hex_to_rgb(bank.color_primary)
    gray = (0.42, 0.45, 0.50)
    light = (0.97, 0.98, 0.99)

    canvas.saveState()

    # Subtle header background band
    canvas.setFillColorRGB(*light)
    canvas.rect(0, PAGE_H - 43*mm, PAGE_W, 43*mm, stroke=0, fill=1)

    # Logo — top left
    logo_drawn = False
    if bank.logo:
        try:
            logo_path = bank.logo.path
            if os.path.exists(logo_path):
                canvas.drawImage(logo_path, ML, PAGE_H - 6*mm - 16*mm,
                                 width=48*mm, height=16*mm,
                                 preserveAspectRatio=True, anchor='nw', mask='auto')
                logo_drawn = True
        except Exception:
            pass

    # Bank name
    canvas.setFillColorRGB(*primary)
    if logo_drawn:
        canvas.setFont('Helvetica-Bold', 13)
        canvas.drawString(ML + 52*mm, PAGE_H - 11*mm, bank.name)
        if bank.tagline:
            canvas.setFont('Helvetica', 7.5)
            canvas.setFillColorRGB(*gray)
            canvas.drawString(ML + 52*mm, PAGE_H - 18*mm, bank.tagline)
    else:
        canvas.setFont('Helvetica-Bold', 15)
        canvas.drawCentredString(PAGE_W / 2, PAGE_H - 13*mm, bank.name)
        if bank.tagline:
            canvas.setFont('Helvetica', 8.5)
            canvas.setFillColorRGB(*gray)
            canvas.drawCentredString(PAGE_W / 2, PAGE_H - 20*mm, bank.tagline)

    # Date — top right
    canvas.setFillColorRGB(*gray)
    canvas.setFont('Helvetica', 8)
    canvas.drawRightString(PAGE_W - MR, PAGE_H - 8*mm, datetime.now().strftime('%d/%m/%Y'))

    # Document type — centred
    canvas.setFillColorRGB(*primary)
    canvas.setFont('Helvetica-Bold', 12)
    canvas.drawCentredString(PAGE_W / 2, PAGE_H - 31*mm, doc_type)

    # Primary rule separating header from content
    canvas.setStrokeColorRGB(*primary)
    canvas.setLineWidth(2.5)
    canvas.line(ML, PAGE_H - 42*mm, PAGE_W - MR, PAGE_H - 42*mm)

    # Footer HR
    footer_y = 37*mm
    canvas.setStrokeColorRGB(0.89, 0.90, 0.92)
    canvas.setLineWidth(0.4)
    canvas.line(ML, footer_y, PAGE_W - MR, footer_y)

    # Footer text (left-aligned, leaving right side for stamp)
    canvas.setFillColorRGB(*gray)
    canvas.setFont('Helvetica', 7)
    info = f"{bank.name}  ·  {bank.address}  ·  {bank.phone}  ·  {bank.email}"
    canvas.drawString(ML, footer_y - 5.5*mm, info[:78])
    canvas.setFont('Helvetica', 6.5)
    canvas.setFillColorRGB(0.74, 0.76, 0.80)
    canvas.drawString(ML, footer_y - 10*mm,
                      "Document généré automatiquement — Ne constitue pas un document contractuel sans signature.")

    # Stamp — bottom right
    _draw_stamp(canvas, bank, PAGE_W - MR - 16*mm, footer_y / 2, radius=15*mm)

    canvas.restoreState()


def _build_info_table(data, primary, col_widths=None):
    if col_widths is None:
        col_widths = [65*mm, 105*mm]
    table = Table(data, colWidths=col_widths)
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#f8fafc')),
        ('TEXTCOLOR', (0, 0), (0, -1), primary),
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
        ('FONTNAME', (1, 0), (1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 0), (-1, -1), 9.5),
        ('ROWBACKGROUNDS', (0, 0), (-1, -1), [colors.white, colors.HexColor('#f8fafc')]),
        ('LINEBELOW', (0, 0), (-1, -2), 0.3, colors.HexColor('#e5e7eb')),
        ('BOX', (0, 0), (-1, -1), 0.5, colors.HexColor('#e5e7eb')),
        ('TOPPADDING', (0, 0), (-1, -1), 7),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 7),
        ('LEFTPADDING', (0, 0), (-1, -1), 10),
        ('RIGHTPADDING', (0, 0), (-1, -1), 8),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
    ]))
    return table


# ── PDF RIB ────────────────────────────────────────────────────────────────

def generate_rib_pdf(bank_account, all_accounts=None):
    buffer = io.BytesIO()
    bank = bank_account.bank
    primary = colors.HexColor(bank.color_primary)

    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        topMargin=45*mm, bottomMargin=38*mm,
        leftMargin=22*mm, rightMargin=22*mm,
    )
    story = []
    page_fn = lambda c, d: _page_bg(c, d, bank, "RELEVÉ D'IDENTITÉ BANCAIRE (RIB)")

    story.append(Spacer(1, 3*mm))

    common_data = [
        ['Titulaire du compte', bank_account.get_full_name()],
        ['Domiciliation', bank.name],
        ['Adresse de la banque', bank.address],
        ['BIC / SWIFT', bank.swift or '—'],
        ['Pays', bank_account.country],
        ['Devise', bank_account.currency],
    ]
    story.append(_build_info_table(common_data, primary))
    story.append(Spacer(1, 7*mm))

    accounts_to_show = all_accounts if (all_accounts and len(all_accounts) > 1) else [bank_account]
    for acc in accounts_to_show:
        label = acc.get_account_type_display().upper()
        story.append(Paragraph(
            f'<b>{label}</b>',
            ParagraphStyle('AccLabel', fontSize=9, textColor=primary,
                           fontName='Helvetica-Bold', spaceBefore=4, spaceAfter=3,
                           leftIndent=2)
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
        story.append(Spacer(1, 4*mm))

    story.append(Spacer(1, 4*mm))
    story.append(KeepTogether([
        Paragraph(
            "Je soussigné(e), certifie que les coordonnées bancaires figurant sur ce document "
            f"sont exactes et correspondent à mon/mes compte(s) ouvert(s) auprès de <b>{bank.name}</b>.",
            ParagraphStyle('Decl', fontSize=9, textColor=colors.HexColor('#374151'),
                           leading=14, spaceAfter=12, leftIndent=4, rightIndent=4)
        ),
    ]))

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
        topMargin=45*mm, bottomMargin=38*mm,
        leftMargin=22*mm, rightMargin=22*mm,
    )
    story = []
    page_fn = lambda c, d: _page_bg(c, d, bank, "BORDEREAU DE VIREMENT")

    story.append(Spacer(1, 4*mm))
    status_table = Table(
        [[Paragraph(f'<b>● {s_label}</b>',
                    ParagraphStyle('StatusLabel', fontSize=11, textColor=colors.HexColor(s_fg),
                                   alignment=TA_CENTER, fontName='Helvetica-Bold'))]],
        colWidths=[166*mm],
    )
    status_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor(s_bg)),
        ('BOX', (0, 0), (-1, -1), 1.5, colors.HexColor(s_border)),
        ('TOPPADDING', (0, 0), (-1, -1), 10),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 10),
        ('LEFTPADDING', (0, 0), (-1, -1), 10),
        ('RIGHTPADDING', (0, 0), (-1, -1), 10),
    ]))
    story.append(status_table)
    story.append(Spacer(1, 6*mm))

    data = [
        ['Référence', transaction.reference],
        ['Date d\'initiation', transaction.created_at.strftime('%d/%m/%Y à %H:%M')],
        ['Type', transaction.get_transaction_type_display()],
        ['Montant', f"{transaction.amount:,.2f} {transaction.currency}"],
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

    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        topMargin=45*mm, bottomMargin=38*mm,
        leftMargin=15*mm, rightMargin=15*mm,
    )
    story = []
    period = f"Période du {date_from.strftime('%d/%m/%Y')} au {date_to.strftime('%d/%m/%Y')}"
    page_fn = lambda c, d: _page_bg(c, d, bank, f"RELEVÉ DE COMPTE  —  {period}")

    story.append(Spacer(1, 3*mm))

    account_info = Table(
        [['Titulaire', bank_account.get_full_name()],
         ['IBAN', bank_account.rib],
         ['Devise', bank_account.currency]],
        colWidths=[45*mm, 135*mm]
    )
    account_info.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
        ('TEXTCOLOR', (0, 0), (0, -1), primary),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('LEFTPADDING', (0, 0), (-1, -1), 8),
        ('RIGHTPADDING', (0, 0), (-1, -1), 8),
        ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#f8fafc')),
        ('LINEBELOW', (0, 0), (-1, -2), 0.3, colors.HexColor('#e5e7eb')),
        ('BOX', (0, 0), (-1, -1), 0.4, colors.HexColor('#e5e7eb')),
    ]))
    story.append(account_info)
    story.append(Spacer(1, 5*mm))

    headers = ['Date', 'Référence', 'Libellé', 'Débit', 'Crédit', 'Statut']
    rows = [headers]
    total_debit = 0
    total_credit = 0

    for txn in transactions:
        if txn.is_debit:
            debit = f"{txn.amount:,.2f}"
            credit = ''
            total_debit += float(txn.amount)
        else:
            debit = ''
            credit = f"{txn.amount:,.2f}"
            total_credit += float(txn.amount)

        rows.append([
            txn.created_at.strftime('%d/%m/%Y'),
            txn.reference,
            (txn.description or txn.get_transaction_type_display())[:35],
            debit,
            credit,
            txn.get_status_display(),
        ])

    rows.append(['', '', 'TOTAUX', f"{total_debit:,.2f}", f"{total_credit:,.2f}", ''])

    col_widths = [22*mm, 30*mm, 68*mm, 22*mm, 22*mm, 16*mm]
    txn_table = Table(rows, colWidths=col_widths, repeatRows=1)

    debit_rows = [i + 1 for i, r in enumerate(rows[1:]) if r[3]]
    credit_rows = [i + 1 for i, r in enumerate(rows[1:]) if r[4]]

    style_commands = [
        ('BACKGROUND', (0, 0), (-1, 0), primary),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 8),
        ('ROWBACKGROUNDS', (0, 1), (-1, -2), [colors.white, colors.HexColor('#f9fafb')]),
        ('GRID', (0, 0), (-1, -1), 0.2, colors.HexColor('#e5e7eb')),
        ('TOPPADDING', (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ('LEFTPADDING', (0, 0), (-1, -1), 4),
        ('RIGHTPADDING', (0, 0), (-1, -1), 4),
        ('ALIGN', (3, 0), (4, -1), 'RIGHT'),
        ('BACKGROUND', (0, len(rows)-1), (-1, len(rows)-1), colors.HexColor('#f1f5f9')),
        ('FONTNAME', (0, len(rows)-1), (-1, len(rows)-1), 'Helvetica-Bold'),
    ]
    for r in debit_rows:
        style_commands.append(('TEXTCOLOR', (3, r), (3, r), colors.HexColor('#dc2626')))
    for r in credit_rows:
        style_commands.append(('TEXTCOLOR', (4, r), (4, r), colors.HexColor('#16a34a')))

    txn_table.setStyle(TableStyle(style_commands))
    story.append(txn_table)
    story.append(Spacer(1, 5*mm))

    story.append(Paragraph(
        f"Solde au {date_to.strftime('%d/%m/%Y')} : <b>{bank_account.balance:,.2f} {bank_account.currency}</b>",
        ParagraphStyle('Balance', fontSize=11, textColor=primary, alignment=TA_RIGHT, spaceAfter=4)
    ))

    doc.build(story, onFirstPage=page_fn, onLaterPages=page_fn)
    buffer.seek(0)
    return buffer
