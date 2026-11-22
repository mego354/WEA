"""
Django Signals connecting all domain models and SecurityAuditLog to NotificationService.
All emissions execute safely via transaction.on_commit() and are wrapped in error isolation.
"""

import logging
from decimal import Decimal

from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver
from django.urls import reverse
from django.utils import timezone

from accounts.models import SecurityAuditLog
from activities.models import Agreement, Visit
from catalog.models import Product
from contacts.models import Contact, ContactTodo
from inventory.models import InventoryStock
from reports.models import CoachingEvaluation, SalesTarget

from .formatters import build_arabic_notification
from .hooks import dispatch_from_audit_log
from .services import NotificationService

logger = logging.getLogger(__name__)


def _safe_url(name: str, pk=None) -> str:
    try:
        return reverse(name, kwargs={'pk': pk}) if pk is not None else reverse(name)
    except Exception:
        return ''


@receiver(post_save, sender=SecurityAuditLog, dispatch_uid='wea_notif_audit_log')
def on_security_audit_log_created(sender, instance, created, raw=False, **kwargs):
    if raw or not created:
        return
    dispatch_from_audit_log(instance)


# --- Visits (pending approval, GPS suspicion, re-approval) ---
@receiver(post_save, sender=Visit, dispatch_uid='wea_notif_visit')
def on_visit_saved(sender, instance, created, raw=False, **kwargs):
    if raw:
        return
    try:
        url = _safe_url('visit_detail', pk=instance.pk)
        if created and instance.approval_status == 'pending':
            fmt = build_arabic_notification(
                event_code='activities.visit_pending_approval',
                target_obj=instance,
                actor=instance.owner or instance.created_by,
            )
            NotificationService.emit(
                event_code='activities.visit_pending_approval',
                target_obj=instance,
                actor=instance.owner or instance.created_by,
                title=fmt['title'],
                body=fmt['body'],
                route_key=fmt['route_key'],
                action_url=url or fmt['action_url'],
                metadata=fmt['metadata'],
                dedupe_key=f"visit_pending:{instance.pk}",
            )
        if getattr(instance, 'gps_integrity_status', '') in ('suspicious', 'flagged') or getattr(instance, 'location_status', '') in ('suspicious', 'outside_range'):
            fmt = build_arabic_notification(
                event_code='activities.visit_gps_suspicious',
                target_obj=instance,
                actor=instance.owner or instance.created_by,
            )
            NotificationService.emit(
                event_code='activities.visit_gps_suspicious',
                target_obj=instance,
                actor=instance.owner or instance.created_by,
                title=fmt['title'],
                body=fmt['body'],
                route_key=fmt['route_key'],
                action_url=url or fmt['action_url'],
                metadata=fmt['metadata'],
                dedupe_key=f"visit_gps:{instance.pk}",
            )
        if getattr(instance, 'waiting_for_reapproval', False):
            fmt = build_arabic_notification(
                event_code='activities.visit_reapproval_required',
                target_obj=instance,
                actor=instance.last_edited_by or instance.owner,
            )
            NotificationService.emit(
                event_code='activities.visit_reapproval_required',
                target_obj=instance,
                actor=instance.last_edited_by or instance.owner,
                title=fmt['title'],
                body=fmt['body'],
                route_key=fmt['route_key'],
                action_url=url or fmt['action_url'],
                metadata=fmt['metadata'],
                dedupe_key=f"visit_reapproval:{instance.pk}:{instance.last_edited_at or instance.updated_at}",
            )
    except Exception:
        logger.exception("Visit notification signal error")


# --- Agreements (rejection fallback if changed directly without audit log) ---
@receiver(pre_save, sender=Agreement, dispatch_uid='wea_notif_agreement_pre')
def on_agreement_pre_save(sender, instance, raw=False, **kwargs):
    if raw or not instance.pk:
        instance._prev_status = None
        return
    try:
        instance._prev_status = Agreement.objects.filter(pk=instance.pk).values_list('status', flat=True).first()
    except Exception:
        instance._prev_status = None


@receiver(post_save, sender=Agreement, dispatch_uid='wea_notif_agreement_post')
def on_agreement_post_save(sender, instance, created, raw=False, **kwargs):
    if raw or created:
        return
    try:
        prev = getattr(instance, '_prev_status', None)
        if prev != instance.status and instance.status == 'rejected':
            actor = instance.approved_by or instance.updated_by
            fmt = build_arabic_notification(
                event_code='activities.agreement_rejected',
                target_obj=instance,
                actor=actor,
            )
            NotificationService.emit(
                event_code='activities.agreement_rejected',
                target_obj=instance,
                actor=actor,
                title=fmt['title'],
                body=fmt['body'],
                route_key=fmt['route_key'],
                action_url=_safe_url('agreement_detail', pk=instance.pk) or fmt['action_url'],
                metadata=fmt['metadata'],
                dedupe_key=f"agreement_rejected:{instance.pk}",
            )
    except Exception:
        logger.exception("Agreement notification signal error")


