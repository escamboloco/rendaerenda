import uuid

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0001_set_site_domain"),
    ]

    operations = [
        migrations.CreateModel(
            name="MarketingSubscriber",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("email", models.EmailField(db_index=True, max_length=254, unique=True)),
                ("name", models.CharField(blank=True, max_length=150)),
                ("is_active", models.BooleanField(default=True)),
                ("consented_at", models.DateTimeField()),
                ("unsubscribed_at", models.DateTimeField(blank=True, null=True)),
                ("unsubscribe_token", models.CharField(db_index=True, max_length=64, unique=True)),
                ("source", models.CharField(default="checkout", max_length=40)),
                ("last_sent_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "indexes": [
                    models.Index(
                        fields=["is_active", "last_sent_at"],
                        name="core_mkt_active_sent_idx",
                    )
                ],
            },
        ),
    ]
