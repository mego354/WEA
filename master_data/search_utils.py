"""
Shared Arabic-aware and case-insensitive search normalization utilities.

Use ``normalize_arabic_text`` and ``filter_by_arabic_search`` across all list
views and autocomplete/search APIs so Arabic character variations match
consistently without altering stored database values or displayed text.
"""

import re
from typing import Iterable, Optional, Sequence

from django.db.models import CharField, F, Q, QuerySet, Value
from django.db.models.functions import Cast, Coalesce, Lower, Replace


# Standard Arabic canonical character mapping
ARABIC_CHAR_MAP = str.maketrans({
    '\u0623': '\u0627',  # أ -> ا
    '\u0625': '\u0627',  # إ -> ا
    '\u0622': '\u0627',  # آ -> ا
    '\u0671': '\u0627',  # ٱ -> ا
    '\u0629': '\u0647',  # ة -> ه
    '\u0649': '\u064a',  # ى -> ي
})

# Tashkeel / Arabic diacritics + tatweel (kashida)
ARABIC_STRIP_RE = re.compile(r'[\u064B-\u065F\u0670\u0640]')
MULTISPACE_RE = re.compile(r'\s+')

# Characters stripped or replaced in SQL expressions (applied sequentially)
_SQL_REPLACEMENTS = (
    ('\u0640', ''),      # ـ tatweel
    ('\u064b', ''),      # fathatan
    ('\u064c', ''),      # dammatan
    ('\u064d', ''),      # kasratan
    ('\u064e', ''),      # fatha
    ('\u064f', ''),      # damma
    ('\u0650', ''),      # kasra
    ('\u0651', ''),      # shadda
    ('\u0652', ''),      # sukun
    ('\u0670', ''),      # superscript alef
    ('\u0623', '\u0627'),  # أ -> ا
    ('\u0625', '\u0627'),  # إ -> ا
    ('\u0622', '\u0627'),  # آ -> ا
    ('\u0671', '\u0627'),  # ٱ -> ا
    ('\u0629', '\u0647'),  # ة -> ه
    ('\u0649', '\u064a'),  # ى -> ي
)


def normalize_arabic_text(text: Optional[str]) -> str:
    """
    Normalize Arabic and mixed Arabic/English text for search matching only.

    Normalizes:
    - أ / إ / آ / ٱ -> ا
    - ة -> ه
    - ى -> ي
    - Strips Arabic diacritics (tashkeel) and tatweel (ـ)
    - Lowercases Latin characters and collapses whitespace
    """
    if text is None:
        return ''
    value = str(text)
    if not value:
        return ''
    value = ARABIC_STRIP_RE.sub('', value)
    value = value.translate(ARABIC_CHAR_MAP)
    value = value.lower()
    return MULTISPACE_RE.sub(' ', value).strip()


def normalized_sql_expr(field_name: str):
    """
    Build a DB-portable ORM expression normalizing a field for search queries.
    Handles NULLs and numeric/related fields cleanly via Coalesce + Cast.
    """
    expr = Coalesce(
        Cast(F(field_name), output_field=CharField()),
        Value(''),
        output_field=CharField(),
    )
    expr = Lower(expr, output_field=CharField())
    for source_char, target_char in _SQL_REPLACEMENTS:
        expr = Replace(
            expr,
            Value(source_char),
            Value(target_char),
            output_field=CharField(),
        )
    return expr


def _safe_annotation_alias(field_name: str) -> str:
    clean = re.sub(r'[^a-zA-Z0-9_]+', '_', field_name).strip('_')
    return f'_ar_norm_{clean}'


def filter_by_arabic_search(
    queryset: QuerySet,
    fields: Sequence[str],
    query: Optional[str],
    *,
    raw_fields: Optional[Sequence[str]] = None,
    numeric_id_field: Optional[str] = None,
) -> QuerySet:
    """
    Filter a QuerySet across multiple text fields with Arabic normalization,
    case-insensitive Latin matching, optional un-normalized identifier/raw
    fields, and optional exact numeric ID lookup.

    Multi-word queries match records where EVERY token matches AT LEAST ONE
    configured field (supports mixed Arabic + English + numeric queries).
    """
    # Signature flexibility: allow both (queryset, fields, query) and (queryset, query, fields)
    if isinstance(fields, (str, bytes)) and (query is None or isinstance(query, (list, tuple, set))):
        fields, query = query, fields

    if not query:
        return queryset
    raw_query = str(query).strip()
    if not raw_query:
        return queryset

    raw_tokens = [tok for tok in MULTISPACE_RE.split(raw_query) if tok]
    if not raw_tokens:
        return queryset

    text_fields = [f for f in (fields or []) if f]
    direct_fields = [f for f in (raw_fields or []) if f]

    annotations_to_add = {}
    field_aliases = []
    existing_annotations = getattr(queryset.query, 'annotations', {})
    for field_name in text_fields:
        alias = _safe_annotation_alias(field_name)
        field_aliases.append(alias)
        if alias not in existing_annotations and alias not in annotations_to_add:
            annotations_to_add[alias] = normalized_sql_expr(field_name)

    if annotations_to_add:
        queryset = queryset.annotate(**annotations_to_add)

    combined_q = Q()
    for raw_token in raw_tokens:
        norm_token = normalize_arabic_text(raw_token)
        token_q = Q()

        if norm_token:
            for alias in field_aliases:
                token_q |= Q(**{f'{alias}__icontains': norm_token})

        for raw_field in direct_fields:
            token_q |= Q(**{f'{raw_field}__icontains': raw_token})

        if numeric_id_field:
            candidate = raw_token.lstrip('#').strip()
            if candidate.isdigit() and len(candidate) <= 12:
                token_q |= Q(**{numeric_id_field: int(candidate)})

        if token_q:
            combined_q &= token_q

    if not combined_q:
        return queryset
    return queryset.filter(combined_q)


