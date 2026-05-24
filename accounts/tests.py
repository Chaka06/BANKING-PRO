"""
Tests automatiques — fonctionnalités financières critiques.
"""
from decimal import Decimal
from unittest.mock import patch
from django.test import TestCase, Client
from django.core.exceptions import ValidationError

from banks.models import Bank
from accounts.models import BankUser, BankAccount, Beneficiary
from accounts.services import AccountService, TransferService, generate_account_id, generate_password
from transactions.models import Transaction
from notifications.models import Notification


def make_bank(**kwargs):
    defaults = dict(
        name='Test Bank', slug='testbank', address='1 rue Test', phone='0100000000',
        email='test@bank.com', swift='TSTBFRPP', bank_code='12345',
        color_primary='#1a3a5c', color_secondary='#2ecc71', color_accent='#f39c12',
        color_text_on_primary='#ffffff', color_background='#f8f9fa',
        color_card='#1a3a5c', color_card_text='#ffffff',
    )
    defaults.update(kwargs)
    return Bank.objects.create(**defaults)


def make_account_data(**kwargs):
    defaults = dict(
        first_name='Jean', last_name='Dupont', email='jean@test.com',
        phone='0600000000', country='France', address='1 rue Paris',
        birth_date='1985-01-15', currency='EUR', balance='1000.00',
        status=BankAccount.STATUS_ACTIVE, manager_name='Marie Martin',
    )
    defaults.update(kwargs)
    return defaults


class GeneratorTests(TestCase):

    def test_account_id_format(self):
        aid = generate_account_id('France')
        self.assertTrue(aid.startswith('FR'))
        self.assertEqual(len(aid), 9)

    def test_account_id_unknown_country(self):
        aid = generate_account_id('Inconnu')
        self.assertTrue(aid.startswith('XX'))

    def test_password_strength(self):
        for _ in range(20):
            pwd = generate_password()
            self.assertGreaterEqual(len(pwd), 12)
            self.assertTrue(any(c.isupper() for c in pwd))
            self.assertTrue(any(c.islower() for c in pwd))
            self.assertTrue(any(c.isdigit() for c in pwd))
            self.assertTrue(any(c in '!@#$%&*' for c in pwd))


class AccountServiceTests(TestCase):

    def setUp(self):
        self.bank = make_bank()

    @patch('accounts.utils.send_account_creation_email')
    def test_create_account_success(self, _):
        account, pwd = AccountService.create_account(self.bank, make_account_data())
        self.assertIsNotNone(account.pk)
        self.assertTrue(account.account_id.startswith('FR'))
        self.assertTrue(account.rib.startswith('FR'))
        self.assertEqual(account.balance, Decimal('1000.00'))
        self.assertIsNotNone(account.user)

    @patch('accounts.utils.send_account_creation_email')
    def test_create_account_user_password(self, _):
        account, pwd = AccountService.create_account(self.bank, make_account_data())
        user = BankUser.objects.get(account_id=account.account_id)
        self.assertTrue(user.check_password(pwd))

    @patch('accounts.utils.send_account_creation_email')
    def test_create_blocked_no_reason_raises(self, _):
        with self.assertRaises(ValidationError):
            AccountService.create_account(self.bank, make_account_data(
                status=BankAccount.STATUS_BLOCKED, block_reason=''
            ))

    @patch('accounts.utils.send_account_creation_email')
    def test_create_blocked_with_reason(self, _):
        account, _ = AccountService.create_account(self.bank, make_account_data(
            status=BankAccount.STATUS_BLOCKED, block_reason='Suspicion de fraude'
        ))
        self.assertTrue(account.is_blocked)

    @patch('accounts.utils.send_account_creation_email')
    def test_block_and_unblock(self, _):
        account, _ = AccountService.create_account(self.bank, make_account_data())
        AccountService.set_account_status(account, BankAccount.STATUS_BLOCKED, block_reason='Test')
        account.refresh_from_db()
        self.assertTrue(account.is_blocked)
        AccountService.set_account_status(account, BankAccount.STATUS_ACTIVE)
        account.refresh_from_db()
        self.assertFalse(account.is_blocked)
        self.assertEqual(account.block_reason, '')


