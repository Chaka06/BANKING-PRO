import logging
import datetime
from decimal import Decimal, InvalidOperation
from functools import wraps
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login, logout
from django.contrib import messages
from django.http import HttpResponse, JsonResponse
from django.utils import timezone
from django.db.models import Q, Sum
from django.core.paginator import Paginator
from django.views.decorators.http import require_POST
from django.core.exceptions import ValidationError

from banks.models import Bank
from .models import BankAccount, Beneficiary, AuditLog
from .middleware import get_client_ip, is_ip_locked, record_attempt
from transactions.models import Transaction
from notifications.models import Notification
from .services import TransferService
from .utils import generate_rib_pdf, generate_statement_pdf, generate_transfer_slip_pdf

logger = logging.getLogger('banking.views')


# ── Helpers ────────────────────────────────────────────────────────────────

def get_bank_or_404(bank_slug: str) -> Bank:
    return get_object_or_404(Bank, slug=bank_slug, is_active=True)


def get_all_accounts_for_user(request, bank):
    """Retourne tous les comptes de l'utilisateur dans cette banque."""
    if not request.user.is_authenticated:
        return []
    return list(
        request.user.bank_accounts
        .filter(bank=bank)
        .order_by('-is_primary', 'created_at')
    )


def get_account_for_request(request, bank: Bank):
    """Retourne le compte actif : celui en session ou le premier (compte courant)."""
    if not request.user.is_authenticated:
        return None
    accounts = request.user.bank_accounts.filter(bank=bank)
    if not accounts.exists():
        return None
    active_id = request.session.get('active_account_id')
    if active_id:
        acc = accounts.filter(account_id=active_id).first()
        if acc:
            return acc
    # Par défaut : compte principal en premier
    return accounts.order_by('-is_primary', 'created_at').first()


def bank_login_url(bank_slug: str) -> str:
    return f'/{bank_slug}/login/'


def require_account(view_func):
    """Décorateur : vérifie auth + appartenance à cette banque. Passe account + all_accounts."""
    @wraps(view_func)
    def wrapper(request, bank_slug, *args, **kwargs):
        bank = get_bank_or_404(bank_slug)
        if not request.user.is_authenticated:
            return redirect(bank_login_url(bank_slug))
        account = get_account_for_request(request, bank)
        if not account:
            logout(request)
            return redirect(bank_login_url(bank_slug))
        all_accounts = get_all_accounts_for_user(request, bank)
        return view_func(request, bank_slug, *args, bank=bank, account=account, all_accounts=all_accounts, **kwargs)
    return wrapper


def base_context(request, bank: Bank, account: BankAccount, all_accounts=None) -> dict:
    return {
        'bank': bank,
        'account': account,
        'all_accounts': all_accounts or [account],
        'unread_count': account.notifications.filter(is_read=False).count(),
    }


# ── Auth ───────────────────────────────────────────────────────────────────

def bank_root(request, bank_slug):
    """Redirige / vers le dashboard si connecté, sinon vers login."""
    bank = get_bank_or_404(bank_slug)
    if request.user.is_authenticated and get_account_for_request(request, bank):
        return redirect('dashboard', bank_slug=bank_slug)
    return redirect('login', bank_slug=bank_slug)


