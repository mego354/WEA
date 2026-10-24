import os
from django.core.management.base import BaseCommand
from django.utils import timezone
from django.contrib.auth import get_user_model
from activities.models import (
    AgreementType, Agreement, VisitTemplate,
    PlannedVisitDay, PlannedVisitItem, Visit, VisitSampleItem
)
from contacts.models import Contact
from catalog.models import Product

User = get_user_model()


class Command(BaseCommand):
    help = "Seed Activities module reference data (Agreement types, Visit templates, initial activities)"

    def handle(self, *args, **options):
        self.stdout.write("Seeding Agreement Types...")
        agreement_types = [
            ("Conference", "مؤتمرات"),
            ("Cash money", "نقدي"),
            ("Devices", "أجهزة طبية"),
            ("Gifts", "هدايا عينية"),
            ("RTD", "طاولة نقاش مستديرة"),
            ("Rx", "روشتات"),
            ("Others", "أخرى"),
        ]
        for name, ar in agreement_types:
            at, created = AgreementType.objects.get_or_create(
                name=name,
                defaults={'display_name_ar': ar, 'is_active': True}
            )
            if created:
                self.stdout.write(f"  Created AgreementType: {name}")

        self.stdout.write("Seeding Visit Templates...")
        templates_data = [
            {
                "name": "Single visit (Pharmacy)",
                "display_name_ar": "زيارة لصيدلية (Single visit - Pharmacy)",
                "display_name_en": "Single visit (Pharmacy)",
                "restrict_account_types": ["Pharmacy", "Pharmacist"],
                "questionnaire": {
                    "questions": [
                        {"order": 1, "title": "Products stock", "type": "narrative"},
                        {"order": 2, "title": "Competitors feedback", "type": "narrative"},
                        {"order": 3, "title": "Order taken ??", "type": "mcq_single", "options": ["Yes", "No"]},
                        {"order": 4, "title": "Write the order", "type": "narrative"}
                    ]
                }
            },
            {
                "name": "Store & Distributor visit",
                "display_name_ar": "زيارة مخزن وشركة توزيع",
                "display_name_en": "Store & Distributor visit",
                "restrict_account_types": ["Drug Store", "Distributor"],
                "questionnaire": {
                    "questions": [
                        {"order": 1, "title": "Store feedback (sales & stock & order & collection)", "type": "narrative"}
                    ]
                }
            },
            {
                "name": "Healthy day",
                "display_name_ar": "يوم طبي (Healthy day)",
                "display_name_en": "Healthy day",
                "restrict_account_types": ["Clinic", "Pharmacy", "Polyclinic"],
                "questionnaire": {
                    "questions": [
                        {"order": 1, "title": "ما هي نتائج اليوم ( روشتات & بيع ) ؟", "type": "narrative"}
                    ]
                }
            },
            {
                "name": "Coaching visit (DR)",
                "display_name_ar": "زيارة تدريبية / مشتركة مع طبيب",
                "display_name_en": "Coaching visit (DR)",
                "restrict_account_types": ["Clinic", "Hospital", "Physician", "Center"],
                "questionnaire": {
                    "questions": [
                        {"order": 1, "title": "Did you meet the Dr ?", "type": "true_false"},
                        {"order": 2, "title": "Set an objective for the visit ?", "type": "true_false"},
                        {"order": 3, "title": "Good relationship with dr & assistant?", "type": "true_false"},
                        {"order": 4, "title": "Promotional Plan", "type": "true_false"},
                        {"order": 5, "title": "Detailing & Focus on selling points", "type": "true_false"},
                        {"order": 6, "title": "Handling Objections", "type": "narrative"},
                        {"order": 7, "title": "General feedback", "type": "narrative"}
                    ]
                }
            },
            {
                "name": "Single visit (DR)",
                "display_name_ar": "زيارة فردية لطبيب (Single visit - DR)",
                "display_name_en": "Single visit (DR)",
                "restrict_account_types": ["Clinic", "Hospital", "Physician", "Polyclinic"],
                "questionnaire": {
                    "questions": [
                        {"order": 1, "title": "Did you meet the Dr ?", "type": "mcq_single", "options": ["Yes", "No"]},
                        {"order": 2, "title": "What happened in the visit ?", "type": "narrative"},
                        {"order": 3, "title": "Reason for not visiting ?", "type": "narrative"},
                        {"order": 4, "title": "Dr need", "type": "narrative"}
                    ]
                }
            },
            {
                "name": "Coaching visit (Pharmacy)",
                "display_name_ar": "زيارة تدريبية لصيدلية (Coaching visit - Pharmacy)",
                "display_name_en": "Coaching visit (Pharmacy)",
                "restrict_account_types": ["Pharmacy"],
                "questionnaire": {
                    "questions": [
                        {"order": 1, "title": "Feedback about all products", "type": "true_false"},
                        {"order": 2, "title": "Accurate feedback ( Dr & Product & Rate )", "type": "true_false"},
                        {"order": 3, "title": "Competitors feedback", "type": "true_false"},
                        {"order": 4, "title": "General Pharmacy feedback", "type": "narrative"}
                    ]
                }
            }
        ]

        for t_info in templates_data:
            vt, created = VisitTemplate.objects.get_or_create(
                name=t_info["name"],
                defaults={
                    "display_name_ar": t_info["display_name_ar"],
                    "display_name_en": t_info["display_name_en"],
                    "restrict_account_types": t_info["restrict_account_types"],
                    "questionnaire": t_info["questionnaire"],
                    "active": True
                }
            )
            if created:
                self.stdout.write(f"  Created VisitTemplate: {t_info['name']}")

        admin_user = User.objects.filter(is_superuser=True).first() or User.objects.first()
        contacts = list(Contact.objects.all()[:15])

        if admin_user and contacts:
            # Seed Agreements if none exist
            if not Agreement.objects.exists():
                self.stdout.write("Seeding sample Agreements...")
                cash_type = AgreementType.objects.filter(name="Cash money").first()
                sample_agreements = [
                    (222, "تحويل 2000 ج مقابل كتابات جيرون", 2000, "new", contacts[0] if len(contacts) > 0 else None),
                    (221, "تم تحويل 800 ج مقابل 40 علبة الترا هيوميدين", 800, "approved", contacts[1] if len(contacts) > 1 else None),
                    (220, "1000 ج مقابل 80 علبة بيوتالاكسي صيدليات جزيرة محمد", 1000, "approved", contacts[2] if len(contacts) > 2 else None),
                    (219, "مؤتمر الجمعية المصرية لطب الأطفال", 5000, "done", contacts[3] if len(contacts) > 3 else None),
                    (218, "دعم علمي وعينات طبية", 1500, "disapproved", contacts[4] if len(contacts) > 4 else None),
                ]
                for snum, title, amt, st, c in sample_agreements:
                    if c:
                        Agreement.objects.create(
                            serial_num=snum,
                            title=title,
                            description=f"<p>{title}</p>",
                            type=cash_type,
                            amount=amt,
                            status=st,
                            customer=c,
                            date=timezone.now().date(),
                            created_by=admin_user,
                            updated_by=admin_user
                        )

            # Seed Planned Visits if none exist
            today = timezone.now().date()
            if not PlannedVisitDay.objects.filter(assignee=admin_user, date=today).exists():
                self.stdout.write("Seeding sample Planned Visit Day...")
                pday = PlannedVisitDay.objects.create(
                    assignee=admin_user,
                    date=today,
                    status="new",
                    created_by=admin_user
                )
                dr_template = VisitTemplate.objects.filter(name="Single visit (DR)").first()
                for idx, c in enumerate(contacts[:3], 1):
                    PlannedVisitItem.objects.create(
                        plan_day=pday,
                        order=idx,
                        contact=c,
                        template=dr_template,
                        notes=f"زيارة دورية للعميل #{idx}"
                    )

            # Seed Visits if none exist
            if not Visit.objects.exists():
                self.stdout.write("Seeding sample Visits...")
                dr_template = VisitTemplate.objects.filter(name="Single visit (DR)").first()
                pharm_template = VisitTemplate.objects.filter(name="Single visit (Pharmacy)").first()
                products = list(Product.objects.all()[:3])

                v1 = Visit.objects.create(
                    serial_num=76948,
                    contact=contacts[0],
                    template=pharm_template,
                    owner=admin_user,
                    is_planned=False,
                    date=today,
                    visit_time=timezone.now(),
                    started_at=timezone.now() - timezone.timedelta(minutes=15),
                    ended_at=timezone.now(),
                    duration=900,
                    status='finished',
                    approval_status='pending',
                    is_successful=True,
                    doubled=False,
                    feedback="تم التواصل مع الصيدلي والتأكد من توافر المستحضرات وتدوين طلبية جديدة.",
                    questionnaire_answers={"Products stock": "متوفر بالكامل", "Order taken ??": "Yes", "Write the order": "10 علب بيوتالاكس"},
                    created_by=admin_user
                )
                if products:
                    VisitSampleItem.objects.create(visit=v1, product=products[0], quantity=2)

                v2 = Visit.objects.create(
                    serial_num=76949,
                    contact=contacts[1] if len(contacts) > 1 else contacts[0],
                    template=dr_template,
                    owner=admin_user,
                    is_planned=True,
                    date=today,
                    visit_time=timezone.now(),
                    started_at=timezone.now() - timezone.timedelta(minutes=30),
                    ended_at=timezone.now() - timezone.timedelta(minutes=10),
                    duration=1200,
                    status='finished',
                    approval_status='approved',
                    is_successful=True,
                    doubled=True,
                    feedback="مقابلة الطبيب وشرح الخطة الترويجية الجديدة ودعم الحالات.",
                    questionnaire_answers={"Did you meet the Dr ?": "Yes", "What happened in the visit ?": "شرح كامل للمنتجات"},
                    created_by=admin_user,
                    approved_by=admin_user
                )

        self.stdout.write(self.style.SUCCESS("Activities reference data seeded successfully!"))
