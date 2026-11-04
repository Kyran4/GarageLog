from django.contrib import messages
from django.contrib.auth import logout
from django.shortcuts import redirect
from django.utils.deprecation import MiddlewareMixin


class SingleSessionPerUserMiddleware(MiddlewareMixin):
    def process_request(self, request):
        user = request.user
        if not user.is_authenticated or not user.active_session_key:
            return None

        if request.session.session_key == user.active_session_key:
            return None

        logout(request)
        messages.warning(
            request,
            'You were signed out because this account was used to sign in on another device.',
        )
        return redirect('accounts:login')
