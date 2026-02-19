"""Initial migration for wagtail-asset-publisher v2."""

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("wagtailcore", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="PublishedAsset",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "asset_type",
                    models.CharField(
                        choices=[("css", "CSS"), ("js", "JavaScript")],
                        max_length=3,
                    ),
                ),
                ("url", models.URLField(max_length=2048)),
                ("content_hashes", models.JSONField(default=list)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "page",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="published_assets",
                        to="wagtailcore.page",
                    ),
                ),
            ],
            options={
                "unique_together": {("page", "asset_type")},
            },
        ),
    ]
