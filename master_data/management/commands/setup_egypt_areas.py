from django.core.management.base import BaseCommand
from master_data.models import Area
from django.db.models import Count


EGYPT_GOVERNORATES = [
    {'code': '01', 'name': 'محافظة القاهرة', 'name_en': 'Cairo'},
    {'code': '02', 'name': 'محافظة الإسكندرية', 'name_en': 'Alexandria'},
    {'code': '03', 'name': 'محافظة الجيزة', 'name_en': 'Giza'},
    {'code': '04', 'name': 'محافظة بورسعيد', 'name_en': 'Port Said'},
    {'code': '05', 'name': 'محافظة السويس', 'name_en': 'Suez'},
    {'code': '06', 'name': 'محافظة الإسماعيلية', 'name_en': 'Ismailia'},
    {'code': '07', 'name': 'محافظة القليوبية', 'name_en': 'Qalyubia'},
    {'code': '08', 'name': 'محافظة الشرقية', 'name_en': 'Sharkia'},
    {'code': '09', 'name': 'محافظة الغربية', 'name_en': 'Gharbia'},
    {'code': '10', 'name': 'محافظة المنوفية', 'name_en': 'Monufia'},
    {'code': '11', 'name': 'محافظة الدقهلية', 'name_en': 'Dakahlia'},
    {'code': '12', 'name': 'محافظة كفر الشيخ', 'name_en': 'Kafr El Sheikh'},
    {'code': '13', 'name': 'محافظة دمياط', 'name_en': 'Damietta'},
    {'code': '14', 'name': 'محافظة البحيرة', 'name_en': 'Beheira'},
    {'code': '15', 'name': 'محافظة الفيوم', 'name_en': 'Faiyum'},
    {'code': '16', 'name': 'محافظة بني سويف', 'name_en': 'Beni Suef'},
    {'code': '17', 'name': 'محافظة المنيا', 'name_en': 'Minya'},
    {'code': '18', 'name': 'محافظة أسيوط', 'name_en': 'Asyut'},
    {'code': '19', 'name': 'محافظة سوهاج', 'name_en': 'Sohag'},
    {'code': '20', 'name': 'محافظة قنا', 'name_en': 'Qena'},
    {'code': '21', 'name': 'محافظة الأقصر', 'name_en': 'Luxor'},
    {'code': '22', 'name': 'محافظة البحر الأحمر', 'name_en': 'Red Sea'},
    {'code': '23', 'name': 'محافظة اسوان', 'name_en': 'Aswan'},
    {'code': '24', 'name': 'محافظة الوادي الجديد', 'name_en': 'New Valley'},
    {'code': '25', 'name': 'محافظة مطروح', 'name_en': 'Matrouh'},
    {'code': '26', 'name': 'محافظة شمال سيناء', 'name_en': 'North Sinai'},
    {'code': '27', 'name': 'محافظة جنوب سيناء', 'name_en': 'South Sinai'},
]

COMPANY_AREA_CODES = ['29', '30', '31', '99999999']


class Command(BaseCommand):
    help = "Populates and standardizes Egyptian governorates hierarchy without modifying company areas."

    def handle(self, *args, **options):
        # 1. Mark and isolate company internal locations safely
        co_areas = Area.objects.filter(code__in=COMPANY_AREA_CODES)
        co_areas.update(is_company_area=True)
        Area.objects.filter(parent__in=co_areas).update(is_company_area=True)
        self.stdout.write(self.style.SUCCESS(f"Preserved {co_areas.count()} company internal areas."))

        # 2. Synchronize the 27 Egyptian Governorates
        created_count = 0
        updated_count = 0

        for gov_data in EGYPT_GOVERNORATES:
            area = Area.objects.filter(code=gov_data['code']).first()
            if not area:
                # Also check by name to prevent duplication
                area = Area.objects.filter(name=gov_data['name'], parent__isnull=True).first()

            if area:
                area.name = gov_data['name']
                area.name_en = gov_data['name_en']
                area.area_type = 'governorate'
                area.is_company_area = False
                area.save()
                updated_count += 1
            else:
                Area.objects.create(
                    code=gov_data['code'],
                    name=gov_data['name'],
                    name_en=gov_data['name_en'],
                    area_type='governorate',
                    is_company_area=False,
                    parent=None
                )
                created_count += 1

        self.stdout.write(self.style.SUCCESS(
            f"Egyptian Governorates initialized: {created_count} created, {updated_count} updated."
        ))

        # 3. Print verification report
        govs = Area.objects.filter(parent__isnull=True, is_company_area=False).annotate(sub_cnt=Count('subareas')).order_by('code')
        self.stdout.write(f"Active Egyptian Governorates total: {govs.count()}")
        for g in govs:
            self.stdout.write(f"  [{g.code}] {g.name} ({g.name_en}) - {g.sub_cnt} subareas")
