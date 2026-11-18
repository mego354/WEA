"""
Shared filtering, multi-value parameter parsing, and scoped Area/Brick resolution utilities.
"""

from typing import List, Optional, Tuple
from django.db.models import Q


def parse_multi_str(query_dict, *param_names: str, exclude_values: Tuple[str, ...] = ('all', '')) -> List[str]:
    """
    Parse one or more GET parameter names supporting repeated params (?x=a&x=b),
    bracketed params (?x[]=a), and comma-separated values (?x=a,b).
    Preserves order and deduplicates.
    """
    seen = set()
    result: List[str] = []
    for name in param_names:
        if not name:
            continue
        raw_vals = query_dict.getlist(name) or query_dict.getlist(f"{name}[]")
        for raw in raw_vals:
            for part in str(raw).split(','):
                val = part.strip()
                if val and val not in exclude_values and val not in seen:
                    seen.add(val)
                    result.append(val)
    return result


def parse_multi_int(query_dict, *param_names: str) -> List[int]:
    """
    Parse one or more GET parameter names into a deduplicated list of integers.
    Non-numeric tokens are safely ignored (never raises ValueError).
    """
    seen = set()
    result: List[int] = []
    for raw in parse_multi_str(query_dict, *param_names):
        if raw.isdigit():
            val = int(raw)
            if val not in seen:
                seen.add(val)
                result.append(val)
    return result


def parse_single_int(query_dict, *param_names: str) -> Optional[int]:
    """
    Safely parse a single integer GET parameter; returns None if missing or non-numeric.
    """
    for name in param_names:
        if not name:
            continue
        raw = (query_dict.get(name) or '').strip()
        if raw and raw.isdigit():
            return int(raw)
    return None


def resolve_scoped_area_brick_filters(
    request,
    module: str,
    area_params: Tuple[str, ...] = ('main_area', 'area_id', 'governorate'),
    brick_params: Tuple[str, ...] = ('brick', 'brick_id', 'area'),
):
    """
    Resolve and validate multi-select Main Area (Governorate) and Brick (Subarea)
    filter IDs strictly against the user's authorized scope via ScopeResolutionService.

    Returns:
        (area_ids, brick_ids, selected_areas_chips, selected_bricks_chips)
    """
    from accounts.scope_service import ScopeResolutionService
    from master_data.models import Area

    raw_area_ids = parse_multi_int(request.GET, *area_params)
    raw_brick_ids = parse_multi_int(request.GET, *brick_params)

    is_super = bool(request.user.is_superuser or getattr(request.user, 'is_super_admin', False))
    if is_super:
        auth_areas_qs = Area.objects.filter(parent__isnull=True, is_company_area=False)
        auth_bricks_qs = Area.objects.filter(parent__isnull=False, is_company_area=False).select_related('parent')
    else:
        auth_areas_qs = ScopeResolutionService.get_scoped_choices(request.user, 'governorates', module)
        auth_bricks_qs = ScopeResolutionService.get_scoped_choices(request.user, 'bricks', module)

    auth_area_ids = set(auth_areas_qs.values_list('id', flat=True))
    auth_brick_parent_map = dict(auth_bricks_qs.values_list('id', 'parent_id'))

    area_ids = [aid for aid in raw_area_ids if aid in auth_area_ids]
    brick_ids = [
        bid for bid in raw_brick_ids
        if bid in auth_brick_parent_map and (not area_ids or auth_brick_parent_map[bid] in area_ids)
    ]

    selected_areas_chips = []
    if area_ids:
        selected_areas_chips = list(Area.objects.filter(id__in=area_ids).values('id', 'name', 'code'))

    selected_bricks_chips = []
    if brick_ids:
        selected_bricks_chips = [
            {
                'id': b.id,
                'name': b.name,
                'code': b.code or '',
                'parent_id': b.parent_id,
                'parent_name': b.parent.name if b.parent else '',
            }
            for b in Area.objects.filter(id__in=brick_ids).select_related('parent')
        ]

    return area_ids, brick_ids, selected_areas_chips, selected_bricks_chips


def build_contact_area_q(area_ids: List[int], prefix: str = '', include_addresses: bool = False) -> Q:
    """
    Build a Q filter matching contacts in any of the given Main Area (Governorate) IDs.
    """
    p = f"{prefix}__" if prefix else ""
    q = (
        Q(**{f"{p}area_id__in": area_ids}) |
        Q(**{f"{p}area__parent_id__in": area_ids}) |
        Q(**{f"{p}brick_id__in": area_ids}) |
        Q(**{f"{p}brick__parent_id__in": area_ids})
    )
    if include_addresses:
        q |= (
            Q(**{f"{p}addresses__area_id__in": area_ids}) |
            Q(**{f"{p}addresses__brick__parent_id__in": area_ids})
        )
    return q


def build_contact_brick_q(brick_ids: List[int], prefix: str = '', include_addresses: bool = False) -> Q:
    """
    Build a Q filter matching contacts in any of the given Brick (Subarea) IDs.
    """
    p = f"{prefix}__" if prefix else ""
    q = Q(**{f"{p}brick_id__in": brick_ids})
    if include_addresses:
        q |= Q(**{f"{p}addresses__brick_id__in": brick_ids})
    return q
