from pathlib import Path
import os

BASE_DIR = Path(__file__).resolve().parent.parent


def _load_dotenv_file(env_path: Path) -> None:
    """Lightweight .env loader (real environment variables always take precedence)."""
    if not env_path.is_file():
        return
    try:
        with env_path.open('r', encoding='utf-8') as f:
            for raw_line in f:
                line = raw_line.strip()
                if not line or line.startswith('#') or '=' not in line:
                    continue
                key, value = line.split('=', 1)
                key = key.strip()
                value = value.strip()
                if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
                    value = value[1:-1]
                if key:
                    os.environ.setdefault(key, value)
    except Exception:
        pass


_load_dotenv_file(BASE_DIR / '.env')

SECRET_KEY = os.getenv('DJANGO_SECRET_KEY', 'django-insecure-enterprise-erp-secret-key-wea-pharma-2026')

DEBUG = os.getenv('DEBUG', 'True').strip().lower() in ('1', 'true', 'yes', 'on')

_allowed_hosts_env = os.getenv('ALLOWED_HOSTS', '').strip()
if _allowed_hosts_env:
    ALLOWED_HOSTS = [h.strip() for h in _allowed_hosts_env.split(',') if h.strip()]
else:
    ALLOWED_HOSTS = ['*'] if DEBUG else ['localhost', '127.0.0.1']

_csrf_trusted_env = os.getenv('CSRF_TRUSTED_ORIGINS', '').strip()
if _csrf_trusted_env:
    CSRF_TRUSTED_ORIGINS = [o.strip() for o in _csrf_trusted_env.split(',') if o.strip()]

if not DEBUG and SECRET_KEY.startswith('django-insecure-'):
    raise RuntimeError("DJANGO_SECRET_KEY must be set to a secure value when DEBUG is False.")

# Custom User Model
AUTH_USER_MODEL = 'accounts.User'

# Application definition
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.humanize',
    # Enterprise ERP Modular Apps
    'accounts.apps.AccountsConfig',
    'master_data.apps.MasterDataConfig',
    'contacts.apps.ContactsConfig',
    'catalog.apps.CatalogConfig',
    'inventory.apps.InventoryConfig',
    'purchases.apps.PurchasesConfig',
    'treasury.apps.TreasuryConfig',
    'sales.apps.SalesConfig',
    'activities.apps.ActivitiesConfig',
    'reports.apps.ReportsConfig',
    'notifications.apps.NotificationsConfig',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'master_data.context_processors.company_context',
            ],
            'builtins': [
                'master_data.templatetags.erp_tags',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'

# Database
# Note: SQLite uses default DELETE journal mode (safe on PythonAnywhere NFS; do NOT enable WAL on NFS).
# Busy timeout is raised to 20s to avoid transient lock errors under concurrent WSGI requests.
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
        'OPTIONS': {
            'timeout': 20,
        },
    }
}

# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator', 'OPTIONS': {'min_length': 6}},
]

# Internationalization
LANGUAGE_CODE = 'ar'
TIME_ZONE = 'Africa/Cairo'
USE_I18N = True
USE_TZ = True

# Static & Media
STATIC_URL = '/static/'
STATICFILES_DIRS = [BASE_DIR / 'static']
STATIC_ROOT = BASE_DIR / 'staticfiles'

MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'
MEDIA_MAX_UPLOAD_SIZE_MB = int(os.getenv('MEDIA_MAX_UPLOAD_SIZE_MB', '10'))

# Cloudflare R2 Object Storage (Credentials exclusively via environment variables)
CLOUDFLARE_R2_ACCESS_KEY = os.getenv('CLOUDFLARE_R2_ACCESS_KEY', '').strip()
CLOUDFLARE_R2_SECRET_KEY = os.getenv('CLOUDFLARE_R2_SECRET_KEY', '').strip()
CLOUDFLARE_R2_BUCKET_NAME = os.getenv('CLOUDFLARE_R2_BUCKET_NAME', '').strip()
CLOUDFLARE_R2_ENDPOINT_URL = os.getenv('CLOUDFLARE_R2_ENDPOINT_URL', '').strip()
CLOUDFLARE_R2_CUSTOM_DOMAIN = os.getenv('CLOUDFLARE_R2_CUSTOM_DOMAIN', '').strip()

