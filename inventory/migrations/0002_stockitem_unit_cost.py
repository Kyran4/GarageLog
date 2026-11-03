import django.core.validators
from decimal import Decimal
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("inventory", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="stockitem",
            name="unit_cost",
            field=models.DecimalField(
                blank=True,
                decimal_places=2,
                help_text="Internal supplier cost from the most recent warehouse order.",
                max_digits=8,
                null=True,
                validators=[django.core.validators.MinValueValidator(Decimal("0"))],
                verbose_name="last supplier unit cost",
            ),
        ),
    ]
