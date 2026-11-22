from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("jobs", "0008_jobcard_checklist_jobcard_checklist_notes"),
    ]

    operations = [
        migrations.AddField(
            model_name="jobpart",
            name="is_estimate",
            field=models.BooleanField(
                default=False,
                help_text="The customer price is an estimate that must be reviewed on the job card.",
            ),
        ),
    ]
