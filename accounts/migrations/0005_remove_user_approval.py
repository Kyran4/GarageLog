from django.db import migrations


def activate_pending_accounts(apps, schema_editor):
    User = apps.get_model('accounts', 'User')
    User.objects.using(schema_editor.connection.alias).filter(
        is_approved=False,
        is_active=False,
    ).update(is_active=True)


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0004_user_admin_approval'),
    ]

    operations = [
        migrations.RunPython(activate_pending_accounts, migrations.RunPython.noop),
        migrations.RemoveField(
            model_name='user',
            name='is_approved',
        ),
    ]