# --- Contacts (created, status changed, credit limit changed) ---
@receiver(pre_save, sender=Contact, dispatch_uid='wea_notif_contact_pre')
def on_contact_pre_save(sender, instance, raw=False, **kwargs):
    if raw or not instance.pk:
        instance._prev_contact_state = None
        return
    try:
        instance._prev_contact_state = Contact.objects.filter(pk=instance.pk).values(
            'status', 'credit_limit'
        ).first()
    except Exception:
        instance._prev_contact_state = None


@receiver(post_save, sender=Contact, dispatch_uid='wea_notif_contact_post')
def on_contact_post_save(sender, instance, created, raw=False, **kwargs):
    if raw:
        return
    try:
        url = _safe_url('contact_detail', pk=instance.pk)
        if created:
            fmt = build_arabic_notification(
                event_code='contacts.contact_created',
                target_obj=instance,
                actor=instance.created_by,
            )
            NotificationService.emit(
                event_code='contacts.contact_created',
                target_obj=instance,
                actor=instance.created_by,
                title=fmt['title'],
                body=fmt['body'],
                route_key=fmt['route_key'],
                action_url=url or fmt['action_url'],
                metadata=fmt['metadata'],
                dedupe_key=f"contact_created:{instance.pk}",
            )
            return

        prev = getattr(instance, '_prev_contact_state', None)
        if not prev:
            return
        if prev.get('status') != instance.status:
            fmt = build_arabic_notification(
                event_code='contacts.contact_status_changed',
                target_obj=instance,
                extra={'old_status': prev.get('status'), 'new_status': instance.status},
            )
            NotificationService.emit(
                event_code='contacts.contact_status_changed',
                target_obj=instance,
                title=fmt['title'],
                body=fmt['body'],
                route_key=fmt['route_key'],
                action_url=url or fmt['action_url'],
                metadata=fmt['metadata'],
                dedupe_key=f"contact_status:{instance.pk}:{instance.status}:{timezone.now().date().isoformat()}",
            )
        prev_credit = Decimal(str(prev.get('credit_limit') or 0))
        curr_credit = Decimal(str(instance.credit_limit or 0))
        if prev_credit != curr_credit:
            fmt = build_arabic_notification(
                event_code='contacts.contact_credit_changed',
                target_obj=instance,
                extra={'old_limit': prev_credit, 'new_limit': curr_credit},
            )
            NotificationService.emit(
                event_code='contacts.contact_credit_changed',
                target_obj=instance,
                title=fmt['title'],
                body=fmt['body'],
                route_key=fmt['route_key'],
                action_url=url or fmt['action_url'],
                metadata=fmt['metadata'],
                dedupe_key=f"contact_credit:{instance.pk}:{curr_credit}",
            )
    except Exception:
        logger.exception("Contact notification signal error")


# --- Contact Todos ---
@receiver(post_save, sender=ContactTodo, dispatch_uid='wea_notif_contact_todo')
def on_contact_todo_created(sender, instance, created, raw=False, **kwargs):
    if raw or not created:
        return
    try:
        contact = instance.contact
        fmt = build_arabic_notification(
            event_code='contacts.todo_assigned',
            target_obj=contact,
            actor=instance.created_by,
            extra={'todo_title': instance.title, 'due_date': instance.due_date},
        )
        NotificationService.emit(
            event_code='contacts.todo_assigned',
            target_obj=contact,
            actor=instance.created_by,
            title=fmt['title'],
            body=fmt['body'],
            route_key=fmt['route_key'],
            action_url=fmt['action_url'] if contact else _safe_url('agenda'),
            extra_owner_ids=[contact.created_by_id] if contact and contact.created_by_id else None,
            metadata=fmt['metadata'],
            dedupe_key=f"contact_todo:{instance.pk}",
        )
    except Exception:
        logger.exception("ContactTodo notification signal error")


# --- Product Price Change ---
@receiver(pre_save, sender=Product, dispatch_uid='wea_notif_product_pre')
def on_product_pre_save(sender, instance, raw=False, **kwargs):
    if raw or not instance.pk:
        instance._prev_retail_price = None
        return
    try:
        instance._prev_retail_price = Product.objects.filter(pk=instance.pk).values_list('retail_price', flat=True).first()
    except Exception:
        instance._prev_retail_price = None


