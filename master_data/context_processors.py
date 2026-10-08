from .models import CompanyProfile


def company_context(request):
    try:
        profile = CompanyProfile.get_settings()
    except Exception:
        profile = None
    return {
        'company': profile
    }
