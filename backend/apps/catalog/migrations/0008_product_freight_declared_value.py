from decimal import Decimal

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("catalog", "0007_alter_productimage_file_alter_productvideo_file"),
    ]

    operations = [
        migrations.AddField(
            model_name="product",
            name="freight_declared_value",
            field=models.DecimalField(
                decimal_places=2,
                default=Decimal("0.00"),
                help_text="Valor aproximado declarado no frete (seguro). Se zero, usa o preço do anúncio.",
                max_digits=8,
            ),
        ),
    ]
