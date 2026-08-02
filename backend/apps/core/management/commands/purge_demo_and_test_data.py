"""
Remove lojas, produtos e contas de demonstração / smoke test do banco.

Uso (produção / Render Shell):
    python manage.py purge_demo_and_test_data --force

Uso local:
    python manage.py purge_demo_and_test_data

Marcadores removidos:
- Loja `loja-teste-pagamento` e produtos `teste-pagamento-*` (seed_payment_test)
- Contas / lojas `@demo.local` e slugs do seed_demo
- Títulos "ITEM TESTE — ..."
"""
from __future__ import annotations

from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Q

from apps.accounts.models import AgeVerification, SellerKYC, User
from apps.catalog.models import Product
from apps.moderation.models import ModerationQueueItem, Report
from apps.offers.models import CustomOrderRequest
from apps.payments.models import Invoice, Order, Payment
from apps.reviews.models import Review
from apps.shipping.models import Shipment
from apps.stores.models import Store, StoreBoost, StoreFollow
from apps.wallet.models import WalletEntry, WithdrawalRequest

PAYMENT_TEST_STORE_SLUG = "loja-teste-pagamento"
PAYMENT_TEST_USERNAME = "teste_pagamento"
PAYMENT_TEST_EMAIL = "teste.pagamento@rendaerenda.local"

DEMO_STORE_SLUGS = {
    "atelie-da-luna",
    "valentina-secreta",
    "morena-misteriosa",
    "ruiva-do-sul",
    "gata-paulista",
    "bella-intima",
    "nina-da-noite",
    "clara-seducao",
    "maya-velvet",
    "sofia-lace",
    "iara-do-centro",
    "priscila-pink",
    "helena-silk",
    "bruna-fitness",
    "camila-closet",
    "duda-secret",
    "fernanda-rouge",
    "giovana-soft",
    "isabela-night",
    "juliana-bloom",
    "karina-heat",
    "lara-prive",
}

DEMO_BUYER_USERNAMES = {
    "comprador1",
    "comprador2",
    "comprador3",
    "comprador4",
    "comprador5",
}


