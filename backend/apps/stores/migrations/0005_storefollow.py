# Generated manually for StoreFollow

import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("stores", "0004_simplified_intermediary"),
    ]

    operations = [
        migrations.CreateModel(
            name="StoreFollow",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "store",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="followers",
                        to="stores.store",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="followed_stores",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
        ),
        migrations.AddConstraint(
            model_name="storefollow",
            constraint=models.UniqueConstraint(fields=("store", "user"), name="store_follow_unique"),
        ),
        migrations.AddIndex(
            model_name="storefollow",
            index=models.Index(fields=["-created_at"], name="stores_stor_created_idx"),
        ),
    ]
