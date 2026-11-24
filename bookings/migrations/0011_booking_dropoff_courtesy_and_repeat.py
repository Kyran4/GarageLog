from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("bookings", "0010_booking_earlier_slot_opt_in_earlierslotoffer"),
        ("workshops", "0002_parts_warehouse"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="booking",
            name="previous_booking",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="repeat_bookings", to="bookings.booking"),
        ),
        migrations.AddField(
            model_name="booking",
            name="same_issue_returned",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="booking",
            name="dropoff_contact",
            field=models.CharField(blank=True, max_length=150),
        ),
        migrations.AddField(
            model_name="booking",
            name="dropoff_details",
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name="booking",
            name="dropoff_issue",
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name="booking",
            name="dropoff_checked_in_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="booking",
            name="dropoff_checked_in_by",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="dropoff_checkins", to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddField(
            model_name="booking",
            name="courtesy_vehicle_requested",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="booking",
            name="courtesy_vehicle_start",
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="booking",
            name="courtesy_vehicle_end",
            field=models.DateField(blank=True, null=True),
        ),
        migrations.CreateModel(
            name="CourtesyVehicle",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("plate", models.CharField(max_length=8, unique=True)),
                ("make", models.CharField(max_length=50)),
                ("model", models.CharField(max_length=50)),
                ("is_active", models.BooleanField(default=True)),
                ("workshop", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="courtesy_vehicles", to="workshops.workshop")),
            ],
            options={"ordering": ["plate"]},
        ),
        migrations.CreateModel(
            name="CourtesyReservation",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("start_date", models.DateField()),
                ("end_date", models.DateField()),
                ("status", models.CharField(choices=[("PENDING", "Pending"), ("ASSIGNED", "Assigned"), ("COLLECTED", "Collected"), ("RETURNED", "Returned"), ("CANCELLED", "Cancelled")], default="ASSIGNED", max_length=20)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("assigned_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="courtesy_assignments", to=settings.AUTH_USER_MODEL)),
                ("booking", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="courtesy_reservation", to="bookings.booking")),
                ("vehicle", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="reservations", to="bookings.courtesyvehicle")),
            ],
            options={"ordering": ["start_date", "end_date"]},
        ),
    ]
