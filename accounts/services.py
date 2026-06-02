"""
Couche service — toute la logique métier financière passe ici.
Aucune vue ni admin ne doit toucher directement les soldes ou créer des transactions.
"""
import secrets
import string
import logging
from decimal import Decimal, ROUND_HALF_UP
from django.db import transaction as db_transaction
from django.utils import timezone
from django.core.exceptions import ValidationError

from .constants import COUNTRY_PREFIXES, COUNTRY_CURRENCIES

logger = logging.getLogger('banking.services')


# ── Génération cryptographiquement sécurisée ──────────────────────────────

def get_country_prefix(country: str) -> str:
    return COUNTRY_PREFIXES.get(country, 'XX')


def get_country_currency(country: str) -> str:
    return COUNTRY_CURRENCIES.get(country, 'EUR')


def generate_base_id(country: str) -> str:
    """Génère prefix + 5 chiffres (ex: FR52603). Garantit qu'aucun compte ne commence par cette base."""
    from .models import BankAccount
    prefix = get_country_prefix(country)
    for _ in range(100):
        digits = ''.join(secrets.choice(string.digits) for _ in range(5))
        base = f"{prefix}{digits}"
        if not BankAccount.objects.filter(account_id__startswith=base).exists():
            return base
    raise RuntimeError("Impossible de générer une base d'identifiant unique après 100 tentatives.")


def generate_rib(country: str, bank_code: str) -> str:
    """
    Génère un IBAN de 27 caractères (format France) :
    FR (2) + check (2) + code banque (5) + code guichet (5) + n° compte (11) + clé RIB (2) = 27
    """
    from .models import BankAccount
    prefix = get_country_prefix(country)
    for _ in range(100):
        code_banque  = bank_code.zfill(5)
        code_guichet = ''.join(secrets.choice(string.digits) for _ in range(5))
        num_compte   = ''.join(secrets.choice(string.digits) for _ in range(11))
        cle_rib      = ''.join(secrets.choice(string.digits) for _ in range(2))
        check_digits = ''.join(secrets.choice(string.digits) for _ in range(2))
        iban = f"{prefix}{check_digits}{code_banque}{code_guichet}{num_compte}{cle_rib}"
        if not BankAccount.objects.filter(rib=iban).exists():
            return iban
    raise RuntimeError("Impossible de générer un IBAN unique après 100 tentatives.")


def generate_rib_for_secondary(primary_rib: str) -> str:
    """
    Génère un IBAN pour un compte secondaire (épargne) en conservant tous les composants
    du compte primaire (prefix, check, code banque, code guichet, clé RIB) et en générant
    uniquement un nouveau numéro de compte (positions 14–25).
    """
    from .models import BankAccount
    prefix  = primary_rib[:2]    # ex: FR
    check   = primary_rib[2:4]   # check digits
    banque  = primary_rib[4:9]   # code banque
    guichet = primary_rib[9:14]  # code guichet
    cle     = primary_rib[25:27] # clé RIB
    for _ in range(100):
        num_compte = ''.join(secrets.choice(string.digits) for _ in range(11))
        iban = f"{prefix}{check}{banque}{guichet}{num_compte}{cle}"
        if not BankAccount.objects.filter(rib=iban).exists():
            return iban
    raise RuntimeError("Impossible de générer un IBAN unique pour le compte secondaire.")


def generate_password() -> str:
    alphabet = string.ascii_letters + string.digits + '!@#$%&*'
    while True:
        pwd = ''.join(secrets.choice(alphabet) for _ in range(12))
        has_upper = any(c.isupper() for c in pwd)
        has_lower = any(c.islower() for c in pwd)
        has_digit = any(c.isdigit() for c in pwd)
        has_special = any(c in '!@#$%&*' for c in pwd)
        if has_upper and has_lower and has_digit and has_special:
            return pwd


# ── AccountService ─────────────────────────────────────────────────────────