R2_ENABLED = all([
    CLOUDFLARE_R2_ACCESS_KEY,
    CLOUDFLARE_R2_SECRET_KEY,
    CLOUDFLARE_R2_BUCKET_NAME,
    CLOUDFLARE_R2_ENDPOINT_URL,
])

STORAGES = {
    'default': {
        'BACKEND': 'master_data.storage.CloudflareR2Storage' if R2_ENABLED else 'django.core.files.storage.FileSystemStorage',
    },
    'staticfiles': {
        'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage',
    },
}

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

LOGIN_URL = '/auth/login/'
LOGIN_REDIRECT_URL = '/home/'
LOGOUT_REDIRECT_URL = '/auth/login/'

# Security & Referrer Policy (required so OpenStreetMap/tile providers receive Referer on desktop browsers)
SECURE_REFERRER_POLICY = 'strict-origin-when-cross-origin'
SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_HTTPONLY = False  # Read by AJAX fetch() helpers when needed
X_FRAME_OPTIONS = 'DENY'
SECURE_CONTENT_TYPE_NOSNIFF = True

if not DEBUG:
    SESSION_COOKIE_SECURE = os.getenv('SESSION_COOKIE_SECURE', 'True').strip().lower() in ('1', 'true', 'yes', 'on')
    CSRF_COOKIE_SECURE = os.getenv('CSRF_COOKIE_SECURE', 'True').strip().lower() in ('1', 'true', 'yes', 'on')
    SECURE_SSL_REDIRECT = os.getenv('SECURE_SSL_REDIRECT', 'False').strip().lower() in ('1', 'true', 'yes', 'on')
    SECURE_HSTS_SECONDS = int(os.getenv('SECURE_HSTS_SECONDS', '31536000'))
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True

# Google Maps & Geolocation Integration
GOOGLE_MAPS_API_KEY = os.getenv('GOOGLE_MAPS_API_KEY', '')

# Firebase Cloud Messaging (FCM HTTP v1) & Native Push Configuration
# NOTE: google-services.json is the Android CLIENT config (belongs in android/app/google-services.json in the Capacitor App Builder).
# Django server push delivery requires a Firebase Admin Service Account JSON key (with private_key & client_email)
# supplied via FIREBASE_SERVICE_ACCOUNT_JSON, FIREBASE_SERVICE_ACCOUNT_PATH, or git-ignored secrets/firebase-service-account.json.
FIREBASE_PROJECT_ID = os.getenv('FIREBASE_PROJECT_ID', 'wea-pharma-mobile').strip()
FIREBASE_ANDROID_PACKAGE_NAME = os.getenv('FIREBASE_ANDROID_PACKAGE_NAME', 'com.acme.WEA').strip()
_default_firebase_sa_path = BASE_DIR / 'secrets' / 'firebase-service-account.json'
_raw_firebase_sa_path = os.getenv(
    'FIREBASE_SERVICE_ACCOUNT_PATH',
    os.getenv('GOOGLE_APPLICATION_CREDENTIALS', str(_default_firebase_sa_path) if _default_firebase_sa_path.is_file() else ''),
).strip()
if _raw_firebase_sa_path and not Path(_raw_firebase_sa_path).is_absolute():
    _raw_firebase_sa_path = str((BASE_DIR / _raw_firebase_sa_path).resolve())
FIREBASE_SERVICE_ACCOUNT_PATH = _raw_firebase_sa_path
FIREBASE_SERVICE_ACCOUNT_JSON = os.getenv('FIREBASE_SERVICE_ACCOUNT_JSON', '').strip()
FCM_DEFAULT_CHANNEL_ID = os.getenv('FCM_DEFAULT_CHANNEL_ID', 'app_push_notifications_channel').strip()


