import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

import django
django.setup()

from django.urls import get_resolver
from django.urls.resolvers import URLPattern, URLResolver

def list_urls(patterns, prefix=''):
    url_list = []
    for pattern in patterns:
        if isinstance(pattern, URLResolver):
            url_list.extend(list_urls(pattern.url_patterns, prefix + str(pattern.pattern)))
        elif isinstance(pattern, URLPattern):
            mod = getattr(pattern.callback, '__module__', '')
            view_name = getattr(pattern.callback, '__name__', str(pattern.callback))
            url_list.append({
                'url': '/' + (prefix + str(pattern.pattern)).lstrip('/'),
                'name': pattern.name or '',
                'view': f"{mod}.{view_name}"
            })
    return url_list

resolver = get_resolver()
urls = list_urls(resolver.url_patterns)

# Filter out admin
app_urls = [u for u in urls if not u['url'].startswith('/admin/')]
print(f"Total Non-Admin Registered URLs: {len(app_urls)}")

# Group by module/app
by_app = {}
for u in app_urls:
    mod_parts = u['view'].split('.')
    app = mod_parts[0] if mod_parts else 'other'
    by_app.setdefault(app, []).append(u)

for app, items in sorted(by_app.items()):
    print(f"\n=== APP: {app} ({len(items)} routes) ===")
    seen_names = set()
    for item in items:
        # avoid duplicate aliases in printout
        key = (item['url'], item['view'])
        if key in seen_names:
            continue
        seen_names.add(key)
        print(f"  {item['url']:<48} | {item['name']:<32} | {item['view']}")
