"""
Middleware anti brute-force : bloque une IP après N tentatives échouées en M minutes.
"""
from django.utils import timezone
from django.http import HttpResponseForbidden
from datetime import timedelta


MAX_ATTEMPTS = 10
WINDOW_MINUTES = 15


def get_client_ip(request):
    x_forwarded = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded:
        return x_forwarded.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR', '0.0.0.0')


def is_ip_locked(ip: str) -> bool:
    from accounts.models import LoginAttempt
    window_start = timezone.now() - timedelta(minutes=WINDOW_MINUTES)
    count = LoginAttempt.objects.filter(
        ip_address=ip,
        success=False,
        created_at__gte=window_start,
    ).count()
    return count >= MAX_ATTEMPTS


def record_attempt(account_id: str, ip: str, bank_slug: str, success: bool):
    from accounts.models import LoginAttempt
    LoginAttempt.objects.create(
        account_id=account_id,
        ip_address=ip,
        bank_slug=bank_slug,
        success=success,
    )
