from decimal import Decimal
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.utils.html import format_html
from django.utils.safestring import mark_safe
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db import transaction as db_transaction

from .models import BankUser, BankAccount, Beneficiary, AuditLog, LoginAttempt
from .services import AccountService


# ── Multi-tenant mixin ────────────────────────────────────────────────────

class BankScopedAdmin(admin.ModelAdmin):
    bank_field = 'bank'

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs
        managed_banks = request.user.managed_banks.values_list('bank_id', flat=True)
        if managed_banks:
            return qs.filter(**{f'{self.bank_field}__in': managed_banks})
        return qs.none()

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == 'bank' and not request.user.is_superuser:
            from banks.models import Bank
            managed_banks = request.user.managed_banks.values_list('bank_id', flat=True)
            kwargs['queryset'] = Bank.objects.filter(pk__in=managed_banks)
        return super().formfield_for_foreignkey(db_field, request, **kwargs)


# ── BankUser (masqué du menu — comptes créés via AccountService) ──────────

@admin.register(BankUser)
class BankUserAdmin(UserAdmin):
    list_display = ['account_id', 'email', 'is_active', 'is_staff', 'date_joined']
    search_fields = ['account_id', 'email']
    ordering = ['-date_joined']
    fieldsets = (
        (None, {'fields': ('account_id', 'password')}),
        ('Email', {'fields': ('email',)}),
        ('Permissions', {'fields': ('is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions')}),
        ('Dates', {'fields': ('last_login', 'date_joined')}),
    )
    add_fieldsets = (
        (None, {'classes': ('wide',), 'fields': ('account_id', 'email', 'password1', 'password2')}),
    )

    def get_model_perms(self, request):
        # Masqué du menu — les utilisateurs sont créés automatiquement par AccountService
        return {}


# ── BankAccount ───────────────────────────────────────────────────────────

