from datetime import date
from decimal import Decimal
from io import BytesIO
from unittest.mock import patch

from django.contrib.contenttypes.models import ContentType
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from PIL import Image

from apps.accounts.models import SellerKYC, User
from apps.catalog.models import Category, Product
from apps.moderation.models import ModerationQueueItem
from apps.stores.models import Store


def _jpeg(name: str = "doc.jpg") -> SimpleUploadedFile:
    buffer = BytesIO()
    Image.new("RGB", (40, 40), color=(200, 120, 80)).save(buffer, format="JPEG")
    return SimpleUploadedFile(name, buffer.getvalue(), content_type="image/jpeg")


@override_settings(
    USE_LOCMEM_CACHE=True,
    RATELIMIT_ENABLE=True,
)
class BackofficeTests(TestCase):
    def setUp(self):
        cache.clear()
        self.staff = User.objects.create_user(
            username="admin@example.com",
            email="admin@example.com",
            password="Senha-Forte-123!",
            cpf="12345678901",
            birth_date=date(1990, 1, 1),
            is_staff=True,
        )
        self.regular = User.objects.create_user(
            username="buyer@example.com",
            email="buyer@example.com",
            password="Senha-Forte-123!",
            cpf="10987654321",
            birth_date=date(1990, 1, 1),
        )

    def test_protected_page_uses_dedicated_login(self):
        response = self.client.get(reverse("backoffice:dashboard"))
        self.assertRedirects(
            response,
            f"{reverse('backoffice:login')}?next={reverse('backoffice:dashboard')}",
        )

    def test_staff_can_login_and_logout_is_post_only(self):
        response = self.client.post(
            reverse("backoffice:login"),
            {"email": self.staff.email, "password": "Senha-Forte-123!"},
        )
        self.assertRedirects(response, reverse("backoffice:dashboard"))
        self.assertEqual(self.client.get(reverse("backoffice:logout")).status_code, 405)
        self.assertRedirects(
            self.client.post(reverse("backoffice:logout")),
            reverse("backoffice:login"),
        )

    def test_login_page_keeps_referrer_for_csrf(self):
        response = self.client.get(reverse("backoffice:login"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Referrer-Policy"], "same-origin")
        self.assertNotContains(response, 'content="no-referrer"')
        self.assertContains(response, "csrfmiddlewaretoken")

    def test_login_error_does_not_enumerate_staff_accounts(self):
        responses = []
        for email in ("missing@example.com", self.regular.email, self.staff.email):
            cache.clear()
            response = self.client.post(
                reverse("backoffice:login"),
                {"email": email, "password": "senha-incorreta"},
            )
            responses.append(response.content.count("E-mail ou senha inválidos".encode()))
        self.assertEqual(responses, [1, 1, 1])

    def test_external_next_is_rejected(self):
        response = self.client.post(
            reverse("backoffice:login") + "?next=https://evil.example/",
            {"email": self.staff.email, "password": "Senha-Forte-123!"},
        )
        self.assertRedirects(response, reverse("backoffice:dashboard"))

    def test_login_rate_limit_blocks_valid_credentials_after_five_attempts(self):
        for _ in range(5):
            self.client.post(
                reverse("backoffice:login"),
                {"email": self.staff.email, "password": "senha-incorreta"},
            )
        response = self.client.post(
            reverse("backoffice:login"),
            {"email": self.staff.email, "password": "Senha-Forte-123!"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.wsgi_request.user.is_authenticated)
        self.assertContains(response, "E-mail ou senha inválidos.")

    def test_non_staff_receives_forbidden(self):
        self.client.force_login(self.regular)
        self.assertEqual(
            self.client.get(reverse("backoffice:dashboard")).status_code,
            403,
        )

    def test_store_list_prioritizes_best_rated(self):
        best = Store.objects.create(
            owner=self.regular,
            slug="melhor",
            display_name="Melhor",
            status=Store.Status.ACTIVE,
            bayesian_rating=Decimal("4.80"),
            review_count=20,
        )
        second_owner = User.objects.create_user(
            username="second@example.com",
            email="second@example.com",
            password="Senha-Forte-123!",
            cpf="11122233344",
            birth_date=date(1990, 1, 1),
        )
        Store.objects.create(
            owner=second_owner,
            slug="segunda",
            display_name="Segunda",
            status=Store.Status.ACTIVE,
            bayesian_rating=Decimal("4.10"),
            review_count=30,
        )
        self.client.force_login(self.staff)
        response = self.client.get(reverse("backoffice:stores"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(list(response.context["stores"])[0], best)

    def test_approve_publishes_product_and_reject_hides_store(self):
        store = Store.objects.create(
            owner=self.regular,
            slug="pendente",
            display_name="Pendente",
            status=Store.Status.PENDING_MODERATION,
        )
        category = Category.objects.create(name="Teste", slug="teste")
        product = Product.objects.create(
            store=store,
            category=category,
            title="Produto",
            slug="produto",
            description="Descrição segura",
            payout_amount=Decimal("10.00"),
            price=Decimal("10.00"),
            status=Product.Status.PENDING_MODERATION,
        )
        product_item = ModerationQueueItem.objects.create(
            target_type=ModerationQueueItem.TargetType.PRODUCT,
            content_type=ContentType.objects.get_for_model(Product),
            object_id=str(product.id),
        )
        store_item = ModerationQueueItem.objects.create(
            target_type=ModerationQueueItem.TargetType.STORE,
            content_type=ContentType.objects.get_for_model(Store),
            object_id=str(store.id),
        )
        self.client.force_login(self.staff)
        self.client.post(
            reverse("backoffice:moderate", args=[product_item.id, "approve"])
        )
        self.client.post(
            reverse("backoffice:moderate", args=[store_item.id, "reject"])
        )
        product.refresh_from_db()
        store.refresh_from_db()
        self.assertEqual(product.status, Product.Status.PUBLISHED)
        self.assertEqual(store.status, Store.Status.SUSPENDED)

    @override_settings(REQUIRE_SELLER_KYC=True)
    def test_cannot_activate_store_without_approved_kyc(self):
        store = Store.objects.create(
            owner=self.regular,
            slug="sem-kyc",
            display_name="Sem KYC",
            status=Store.Status.PENDING_MODERATION,
        )
        store_item = ModerationQueueItem.objects.create(
            target_type=ModerationQueueItem.TargetType.STORE,
            content_type=ContentType.objects.get_for_model(Store),
            object_id=str(store.id),
        )
        self.client.force_login(self.staff)
        response = self.client.post(
            reverse("backoffice:moderate", args=[store_item.id, "approve"]),
            follow=True,
        )
        store.refresh_from_db()
        store_item.refresh_from_db()
        self.assertEqual(store.status, Store.Status.PENDING_MODERATION)
        self.assertEqual(store_item.decision, ModerationQueueItem.Decision.PENDING)
        self.assertContains(response, "Aprove o KYC")

    @override_settings(REQUIRE_SELLER_KYC=True)
    def test_kyc_approve_activates_store_and_serves_security_photos(self):
        store = Store.objects.create(
            owner=self.regular,
            slug="com-kyc",
            display_name="Com KYC",
            status=Store.Status.PENDING_MODERATION,
        )
        ModerationQueueItem.objects.create(
            target_type=ModerationQueueItem.TargetType.STORE,
            content_type=ContentType.objects.get_for_model(Store),
            object_id=str(store.id),
        )
        kyc = SellerKYC.objects.create(
            user=self.regular,
            status=SellerKYC.Status.PENDING,
            document_front=_jpeg("front.jpg"),
            document_back=_jpeg("back.jpg"),
            selfie_with_document=_jpeg("selfie.jpg"),
        )
        self.client.force_login(self.staff)
        detail = self.client.get(reverse("backoffice:seller_detail", args=[store.id]))
        self.assertEqual(detail.status_code, 200)
        self.assertContains(detail, "Fotos de segurança")
        self.assertContains(detail, kyc.verification_code)

        photo = self.client.get(
            reverse("backoffice:kyc_file", args=[kyc.id, "document_front"])
        )
        self.assertEqual(photo.status_code, 200)
        self.assertIn("no-store", photo["Cache-Control"])

        response = self.client.post(
            reverse("backoffice:kyc_decide", args=[kyc.id, "approve"]),
            {"document_birth_date": "1991-05-20"},
        )
        self.assertRedirects(response, reverse("backoffice:seller_detail", args=[store.id]))
        kyc.refresh_from_db()
        store.refresh_from_db()
        self.regular.refresh_from_db()
        self.assertEqual(kyc.status, SellerKYC.Status.APPROVED)
        self.assertEqual(store.status, Store.Status.ACTIVE)
        self.assertTrue(self.regular.is_age_verified)

    def test_kyc_queue_lists_pending(self):
        SellerKYC.objects.create(
            user=self.regular,
            status=SellerKYC.Status.PENDING,
            document_front=_jpeg("front.jpg"),
            document_back=_jpeg("back.jpg"),
            selfie_with_document=_jpeg("selfie.jpg"),
        )
        self.client.force_login(self.staff)
        response = self.client.get(reverse("backoffice:kyc_queue"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.regular.email)


class CreateAdminCommandTests(TestCase):
    def test_command_creates_admin_from_environment(self):
        env = {
            "ADMIN_EMAIL": "owner@example.com",
            "ADMIN_PASSWORD": "Senha-Administrativa-123!",
            "ADMIN_CPF": "98765432100",
            "ADMIN_BIRTH_DATE": "1990-01-01",
        }
        with patch.dict("os.environ", env):
            call_command("create_admin")
        admin = User.objects.get(email="owner@example.com")
        self.assertTrue(admin.is_staff)
        self.assertTrue(admin.is_superuser)
        self.assertTrue(admin.check_password(env["ADMIN_PASSWORD"]))

    def test_redeploy_preserves_existing_admin_password(self):
        admin = User.objects.create_user(
            username="owner@example.com",
            email="owner@example.com",
            password="Senha-Original-123!",
            cpf="98765432100",
            birth_date=date(1990, 1, 1),
        )
        env = {
            "ADMIN_EMAIL": admin.email,
            "ADMIN_PASSWORD": "Senha-No-Render-123!",
            "ADMIN_CPF": admin.cpf,
            "ADMIN_BIRTH_DATE": "1990-01-01",
        }
        with patch.dict("os.environ", env):
            call_command("create_admin")
        admin.refresh_from_db()
        self.assertTrue(admin.is_staff)
        self.assertTrue(admin.is_superuser)
        self.assertTrue(admin.check_password("Senha-Original-123!"))

    def test_password_reset_requires_explicit_flag(self):
        admin = User.objects.create_user(
            username="owner@example.com",
            email="owner@example.com",
            password="Senha-Original-123!",
            cpf="98765432100",
            birth_date=date(1990, 1, 1),
        )
        env = {
            "ADMIN_EMAIL": admin.email,
            "ADMIN_PASSWORD": "Senha-Nova-Segura-123!",
            "ADMIN_CPF": admin.cpf,
            "ADMIN_BIRTH_DATE": "1990-01-01",
        }
        with patch.dict("os.environ", env):
            call_command("create_admin", reset_password=True)
        admin.refresh_from_db()
        self.assertTrue(admin.check_password(env["ADMIN_PASSWORD"]))

    def test_existing_admin_only_needs_email_on_later_deploys(self):
        admin = User.objects.create_user(
            username="owner@example.com",
            email="owner@example.com",
            password="Senha-Original-123!",
            cpf="98765432100",
            birth_date=date(1990, 1, 1),
            is_staff=True,
            is_superuser=True,
        )
        env = {
            "ADMIN_EMAIL": admin.email,
            "ADMIN_PASSWORD": "",
            "ADMIN_CPF": "",
            "ADMIN_BIRTH_DATE": "",
        }
        with patch.dict("os.environ", env):
            call_command("create_admin")
        admin.refresh_from_db()
        self.assertTrue(admin.is_staff)
        self.assertTrue(admin.is_superuser)
        self.assertTrue(admin.check_password("Senha-Original-123!"))

    def test_promotes_existing_account_when_admin_cpf_already_used(self):
        """Deploy não pode falhar se ADMIN_CPF já está em outra conta."""
        existing = User.objects.create_user(
            username="conta@antiga.com",
            email="conta@antiga.com",
            password="Senha-Original-123!",
            cpf="98765432100",
            birth_date=date(1990, 1, 1),
        )
        env = {
            "ADMIN_EMAIL": "novo-admin@example.com",
            "ADMIN_PASSWORD": "Senha-Administrativa-123!",
            "ADMIN_CPF": existing.cpf,
            "ADMIN_BIRTH_DATE": "1990-01-01",
        }
        with patch.dict("os.environ", env):
            call_command("create_admin")
        existing.refresh_from_db()
        self.assertTrue(existing.is_staff)
        self.assertTrue(existing.is_superuser)
        self.assertEqual(existing.email, "novo-admin@example.com")
        self.assertFalse(User.objects.filter(email="conta@antiga.com").exists())
        self.assertEqual(User.objects.filter(cpf=existing.cpf).count(), 1)
