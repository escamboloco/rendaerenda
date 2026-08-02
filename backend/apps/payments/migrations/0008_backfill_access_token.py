"""
Preenche access_token nos pedidos criados antes de o token existir.

Sem token o pedido fica inalcançável: a compradora não abre o link do
e-mail e a página da vendedora quebrava ao montar a URL. Gera um token
por pedido, com o mesmo tamanho usado no checkout.
"""
import secrets

from django.db import migrations


def backfill_tokens(apps, schema_editor):
    Order = apps.get_model("payments", "Order")
    pending = Order.objects.filter(access_token="").only("id")
    for order in pending.iterator():
        Order.objects.filter(pk=order.pk).update(access_token=secrets.token_urlsafe(32))


def noop(apps, schema_editor):
    """Token gerado não volta atrás — apagar quebraria links já enviados."""


class Migration(migrations.Migration):
    dependencies = [("payments", "0007_ordermessage")]

    operations = [migrations.RunPython(backfill_tokens, noop)]
