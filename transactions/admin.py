from decimal import Decimal
from django.contrib import admin
from django.utils.html import format_html
from django.contrib import messages
from django.core.exceptions import ValidationError
from .models import Transaction
from accounts.services import TransferService
from accounts.utils import fmt_amount


@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    list_display = [
        'reference', 'account_display', 'bank_badge',
        'type_badge', 'amount_display', 'status_badge', 'created_at'
    ]
    list_filter = ['transaction_type', 'status', 'account__bank', 'created_at']
    list_select_related = ['account', 'account__bank', 'beneficiary']
    search_fields = [
        'reference', 'account__first_name', 'account__last_name',
        'account__account_id', 'beneficiary_name', 'beneficiary_iban',
    ]
    readonly_fields = [
        'reference', 'created_at', 'validated_at',
        'account_balance_info', 'account_iban_display',
    ]
    ordering = ['-created_at']
    date_hierarchy = 'created_at'

    fieldsets = (
        ('Identification', {
            'fields': ('reference', 'account', 'account_balance_info', 'account_iban_display', 'created_at', 'validated_at')
        }),
        ('Détails du mouvement', {
            'fields': ('transaction_type', 'amount', 'currency', 'description', 'status')
        }),
        ('Bénéficiaire', {
            'fields': (
                'beneficiary',
                'beneficiary_name', 'beneficiary_iban',
                'beneficiary_email', 'beneficiary_bank',
            ),
            'classes': ('collapse',),
            'description': 'Pour les virements seulement.',
        }),
        ('Rejet (uniquement si statut = Rejeté)', {
            'fields': ('rejection_reason', 'rejection_fee'),
            'description': (
                '⚠️ Le motif est obligatoire en cas de rejet. '
                'Les frais de redirection sont informativement indiqués au client '
                'mais ne sont PAS déduits automatiquement du solde.'
            ),
            'classes': ('collapse',),
        }),
    )

    # ── Display helpers ───────────────────────────────────────────────────

    def account_display(self, obj):
        return format_html(
            '<strong>{}</strong><br><span style="color:#6b7280;font-size:11px;font-family:monospace;">{}</span>',
            obj.account.get_full_name(), obj.account.account_id
        )
    account_display.short_description = 'Compte'
    account_display.admin_order_field = 'account__last_name'

    def bank_badge(self, obj):
        bank = obj.account.bank
        return format_html(
            '<span style="background:{};color:{};padding:2px 8px;border-radius:8px;font-size:11px;font-weight:600;">{}</span>',
            bank.color_primary, bank.color_text_on_primary, bank.name
        )
    bank_badge.short_description = 'Banque'

    def type_badge(self, obj):
        config = {
            'transfer_out': ('#fef9c3', '#92400e', '↗ Virement sortant'),
            'transfer_in': ('#dcfce7', '#166534', '↙ Virement entrant'),
            'withdrawal': ('#fee2e2', '#991b1b', '💸 Retrait guichet'),
            'deposit': ('#dbeafe', '#1e40af', '💰 Dépôt'),
            'payment': ('#f3f4f6', '#374151', '📄 Paiement'),
        }
        bg, fg, label = config.get(obj.transaction_type, ('#f3f4f6', '#374151', obj.transaction_type))
        return format_html(
            '<span style="background:{};color:{};padding:2px 8px;border-radius:8px;font-size:11px;white-space:nowrap;">{}</span>',
            bg, fg, label
        )
    type_badge.short_description = 'Type'

    def amount_display(self, obj):
        amount_str = f"{fmt_amount(obj.amount)}"
        if obj.is_debit:
            return format_html(
                '<span style="color:#dc2626;font-weight:700;font-family:monospace;">− {} {}</span>',
                amount_str, obj.currency
            )
        return format_html(
            '<span style="color:#16a34a;font-weight:700;font-family:monospace;">+ {} {}</span>',
            amount_str, obj.currency
        )
    amount_display.short_description = 'Montant'
    amount_display.admin_order_field = 'amount'

    def status_badge(self, obj):
        config = {
            'pending': ('#fef9c3', '#92400e', '⏳ En cours'),
            'validated': ('#dcfce7', '#166534', '✅ Validé'),
            'rejected': ('#fee2e2', '#991b1b', '❌ Rejeté'),
        }
        bg, fg, label = config.get(obj.status, ('#f3f4f6', '#374151', obj.status))
        return format_html(
            '<span style="background:{};color:{};padding:3px 10px;border-radius:12px;font-size:11px;font-weight:600;">{}</span>',
            bg, fg, label
        )
    status_badge.short_description = 'Statut'

    def account_balance_info(self, obj):
        if not obj.pk:
            return '—'
        account = obj.account
        color = '#16a34a' if account.balance >= 0 else '#dc2626'
        balance_str = f"{fmt_amount(account.balance)}"
        return format_html(
            '<span style="color:{};font-weight:700;font-size:14px;font-family:monospace;">{} {}</span>',
            color, balance_str, account.currency
        )
    account_balance_info.short_description = 'Solde actuel du compte'

    def account_iban_display(self, obj):
        if not obj.pk:
            return '—'
        return format_html(
            '<code style="font-size:12px;color:#374151;">{}</code>',
            obj.account.rib
        )
    account_iban_display.short_description = 'IBAN du compte'

    # ── Save : utiliser TransferService pour les changements de statut ────

    def save_model(self, request, obj, form, change):
        actor = request.user.get_username()

        if change and obj.pk:
            try:
                old = Transaction.objects.get(pk=obj.pk)
            except Transaction.DoesNotExist:
                super().save_model(request, obj, form, change)
                return

            old_status = old.status
            new_status = obj.status

            if old_status != new_status:
                # Changement de statut → passer par TransferService
                if old_status == Transaction.STATUS_PENDING and new_status == Transaction.STATUS_VALIDATED:
                    try:
                        TransferService.validate_transfer(old, actor=actor)
                        # Envoyer emails
                        try:
                            from accounts.utils import send_transfer_validated_email
                            send_transfer_validated_email(old)
                        except Exception as e:
                            messages.warning(request, f"Emails de validation non envoyés : {e}")
                        messages.success(request, f"✅ Virement {old.reference} validé.")
                    except ValidationError as e:
                        messages.error(request, str(e.message))
                    return  # Le service a déjà tout sauvegardé

                elif old_status == Transaction.STATUS_PENDING and new_status == Transaction.STATUS_REJECTED:
                    rejection_reason = obj.rejection_reason.strip()
                    if not rejection_reason:
                        messages.error(request, "⚠️ Un motif de rejet est obligatoire.")
                        return

                    rejection_fee = obj.rejection_fee if obj.rejection_fee else None

                    try:
                        TransferService.reject_transfer(old, rejection_reason, rejection_fee, actor=actor)
                        try:
                            from accounts.utils import send_transfer_rejected_email
                            send_transfer_rejected_email(old)
                        except Exception as e:
                            messages.warning(request, f"Emails de rejet non envoyés : {e}")
                        messages.success(request, f"❌ Virement {old.reference} rejeté et solde remboursé.")
                    except ValidationError as e:
                        messages.error(request, str(e.message))
                    return

                else:
                    messages.error(
                        request,
                        f"Transition de statut invalide : {old_status} → {new_status}. "
                        "Seule la transition PENDING → VALIDÉ ou PENDING → REJETÉ est autorisée."
                    )
                    return
            else:
                # Pas de changement de statut — mise à jour normale des autres champs
                super().save_model(request, obj, form, change)

        elif not change:
            # Nouvelle transaction créée manuellement par l'admin
            try:
                from accounts.services import TransferService
                txn = TransferService.create_manual_movement(
                    account=obj.account,
                    movement_type=obj.transaction_type,
                    amount=obj.amount,
                    description=obj.description,
                    actor=actor,
                    extra={
                        'beneficiary_name': obj.beneficiary_name,
                        'beneficiary_iban': obj.beneficiary_iban,
                        'beneficiary_email': obj.beneficiary_email,
                        'beneficiary_bank': obj.beneficiary_bank,
                    }
                )
                messages.success(request, f"✅ Mouvement {txn.reference} enregistré. Solde mis à jour.")
            except ValidationError as e:
                messages.error(request, str(e.message))
            return
