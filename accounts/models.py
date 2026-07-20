import secrets
import string
from decimal import Decimal
from django.db import models
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from banks.models import Bank
from .constants import COUNTRY_PREFIXES, COUNTRY_CURRENCIES


class BankUserManager(BaseUserManager):
    def create_user(self, account_id, password=None, **extra_fields):
        if not account_id:
            raise ValueError("L'identifiant est obligatoire")
        user = self.model(account_id=account_id, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, account_id, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        return self.create_user(account_id, password, **extra_fields)


class BankUser(AbstractBaseUser, PermissionsMixin):
    account_id = models.CharField(max_length=20, unique=True, verbose_name="Identifiant", db_index=True)
    email = models.EmailField(unique=True, db_index=True)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    date_joined = models.DateTimeField(auto_now_add=True)

    USERNAME_FIELD = 'account_id'
    REQUIRED_FIELDS = ['email']

    objects = BankUserManager()

    class Meta:
        verbose_name = "Utilisateur"
        verbose_name_plural = "Utilisateurs"

    def __str__(self):
        return self.account_id


class BankAccount(models.Model):
    STATUS_ACTIVE = 'active'
    STATUS_BLOCKED = 'blocked'
    STATUS_CHOICES = [
        (STATUS_ACTIVE, 'Compte actif'),
        (STATUS_BLOCKED, 'Compte bloqué'),
    ]

    TYPE_COURANT = 'courant'
    TYPE_EPARGNE = 'epargne'
    ACCOUNT_TYPE_CHOICES = [
        (TYPE_COURANT, 'Compte courant'),
        (TYPE_EPARGNE, 'Compte épargne'),
    ]

    bank = models.ForeignKey(Bank, on_delete=models.PROTECT, related_name='accounts', verbose_name="Banque", db_index=True)
    # ForeignKey (pas OneToOne) : un utilisateur peut avoir plusieurs comptes (courant + épargne)
    user = models.ForeignKey(BankUser, on_delete=models.CASCADE, related_name='bank_accounts', verbose_name="Utilisateur")

    account_type = models.CharField(
        max_length=20, choices=ACCOUNT_TYPE_CHOICES,
        default=TYPE_COURANT, verbose_name="Type de compte",
    )
    is_primary = models.BooleanField(default=True, verbose_name="Compte principal")

    account_id = models.CharField(max_length=20, unique=True, verbose_name="Identifiant du compte", db_index=True)
    rib = models.CharField(max_length=34, unique=True, verbose_name="RIB / IBAN")
    plain_password = models.CharField(max_length=100, blank=True, verbose_name="Mot de passe initial (visible admin uniquement)")

    first_name = models.CharField(max_length=100, verbose_name="Prénom")
    last_name = models.CharField(max_length=100, verbose_name="Nom")
    email = models.EmailField(verbose_name="Adresse email", db_index=True)
    phone = models.CharField(max_length=20, verbose_name="Numéro de téléphone")
    country = models.CharField(max_length=100, verbose_name="Pays")
    address = models.TextField(verbose_name="Adresse géographique")
    birth_date = models.DateField(verbose_name="Date de naissance")

    currency = models.CharField(max_length=3, blank=True, verbose_name="Devise")
    balance = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'), verbose_name="Solde")
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=STATUS_ACTIVE, verbose_name="Statut du compte", db_index=True)

    block_reason = models.TextField(blank=True, verbose_name="Motif du blocage")
    unblock_fee = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, verbose_name="Frais de déblocage")

    manager_name = models.CharField(max_length=200, verbose_name="Nom du gestionnaire")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Compte bancaire"
        verbose_name_plural = "Comptes bancaires"
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['bank', 'status']),
            models.Index(fields=['bank', 'account_id']),
            models.Index(fields=['bank', 'email']),
        ]

    def __str__(self):
        return f"{self.first_name} {self.last_name} — {self.get_account_type_display()} {self.account_id} ({self.bank.name})"

    def get_full_name(self):
        return f"{self.first_name} {self.last_name}"

    @property
    def is_blocked(self):
        return self.status == self.STATUS_BLOCKED

    def get_login_url(self):
        from django.conf import settings
        return f"{settings.SITE_URL}/{self.bank.slug}/login/"

    def get_country_prefix(self):
        return COUNTRY_PREFIXES.get(self.country, 'XX')

    # ── Composants RIB / IBAN ───────────────────────────────────────────────
    # Structure IBAN 27 chars : FR(2) + check(2) + banque(5) + guichet(5) + compte(11) + clé(2)

    @property
    def iban_formatted(self):
        """FR76 3000 6837 52XX XXXX XXXX XXX — groupes de 4."""
        iban = self.rib or ''
        return ' '.join(iban[i:i+4] for i in range(0, len(iban), 4))

    @property
    def rib_code_banque(self):
        return self.rib[4:9] if len(self.rib) >= 9 else ''

    @property
    def rib_code_guichet(self):
        return self.rib[9:14] if len(self.rib) >= 14 else ''

    @property
    def rib_numero_compte(self):
        return self.rib[14:25] if len(self.rib) >= 25 else ''

    @property
    def rib_cle(self):
        return self.rib[25:27] if len(self.rib) >= 27 else ''


