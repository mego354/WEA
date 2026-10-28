from django.shortcuts import redirect
from django.contrib.auth.decorators import login_required
from django.urls import reverse


@login_required
def approvals_hub(request):
    """
    Canonical redirect: The separate approval tab has been removed in favor of
    integrating approvals directly into item detail pages and existing list views.
    Redirects legacy bookmarks and navigation links:
    - tab=orders -> sales_orders_list?status=pending
    - others -> visits_list?approval_status=pending
    """
    tab = request.GET.get('tab', 'visits')
    if tab == 'orders':
        url = reverse('sales_orders_list') + '?status=pending'
    elif tab in ['transfers', 'requests', 'inventory']:
        url = reverse('product_transfers_list') + '?status=pending'
    else:
        url = reverse('visits_list') + '?approval_status=pending'
    return redirect(url)
