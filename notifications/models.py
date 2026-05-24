from django.db import models
from accounts.models import BankAccount


class Notification(models.Model):
    TYPE_INFO = 'info'
    TYPE_SUCCESS = 'success'
    TYPE_WARNING = 'warning'
    TYPE_DANGER = 'danger'

    TYPE_CHOICES = [
        (TYPE_INFO, 'Information'),
        (TYPE_SUCCESS, 'Succès'),
        (TYPE_WARNING, 'Avertissement'),
        (TYPE_DANGER, 'Alerte'),
    ]

    account = models.ForeignKey(BankAccount, on_delete=models.CASCADE, related_name='notifications', verbose_name="Compte")
    title = models.CharField(max_length=200, verbose_name="Titre")
    message = models.TextField(verbose_name="Message")
    notification_type = models.CharField(max_length=10, choices=TYPE_CHOICES, default=TYPE_INFO, verbose_name="Type")
    is_read = models.BooleanField(default=False, verbose_name="Lu")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Notification"
        verbose_name_plural = "Notifications"
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.account} — {self.title}"
