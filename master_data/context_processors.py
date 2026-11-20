from django.conf import settings
from .models import CompanyProfile


def company_context(request):
    try:
        profile = CompanyProfile.get_settings()
    except Exception:
        profile = None
    is_auth = bool(getattr(getattr(request, 'user', None), 'is_authenticated', False))
    return {
        'company': profile,
        'google_maps_api_key': getattr(settings, 'GOOGLE_MAPS_API_KEY', '') if is_auth else '',
    }

