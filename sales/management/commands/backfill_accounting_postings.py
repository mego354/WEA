import json
from decimal import Decimal
from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from sales.models import SalesOrder, SalesReturnOrder, CustomerAccount, CustomerTransaction
from sales.services import find_existing_sales_order_transaction, find_existing_sales_return_transaction
from purchases.models import PurchaseOrder, PurchaseReturnOrder
from purchases.services import find_existing_purchase_order_transaction, find_existing_purchase_return_transaction
from treasury.models import VendorAccount, VendorTransaction


class Command(BaseCommand):
    help = (
        "Idempotent accounting posting backfill & status reconciliation. "
        "Links existing ledger records to orders without double-posting or mutating reconciled balances."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--apply',
            action='store_true',
            help='Apply status reconciliation for orders that already have a confirmed ledger entry. Without --apply runs in dry-run mode.',
        )
        parser.add_argument(
            '--report-json',
            type=str,
            default='',
            help='Optional path to write a detailed JSON backfill report.',
        )

    def handle(self, *args, **options):
        apply_changes = options['apply']
        report_path = options['report_json']

        before_cust_sum = CustomerAccount.objects.aggregate(s=Sum('current_balance'))['s'] or Decimal('0.00')
        before_vend_sum = VendorAccount.objects.aggregate(s=Sum('current_balance'))['s'] or Decimal('0.00')
        before_ct_count = CustomerTransaction.objects.count()
        before_vt_count = VendorTransaction.objects.count()

        report = {
            'mode': 'APPLY' if apply_changes else 'DRY_RUN',
            'timestamp': timezone.now().isoformat(),
            'linked_and_reconciled': [],
            'newly_posted': [],
            'skipped_already_terminal': {'sales_orders': 0, 'sales_returns': 0, 'purchase_orders': 0, 'purchase_returns': 0},
            'skipped_historical_reconciled': [],
            'unresolved_pending': [],
            'balance_verification': {},
        }

        # 1. Sales Orders
        with transaction.atomic():
            for so in SalesOrder.objects.select_related('customer', 'memo').exclude(status__in=['cancelled', 'rejected']).order_by('id'):
                tx = find_existing_sales_order_transaction(so)
                if so.status == 'invoiced':
                    if tx:
                        report['skipped_already_terminal']['sales_orders'] += 1
                    else:
                        report['skipped_historical_reconciled'].append({
                            'entity': 'SalesOrder',
                            'id': so.id,
                            'order_number': so.order_number,
                            'status': so.status,
                            'date': str(so.order_date),
                            'grand_total': str(so.grand_total),
                            'reason': 'Historical already-invoiced order preserved without mutating reconciled WEA customer balance.',
                        })
                    continue

                if tx:
                    old_status = so.status
                    if apply_changes:
                        so.status = 'invoiced'
                        so.save(update_fields=['status', 'updated_at'])
                    report['linked_and_reconciled'].append({
                        'entity': 'SalesOrder',
                        'id': so.id,
                        'order_number': so.order_number,
                        'old_status': old_status,
                        'new_status': 'invoiced',
                        'existing_transaction_serial': tx.serial,
                        'grand_total': str(so.grand_total),
                        'balance_mutated': False,
                    })
                else:
                    report['unresolved_pending'].append({
                        'entity': 'SalesOrder',
                        'id': so.id,
                        'order_number': so.order_number,
                        'status': so.status,
                        'customer': so.customer.name,
                        'date': str(so.order_date),
                        'grand_total': str(so.grand_total),
                        'has_memo': bool(so.memo_id),
                        'reason': 'Open non-invoiced order with no matching CustomerTransaction; requires manual business review (not force-posted).',
                    })

            # 2. Sales Return Orders
            for sro in SalesReturnOrder.objects.select_related('customer', 'memo').exclude(status__in=['cancelled', 'rejected']).order_by('id'):
                tx = find_existing_sales_return_transaction(sro)
                if sro.status == 'settled':
                    if tx:
                        report['skipped_already_terminal']['sales_returns'] += 1
                    else:
                        report['skipped_historical_reconciled'].append({
                            'entity': 'SalesReturnOrder',
                            'id': sro.id,
                            'order_number': sro.order_number,
                            'status': sro.status,
                            'date': str(sro.order_date),
                            'grand_total': str(sro.grand_total),
                            'reason': 'Historical already-settled return preserved without mutating reconciled WEA customer balance.',
                        })
                    continue

                if tx:
                    old_status = sro.status
                    if apply_changes:
                        sro.status = 'settled'
                        if not sro.settled_at:
                            sro.settled_at = timezone.now()
                        sro.save(update_fields=['status', 'settled_at', 'updated_at'])
                    report['linked_and_reconciled'].append({
                        'entity': 'SalesReturnOrder',
                        'id': sro.id,
                        'order_number': sro.order_number,
                        'old_status': old_status,
                        'new_status': 'settled',
                        'existing_transaction_serial': tx.serial,
                        'grand_total': str(sro.grand_total),
                        'balance_mutated': False,
                    })
                else:
                    report['unresolved_pending'].append({
                        'entity': 'SalesReturnOrder',
                        'id': sro.id,
                        'order_number': sro.order_number,
                        'status': sro.status,
                        'customer': sro.customer.name,
                        'date': str(sro.order_date),
                        'grand_total': str(sro.grand_total),
                        'has_memo': bool(sro.memo_id),
                        'reason': 'Open pending return with no warehouse memo and no CustomerTransaction; awaiting manager decision (not force-posted).',
                    })

            # 3. Purchase Orders
            for po in PurchaseOrder.objects.select_related('supplier', 'memo').exclude(status__in=['cancelled', 'rejected']).order_by('id'):
                tx = find_existing_purchase_order_transaction(po)
                if po.status == 'settled':
                    if tx:
                        report['skipped_already_terminal']['purchase_orders'] += 1
                    else:
                        report['skipped_historical_reconciled'].append({
                            'entity': 'PurchaseOrder',
                            'id': po.id,
                            'order_number': po.order_number,
                            'status': po.status,
                            'date': str(po.order_date),
                            'grand_total': str(po.grand_total),
                            'reason': 'Historical settled PO preserved without mutating reconciled WEA supplier balance.',
                        })
                    continue

                if tx:
                    old_status = po.status
                    if apply_changes:
                        po.status = 'settled'
                        if not po.invoiced_at:
                            po.invoiced_at = timezone.now()
                        po.save(update_fields=['status', 'invoiced_at', 'updated_at'])
                    report['linked_and_reconciled'].append({
                        'entity': 'PurchaseOrder',
                        'id': po.id,
                        'order_number': po.order_number,
                        'old_status': old_status,
                        'new_status': 'settled',
                        'existing_transaction_serial': tx.serial,
                        'grand_total': str(po.grand_total),
                        'balance_mutated': False,
                    })
                elif (po.grand_total or Decimal('0.00')) == Decimal('0.00'):
                    report['skipped_historical_reconciled'].append({
                        'entity': 'PurchaseOrder',
                        'id': po.id,
                        'order_number': po.order_number,
                        'status': po.status,
                        'date': str(po.order_date),
                        'grand_total': str(po.grand_total),
                        'reason': 'Zero-total historical PO; no financial entry required.',
                    })
                else:
                    report['unresolved_pending'].append({
                        'entity': 'PurchaseOrder',
                        'id': po.id,
                        'order_number': po.order_number,
                        'status': po.status,
                        'supplier': po.supplier.name,
                        'date': str(po.order_date),
                        'grand_total': str(po.grand_total),
                        'has_memo': bool(po.memo_id),
                        'reason': 'Non-settled PO with no VendorTransaction; requires review.',
                    })

            # 4. Purchase Return Orders
            for pro in PurchaseReturnOrder.objects.select_related('supplier', 'memo').exclude(status__in=['cancelled', 'rejected']).order_by('id'):
                tx = find_existing_purchase_return_transaction(pro)
                if pro.status == 'settled':
                    report['skipped_already_terminal']['purchase_returns'] += 1
                elif tx:
                    old_status = pro.status
                    if apply_changes:
                        pro.status = 'settled'
                        if not pro.settled_at:
                            pro.settled_at = timezone.now()
                        pro.save(update_fields=['status', 'settled_at', 'updated_at'])
                    report['linked_and_reconciled'].append({
                        'entity': 'PurchaseReturnOrder',
                        'id': pro.id,
                        'order_number': pro.order_number,
                        'old_status': old_status,
                        'new_status': 'settled',
                        'existing_transaction_serial': tx.serial,
                        'grand_total': str(pro.grand_total),
                        'balance_mutated': False,
                    })
                else:
                    report['unresolved_pending'].append({
                        'entity': 'PurchaseReturnOrder',
                        'id': pro.id,
                        'order_number': pro.order_number,
                        'status': pro.status,
                        'supplier': pro.supplier.name,
                        'date': str(pro.order_date),
                        'grand_total': str(pro.grand_total),
                        'has_memo': bool(pro.memo_id),
                        'reason': 'Non-settled purchase return with no VendorTransaction; requires review.',
                    })

        after_cust_sum = CustomerAccount.objects.aggregate(s=Sum('current_balance'))['s'] or Decimal('0.00')
        after_vend_sum = VendorAccount.objects.aggregate(s=Sum('current_balance'))['s'] or Decimal('0.00')
        after_ct_count = CustomerTransaction.objects.count()
        after_vt_count = VendorTransaction.objects.count()

        report['balance_verification'] = {
            'customer_balance_before': str(before_cust_sum),
            'customer_balance_after': str(after_cust_sum),
            'customer_balance_unchanged': before_cust_sum == after_cust_sum,
            'vendor_balance_before': str(before_vend_sum),
            'vendor_balance_after': str(after_vend_sum),
            'vendor_balance_unchanged': before_vend_sum == after_vend_sum,
            'customer_tx_count_before': before_ct_count,
            'customer_tx_count_after': after_ct_count,
            'vendor_tx_count_before': before_vt_count,
            'vendor_tx_count_after': after_vt_count,
        }

        if report_path:
            with open(report_path, 'w', encoding='utf-8') as fh:
                json.dump(report, fh, ensure_ascii=False, indent=2)

        self.stdout.write(self.style.SUCCESS(f"=== Backfill Report ({report['mode']}) ==="))
        self.stdout.write(f"Linked & Reconciled (zero balance mutation): {len(report['linked_and_reconciled'])}")
        self.stdout.write(f"Newly Posted: {len(report['newly_posted'])}")
        self.stdout.write(f"Already Terminal & Matched: {report['skipped_already_terminal']}")
        self.stdout.write(f"Skipped Historical Reconciled: {len(report['skipped_historical_reconciled'])}")
        self.stdout.write(f"Unresolved Pending (manual review): {len(report['unresolved_pending'])}")
        for item in report['unresolved_pending']:
            self.stdout.write(f"  - {item['entity']} {item['order_number']} ({item['status']}, {item['grand_total']} EGP): {item['reason']}")
        self.stdout.write(f"Balance Parity Verified: customer={report['balance_verification']['customer_balance_unchanged']}, vendor={report['balance_verification']['vendor_balance_unchanged']}")
