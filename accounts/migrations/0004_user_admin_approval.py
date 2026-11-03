from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0003_user_workshop'),
    ]

    operations = [
        migrations.RenameField(
            model_name='user',
            old_name='email_verified',
            new_name='is_approved',
        ),
        migrations.AlterField(
            model_name='user',
            name='is_approved',
            field=models.BooleanField(
                default=False,
                help_text='Whether an admin has approved this account to use GarageLog.',
            ),
        ),
    ]
