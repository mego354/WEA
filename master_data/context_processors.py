from django.conf import settings
from .models import CompanyProfile


def company_context(request):
    try:
        profile = CompanyProfile.get_settings()
    except Exception:
        profile = None
    return {
        'company': profile,
        'google_maps_api_key': getattr(settings, 'GOOGLE_MAPS_API_KEY', ''),
    }

