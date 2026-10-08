import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
import django
django.setup()

from master_data.models import Area

# List of areas from reference ERP
reference_areas = [
    "NA",
    "WEA",
    "WEA Stores Great cairo",
    "WEA Stores Upper Egypt",
    "اونلاين",
    "محافظة اسوان",
    "محافظة اسيوط",
    "محافظة الاسكندرية",
    "محافظة الاسماعيلية",
    "محافظة الاقصر",
    "محافظة البحر الاحمر",
    "محافظة البحيرة",
    "محافظة الجيزة",
    "محافظة الدقهلية",
    "محافظة السويس",
    "محافظة الشرقية",
    "محافظة الغربية",
    "محافظة الفيوم",
    "محافظة القاهرة",
    "محافظة القليوبية",
    "محافظة المنوفية",
    "محافظة المنيا",
    "محافظة الوادي الجديد",
    "محافظة بني سويف",
    "محافظة بورسعيد",
    "محافظة جنوب سيناء",
    "محافظة دمياط",
    "محافظة سوهاج",
    "محافظة شمال سيناء",
    "محافظة قنا",
    "محافظة كفر الشيخ",
    "محافظة مطروح",
    "موردين"
]

# Sample Subareas for key governorates
subareas_map = {
    "محافظة القاهرة": [
        "مدينة نصر", "مصر الجديدة", "المعادي", "التجمع الخامس", "القاهرة الجديدة", "شبرا", "المقطم", "وسط البلد", "حلوان", "الزمالك", "عين شمس", "المرج", "العباسية"
    ],
    "محافظة الجيزة": [
        "الدقي", "المهندسين", "العجوزة", "الهرم", "فيصل", "6 أكتوبر", "الشيخ زايد", "حدائق الأهرام", "العمرانية", "الحوامدية", "البدرشين"
    ],
    "محافظة الاسكندرية": [
        "سموحة", "محطة الرمل", "ميامي", "سيدي جابر", "المنتزه", "العجمي", "لوران", "الإبراهيمية", "العطارين"
    ],
    "محافظة القليوبية": [
        "شبرا الخيمة", "بنها", "قليوب", "الخانكة", "القناطر الخيرية", "طوخ"
    ],
    "محافظة الغربية": [
        "طنطا", "المحلة الكبرى", "زفتى", "كفر الزيات", "سمنود"
    ],
    "محافظة الدقهلية": [
        "المنصورة", "ميت غمر", "السنبلاوين", "دكرنس", "بلقاس"
    ],
    "محافظة الشرقية": [
        "الزقازيق", "العاشر من رمضان", "بلبيس", "فاقوس", "أبو كبير"
    ]
}

created_gov = 0
for idx, name in enumerate(reference_areas, start=1):
    code = f"GOV-{idx:03d}"
    gov, created = Area.objects.get_or_create(
        name=name,
        defaults={
            'code': code,
            'area_type': 'governorate'
        }
    )
    if created:
        created_gov += 1

    # Add subareas if defined
    if name in subareas_map:
        for s_idx, s_name in enumerate(subareas_map[name], start=1):
            sub_code = f"{gov.code}-SUB-{s_idx:02d}"
            Area.objects.get_or_create(
                name=s_name,
                parent=gov,
                defaults={
                    'code': sub_code,
                    'area_type': 'subarea'
                }
            )

print(f"Seeding completed. Total governorates created: {created_gov}, Total Areas: {Area.objects.count()}")
