import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

import django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from activities.models import VisitTemplate, VisitTemplateQuestion

TEMPLATES_DATA = [
    {
        'name': 'single_visit_dr',
        'display_name_ar': 'Single visit (DR)',
        'display_name_en': 'Single visit (DR)',
        'active': True,
        'mode': 'checkin_checkout',
        'allow_unplanned': True,
        'auto_approve_unplanned': True,
        'enable_product_detailing': True,
        'enable_double_visit_assessment_only': False,
        'visit_outcome_mode': 'enabled_auto_approve_unsuccessful',
        'restrict_account_types': ['Clinic', 'Hospital', 'Health Unit', 'Dispensary', 'Polyclinic', 'Center', 'Distributor'],
        'questions': [
            {
                'text_ar': '? Did you meet the Dr',
                'text_en': 'Did you meet the Dr ?',
                'question_type': 'single_choice',
                'options': [
                    {'text_ar': 'Yes', 'text_en': 'Yes', 'value': 'Yes'},
                    {'text_ar': 'No', 'text_en': 'No', 'value': 'No'},
                ],
                'is_required': True,
                'is_conditional': False,
                'stage': 'all',
                'order': 1,
            },
            {
                'text_ar': '? What happened int he visit',
                'text_en': 'What happened in the visit ?',
                'question_type': 'textarea',
                'options': [],
                'is_required': True,
                'is_conditional': True,
                'conditional_parent_idx': 0,
                'conditional_trigger_value': 'Yes',
                'stage': 'all',
                'order': 2,
            },
            {
                'text_ar': '? Reason for not visiting',
                'text_en': 'Reason for not visiting ?',
                'question_type': 'textarea',
                'options': [],
                'is_required': True,
                'is_conditional': True,
                'conditional_parent_idx': 0,
                'conditional_trigger_value': 'No',
                'stage': 'all',
                'order': 3,
            },
            {
                'text_ar': 'Dr need',
                'text_en': 'Dr need',
                'question_type': 'text',
                'options': [],
                'is_required': True,
                'is_conditional': True,
                'conditional_parent_idx': 0,
                'conditional_trigger_value': 'Yes',
                'stage': 'all',
                'order': 4,
            },
        ]
    },
    {
        'name': 'single_visit_pharmacy',
        'display_name_ar': 'Single visit (Pharmacy)',
        'display_name_en': 'Single visit (Pharmacy)',
        'active': True,
        'mode': 'checkin_checkout',
        'allow_unplanned': True,
        'auto_approve_unplanned': True,
        'enable_product_detailing': True,
        'enable_double_visit_assessment_only': False,
        'visit_outcome_mode': 'enabled_auto_approve_unsuccessful',
        'restrict_account_types': ['Pharmacy'],
        'questions': [
            {
                'text_ar': 'Feedback about all products',
                'text_en': 'Feedback about all products',
                'question_type': 'single_choice',
                'options': [
                    {'text_ar': 'نعم', 'text_en': 'Yes', 'value': 'yes'},
                    {'text_ar': 'لا', 'text_en': 'No', 'value': 'no'},
                ],
                'is_required': True,
                'is_conditional': False,
                'stage': 'all',
                'order': 1,
            },
            {
                'text_ar': 'Accurate feedback ( Dr & Prdouct & Rate )',
                'text_en': 'Accurate feedback ( Dr & Product & Rate )',
                'question_type': 'single_choice',
                'options': [
                    {'text_ar': 'نعم', 'text_en': 'Yes', 'value': 'yes'},
                    {'text_ar': 'لا', 'text_en': 'No', 'value': 'no'},
                ],
                'is_required': True,
                'is_conditional': False,
                'stage': 'all',
                'order': 2,
            },
            {
                'text_ar': 'Competitors feedback',
                'text_en': 'Competitors feedback',
                'question_type': 'single_choice',
                'options': [
                    {'text_ar': 'نعم', 'text_en': 'Yes', 'value': 'yes'},
                    {'text_ar': 'لا', 'text_en': 'No', 'value': 'no'},
                ],
                'is_required': True,
                'is_conditional': False,
                'stage': 'all',
                'order': 3,
            },
        ]
    },
    {
        'name': 'coaching_visit_dr',
        'display_name_ar': 'Coaching visit (DR)',
        'display_name_en': 'Coaching visit (DR)',
        'active': True,
        'mode': 'checkin_checkout',
        'allow_unplanned': True,
        'auto_approve_unplanned': True,
        'enable_product_detailing': True,
        'enable_double_visit_assessment_only': True,
        'visit_outcome_mode': 'enabled_auto_approve_unsuccessful',
        'restrict_account_types': ['Clinic', 'Hospital', 'Polyclinic', 'Center'],
        'questions': [
            {
                'text_ar': '? Did you meet the Dr',
                'text_en': 'Did you meet the Dr ?',
                'question_type': 'single_choice',
                'options': [
                    {'text_ar': 'Yes', 'text_en': 'Yes', 'value': 'Yes'},
                    {'text_ar': 'No', 'text_en': 'No', 'value': 'No'},
                ],
                'is_required': True,
                'is_conditional': False,
                'stage': 'all',
                'order': 1,
            },
            {
                'text_ar': 'Set an objective for the visit',
                'text_en': 'Set an objective for the visit',
                'question_type': 'textarea',
                'options': [],
                'is_required': True,
                'is_conditional': False,
                'stage': 'start_only',
                'order': 2,
            },
            {
                'text_ar': 'Evaluation / Feedback',
                'text_en': 'Evaluation / Feedback',
                'question_type': 'textarea',
                'options': [],
                'is_required': True,
                'is_conditional': False,
                'stage': 'end_only',
                'order': 3,
            },
        ]
    },
    {
        'name': 'coaching_visit_pharmacy',
        'display_name_ar': 'Coaching visit (Pharmacy)',
        'display_name_en': 'Coaching visit (Pharmacy)',
        'active': True,
        'mode': 'checkin_checkout',
        'allow_unplanned': True,
        'auto_approve_unplanned': True,
        'enable_product_detailing': True,
        'enable_double_visit_assessment_only': True,
        'visit_outcome_mode': 'enabled_auto_approve_unsuccessful',
        'restrict_account_types': ['Pharmacy'],
        'questions': [
            {
                'text_ar': 'Feedback about all products',
                'text_en': 'Feedback about all products',
                'question_type': 'single_choice',
                'options': [
                    {'text_ar': 'نعم', 'text_en': 'Yes', 'value': 'yes'},
                    {'text_ar': 'لا', 'text_en': 'No', 'value': 'no'},
                ],
                'is_required': True,
                'is_conditional': False,
                'stage': 'all',
                'order': 1,
            },
            {
                'text_ar': 'Accurate feedback ( Dr & Prdouct & Rate )',
                'text_en': 'Accurate feedback ( Dr & Product & Rate )',
                'question_type': 'single_choice',
                'options': [
                    {'text_ar': 'نعم', 'text_en': 'Yes', 'value': 'yes'},
                    {'text_ar': 'لا', 'text_en': 'No', 'value': 'no'},
                ],
                'is_required': True,
                'is_conditional': False,
                'stage': 'all',
                'order': 2,
            },
            {
                'text_ar': 'Competitors feedback',
                'text_en': 'Competitors feedback',
                'question_type': 'single_choice',
                'options': [
                    {'text_ar': 'نعم', 'text_en': 'Yes', 'value': 'yes'},
                    {'text_ar': 'لا', 'text_en': 'No', 'value': 'no'},
                ],
                'is_required': True,
                'is_conditional': False,
                'stage': 'all',
                'order': 3,
            },
        ]
    },
    {
        'name': 'store_distributor_visit',
        'display_name_ar': 'Store & Distributor visit',
        'display_name_en': 'Store & Distributor visit',
        'active': True,
        'mode': 'checkin_checkout',
        'allow_unplanned': True,
        'auto_approve_unplanned': True,
        'enable_product_detailing': False,
        'enable_double_visit_assessment_only': False,
        'visit_outcome_mode': 'enabled_auto_approve_unsuccessful',
        'restrict_account_types': ['Store', 'Distributor'],
        'questions': [
            {
                'text_ar': 'Stock check',
                'text_en': 'Stock check',
                'question_type': 'single_choice',
                'options': [
                    {'text_ar': 'نعم', 'text_en': 'Yes', 'value': 'yes'},
                    {'text_ar': 'لا', 'text_en': 'No', 'value': 'no'},
                ],
                'is_required': True,
                'is_conditional': False,
                'stage': 'all',
                'order': 1,
            },
            {
                'text_ar': 'Collection / Order details',
                'text_en': 'Collection / Order details',
                'question_type': 'textarea',
                'options': [],
                'is_required': True,
                'is_conditional': False,
                'stage': 'all',
                'order': 2,
            },
        ]
    },
    {
        'name': 'healthy_day',
        'display_name_ar': 'Healthy day',
        'display_name_en': 'Healthy day',
        'active': True,
        'mode': 'checkin_checkout',
        'allow_unplanned': True,
        'auto_approve_unplanned': True,
        'enable_product_detailing': False,
        'enable_double_visit_assessment_only': False,
        'visit_outcome_mode': 'enabled_auto_approve_unsuccessful',
        'restrict_account_types': [],
        'questions': [
            {
                'text_ar': 'هل كان يوم ناجح ؟',
                'text_en': 'Was it a successful day ?',
                'question_type': 'single_choice',
                'options': [
                    {'text_ar': 'نعم', 'text_en': 'Yes', 'value': 'yes'},
                    {'text_ar': 'لا', 'text_en': 'No', 'value': 'no'},
                ],
                'is_required': True,
                'is_conditional': False,
                'stage': 'start_only',
                'order': 1,
            },
            {
                'text_ar': 'ما هى نتائج اليوم ( روشتات & بيع ) ؟',
                'text_en': 'What were the results of the day (prescriptions & sales) ?',
                'question_type': 'textarea',
                'options': [],
                'is_required': True,
                'is_conditional': False,
                'stage': 'end_only',
                'order': 2,
            },
        ]
    },
]

def seed_templates():
    created_count = 0
    updated_count = 0

    for t_data in TEMPLATES_DATA:
        questions_data = t_data.pop('questions')
        template, created = VisitTemplate.objects.update_or_create(
            name=t_data['name'],
            defaults=t_data
        )
        if created:
            created_count += 1
        else:
            updated_count += 1

        # Seed questions
        # Remove old questions if re-seeding to ensure fresh state
        template.questions.all().delete()
        created_questions = []

        for q_data in questions_data:
            parent_idx = q_data.pop('conditional_parent_idx', None)
            parent_question = created_questions[parent_idx] if parent_idx is not None and parent_idx < len(created_questions) else None

            question = VisitTemplateQuestion.objects.create(
                template=template,
                conditional_parent=parent_question,
                **q_data
            )
            created_questions.append(question)

    print(f"DONE: Created {created_count}, Updated {updated_count} templates. Total active templates: {VisitTemplate.objects.count()}. Total questions: {VisitTemplateQuestion.objects.count()}")

if __name__ == '__main__':
    seed_templates()