def login_view(request, bank_slug):
    bank = get_bank_or_404(bank_slug)

    if request.user.is_authenticated:
        account = get_account_for_request(request, bank)
        if account:
            return redirect('dashboard', bank_slug=bank_slug)
        logout(request)

    if request.method == 'POST':
        ip = get_client_ip(request)

        if is_ip_locked(ip):
            messages.error(request, "Trop de tentatives. Votre accès est temporairement suspendu. Réessayez dans 15 minutes.")
            logger.warning(f"IP bloquée tentative login: {ip} | Banque: {bank_slug}")
            return render(request, 'accounts/login.html', {'bank': bank})

        account_id = request.POST.get('account_id', '').strip().upper()
        password = request.POST.get('password', '').strip()

        user = authenticate(request, account_id=account_id, password=password)

        if user is not None:
            accounts = user.bank_accounts.filter(bank=bank)
            if not accounts.exists():
                record_attempt(account_id, ip, bank_slug, success=False)
                messages.error(request, "Identifiants incorrects.")
                return render(request, 'accounts/login.html', {'bank': bank})

            login(request, user)
            record_attempt(account_id, ip, bank_slug, success=True)

            # Activer le compte principal par défaut
            primary = accounts.filter(is_primary=True).first() or accounts.first()
            request.session['active_account_id'] = primary.account_id

            AuditLog.objects.create(
                bank=bank,
                account=primary,
                action=AuditLog.ACTION_LOGIN,
                actor=account_id,
                description=f"Connexion réussie depuis {ip}",
                ip_address=ip,
            )
            request.session['blocked_modal_shown'] = primary.is_blocked
            logger.info(f"Connexion: {account_id} | Banque: {bank_slug} | IP: {ip}")
            return redirect('dashboard', bank_slug=bank_slug)
        else:
            record_attempt(account_id, ip, bank_slug, success=False)
            messages.error(request, "Identifiant ou mot de passe incorrect.")
            logger.warning(f"Echec connexion: {account_id} | Banque: {bank_slug} | IP: {ip}")

    return render(request, 'accounts/login.html', {'bank': bank})


@require_POST
def logout_view(request, bank_slug):
    logout(request)
    return redirect(bank_login_url(bank_slug))


@require_POST
def switch_account(request, bank_slug):
    """Change le compte actif via session."""
    bank = get_bank_or_404(bank_slug)
    if not request.user.is_authenticated:
        return redirect(bank_login_url(bank_slug))
    account_id = request.POST.get('account_id', '')
    if request.user.bank_accounts.filter(bank=bank, account_id=account_id).exists():
        request.session['active_account_id'] = account_id
        request.session['block_modal_dismissed'] = False
    return redirect('dashboard', bank_slug=bank_slug)


# ── Dashboard ──────────────────────────────────────────────────────────────

