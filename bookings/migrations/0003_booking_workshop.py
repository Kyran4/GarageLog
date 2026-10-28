import django.db.models.deletion
from django.db import migrations, models


def assign_default_workshop(apps, schema_editor):
    """Bookings made before workshops existed all go to the first workshop (or a default one)."""
    Booking = apps.get_model('bookings', 'Booking')
    Workshop = apps.get_model('workshops', 'Workshop')
    bookings = Booking.objects.filter(workshop__isnull=True)
    if not bookings.exists():
        return
    workshop = Workshop.objects.order_by('pk').first() or Workshop.objects.create(name='Main Workshop')
    bookings.update(workshop=workshop)


class Migration(migrations.Migration):

    dependencies = [
        ('bookings', '0002_booking_vehicle_and_slot_constraints'),
        ('workshops', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='booking',
            name='workshop',
            field=models.ForeignKey(
                null=True, on_delete=django.db.models.deletion.PROTECT,
                related_name='bookings', to='workshops.workshop',
            ),
        ),
        migrations.RunPython(assign_default_workshop, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='booking',
            name='workshop',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name='bookings', to='workshops.workshop',
            ),
        ),
    ]
