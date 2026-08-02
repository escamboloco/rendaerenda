import secrets
from datetime import date
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from apps.accounts.deletion import AccountDeletionError, delete_user_account
from apps.accounts.models import User
from apps.payments.models import Order
from apps.stores.models import Store


class AccountDeletionTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="buyer@example.com",
            email="buyer@example.com",
            password="Senha-Forte-123!",
            cpf="52998224725",
            birth_date=date(1991, 3, 3),
        )

    def test_delete_account_anonymizes_and_logs_out(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("accounts_pages:delete_account"),
            {"password": "Senha-Forte-123!", "confirm_delete": "EXCLUIR"},
        )
        self.assertRedirects(response, reverse("stores:home"), fetch_redirect_response=False)
        self.user.refresh_from_db()
        self.assertFalse(self.user.is_active)
        self.assertTrue(self.user.is_banned)
        self.assertTrue(self.user.email.startswith("deleted-"))
        self.assertFalse(self.user.has_usable_password())
        # Sessão encerrada
        follow = self.client.get(reverse("accounts_pages:profile_page"))
        self.assertEqual(follow.status_code, 302)

    def test_wrong_password_keeps_account(self):
        with self.assertRaises(AccountDeletionError):
            delete_user_account(self.user, password="errada")
        self.user.refresh_from_db()
        self.assertTrue(self.user.is_active)
        self.assertEqual(self.user.email, "buyer@example.com")

    def test_open_order_blocks_deletion(self):
        seller = User.objects.create_user(
            username="seller@example.com",
            email="seller@example.com",
            password="Senha-Forte-123!",
            cpf="39053344705",
            birth_date=date(1990, 1, 1),
            role=User.Role.SELLER,
        )
        store = Store.objects.create(
            owner=seller,
            slug="loja-teste-delete",
            display_name="Loja",
            status=Store.Status.ACTIVE,
        )
        Order.objects.create(
            buyer=self.user,
            store=store,
            status=Order.Status.PAID,
            items_total=Decimal("50.00"),
            shipping_total=Decimal("0.00"),
            packaging_fee=Decimal("0.00"),
            access_token=secrets.token_urlsafe(32),
        )
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("accounts_pages:delete_account"),
            {"password": "Senha-Forte-123!", "confirm_delete": "EXCLUIR"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "pedidos em andamento")
        self.user.refresh_from_db()
        self.assertTrue(self.user.is_active)
