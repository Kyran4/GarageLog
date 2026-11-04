from django.contrib.auth.signals import user_logged_in
from django.dispatch import receiver


@receiver(user_logged_in, dispatch_uid='accounts.store_active_session')
def store_active_session(sender, request, user, **kwargs):
    session_key = request.session.session_key
    if not session_key:
        request.session.create()
        session_key = request.session.session_key

    type(user)._default_manager.filter(pk=user.pk).update(active_session_key=session_key)