class Beneficiary(models.Model):
    account = models.ForeignKey(BankAccount, on_delete=models.CASCADE, related_name='beneficiaries', verbose_name="Compte source")
    first_name = models.CharField(max_length=100, verbose_name="Prénom")
    last_name = models.CharField(max_length=100, verbose_name="Nom")
    account_number = models.CharField(max_length=34, verbose_name="Numéro de compte (IBAN)")
    email = models.EmailField(blank=True, verbose_name="Email du bénéficiaire")
    bank_name = models.CharField(max_length=200, verbose_name="Nom de la banque du bénéficiaire")
    bank_swift = models.CharField(max_length=11, blank=True, verbose_name="SWIFT/BIC de la banque")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Bénéficiaire"
        verbose_name_plural = "Bénéficiaires"
        ordering = ['last_name', 'first_name']
        unique_together = [('account', 'account_number')]

    def __str__(self):
        return f"{self.first_name} {self.last_name} — {self.account_number}"

    def get_full_name(self):
        return f"{self.first_name} {self.last_name}"


class LoginAttempt(models.Model):
    account_id = models.CharField(max_length=20, db_index=True)
    ip_address = models.GenericIPAddressField()
    success = models.BooleanField(default=False)
    bank_slug = models.CharField(max_length=100)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Tentative de connexion"
        verbose_name_plural = "Tentatives de connexion"
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['ip_address', 'created_at']),
            models.Index(fields=['account_id', 'created_at']),
        ]


class AuditLog(models.Model):
    ACTION_ACCOUNT_CREATED = 'account_created'
    ACTION_ACCOUNT_BLOCKED = 'account_blocked'
    ACTION_ACCOUNT_UNBLOCKED = 'account_unblocked'
    ACTION_TRANSFER_CREATED = 'transfer_created'
    ACTION_TRANSFER_VALIDATED = 'transfer_validated'
    ACTION_TRANSFER_REJECTED = 'transfer_rejected'
    ACTION_BALANCE_UPDATED = 'balance_updated'
    ACTION_LOGIN = 'login'
    ACTION_PASSWORD_CHANGED = 'password_changed'

    ACTION_CHOICES = [
        (ACTION_ACCOUNT_CREATED, 'Compte créé'),
        (ACTION_ACCOUNT_BLOCKED, 'Compte bloqué'),
        (ACTION_ACCOUNT_UNBLOCKED, 'Compte débloqué'),
        (ACTION_TRANSFER_CREATED, 'Virement créé'),
        (ACTION_TRANSFER_VALIDATED, 'Virement validé'),
        (ACTION_TRANSFER_REJECTED, 'Virement rejeté'),
        (ACTION_BALANCE_UPDATED, 'Solde mis à jour'),
        (ACTION_LOGIN, 'Connexion'),
        (ACTION_PASSWORD_CHANGED, 'Mot de passe modifié'),
    ]

    bank = models.ForeignKey(Bank, on_delete=models.SET_NULL, related_name='audit_logs', null=True, blank=True)
    account = models.ForeignKey(BankAccount, on_delete=models.SET_NULL, null=True, blank=True, related_name='audit_logs')
    action = models.CharField(max_length=30, choices=ACTION_CHOICES, db_index=True)
    actor = models.CharField(max_length=200, verbose_name="Acteur (admin/client)")
    description = models.TextField()
    extra_data = models.JSONField(default=dict, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Journal d'audit"
        verbose_name_plural = "Journal d'audit"
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['bank', 'created_at']),
            models.Index(fields=['account', 'action']),
        ]

    def __str__(self):
        return f"{self.created_at:%d/%m/%Y %H:%M} — {self.get_action_display()} — {self.actor}"
