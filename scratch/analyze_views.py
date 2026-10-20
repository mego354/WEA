import os
import sys
import json
import inspect

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
                'module': mod,
                'view_name': view_name,
                'callback': pattern.callback
            })
    return url_list

resolver = get_resolver()
all_urls = list_urls(resolver.url_patterns)
app_urls = [u for u in all_urls if not u['url'].startswith('/admin/')]

# Deduplicate by (module, view_name)
unique_views = {}
for u in app_urls:
    key = f"{u['module']}.{u['view_name']}"
    if key not in unique_views:
        # inspect source code to check for Paginator, pagination, querysets, templates
        src = ""
        try:
            src = inspect.getsource(u['callback'])
        except Exception:
            pass
        
        has_paginator = 'Paginator' in src or 'page_obj' in src or 'paginate' in src
        has_select_related = 'select_related' in src
        has_prefetch_related = 'prefetch_related' in src
        has_render = 'render(' in src
        
        # Check template name if identifiable
        template_names = []
        for line in src.splitlines():
            if 'render(' in line and '.html' in line:
                for token in line.split():
                    if '.html' in token:
                        template_names.append(token.strip('\'",()'))

        unique_views[key] = {
            'module': u['module'],
            'view_name': u['view_name'],
            'url': u['url'],
            'name': u['name'],
            'has_paginator': has_paginator,
            'has_select_related': has_select_related,
            'has_prefetch_related': has_prefetch_related,
            'is_html_view': has_render,
            'templates': template_names
        }

with open('scratch/views_inventory.json', 'w', encoding='utf-8') as f:
    json.dump(unique_views, f, indent=2, ensure_ascii=False)

print(f"Total Unique Application Views: {len(unique_views)}")
html_views = [v for v in unique_views.values() if v['is_html_view']]
print(f"HTML Rendering Views: {len(html_views)}")
paginated_views = [v for v in unique_views.values() if v['has_paginator']]
print(f"Views with Paginator: {len(paginated_views)}")
unpaginated_views = [v for v in html_views if not v['has_paginator'] and ('list' in v['view_name'] or 'index' in v['view_name'] or 'all' in v['view_name'])]
print(f"List-like Views WITHOUT Paginator: {len(unpaginated_views)}")
for v in unpaginated_views:
    print(f"  * {v['module']}.{v['view_name']} -> {v['url']}")