class TransferServiceTests(TestCase):

    def setUp(self):
        self.bank = make_bank()
        with patch('accounts.utils.send_account_creation_email'):
            self.account, _ = AccountService.create_account(self.bank, make_account_data(balance='500.00'))
        self.beneficiary = Beneficiary.objects.create(
            account=self.account, first_name='Alice', last_name='Martin',
            account_number='FR7630001007941234567890185', bank_name='BNP Paribas',
        )

    def test_transfer_deducts_balance(self):
        TransferService.initiate_transfer(self.account, self.beneficiary, Decimal('100.00'), 'Test', actor='client')
        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal('400.00'))

    def test_transfer_insufficient_funds_raises(self):
        with self.assertRaises(ValidationError):
            TransferService.initiate_transfer(self.account, self.beneficiary, Decimal('600.00'), '', actor='client')

    def test_transfer_zero_raises(self):
        with self.assertRaises(ValidationError):
            TransferService.initiate_transfer(self.account, self.beneficiary, Decimal('0.00'), '', actor='client')

    def test_validate_keeps_balance(self):
        txn = TransferService.initiate_transfer(self.account, self.beneficiary, Decimal('100.00'), '', actor='client')
        TransferService.validate_transfer(txn, actor='admin')
        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal('400.00'))

    def test_reject_restores_balance(self):
        txn = TransferService.initiate_transfer(self.account, self.beneficiary, Decimal('100.00'), '', actor='client')
        TransferService.reject_transfer(txn, 'Documents manquants', actor='admin')
        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal('500.00'))

    def test_reject_without_reason_raises(self):
        txn = TransferService.initiate_transfer(self.account, self.beneficiary, Decimal('100.00'), '', actor='client')
        with self.assertRaises(ValidationError):
            TransferService.reject_transfer(txn, '', actor='admin')

    def test_double_validate_raises(self):
        txn = TransferService.initiate_transfer(self.account, self.beneficiary, Decimal('50.00'), '', actor='client')
        TransferService.validate_transfer(txn, actor='admin')
        with self.assertRaises(ValidationError):
            TransferService.validate_transfer(txn, actor='admin')

    def test_double_reject_raises(self):
        txn = TransferService.initiate_transfer(self.account, self.beneficiary, Decimal('50.00'), '', actor='client')
        TransferService.reject_transfer(txn, 'Motif A', actor='admin')
        with self.assertRaises(ValidationError):
            TransferService.reject_transfer(txn, 'Motif B', actor='admin')

    def test_blocked_account_cannot_transfer(self):
        AccountService.set_account_status(self.account, BankAccount.STATUS_BLOCKED, block_reason='Test')
        with self.assertRaises(ValidationError):
            TransferService.initiate_transfer(self.account, self.beneficiary, Decimal('100.00'), '', actor='client')

    def test_transfer_creates_pending_status(self):
        txn = TransferService.initiate_transfer(self.account, self.beneficiary, Decimal('50.00'), '', actor='client')
        self.assertEqual(txn.status, Transaction.STATUS_PENDING)

    def test_transfer_creates_notification(self):
        TransferService.initiate_transfer(self.account, self.beneficiary, Decimal('50.00'), '', actor='client')
        self.assertTrue(self.account.notifications.filter(notification_type=Notification.TYPE_INFO).exists())


class LoginViewTests(TestCase):

    def setUp(self):
        self.bank = make_bank()
        with patch('accounts.utils.send_account_creation_email'):
            self.account, self.pwd = AccountService.create_account(self.bank, make_account_data())
        self.client = Client()

    def test_login_page_loads(self):
        r = self.client.get('/testbank/login/')
        self.assertEqual(r.status_code, 200)

    def test_login_success_redirects(self):
        r = self.client.post('/testbank/login/', {
            'account_id': self.account.account_id,
            'password': self.pwd,
        })
        self.assertRedirects(r, '/testbank/dashboard/')

    def test_login_wrong_password(self):
        r = self.client.post('/testbank/login/', {
            'account_id': self.account.account_id,
            'password': 'wrongpassword123!',
        })
        self.assertEqual(r.status_code, 200)

    def test_login_wrong_bank_denied(self):
        bank2 = make_bank(name='Other Bank', slug='otherbank', email='other@bank.com',
                          swift='OTHBFRPP', bank_code='99999')
        r = self.client.post('/otherbank/login/', {
            'account_id': self.account.account_id,
            'password': self.pwd,
        })
        self.assertEqual(r.status_code, 200)

    def test_dashboard_requires_auth(self):
        r = self.client.get('/testbank/dashboard/')
        self.assertRedirects(r, '/testbank/login/')
