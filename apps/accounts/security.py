from datetime import datetime, timedelta

from django.utils import timezone

REAUTH_DURACION = timedelta(minutes=10)
SESSION_KEY_REAUTH = 'cuenta_reauth_at'


def tiene_reauth_reciente(request):
    marca = request.session.get(SESSION_KEY_REAUTH)
    if not marca:
        return False
    try:
        momento = datetime.fromisoformat(marca)
    except ValueError:
        return False
    return timezone.now() - momento < REAUTH_DURACION


def marcar_reauth(request):
    request.session[SESSION_KEY_REAUTH] = timezone.now().isoformat()