@receiver(post_save, sender=Product, dispatch_uid='wea_notif_product_post')
def on_product_post_save(sender, instance, created, raw=False, **kwargs):
    if raw or created:
        return
    try:
        prev = getattr(instance, '_prev_retail_price', None)
        if prev is not None and Decimal(str(prev)) != Decimal(str(instance.retail_price or 0)):
            fmt = build_arabic_notification(
                event_code='catalog.product_price_changed',
                target_obj=instance,
                extra={'old_price': prev, 'new_price': instance.retail_price or 0},
            )
            NotificationService.emit(
                event_code='catalog.product_price_changed',
                target_obj=instance,
                title=fmt['title'],
                body=fmt['body'],
                route_key=fmt['route_key'],
                action_url=_safe_url('product_detail', pk=instance.pk) or fmt['action_url'],
                metadata=fmt['metadata'],
                dedupe_key=f"product_price:{instance.pk}:{instance.retail_price}",
            )
    except Exception:
        logger.exception("Product price notification signal error")


# --- Inventory Low Stock Alert ---
@receiver(pre_save, sender=InventoryStock, dispatch_uid='wea_notif_stock_pre')
def on_stock_pre_save(sender, instance, raw=False, **kwargs):
    if raw or not instance.pk:
        instance._prev_qty_on_hand = None
        return
    try:
        instance._prev_qty_on_hand = InventoryStock.objects.filter(pk=instance.pk).values_list('qty_on_hand', flat=True).first()
    except Exception:
        instance._prev_qty_on_hand = None


@receiver(post_save, sender=InventoryStock, dispatch_uid='wea_notif_stock_post')
def on_stock_post_save(sender, instance, created, raw=False, **kwargs):
    if raw:
        return
    try:
        threshold = Decimal('5.00')
        prev_qty = getattr(instance, '_prev_qty_on_hand', None)
        curr_qty = Decimal(str(instance.qty_on_hand or 0))
        if curr_qty <= threshold and (prev_qty is None or Decimal(str(prev_qty)) > threshold):
            fmt = build_arabic_notification(
                event_code='inventory.low_stock_alert',
                target_obj=instance,
            )
            NotificationService.emit(
                event_code='inventory.low_stock_alert',
                target_obj=instance,
                title=fmt['title'],
                body=fmt['body'],
                route_key=fmt['route_key'],
                action_url=_safe_url('inventory_stock_list') or fmt['action_url'],
                metadata=fmt['metadata'],
                dedupe_key=f"low_stock:{instance.pk}:{timezone.now().date().isoformat()}",
            )
    except Exception:
        logger.exception("InventoryStock low-stock notification signal error")


# --- Reports: Sales Targets & Coaching Evaluations ---
@receiver(post_save, sender=SalesTarget, dispatch_uid='wea_notif_sales_target')
def on_sales_target_saved(sender, instance, created, raw=False, **kwargs):
    if raw:
        return
    try:
        fmt = build_arabic_notification(
            event_code='reports.target_assigned',
            target_obj=instance,
            actor=instance.created_by,
        )
        NotificationService.emit(
            event_code='reports.target_assigned',
            target_obj=instance,
            actor=instance.created_by,
            title=fmt['title'],
            body=fmt['body'],
            route_key=fmt['route_key'],
            action_url=_safe_url('performance_overview') or fmt['action_url'],
            extra_owner_ids=[instance.user_id] if instance.user_id else None,
            metadata=fmt['metadata'],
            dedupe_key=f"sales_target:{instance.pk}:{instance.updated_at.strftime('%Y%m%d%H%M') if instance.updated_at else ''}",
        )
    except Exception:
        logger.exception("SalesTarget notification signal error")


@receiver(post_save, sender=CoachingEvaluation, dispatch_uid='wea_notif_coaching')
def on_coaching_evaluation_created(sender, instance, created, raw=False, **kwargs):
    if raw or not created:
        return
    try:
        fmt = build_arabic_notification(
            event_code='reports.coaching_evaluated',
            target_obj=instance,
            actor=instance.manager,
        )
        NotificationService.emit(
            event_code='reports.coaching_evaluated',
            target_obj=instance,
            actor=instance.manager,
            title=fmt['title'],
            body=fmt['body'],
            route_key=fmt['route_key'],
            action_url=_safe_url('performance_detailed') or fmt['action_url'],
            extra_owner_ids=[instance.rep_id] if instance.rep_id else None,
            metadata=fmt['metadata'],
            dedupe_key=f"coaching:{instance.pk}",
        )
    except Exception:
        logger.exception("CoachingEvaluation notification signal error")