@admin.register(BankAccount)
class BankAccountAdmin(BankScopedAdmin):
    list_display = [
        'get_full_name', 'account_id_display', 'bank_badge', 'country',
        'currency', 'balance_display', 'status_badge',
        'manager_name', 'created_at',
    ]
    list_filter = ['bank', 'status', 'country', 'currency']
    list_select_related = ['bank', 'user']
    search_fields = ['first_name', 'last_name', 'account_id', 'rib', 'email', 'phone']
    ordering = ['-created_at']
    date_hierarchy = 'created_at'

    def get_queryset(self, request):
        # Un seul portefeuille par client dans la liste → affiche uniquement le compte courant (primaire)
        return super().get_queryset(request).filter(is_primary=True)

    _ADD_FIELDSETS = (
        ('Banque & Gestionnaire', {
            'fields': ('bank', 'manager_name'),
        }),
        ('Informations personnelles', {
            'fields': ('first_name', 'last_name', 'email', 'phone', 'country', 'address', 'birth_date'),
        }),
        ('Compte Courant — Solde initial', {
            'fields': ('balance', 'status'),
            'description': 'La devise est automatiquement déterminée par le pays sélectionné.',
        }),
        ('Compte Épargne — Solde initial', {
            'fields': ('balance_epargne',),
            'description': 'Solde initial du compte épargne (laisser 0.00 si non renseigné).',
        }),
        ('Blocage du compte', {
            'fields': ('block_reason', 'unblock_fee'),
            'classes': ('collapse',),
            'description': '⚠️ Remplir uniquement si le statut est "Compte bloqué". Le motif de blocage est alors obligatoire.',
        }),
    )

    _CHANGE_FIELDSETS = (
        ('Banque & Gestionnaire', {
            'fields': ('bank', 'manager_name'),
        }),
        ('Identifiants générés automatiquement', {
            'fields': ('credentials_display', 'login_url_display', 'account_id', 'rib', 'plain_password'),
            'classes': ('collapse',),
            'description': 'Générés à la création — communiquer ces informations au client en main propre ou par courrier sécurisé.',
        }),
        ('Informations personnelles', {
            'fields': ('first_name', 'last_name', 'email', 'phone', 'country', 'address', 'birth_date'),
        }),
        ('Compte Courant', {
            'fields': ('currency', 'balance', 'status'),
        }),
        ('Compte Épargne', {
            'fields': ('epargne_display',),
            'description': 'Compte épargne associé à ce portefeuille client.',
        }),
        ('Blocage du compte courant', {
            'fields': ('block_reason', 'unblock_fee'),
            'description': '⚠️ Remplir uniquement si le statut est "Compte bloqué". Le motif est obligatoire.',
        }),
        ('Horodatage', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',),
        }),
    )

    def get_fieldsets(self, request, obj=None):
        return self._ADD_FIELDSETS if obj is None else self._CHANGE_FIELDSETS

    def get_readonly_fields(self, request, obj=None):
        if obj is None:
            return []
        return ['account_id', 'rib', 'plain_password',
                'credentials_display', 'login_url_display',
                'created_at', 'updated_at', 'epargne_display']

    def get_form(self, request, obj=None, **kwargs):
        from django import forms
        from decimal import Decimal
        from .constants import COUNTRY_LIST

        # balance_epargne n'est pas un champ du modèle — on l'exclut de modelform_factory
        # puis on l'injecte manuellement dans base_fields
        if obj is None and 'fields' not in kwargs:
            model_fields = []
            for _, opts in self._ADD_FIELDSETS:
                model_fields.extend(f for f in opts.get('fields', []) if f != 'balance_epargne')
            kwargs['fields'] = model_fields

        form = super().get_form(request, obj, **kwargs)

        form.base_fields['country'] = forms.ChoiceField(
            choices=[(c, c) for c in COUNTRY_LIST],
            label='Pays',
        )
        if obj is None:
            form.base_fields['balance_epargne'] = forms.DecimalField(
                label='Solde initial — Compte Épargne',
                initial=Decimal('0.00'),
                min_value=Decimal('0.00'),
                max_digits=15,
                decimal_places=2,
                required=False,
                help_text='Laissez 0.00 si le compte épargne démarre sans solde.',
            )
        return form

    # ── Display helpers ───────────────────────────────────────────────────

    def get_full_name(self, obj):
        return obj.get_full_name()
    get_full_name.short_description = 'Titulaire'
    get_full_name.admin_order_field = 'last_name'

    def account_id_display(self, obj):
        return format_html(
            '<span style="font-family:monospace;font-size:12px;">{}</span>'
            '<br><small style="color:#6b7280;">{}</small>',
            obj.account_id, obj.get_account_type_display()
        )
    account_id_display.short_description = 'Identifiant'
    account_id_display.admin_order_field = 'account_id'

    def bank_badge(self, obj):
        return format_html(
            '<span style="background:{};color:{};padding:3px 10px;border-radius:10px;'
            'font-size:11px;font-weight:600;">{}</span>',
            obj.bank.color_primary, obj.bank.color_text_on_primary, obj.bank.name
        )
    bank_badge.short_description = 'Banque'
    bank_badge.admin_order_field = 'bank__name'

    def balance_display(self, obj):
        color = '#16a34a' if obj.balance >= 0 else '#dc2626'
        amount = f'{obj.balance:,.2f}'
        return format_html(
            '<span style="color:{};font-weight:700;font-family:monospace;">{} {}</span>',
            color, amount, obj.currency
        )
    balance_display.short_description = 'Solde'
    balance_display.admin_order_field = 'balance'

    def status_badge(self, obj):
        if obj.status == BankAccount.STATUS_ACTIVE:
            return mark_safe(
                '<span style="background:#dcfce7;color:#166534;padding:3px 10px;'
                'border-radius:12px;font-size:11px;font-weight:600;">● Actif</span>'
            )
        return mark_safe(
            '<span style="background:#fee2e2;color:#991b1b;padding:3px 10px;'
            'border-radius:12px;font-size:11px;font-weight:600;">🔒 Bloqué</span>'
        )
    status_badge.short_description = 'Statut'

    def credentials_display(self, obj):
        if not obj.pk:
            return mark_safe('<em style="color:#6b7280;">Disponible après la création du compte.</em>')
        from .encryption import decrypt_field
        pwd = decrypt_field(obj.plain_password) if obj.plain_password else '(réinitialisé)'
        return format_html(
            '<div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;padding:16px;">'
            '<p style="margin:0 0 8px;font-size:13px;color:#374151;">'
            '<strong>Identifiant :</strong> '
            '<code style="background:#e2e8f0;padding:3px 8px;border-radius:4px;font-size:13px;">{}</code></p>'
            '<p style="margin:0 0 8px;font-size:13px;color:#374151;">'
            '<strong>Mot de passe initial :</strong> '
            '<code style="background:#e2e8f0;padding:3px 8px;border-radius:4px;font-size:13px;">{}</code></p>'
            '<p style="margin:8px 0 0;font-size:11px;color:#9ca3af;">'
            '⚠️ À communiquer de manière sécurisée au titulaire.</p>'
            '</div>',
            obj.account_id, pwd
        )
    credentials_display.short_description = 'Identifiants à communiquer au client'

    def login_url_display(self, obj):
        if not obj.pk:
            return '—'
        url = obj.get_login_url()
        return format_html(
            '<a href="{}" target="_blank" style="color:#2563eb;text-decoration:none;'
            'font-family:monospace;font-size:12px;">{}</a>',
            url, url
        )
    login_url_display.short_description = 'Lien de connexion'

    def epargne_display(self, obj):
        if not obj.pk:
            return '—'
        epargne = obj.user.bank_accounts.filter(bank=obj.bank, is_primary=False).first()
        if not epargne:
            return mark_safe('<em style="color:#9ca3af;font-size:12px;">Aucun compte épargne associé.</em>')
        edit_url = f'/admin/accounts/bankaccount/{epargne.pk}/change/'
        balance_color = '#16a34a' if epargne.balance >= 0 else '#dc2626'
        status_badge = (
            '<span style="background:#dcfce7;color:#166534;padding:2px 8px;border-radius:10px;'
            'font-size:11px;font-weight:600;">● Actif</span>'
            if epargne.status == 'active' else
            '<span style="background:#fee2e2;color:#991b1b;padding:2px 8px;border-radius:10px;'
            'font-size:11px;font-weight:600;">🔒 Bloqué</span>'
        )
        return format_html(
            '<div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;padding:16px 20px;">'
            '<table style="border-collapse:collapse;">'
            '<tr><td style="color:#6b7280;font-size:12px;padding:4px 16px 4px 0;">Identifiant</td>'
            '<td style="font-family:monospace;font-size:12px;font-weight:600;color:#111827;">{}</td></tr>'
            '<tr><td style="color:#6b7280;font-size:12px;padding:4px 16px 4px 0;">IBAN</td>'
            '<td style="font-family:monospace;font-size:11px;color:#374151;">{}</td></tr>'
            '<tr><td style="color:#6b7280;font-size:12px;padding:4px 16px 4px 0;">Solde</td>'
            '<td style="font-family:monospace;font-weight:700;font-size:14px;color:{};">{} {}</td></tr>'
            '<tr><td style="color:#6b7280;font-size:12px;padding:4px 16px 4px 0;">Statut</td>'
            '<td>{}</td></tr>'
            '</table>'
            '<div style="margin-top:12px;">'
            '<a href="{}" style="color:#2563eb;font-size:12px;font-weight:600;text-decoration:none;'
            'background:#eff6ff;padding:7px 14px;border-radius:4px;border:1px solid #bfdbfe;">'
            '✏ Modifier le compte épargne</a>'
            '</div></div>',
            epargne.account_id,
            epargne.rib,
            balance_color, f'{epargne.balance:,.2f}', epargne.currency,
            mark_safe(status_badge),
            edit_url,
        )
    epargne_display.short_description = 'Compte Épargne'

    # ── Save model ────────────────────────────────────────────────────────

    def save_model(self, request, obj, form, change):
        actor = request.user.get_username()

        if not change:
            from decimal import Decimal
            # Bloquer si un compte existe déjà pour cet email dans cette banque
            try:
                from .models import BankUser
                existing_user = BankUser.objects.get(email=obj.email)
                if existing_user.bank_accounts.filter(bank=obj.bank).exists():
                    messages.error(request, mark_safe(
                        f'⚠️ Un compte pour <strong>{obj.email}</strong> existe déjà dans '
                        f'<strong>{obj.bank.name}</strong>. Consultez ou modifiez le compte existant.'
                    ))
                    return
            except BankUser.DoesNotExist:
                pass

            balance_epargne = Decimal('0.00')
            if hasattr(form, 'cleaned_data') and form.cleaned_data.get('balance_epargne') is not None:
                balance_epargne = form.cleaned_data['balance_epargne']

            data = {
                'first_name':   obj.first_name,
                'last_name':    obj.last_name,
                'email':        obj.email,
                'phone':        obj.phone,
                'country':      obj.country,
                'address':      obj.address,
                'birth_date':   obj.birth_date,
                'currency':     obj.currency or '',
                'balance':      obj.balance,
                'status':       obj.status,
                'block_reason': obj.block_reason,
                'unblock_fee':  obj.unblock_fee,
                'manager_name': obj.manager_name,
                'account_type': BankAccount.TYPE_COURANT,
            }
            try:
                # Compte courant (principal)
                courant, plain_pwd = AccountService.create_account(obj.bank, data, actor=actor)

                if not plain_pwd:
                    messages.error(request, "Erreur interne : le mot de passe n'a pas pu être généré. Supprimez le compte créé et réessayez.")
                    return

                # Compte épargne (secondaire)
                epargne, _ = AccountService.create_account(
                    obj.bank,
                    {**data, 'account_type': BankAccount.TYPE_EPARGNE, 'balance': balance_epargne},
                    actor=actor,
                )

                # Pointer obj vers le courant pour la redirection Django admin
                obj.pk           = courant.pk
                obj.account_id   = courant.account_id
                obj.rib          = courant.rib
                obj.plain_password = courant.plain_password
                obj.user         = courant.user

                # Message de succès avec toutes les infos d'accès
                login_url = courant.get_login_url()
                messages.success(request, mark_safe(
                    f'<div style="line-height:1.8;">'
                    f'<strong style="font-size:14px;">Comptes créés — {courant.get_full_name()}</strong><br>'
                    f'<table style="margin-top:6px;border-collapse:collapse;">'
                    f'<tr><td style="padding:2px 16px 2px 0;"><strong>Identifiant :</strong></td>'
                    f'<td><code style="background:#e2e8f0;padding:2px 8px;border-radius:4px;">'
                    f'{courant.account_id}</code></td></tr>'
                    f'<tr><td style="padding:2px 16px 2px 0;"><strong>Mot de passe :</strong></td>'
                    f'<td><code style="background:#e2e8f0;padding:2px 8px;border-radius:4px;">'
                    f'{plain_pwd}</code></td></tr>'
                    f'<tr><td style="padding:2px 16px 2px 0;"><strong>Connexion :</strong></td>'
                    f'<td><a href="{login_url}" target="_blank" style="color:#2563eb;">'
                    f'{login_url}</a></td></tr>'
                    f'<tr><td style="padding:2px 16px 2px 0;"><strong>RIB Courant :</strong></td>'
                    f'<td><code style="background:#e2e8f0;padding:2px 8px;border-radius:4px;">'
                    f'{courant.rib}</code></td></tr>'
                    f'<tr><td style="padding:2px 16px 2px 0;"><strong>RIB Épargne :</strong></td>'
                    f'<td><code style="background:#e2e8f0;padding:2px 8px;border-radius:4px;">'
                    f'{epargne.rib}</code></td></tr>'
                    f'</table>'
                    f'<p style="margin:6px 0 0;font-size:11px;color:#9ca3af;">'
                    f'⚠️ Communiquer ces informations de manière sécurisée au titulaire.</p>'
                    f'</div>'
                ))

                try:
                    from .utils import send_account_creation_email
                    send_account_creation_email(courant)
                    messages.success(request, f"Email envoyé à {courant.email}")
                except Exception as e:
                    messages.warning(request, f"Compte créé mais email non envoyé : {e}")

                return

            except (ValidationError, Exception) as e:
                messages.error(request, f"Erreur lors de la création : {e}")
                raise

        else:
            try:
                old = BankAccount.objects.get(pk=obj.pk)
                if old.status != obj.status:
                    AccountService.set_account_status(
                        old,
                        new_status=obj.status,
                        block_reason=obj.block_reason,
                        unblock_fee=obj.unblock_fee,
                        actor=actor,
                    )
                    if obj.status == BankAccount.STATUS_ACTIVE:
                        obj.block_reason = ''
            except ValidationError as e:
                messages.error(request, str(e.message))
                raise

            super().save_model(request, obj, form, change)


