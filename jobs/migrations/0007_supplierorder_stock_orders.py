import django.core.validators
import django.db.models.deletion
from django.db import migrations, models


def copy_job_part_details(apps, schema_editor):
    SupplierOrder = apps.get_model("jobs", "SupplierOrder")
    for order in SupplierOrder.objects.select_related("job_part").all():
        order.part_id = order.job_part.part_id
        order.quantity = order.job_part.quantity
        order.save(update_fields=["part", "quantity"])


class Migration(migrations.Migration):

    dependencies = [
        ("inventory", "0001_initial"),
        ("jobs", "0006_jobpart_supply_status_supplierorder"),
    ]

    operations = [
        migrations.AddField(
            model_name="supplierorder",
            name="part",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="supplier_orders",
                to="inventory.part",
            ),
        ),
        migrations.AddField(
            model_name="supplierorder",
            name="quantity",
            field=models.PositiveIntegerField(
                default=1,
                validators=[django.core.validators.MinValueValidator(1)],
            ),
        ),
        migrations.AlterField(
            model_name="supplierorder",
            name="job_part",
            field=models.OneToOneField(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="supplier_order",
                to="jobs.jobpart",
            ),
        ),
        migrations.RunPython(copy_job_part_details, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="supplierorder",
            name="part",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="supplier_orders",
                to="inventory.part",
            ),
        ),
    ]
