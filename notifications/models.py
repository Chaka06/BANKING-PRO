from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from accounts.models import BankAccount


class Notification(models.Model):
    TYPE_INFO = 'info'
    TYPE_SUCCESS = 'success'
    TYPE_WARNING = 'warning'
    TYPE_DANGER = 'danger'

    TYPE_CHOICES = [
        (TYPE_INFO, _('Information')),
        (TYPE_SUCCESS, _('Succès')),
        (TYPE_WARNING, _('Avertissement')),
        (TYPE_DANGER, _('Alerte')),
    ]

    account = models.ForeignKey(BankAccount, on_delete=models.CASCADE, related_name='notifications', verbose_name="Compte")
    title = models.CharField(max_length=200, verbose_name="Titre")
    message = models.TextField(verbose_name="Message")
    notification_type = models.CharField(max_length=10, choices=TYPE_CHOICES, default=TYPE_INFO, verbose_name="Type")
    is_read = models.BooleanField(default=False, verbose_name="Lu")
    # default=timezone.now (et non auto_now_add) : permet à AccountService.create_account
    # de faire correspondre la date de la notification de bienvenue à la date de création
    # du compte choisie par l'admin, au lieu de toujours prendre l'heure réelle d'envoi.
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        verbose_name = "Notification"
        verbose_name_plural = "Notifications"
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.account} — {self.title}"