# ── Beneficiary ───────────────────────────────────────────────────────────

@admin.register(Beneficiary)
class BeneficiaryAdmin(admin.ModelAdmin):
    list_display = ['get_full_name', 'account', 'account_number', 'bank_name', 'email', 'created_at']
    search_fields = ['first_name', 'last_name', 'account_number', 'bank_name', 'account__account_id']
    list_filter = ['account__bank']
    list_select_related = ['account', 'account__bank']

    def get_full_name(self, obj):
        return obj.get_full_name()
    get_full_name.short_description = 'Bénéficiaire'


# ── AuditLog ──────────────────────────────────────────────────────────────

@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ['created_at', 'action_badge', 'actor', 'account', 'bank', 'description_short']
    list_filter = ['action', 'bank', 'created_at']
    search_fields = ['actor', 'description', 'account__account_id', 'account__first_name', 'account__last_name']
    list_select_related = ['bank', 'account']
    readonly_fields = ['bank', 'account', 'action', 'actor', 'description', 'extra_data', 'ip_address', 'created_at']
    ordering = ['-created_at']
    date_hierarchy = 'created_at'

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser

    def action_badge(self, obj):
        color_map = {
            'account_created':   ('#dcfce7', '#166534'),
            'account_blocked':   ('#fee2e2', '#991b1b'),
            'account_unblocked': ('#dbeafe', '#1e40af'),
            'transfer_created':  ('#fef9c3', '#92400e'),
            'transfer_validated':('#dcfce7', '#166534'),
            'transfer_rejected': ('#fee2e2', '#991b1b'),
            'balance_updated':   ('#e0e7ff', '#3730a3'),
            'login':             ('#f3f4f6', '#374151'),
            'password_changed':  ('#fdf4ff', '#7e22ce'),
        }
        bg, fg = color_map.get(obj.action, ('#f3f4f6', '#374151'))
        return format_html(
            '<span style="background:{};color:{};padding:2px 8px;border-radius:10px;'
            'font-size:11px;white-space:nowrap;">{}</span>',
            bg, fg, obj.get_action_display()
        )
    action_badge.short_description = 'Action'

    def description_short(self, obj):
        return obj.description[:80] + ('…' if len(obj.description) > 80 else '')
    description_short.short_description = 'Description'


# ── LoginAttempt ──────────────────────────────────────────────────────────

@admin.register(LoginAttempt)
class LoginAttemptAdmin(admin.ModelAdmin):
    list_display = ['created_at', 'account_id', 'ip_address', 'bank_slug', 'success_badge']
    list_filter = ['success', 'bank_slug', 'created_at']
    search_fields = ['account_id', 'ip_address']
    readonly_fields = ['account_id', 'ip_address', 'bank_slug', 'success', 'created_at']
    ordering = ['-created_at']
    date_hierarchy = 'created_at'

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def success_badge(self, obj):
        if obj.success:
            return mark_safe(
                '<span style="background:#dcfce7;color:#166534;padding:2px 8px;'
                'border-radius:10px;font-size:11px;">✓ Succès</span>'
            )
        return mark_safe(
            '<span style="background:#fee2e2;color:#991b1b;padding:2px 8px;'
            'border-radius:10px;font-size:11px;">✗ Échec</span>'
        )
    success_badge.short_description = 'Résultat'