class AccountService:

    @staticmethod
    @db_transaction.atomic
    def create_account(bank, data: dict, actor: str = 'admin') -> 'BankAccount':
        """
        Crée un compte bancaire.
        Si un BankUser avec le même email existe déjà, on lui ajoute un compte (compte épargne, etc.)
        sans créer un nouveau BankUser ni changer le mot de passe.
        Opération atomique.
        """
        from .models import BankUser, BankAccount, AuditLog
        from notifications.models import Notification

        country = data['country']
        currency = data.get('currency') or get_country_currency(country)
        account_type = data.get('account_type', BankAccount.TYPE_COURANT)

        plain_pwd = None
        try:
            # Utilisateur existant
            user = BankUser.objects.get(email=data['email'])
            # On vérifie uniquement le compte courant pour déterminer is_primary
            # (un épargne orphelin ne doit pas bloquer la création d'un nouveau courant)
            existing_courant = user.bank_accounts.filter(bank=bank, account_type=BankAccount.TYPE_COURANT).count()
            is_primary = existing_courant == 0

            if is_primary:
                # Premier compte courant dans cette banque.
                # On réutilise le BankUser.account_id existant pour que
                # l'authentification corresponde toujours à l'identifiant affiché.
                account_id = user.account_id
                if BankAccount.objects.filter(account_id=account_id).exists():
                    raise ValidationError(
                        f"L'identifiant {account_id} est déjà utilisé par un autre compte actif. "
                        "Supprimez d'abord l'ancien compte avant d'en créer un nouveau."
                    )
                rib = generate_rib(country, bank.bank_code)
                plain_pwd = generate_password()
                user.set_password(plain_pwd)
                user.save(update_fields=['password'])
            else:
                # Compte épargne — s'appuie sur le courant existant
                primary = user.bank_accounts.filter(bank=bank, account_type=BankAccount.TYPE_COURANT).first()
                if primary:
                    base = primary.account_id[:-2]
                    rib = generate_rib_for_secondary(primary.rib)
                else:
                    base = generate_base_id(country)
                    rib = generate_rib(country, bank.bank_code)
                existing_in_bank = user.bank_accounts.filter(bank=bank).count()
                suffix = existing_in_bank + 1
                account_id = f"{base}{str(suffix).zfill(2)}"
                if BankAccount.objects.filter(account_id=account_id).exists():
                    raise RuntimeError(f"L'identifiant {account_id} est déjà utilisé.")

        except BankUser.DoesNotExist:
            # Nouvel utilisateur → tout généré de zéro
            base = generate_base_id(country)
            account_id = f"{base}01"
            rib = generate_rib(country, bank.bank_code)
            plain_pwd = generate_password()
            user = BankUser.objects.create_user(
                account_id=account_id,
                email=data['email'],
                password=plain_pwd,
            )
            is_primary = True

        status = data.get('status', BankAccount.STATUS_ACTIVE)
        block_reason = data.get('block_reason', '')
        unblock_fee = data.get('unblock_fee')

        if status == BankAccount.STATUS_BLOCKED and not block_reason:
            raise ValidationError("Un motif de blocage est obligatoire pour un compte bloqué.")

        from .encryption import encrypt_field
        account = BankAccount.objects.create(
            bank=bank,
            user=user,
            account_type=account_type,
            is_primary=is_primary,
            account_id=account_id,
            rib=rib,
            plain_password=encrypt_field(plain_pwd) if plain_pwd else '',
            first_name=data['first_name'],
            last_name=data['last_name'],
            email=data['email'],
            phone=data['phone'],
            country=country,
            address=data['address'],
            birth_date=data['birth_date'],
            currency=currency,
            balance=Decimal(str(data.get('balance', '0.00'))),
            status=status,
            block_reason=block_reason,
            unblock_fee=unblock_fee,
            manager_name=data['manager_name'],
        )

        AuditLog.objects.create(
            bank=bank,
            account=account,
            action=AuditLog.ACTION_ACCOUNT_CREATED,
            actor=actor,
            description=f"Compte créé pour {account.get_full_name()} — {account_id} ({account.get_account_type_display()})",
            extra_data={'country': country, 'currency': currency, 'status': status, 'account_type': account_type},
        )

        if status == BankAccount.STATUS_BLOCKED:
            Notification.objects.create(
                account=account,
                title="Compte créé — En attente de déblocage",
                message=f"Votre compte a été créé mais est actuellement bloqué. Motif : {block_reason}",
                notification_type=Notification.TYPE_WARNING,
            )
        else:
            Notification.objects.create(
                account=account,
                title=f"Bienvenue chez {bank.name}",
                message=f"Votre {account.get_account_type_display().lower()} est ouvert et opérationnel.",
                notification_type=Notification.TYPE_SUCCESS,
            )

        logger.info(f"Compte créé: {account_id} ({account_type}) | Banque: {bank.name} | Acteur: {actor}")
        return account, plain_pwd

    @staticmethod
    @db_transaction.atomic
    def set_account_status(account, new_status: str, block_reason: str = '', unblock_fee=None, actor: str = 'admin'):
        """Bloque ou débloque un compte avec audit trail complet."""
        from .models import AuditLog, BankAccount
        from notifications.models import Notification

        old_status = account.status

        if new_status == BankAccount.STATUS_BLOCKED and not block_reason:
            raise ValidationError("Un motif de blocage est obligatoire.")

        account.status = new_status
        if new_status == BankAccount.STATUS_BLOCKED:
            account.block_reason = block_reason
            account.unblock_fee = unblock_fee
        else:
            account.block_reason = ''
            account.unblock_fee = None

        account.save(update_fields=['status', 'block_reason', 'unblock_fee', 'updated_at'])

        action = AuditLog.ACTION_ACCOUNT_BLOCKED if new_status == BankAccount.STATUS_BLOCKED else AuditLog.ACTION_ACCOUNT_UNBLOCKED
        AuditLog.objects.create(
            bank=account.bank,
            account=account,
            action=action,
            actor=actor,
            description=f"Statut changé de {old_status} → {new_status}" + (f" | Motif: {block_reason}" if block_reason else ""),
        )

        if new_status == BankAccount.STATUS_BLOCKED:
            Notification.objects.create(
                account=account,
                title="Votre compte a été bloqué",
                message=f"Motif : {block_reason}" + (f" | Frais de déblocage : {unblock_fee} {account.currency}" if unblock_fee else ""),
                notification_type=Notification.TYPE_DANGER,
            )
            try:
                from .utils import send_account_blocked_email
                send_account_blocked_email(account)
            except Exception as e:
                logger.warning(f"Email blocage non envoyé pour {account.account_id}: {e}")
        else:
            Notification.objects.create(
                account=account,
                title="Votre compte a été débloqué",
                message="Votre compte est à nouveau pleinement opérationnel.",
                notification_type=Notification.TYPE_SUCCESS,
            )
            try:
                from .utils import send_account_unblocked_email
                send_account_unblocked_email(account)
            except Exception as e:
                logger.warning(f"Email déblocage non envoyé pour {account.account_id}: {e}")

        logger.info(f"Statut compte {account.account_id}: {old_status} → {new_status} | Acteur: {actor}")