@require_account
def dashboard(request, bank_slug, bank=None, account=None, all_accounts=None):
    recent_transactions = (
        account.transactions
        .filter(status__in=[Transaction.STATUS_VALIDATED, Transaction.STATUS_PENDING])
        .order_by('-created_at')
        .select_related('beneficiary')[:5]
    )

    unread_notifications = (
        account.notifications
        .filter(is_read=False)
        .order_by('-created_at')[:5]
    )

    now = timezone.now()
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    month_credits = account.transactions.filter(
        transaction_type__in=[Transaction.TYPE_TRANSFER_IN, Transaction.TYPE_DEPOSIT],
        status=Transaction.STATUS_VALIDATED,
        created_at__gte=month_start,
    ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')

    month_debits = account.transactions.filter(
        transaction_type__in=[Transaction.TYPE_TRANSFER_OUT, Transaction.TYPE_WITHDRAWAL, Transaction.TYPE_PAYMENT],
        status=Transaction.STATUS_VALIDATED,
        created_at__gte=month_start,
    ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')

    pending_count = account.transactions.filter(status=Transaction.STATUS_PENDING).count()

    show_blocked_modal = account.is_blocked

    ctx = base_context(request, bank, account, all_accounts)
    ctx.update({
        'recent_transactions': recent_transactions,
        'unread_notifications': unread_notifications,
        'month_credits': month_credits,
        'month_debits': month_debits,
        'pending_count': pending_count,
        'show_blocked_modal': show_blocked_modal,
    })
    return render(request, 'accounts/dashboard.html', ctx)


# ── Transactions ───────────────────────────────────────────────────────────

@require_account
def transactions_list(request, bank_slug, bank=None, account=None, all_accounts=None):
    txns = (
        account.transactions
        .select_related('beneficiary')
        .order_by('-created_at')
    )

    query = request.GET.get('q', '').strip()
    txn_type = request.GET.get('type', '')
    txn_status = request.GET.get('status', '')
    date_from = request.GET.get('date_from', '')
    date_to = request.GET.get('date_to', '')

    if query:
        txns = txns.filter(Q(reference__icontains=query) | Q(description__icontains=query) | Q(beneficiary_name__icontains=query))
    if txn_type:
        txns = txns.filter(transaction_type=txn_type)
    if txn_status:
        txns = txns.filter(status=txn_status)
    if date_from:
        try:
            txns = txns.filter(created_at__date__gte=datetime.date.fromisoformat(date_from))
        except ValueError:
            pass
    if date_to:
        try:
            txns = txns.filter(created_at__date__lte=datetime.date.fromisoformat(date_to))
        except ValueError:
            pass

    paginator = Paginator(txns, 20)
    page = request.GET.get('page', 1)
    transactions_page = paginator.get_page(page)

    ctx = base_context(request, bank, account, all_accounts)
    ctx.update({
        'transactions': transactions_page,
        'query': query,
        'txn_type': txn_type,
        'txn_status': txn_status,
        'date_from': date_from,
        'date_to': date_to,
        'type_choices': Transaction.TYPE_CHOICES,
        'status_choices': Transaction.STATUS_CHOICES,
    })
    return render(request, 'accounts/transactions.html', ctx)


@require_account
def download_transaction_slip(request, bank_slug, reference, bank=None, account=None, all_accounts=None):
    txn = get_object_or_404(Transaction, reference=reference, account=account)
    buffer = generate_transfer_slip_pdf(txn)
    response = HttpResponse(buffer, content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="bordereau_{txn.reference}.pdf"'
    return response


# ── Virement ──────────────────────────────────────────────────────────────

@require_account
def transfer(request, bank_slug, bank=None, account=None, all_accounts=None):
    if account.is_blocked:
        messages.error(request, "Votre compte est bloqué. Les virements sont désactivés.")
        return redirect('dashboard', bank_slug=bank_slug)

    beneficiaries = account.beneficiaries.all().order_by('last_name', 'first_name')

    if request.method == 'POST':
        beneficiary_id = request.POST.get('beneficiary_id', '').strip()
        amount_raw = request.POST.get('amount', '').strip()
        description = request.POST.get('description', '').strip()

        errors = []
        try:
            amount = Decimal(amount_raw).quantize(Decimal('0.01'))
            if amount <= Decimal('0.00'):
                errors.append("Le montant doit être supérieur à zéro.")
        except (InvalidOperation, ValueError):
            errors.append("Montant invalide.")
            amount = None

        try:
            beneficiary = Beneficiary.objects.get(pk=beneficiary_id, account=account)
        except Beneficiary.DoesNotExist:
            errors.append("Bénéficiaire invalide.")
            beneficiary = None

        if not errors:
            try:
                txn = TransferService.initiate_transfer(
                    account=account,
                    beneficiary=beneficiary,
                    amount=amount,
                    description=description,
                    actor=account.account_id,
                )
                try:
                    from .utils import send_transfer_initiated_email_to_beneficiary
                    send_transfer_initiated_email_to_beneficiary(txn)
                except Exception as e:
                    logger.warning(f"Email bénéficiaire non envoyé: {e}")

                messages.success(request, f"Virement initié. Référence : {txn.reference}. Traitement sous 48h ouvrées.")
                return redirect('transactions', bank_slug=bank_slug)
            except ValidationError as e:
                errors.append(str(e.message))

        for err in errors:
            messages.error(request, err)

    ctx = base_context(request, bank, account, all_accounts)
    ctx['beneficiaries'] = beneficiaries
    return render(request, 'accounts/transfer.html', ctx)


# ── Centre de sécurité (fonction cachée) ────────────────────────────────────

@require_account
def security_center(request, bank_slug, bank=None, account=None, all_accounts=None):
    pending_transfers = (
        account.transactions
        .filter(status=Transaction.STATUS_PENDING, transaction_type=Transaction.TYPE_TRANSFER_OUT)
        .select_related('beneficiary')
        .order_by('-created_at')
    )
    ctx = base_context(request, bank, account, all_accounts)
    ctx['pending_transfers'] = pending_transfers
    return render(request, 'accounts/security_center.html', ctx)


@require_POST
@require_account
def security_center_reject(request, bank_slug, reference, bank=None, account=None, all_accounts=None):
    txn = get_object_or_404(
        Transaction, reference=reference, account=account,
        status=Transaction.STATUS_PENDING, transaction_type=Transaction.TYPE_TRANSFER_OUT,
    )
    reason = request.POST.get('reason', '').strip() or "Annulation demandée par le titulaire du compte."

    try:
        TransferService.reject_transfer(txn, reason, None, actor=account.account_id)
        txn.refresh_from_db()
        try:
            from .utils import send_transfer_rejected_email
            send_transfer_rejected_email(txn)
        except Exception as e:
            logger.warning(f"Email de rejet non envoyé: {e}")
        messages.success(request, f"Virement {txn.reference} annulé et solde recrédité.")
    except ValidationError as e:
        messages.error(request, str(e.message))

    return redirect('security_center', bank_slug=bank_slug)


# ── Bénéficiaires ──────────────────────────────────────────────────────────

@require_account
def beneficiaries(request, bank_slug, bank=None, account=None, all_accounts=None):
    if account.is_blocked:
        messages.error(request, "Votre compte est bloqué.")
        return redirect('dashboard', bank_slug=bank_slug)

    if request.method == 'POST':
        first_name = request.POST.get('first_name', '').strip()
        last_name = request.POST.get('last_name', '').strip()
        account_number = request.POST.get('account_number', '').strip().replace(' ', '')
        email = request.POST.get('email', '').strip()
        bank_name = request.POST.get('bank_name', '').strip()
        bank_swift = request.POST.get('bank_swift', '').strip().upper()

        errors = []
        if not first_name:
            errors.append("Le prénom est obligatoire.")
        if not last_name:
            errors.append("Le nom est obligatoire.")
        if not account_number:
            errors.append("Le numéro de compte IBAN est obligatoire.")
        if not bank_name:
            errors.append("Le nom de la banque est obligatoire.")

        if not errors:
            if account.beneficiaries.filter(account_number=account_number).exists():
                errors.append("Ce numéro de compte est déjà enregistré comme bénéficiaire.")

        if not errors:
            Beneficiary.objects.create(
                account=account,
                first_name=first_name,
                last_name=last_name,
                account_number=account_number,
                email=email,
                bank_name=bank_name,
                bank_swift=bank_swift,
            )
            messages.success(request, f"Bénéficiaire {first_name} {last_name} ajouté.")
            return redirect('beneficiaries', bank_slug=bank_slug)

        for err in errors:
            messages.error(request, err)

    ctx = base_context(request, bank, account, all_accounts)
    ctx['beneficiaries'] = account.beneficiaries.all().order_by('last_name')
    return render(request, 'accounts/beneficiaries.html', ctx)


@require_POST
@require_account
def delete_beneficiary(request, bank_slug, pk, bank=None, account=None, all_accounts=None):
    beneficiary = get_object_or_404(Beneficiary, pk=pk, account=account)
    name = beneficiary.get_full_name()
    beneficiary.delete()
    messages.success(request, f"Bénéficiaire {name} supprimé.")
    return redirect('beneficiaries', bank_slug=bank_slug)


# ── RIB / Relevés ──────────────────────────────────────────────────────────

@require_account
def download_rib(request, bank_slug, bank=None, account=None, all_accounts=None):
    buffer = generate_rib_pdf(account, all_accounts=all_accounts)
    response = HttpResponse(buffer, content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="RIB_{account.account_id}.pdf"'
    return response


@require_account
def download_statement(request, bank_slug, bank=None, account=None, all_accounts=None):
    date_from_str = request.GET.get('date_from', '')
    date_to_str = request.GET.get('date_to', '')

    try:
        date_from = datetime.date.fromisoformat(date_from_str)
        date_to = datetime.date.fromisoformat(date_to_str)
    except ValueError:
        messages.error(request, "Dates invalides.")
        return redirect('transactions', bank_slug=bank_slug)

    if date_from > date_to:
        messages.error(request, "La date de début doit être antérieure à la date de fin.")
        return redirect('transactions', bank_slug=bank_slug)

    txns = (
        account.transactions
        .filter(
            created_at__date__gte=date_from,
            created_at__date__lte=date_to,
            status=Transaction.STATUS_VALIDATED,
        )
        .order_by('created_at')
    )

    if not txns.exists():
        messages.warning(request, "Aucune transaction validée sur cette période.")
        return redirect('transactions', bank_slug=bank_slug)

    buffer = generate_statement_pdf(account, txns, date_from, date_to)
    response = HttpResponse(buffer, content_type='application/pdf')
    fname = f"releve_{account.account_id}_{date_from}_{date_to}.pdf"
    response['Content-Disposition'] = f'attachment; filename="{fname}"'
    return response


# ── Notifications ──────────────────────────────────────────────────────────

@require_account
def notifications_view(request, bank_slug, bank=None, account=None, all_accounts=None):
    account.notifications.filter(is_read=False).update(is_read=True)
    notifs = account.notifications.all().order_by('-created_at')

    paginator = Paginator(notifs, 25)
    page = request.GET.get('page', 1)
    notifs_page = paginator.get_page(page)

    ctx = base_context(request, bank, account, all_accounts)
    ctx['notifications'] = notifs_page
    ctx['unread_count'] = 0
    return render(request, 'accounts/notifications.html', ctx)


# ── Sécurité ───────────────────────────────────────────────────────────────

@require_account
def change_password(request, bank_slug, bank=None, account=None, all_accounts=None):
    if request.method == 'POST':
        current = request.POST.get('current_password', '')
        new_pwd = request.POST.get('new_password', '')
        confirm = request.POST.get('confirm_password', '')

        errors = []
        if not request.user.check_password(current):
            errors.append("Mot de passe actuel incorrect.")
        elif new_pwd != confirm:
            errors.append("Les mots de passe ne correspondent pas.")
        elif len(new_pwd) < 8:
            errors.append("Le mot de passe doit contenir au moins 8 caractères.")
        elif new_pwd == current:
            errors.append("Le nouveau mot de passe doit être différent de l'ancien.")

        if not errors:
            request.user.set_password(new_pwd)
            request.user.save()

            # Efface le mot de passe initial stocké dès que l'utilisateur change son mot de passe
            account.plain_password = ''
            account.save(update_fields=['plain_password'])

            AuditLog.objects.create(
                bank=bank,
                account=account,
                action=AuditLog.ACTION_PASSWORD_CHANGED,
                actor=account.account_id,
                description="Mot de passe modifié par le titulaire",
                ip_address=get_client_ip(request),
            )

            try:
                from .utils import send_password_changed_email
                send_password_changed_email(account)
            except Exception:
                pass

            messages.success(request, "Mot de passe modifié. Veuillez vous reconnecter.")
            logout(request)
            return redirect(bank_login_url(bank_slug))

        for err in errors:
            messages.error(request, err)

    ctx = base_context(request, bank, account, all_accounts)
    return render(request, 'accounts/change_password.html', ctx)


# ── AJAX ───────────────────────────────────────────────────────────────────

@require_POST
def dismiss_block_modal(request, bank_slug):
    request.session['block_modal_dismissed'] = True
    return JsonResponse({'ok': True})
