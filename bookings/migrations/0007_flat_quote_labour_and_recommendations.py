from decimal import Decimal

import django.core.validators
from django.db import migrations, models


LABOUR_RECOMMENDATIONS = {
    "WoF Inspection": Decimal("55.00"),
    "Oil Change": Decimal("60.00"),
    "Full Service": Decimal("180.00"),
    "Brake Repair": Decimal("120.00"),
    "Tyre Replacement": Decimal("60.00"),
    "Battery Replacement": Decimal("45.00"),
    "Engine Diagnostics": Decimal("100.00"),
}


def migrate_labour_charges(apps, schema_editor):
    QuoteLabour = apps.get_model("bookings", "BookingQuoteLabour")
    database = schema_editor.connection.alias
    for line in QuoteLabour.objects.using(database).all().iterator():
        line.charge = (
            Decimal(line.hours) * Decimal(line.hourly_rate)
        ).quantize(Decimal("0.01"))
        line.save(using=database, update_fields=["charge"])


def seed_labour_recommendations(apps, schema_editor):
    Recommendation = apps.get_model("bookings", "ServiceLabourRecommendation")
    database = schema_editor.connection.alias
    Recommendation.objects.using(database).bulk_create([
        Recommendation(service_type=service_type, recommended_charge=charge)
        for service_type, charge in LABOUR_RECOMMENDATIONS.items()
    ])


def remove_seeded_recommendations(apps, schema_editor):
    Recommendation = apps.get_model("bookings", "ServiceLabourRecommendation")
    Recommendation.objects.using(schema_editor.connection.alias).filter(
        service_type__in=LABOUR_RECOMMENDATIONS,
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("bookings", "0006_bookingquotelabour_bookingquotepart"),
    ]

    operations = [
        migrations.AddField(
            model_name="bookingquotelabour",
            name="charge",
            field=models.DecimalField(
                decimal_places=2,
                max_digits=8,
                null=True,
            ),
        ),
        migrations.RunPython(migrate_labour_charges, migrations.RunPython.noop),
        migrations.RemoveField(
            model_name="bookingquotelabour",
            name="hours",
        ),
        migrations.RemoveField(
            model_name="bookingquotelabour",
            name="hourly_rate",
        ),
        migrations.AlterField(
            model_name="bookingquotelabour",
            name="charge",
            field=models.DecimalField(
                decimal_places=2,
                max_digits=8,
                validators=[django.core.validators.MinValueValidator(Decimal("0.00"))],
            ),
        ),
        migrations.CreateModel(
            name="ServiceLabourRecommendation",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("service_type", models.CharField(max_length=100, unique=True)),
                ("recommended_charge", models.DecimalField(
                    decimal_places=2,
                    max_digits=8,
                    validators=[django.core.validators.MinValueValidator(Decimal("0.00"))],
                )),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "ordering": ["service_type"],
                "verbose_name": "service labour recommendation",
                "verbose_name_plural": "service labour recommendations",
            },
        ),
        migrations.RunPython(seed_labour_recommendations, remove_seeded_recommendations),
    ]