# ── TransferService ────────────────────────────────────────────────────────

class TransferService:

    @staticmethod
    @db_transaction.atomic
    def initiate_transfer(account, beneficiary, amount: Decimal, description: str, actor: str) -> 'Transaction':
        """
        Initie un virement sortant.
        Utilise select_for_update() pour éviter la double-dépense en cas de concurrence.
        """
        from transactions.models import Transaction
        from .models import AuditLog, BankAccount
        from notifications.models import Notification

        if not isinstance(amount, Decimal):
            amount = Decimal(str(amount))

        amount = amount.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

        if amount <= Decimal('0.00'):
            raise ValidationError("Le montant doit être strictement positif.")

        # Verrouillage ligne pour éviter concurrence
        locked_account = BankAccount.objects.select_for_update().get(pk=account.pk)

        if locked_account.is_blocked:
            raise ValidationError("Ce compte est bloqué. Impossible d'initier un virement.")

        if locked_account.balance < amount:
            raise ValidationError(
                f"Solde insuffisant. Disponible : {locked_account.balance} {locked_account.currency}, "
                f"demandé : {amount} {locked_account.currency}."
            )

        # Déduire immédiatement (réservation)
        locked_account.balance -= amount
        locked_account.save(update_fields=['balance', 'updated_at'])

        txn = Transaction.objects.create(
            account=locked_account,
            transaction_type=Transaction.TYPE_TRANSFER_OUT,
            amount=amount,
            currency=locked_account.currency,
            description=description,
            status=Transaction.STATUS_PENDING,
            beneficiary=beneficiary,
            beneficiary_name=beneficiary.get_full_name(),
            beneficiary_iban=beneficiary.account_number,
            beneficiary_email=beneficiary.email,
            beneficiary_bank=beneficiary.bank_name,
        )

        AuditLog.objects.create(
            bank=locked_account.bank,
            account=locked_account,
            action=AuditLog.ACTION_TRANSFER_CREATED,
            actor=actor,
            description=f"Virement {txn.reference} initié : {amount} {locked_account.currency} → {beneficiary.get_full_name()}",
            extra_data={
                'reference': txn.reference,
                'amount': str(amount),
                'currency': locked_account.currency,
                'beneficiary': beneficiary.get_full_name(),
                'beneficiary_iban': beneficiary.account_number,
            },
        )

        Notification.objects.create(
            account=locked_account,
            title=f"Virement initié — {txn.reference}",
            message=f"Virement de {amount} {locked_account.currency} vers {beneficiary.get_full_name()} en cours de validation.",
            notification_type=Notification.TYPE_INFO,
        )

        logger.info(f"Virement initié: {txn.reference} | {amount} {locked_account.currency} | Acteur: {actor}")
        return txn

    @staticmethod
    @db_transaction.atomic
    def validate_transfer(transaction, actor: str = 'admin'):
        """Valide un virement en attente."""
        from transactions.models import Transaction
        from .models import AuditLog
        from notifications.models import Notification

        locked_txn = Transaction.objects.select_for_update().get(pk=transaction.pk)

        if locked_txn.status != Transaction.STATUS_PENDING:
            raise ValidationError(f"Ce virement ne peut pas être validé (statut actuel : {locked_txn.status}).")

        locked_txn.status = Transaction.STATUS_VALIDATED
        locked_txn.validated_at = timezone.now()
        locked_txn.save(update_fields=['status', 'validated_at'])

        AuditLog.objects.create(
            bank=locked_txn.account.bank,
            account=locked_txn.account,
            action=AuditLog.ACTION_TRANSFER_VALIDATED,
            actor=actor,
            description=f"Virement {locked_txn.reference} validé.",
            extra_data={'reference': locked_txn.reference, 'amount': str(locked_txn.amount)},
        )

        Notification.objects.create(
            account=locked_txn.account,
            title=f"Virement {locked_txn.reference} validé",
            message=f"Votre virement de {locked_txn.amount} {locked_txn.currency} vers {locked_txn.get_beneficiary_display_name()} a été validé.",
            notification_type=Notification.TYPE_SUCCESS,
        )

        logger.info(f"Virement validé: {locked_txn.reference} | Acteur: {actor}")
        return locked_txn

    @staticmethod
    @db_transaction.atomic
    def reject_transfer(transaction, rejection_reason: str, rejection_fee: Decimal = None, actor: str = 'admin'):
        """
        Rejette un virement et rembourse le solde.
        Les frais de redirection NE sont PAS déduits du solde.
        """
        from transactions.models import Transaction
        from .models import AuditLog, BankAccount
        from notifications.models import Notification

        if not rejection_reason or not rejection_reason.strip():
            raise ValidationError("Un motif de rejet est obligatoire.")

        locked_txn = Transaction.objects.select_for_update().get(pk=transaction.pk)

        if locked_txn.status != Transaction.STATUS_PENDING:
            raise ValidationError(f"Ce virement ne peut pas être rejeté (statut actuel : {locked_txn.status}).")

        locked_txn.status = Transaction.STATUS_REJECTED
        locked_txn.rejection_reason = rejection_reason.strip()
        locked_txn.rejection_fee = rejection_fee
        locked_txn.validated_at = timezone.now()
        locked_txn.save(update_fields=['status', 'rejection_reason', 'rejection_fee', 'validated_at'])

        # Rembourser le solde uniquement pour les débits
        if locked_txn.is_debit:
            locked_account = BankAccount.objects.select_for_update().get(pk=locked_txn.account.pk)
            locked_account.balance += locked_txn.amount
            locked_account.save(update_fields=['balance', 'updated_at'])

        AuditLog.objects.create(
            bank=locked_txn.account.bank,
            account=locked_txn.account,
            action=AuditLog.ACTION_TRANSFER_REJECTED,
            actor=actor,
            description=f"Virement {locked_txn.reference} rejeté. Motif: {rejection_reason}",
            extra_data={
                'reference': locked_txn.reference,
                'amount': str(locked_txn.amount),
                'rejection_reason': rejection_reason,
                'rejection_fee': str(rejection_fee) if rejection_fee else None,
            },
        )

        Notification.objects.create(
            account=locked_txn.account,
            title=f"Virement {locked_txn.reference} rejeté",
            message=f"Votre virement de {locked_txn.amount} {locked_txn.currency} a été rejeté. Motif : {rejection_reason}",
            notification_type=Notification.TYPE_DANGER,
        )

        logger.info(f"Virement rejeté: {locked_txn.reference} | Motif: {rejection_reason} | Acteur: {actor}")
        return locked_txn

    @staticmethod
    @db_transaction.atomic
    def create_manual_movement(account, movement_type: str, amount: Decimal, description: str, actor: str, extra: dict = None):
        """
        Enregistre un mouvement manuel (admin) : dépôt, retrait, virement entrant, paiement.
        """
        from transactions.models import Transaction
        from .models import AuditLog, BankAccount
        from notifications.models import Notification

        if not isinstance(amount, Decimal):
            amount = Decimal(str(amount))
        amount = amount.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

        if amount <= Decimal('0.00'):
            raise ValidationError("Le montant doit être strictement positif.")

        locked_account = BankAccount.objects.select_for_update().get(pk=account.pk)

        DEBIT_TYPES = [Transaction.TYPE_TRANSFER_OUT, Transaction.TYPE_WITHDRAWAL, Transaction.TYPE_PAYMENT]
        is_debit = movement_type in DEBIT_TYPES

        if is_debit and locked_account.balance < amount:
            raise ValidationError(
                f"Solde insuffisant pour ce mouvement. Disponible : {locked_account.balance} {locked_account.currency}."
            )

        txn = Transaction.objects.create(
            account=locked_account,
            transaction_type=movement_type,
            amount=amount,
            currency=locked_account.currency,
            description=description,
            status=Transaction.STATUS_VALIDATED,
            beneficiary_name=(extra or {}).get('beneficiary_name', ''),
            beneficiary_iban=(extra or {}).get('beneficiary_iban', ''),
            beneficiary_email=(extra or {}).get('beneficiary_email', ''),
            beneficiary_bank=(extra or {}).get('beneficiary_bank', ''),
        )

        if is_debit:
            locked_account.balance -= amount
        else:
            locked_account.balance += amount
        locked_account.save(update_fields=['balance', 'updated_at'])

        AuditLog.objects.create(
            bank=locked_account.bank,
            account=locked_account,
            action=AuditLog.ACTION_BALANCE_UPDATED,
            actor=actor,
            description=f"Mouvement manuel {txn.get_transaction_type_display()} : {'−' if is_debit else '+'}{amount} {locked_account.currency}",
            extra_data={'reference': txn.reference, 'amount': str(amount), 'type': movement_type},
        )

        Notification.objects.create(
            account=locked_account,
            title=f"Nouveau mouvement — {txn.get_transaction_type_display()}",
            message=f"{'Débit' if is_debit else 'Crédit'} de {amount} {locked_account.currency} sur votre compte.",
            notification_type=Notification.TYPE_INFO,
        )

        logger.info(f"Mouvement manuel: {txn.reference} | {movement_type} | {amount} | Acteur: {actor}")
        return txn
