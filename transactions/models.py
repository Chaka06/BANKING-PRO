import uuid
from django.db import models
from accounts.models import BankAccount, Beneficiary


def generate_reference():
    return f"TXN{uuid.uuid4().hex[:10].upper()}"


class Transaction(models.Model):
    TYPE_TRANSFER_OUT = 'transfer_out'
    TYPE_TRANSFER_IN = 'transfer_in'
    TYPE_WITHDRAWAL = 'withdrawal'
    TYPE_DEPOSIT = 'deposit'
    TYPE_PAYMENT = 'payment'

    TYPE_CHOICES = [
        (TYPE_TRANSFER_OUT, 'Virement sortant'),
        (TYPE_TRANSFER_IN, 'Virement entrant'),
        (TYPE_WITHDRAWAL, 'Retrait au guichet'),
        (TYPE_DEPOSIT, 'Dépôt en banque'),
        (TYPE_PAYMENT, 'Paiement de facture'),
    ]

    STATUS_PENDING = 'pending'
    STATUS_VALIDATED = 'validated'
    STATUS_REJECTED = 'rejected'

    STATUS_CHOICES = [
        (STATUS_PENDING, 'En cours de validation'),
        (STATUS_VALIDATED, 'Validé'),
        (STATUS_REJECTED, 'Rejeté'),
    ]

    account = models.ForeignKey(BankAccount, on_delete=models.PROTECT, related_name='transactions', verbose_name="Compte")
    reference = models.CharField(max_length=20, unique=True, default=generate_reference, verbose_name="Référence")
    transaction_type = models.CharField(max_length=20, choices=TYPE_CHOICES, verbose_name="Type")
    amount = models.DecimalField(max_digits=15, decimal_places=2, verbose_name="Montant")
    currency = models.CharField(max_length=3, verbose_name="Devise")
    description = models.TextField(blank=True, verbose_name="Description / Libellé")
    status = models.CharField(max_length=15, choices=STATUS_CHOICES, default=STATUS_VALIDATED, verbose_name="Statut")

    # Pour les virements sortants avec bénéficiaire enregistré
    beneficiary = models.ForeignKey(Beneficiary, null=True, blank=True, on_delete=models.SET_NULL, verbose_name="Bénéficiaire")

    # Pour les virements manuels (admin)
    beneficiary_name = models.CharField(max_length=200, blank=True, verbose_name="Nom du bénéficiaire (manuel)")
    beneficiary_iban = models.CharField(max_length=34, blank=True, verbose_name="IBAN bénéficiaire (manuel)")
    beneficiary_email = models.EmailField(blank=True, verbose_name="Email bénéficiaire (manuel)")
    beneficiary_bank = models.CharField(max_length=200, blank=True, verbose_name="Banque bénéficiaire (manuel)")

    # Rejet
    rejection_reason = models.TextField(blank=True, verbose_name="Motif du rejet")
    rejection_fee = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, verbose_name="Frais de redirection")

    created_at = models.DateTimeField(auto_now_add=True)
    validated_at = models.DateTimeField(null=True, blank=True, verbose_name="Date de validation/rejet")

    class Meta:
        verbose_name = "Transaction"
        verbose_name_plural = "Transactions"
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['account', 'created_at']),
            models.Index(fields=['account', 'status']),
            models.Index(fields=['status', 'created_at']),
        ]

    def __str__(self):
        return f"{self.reference} — {self.get_transaction_type_display()} {self.amount} {self.currency}"

    @property
    def is_debit(self):
        return self.transaction_type in [self.TYPE_TRANSFER_OUT, self.TYPE_WITHDRAWAL, self.TYPE_PAYMENT]

    @property
    def is_credit(self):
        return self.transaction_type in [self.TYPE_TRANSFER_IN, self.TYPE_DEPOSIT]

    def get_signed_amount(self):
        if self.is_debit:
            return -self.amount
        return self.amount

    def get_beneficiary_display_name(self):
        if self.beneficiary:
            return self.beneficiary.get_full_name()
        return self.beneficiary_name or '—'

    def get_beneficiary_display_email(self):
        if self.beneficiary:
            return self.beneficiary.email
        return self.beneficiary_email or ''
