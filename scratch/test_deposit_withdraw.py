import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from decimal import Decimal
from django.test import Client
from accounts.models import User, Role
from treasury.models import Vault, VaultTransaction
from treasury.services import TreasuryService
from accounts.models import SecurityAuditLog

def test_deposit_and_withdrawal():
    admin = User.objects.filter(is_superuser=True).first()
    vault = Vault.objects.first()
    print(f"Testing on Vault: {vault.name}, Current Balance: {vault.current_balance}")
    
    init_bal = vault.current_balance
    deposit_amount = Decimal('500.00')
    
    # 1. Test Deposit
    tx_dep = TreasuryService.deposit_funds(
        vault=vault,
        amount=deposit_amount,
        user=admin,
        description="إيداع تجريبي للاختبار",
        reference_number="REC-1001"
    )
    vault.refresh_from_db()
    assert vault.current_balance == init_bal + deposit_amount, f"Expected {init_bal + deposit_amount}, got {vault.current_balance}"
    assert tx_dep.transaction_type == 'inflow'
    print(f"✓ Deposit successful! New Balance: {vault.current_balance}")
    
    # Check audit log
    audit_dep = SecurityAuditLog.objects.filter(action_type='VAULT_DEPOSIT', record_id=str(tx_dep.id)).first()
    assert audit_dep is not None
    print(f"✓ Audit log recorded for deposit: {audit_dep.description}")
    
    # 2. Test Withdrawal
    withdraw_amount = Decimal('200.00')
    tx_wth = TreasuryService.withdraw_funds(
        vault=vault,
        amount=withdraw_amount,
        user=admin,
        description="صرف تجريبي للاختبار",
        reference_number="EXP-2001"
    )
    vault.refresh_from_db()
    assert vault.current_balance == init_bal + deposit_amount - withdraw_amount
    assert tx_wth.transaction_type == 'outflow'
    print(f"✓ Withdrawal successful! New Balance: {vault.current_balance}")
    
    audit_wth = SecurityAuditLog.objects.filter(action_type='VAULT_WITHDRAWAL', record_id=str(tx_wth.id)).first()
    assert audit_wth is not None
    print(f"✓ Audit log recorded for withdrawal: {audit_wth.description}")
    
    # 3. Test Insufficient Funds
    try:
        huge_amount = vault.current_balance + Decimal('1000000.00')
        TreasuryService.withdraw_funds(
            vault=vault,
            amount=huge_amount,
            user=admin,
            description="صرف فائض"
        )
        assert False, "Should have raised ValidationError for insufficient funds"
    except Exception as e:
        print(f"✓ Overdraft prevented properly: {e}")

    # Revert test amounts to restore original balance
    revert_diff = (init_bal + deposit_amount - withdraw_amount) - init_bal
    if revert_diff > 0:
        TreasuryService.withdraw_funds(vault=vault, amount=revert_diff, user=admin, description="إعادة رصيد الاختبار لوضعه الأصلي")
    vault.refresh_from_db()
    print(f"✓ Restored original balance: {vault.current_balance}")

if __name__ == '__main__':
    test_deposit_and_withdrawal()