class Command(BaseCommand):
    help = "Apaga lojas/produtos/contas de demo e smoke test — deixa o banco pronto para produção."

    def add_arguments(self, parser):
        parser.add_argument(
            "--force",
            action="store_true",
            help="Obrigatório quando DEBUG=False (produção).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Só lista o que seria removido, sem apagar.",
        )

    def handle(self, *args, **options):
        if not settings.DEBUG and not options["force"]:
            raise CommandError(
                "Em produção rode com --force. Ex.: "
                "python manage.py purge_demo_and_test_data --force"
            )

        stores = self._target_stores()
        users = self._target_users(stores)
        products = self._target_products(stores)

        store_count = stores.count()
        product_count = products.count()
        user_count = users.count()

        self.stdout.write(
            f"Alvos: {store_count} loja(s), {product_count} produto(s), {user_count} conta(s)."
        )
        for store in stores.order_by("slug"):
            self.stdout.write(f"  · loja /{store.slug}/ ({store.display_name})")
        for user in users.order_by("email"):
            self.stdout.write(f"  · conta {user.email or user.username}")

        if options["dry_run"]:
            self.stdout.write(self.style.WARNING("Dry-run: nada foi apagado."))
            return

        if store_count == 0 and user_count == 0 and product_count == 0:
            self.stdout.write(self.style.SUCCESS("Nada de demo/smoke test para limpar."))
            return

        with transaction.atomic():
            removed = self._purge(stores, users, products)

        self.stdout.write(
            self.style.SUCCESS(
                "Limpeza concluída: "
                f"{removed['orders']} pedido(s), {removed['products']} produto(s), "
                f"{removed['stores']} loja(s), {removed['users']} conta(s)."
            )
        )

    def _target_stores(self):
        return Store.objects.filter(
            Q(slug=PAYMENT_TEST_STORE_SLUG)
            | Q(slug__in=DEMO_STORE_SLUGS)
            | Q(owner__email__iendswith="@demo.local")
            | Q(owner__username=PAYMENT_TEST_USERNAME)
            | Q(owner__email__iexact=PAYMENT_TEST_EMAIL)
            | Q(psp_subaccount_id__startswith="demo-sub-")
            | Q(bio__icontains="só para testar checkout")
            | Q(display_name__icontains="Loja Teste Pagamento")
        ).distinct()

    def _target_users(self, stores):
        store_owner_ids = list(stores.values_list("owner_id", flat=True))
        return User.objects.filter(
            Q(id__in=store_owner_ids)
            | Q(email__iendswith="@demo.local")
            | Q(username=PAYMENT_TEST_USERNAME)
            | Q(email__iexact=PAYMENT_TEST_EMAIL)
            | Q(username__in=DEMO_BUYER_USERNAMES)
            | Q(username="admin", email__iexact="admin@demo.local")
        ).distinct()

    def _target_products(self, stores):
        return Product.objects.filter(
            Q(store__in=stores)
            | Q(slug__startswith="teste-pagamento")
            | Q(title__startswith="ITEM TESTE")
            | Q(description__icontains="Produto fictício para teste de pagamento")
        ).distinct()

    def _purge(self, stores, users, products) -> dict:
        store_ids = list(stores.values_list("id", flat=True))
        product_ids = list(products.values_list("id", flat=True))
        # Staff real de produção (ADMIN_*) não é apagado — só demo@local / teste.
        deletable_users = users.exclude(
            Q(is_staff=True) & ~Q(email__iendswith="@demo.local") & ~Q(username=PAYMENT_TEST_USERNAME)
        )
        user_ids = list(deletable_users.values_list("id", flat=True))

        orders = Order.objects.filter(
            Q(store_id__in=store_ids)
            | Q(buyer_id__in=user_ids)
            | Q(items__product_id__in=product_ids)
        ).distinct()
        order_ids = list(orders.values_list("id", flat=True))

        # Invoice.order é PROTECT — desvincula ou apaga antes do pedido.
        Invoice.objects.filter(order_id__in=order_ids).delete()
        Payment.objects.filter(order_id__in=order_ids).delete()
        Shipment.objects.filter(order_id__in=order_ids).delete()
        WalletEntry.objects.filter(
            Q(order_id__in=order_ids) | Q(store_id__in=store_ids)
        ).delete()
        WithdrawalRequest.objects.filter(store_id__in=store_ids).delete()
        Review.objects.filter(
            Q(store_id__in=store_ids) | Q(order_id__in=order_ids) | Q(buyer_id__in=user_ids)
        ).delete()
        CustomOrderRequest.objects.filter(
            Q(store_id__in=store_ids) | Q(buyer_id__in=user_ids)
        ).delete()
        StoreFollow.objects.filter(
            Q(store_id__in=store_ids) | Q(user_id__in=user_ids)
        ).delete()
        StoreBoost.objects.filter(store_id__in=store_ids).delete()

        product_ct = ContentType.objects.get_for_model(Product)
        store_ct = ContentType.objects.get_for_model(Store)
        ModerationQueueItem.objects.filter(
            Q(content_type=product_ct, object_id__in=[str(pid) for pid in product_ids])
            | Q(content_type=store_ct, object_id__in=[str(sid) for sid in store_ids])
        ).delete()
        Report.objects.filter(
            Q(content_type=product_ct, object_id__in=[str(pid) for pid in product_ids])
            | Q(content_type=store_ct, object_id__in=[str(sid) for sid in store_ids])
            | Q(reporter_id__in=user_ids)
        ).delete()

        # OrderItem.product é PROTECT — apagar pedidos (CASCADE items) antes dos produtos.
        Order.objects.filter(id__in=order_ids).delete()
        Product.objects.filter(id__in=product_ids).delete()
        # Wallet/Withdrawal já limpos; Store pode ir embora.
        Store.objects.filter(id__in=store_ids).delete()

        SellerKYC.objects.filter(user_id__in=user_ids).delete()
        AgeVerification.objects.filter(user_id__in=user_ids).delete()
        User.objects.filter(id__in=user_ids).delete()

        return {
            "orders": len(order_ids),
            "products": len(product_ids),
            "stores": len(store_ids),
            "users": len(user_ids),
        }
