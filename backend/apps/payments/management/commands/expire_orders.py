"""
Devolve para a vitrine o estoque de pedidos cujo Pix nunca foi pago.

Sem isso, cada carrinho abandonado tira um item unico do ar para sempre —
o defeito mais caro de marketplace de peca unica. Antes de expirar, o
comando confere a cobranca no Asaas (webhook pode ter se perdido).

Roda de 10 em 10 minutos via Render Cron (ver render.yaml).
"""
from django.core.management.base import BaseCommand

from apps.payments.checkout import expire_stale_orders, reconcile_pending_payments


class Command(BaseCommand):
    help = "Confere pagamentos pendentes no PSP, expira pedidos não pagos e devolve o estoque."

    def add_arguments(self, parser):
        parser.add_argument(
            "--skip-reconcile",
            action="store_true",
            help="Não consultar o PSP; apenas expirar o que já venceu.",
        )

    def handle(self, *args, **options):
        if not options["skip_reconcile"]:
            confirmed = reconcile_pending_payments()
            self.stdout.write(f"Pagamentos confirmados na reconciliação: {confirmed}")
        expired = expire_stale_orders()
        self.stdout.write(self.style.SUCCESS(f"Pedidos expirados: {expired}"))