def matches_arabic_query(values: Iterable[Optional[str]], query: Optional[str]) -> bool:
    """
    In-memory Arabic-normalized search helper matching the same token semantics
    as ``filter_by_arabic_search``.
    """
    if not query or not str(query).strip():
        return True
    norm_tokens = [tok for tok in normalize_arabic_text(query).split(' ') if tok]
    if not norm_tokens:
        return True
    if isinstance(values, str):
        values = [values]
    normalized_values = [normalize_arabic_text(v) for v in values if v is not None]
    return all(any(tok in val for val in normalized_values) for tok in norm_tokens)


def parse_search_limit(request, default: int = 30, maximum: int = 50) -> int:
    """Safely parse and clamp the `limit` query parameter for search APIs."""
    try:
        raw = int(request.GET.get('limit', default))
    except (TypeError, ValueError):
        raw = default
    return min(max(raw, 1), maximum)


def get_bounded_select_options(scoped_qs, selected_id=None, limit: int = 100) -> list:
    """
    Return a bounded list of model instances from `scoped_qs`, ensuring any valid
    `selected_id` present in `scoped_qs` is included first even when it sits beyond
    the alphabetical `[:limit]` window (so edit/filter pages never lose selection).
    """
    items = list(scoped_qs[:limit])
    if selected_id not in (None, ''):
        try:
            target_pk = int(selected_id)
        except (TypeError, ValueError):
            target_pk = None
        if target_pk is not None and not any(obj.pk == target_pk for obj in items):
            selected_obj = scoped_qs.filter(pk=target_pk).first()
            if selected_obj is not None:
                items.insert(0, selected_obj)
    return items


def serialize_contact_option(contact) -> dict:
    """Serialize a scoped Contact record for smart-search dropdown JSON responses."""
    area_name = contact.area.name if getattr(contact, 'area', None) else ''
    brick_name = contact.brick.name if getattr(contact, 'brick', None) else ''
    geo = f"{area_name} - {brick_name}" if (area_name and brick_name and area_name != brick_name) else (brick_name or area_name)
    code_part = f" • {contact.code}" if getattr(contact, 'code', None) else ''
    subtext_parts = [f"#{contact.serial_num}" if getattr(contact, 'serial_num', None) else '']
    if geo:
        subtext_parts.append(geo)
    if getattr(contact, 'mobile', None):
        subtext_parts.append(contact.mobile)
    subtext = " | ".join(p for p in subtext_parts if p)
    return {
        'id': contact.id,
        'text': f"{contact.name}{code_part}",
        'name': contact.name,
        'serial_num': contact.serial_num,
        'code': contact.code or '',
        'mobile': contact.mobile or '',
        'area': area_name,
        'brick': brick_name,
        'subtext': subtext,
    }


def serialize_warehouse_option(warehouse) -> dict:
    """Serialize a scoped Warehouse record for smart-search dropdown JSON responses."""
    parts = [warehouse.code] if getattr(warehouse, 'code', None) else []
    if getattr(warehouse, 'is_main', False):
        parts.append('رئيسي')
    if getattr(warehouse, 'area', None):
        parts.append(warehouse.area.name)
    if getattr(warehouse, 'assigned_user', None):
        parts.append(warehouse.assigned_user.name or warehouse.assigned_user.username)
    return {
        'id': warehouse.id,
        'text': warehouse.name,
        'name': warehouse.name,
        'code': warehouse.code or '',
        'subtext': " | ".join(parts),
    }


def serialize_vault_option(vault) -> dict:
    """Serialize a scoped Vault record for smart-search dropdown JSON responses."""
    type_label = vault.get_vault_type_display() if hasattr(vault, 'get_vault_type_display') else vault.vault_type
    sub_parts = [f"#{vault.serial_num}", f"{vault.current_balance:,.2f} ج.م"]
    if type_label:
        sub_parts.append(type_label.split('(')[0].strip())
    if getattr(vault, 'assigned_user', None):
        sub_parts.append(vault.assigned_user.name or vault.assigned_user.username)
    return {
        'id': vault.id,
        'text': f"{vault.name} (رصيد: {vault.current_balance:,.2f} ج.م)",
        'name': vault.name,
        'serial_num': vault.serial_num,
        'balance': str(vault.current_balance),
        'subtext': " | ".join(sub_parts),
    }


