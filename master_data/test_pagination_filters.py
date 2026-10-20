from django.test import TestCase, RequestFactory
from django.template import Context, Template
from master_data.pagination_utils import paginate_queryset
from master_data.templatetags.erp_tags import url_replace, url_remove_param, smart_page_range
from django.core.paginator import Paginator


class PaginationUtilsTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.sample_list = list(range(1, 151))  # 150 items

    def test_default_pagination(self):
        request = self.factory.get('/some-list/')
        paginator, page_obj = paginate_queryset(request, self.sample_list, default_per_page=25)
        self.assertEqual(paginator.per_page, 25)
        self.assertEqual(paginator.count, 150)
        self.assertEqual(paginator.num_pages, 6)
        self.assertEqual(page_obj.number, 1)
        self.assertEqual(len(page_obj.object_list), 25)
        self.assertEqual(page_obj.start_index(), 1)
        self.assertEqual(page_obj.end_index(), 25)

    def test_custom_per_page_selection(self):
        request = self.factory.get('/some-list/?per_page=50')
        paginator, page_obj = paginate_queryset(request, self.sample_list, default_per_page=25)
        self.assertEqual(paginator.per_page, 50)
        self.assertEqual(paginator.num_pages, 3)

    def test_per_page_safety_cap(self):
        # Even if a malicious or huge per_page is requested, it must be capped at max_per_page (100)
        request = self.factory.get('/some-list/?per_page=5000')
        paginator, page_obj = paginate_queryset(request, self.sample_list, default_per_page=25, max_per_page=100)
        self.assertEqual(paginator.per_page, 100)

    def test_invalid_per_page_fallback(self):
        request = self.factory.get('/some-list/?per_page=invalid_string')
        paginator, page_obj = paginate_queryset(request, self.sample_list, default_per_page=25)
        self.assertEqual(paginator.per_page, 25)

    def test_negative_per_page_fallback(self):
        request = self.factory.get('/some-list/?per_page=-10')
        paginator, page_obj = paginate_queryset(request, self.sample_list, default_per_page=25)
        self.assertEqual(paginator.per_page, 25)

    def test_out_of_range_page_fallback_to_last(self):
        request = self.factory.get('/some-list/?page=999')
        paginator, page_obj = paginate_queryset(request, self.sample_list, default_per_page=25)
        self.assertEqual(page_obj.number, 6)  # Last page

    def test_invalid_page_fallback_to_first(self):
        request = self.factory.get('/some-list/?page=abc')
        paginator, page_obj = paginate_queryset(request, self.sample_list, default_per_page=25)
        self.assertEqual(page_obj.number, 1)

    def test_empty_dataset_pagination(self):
        request = self.factory.get('/some-list/')
        paginator, page_obj = paginate_queryset(request, [], default_per_page=25)
        self.assertEqual(paginator.count, 0)
        self.assertEqual(paginator.num_pages, 1)
        self.assertEqual(page_obj.number, 1)
        self.assertEqual(len(page_obj.object_list), 0)


class UrlReplaceAndFilterTagsTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def test_url_replace_preserves_existing_params(self):
        request = self.factory.get('/products/?search=panadol&category=2&page=1')
        context = {'request': request}
        result = url_replace(context, page=2)
        self.assertIn('page=2', result)
        self.assertIn('search=panadol', result)
        self.assertIn('category=2', result)

    def test_url_replace_removes_none_and_empty(self):
        request = self.factory.get('/products/?search=panadol&status=active&page=2')
        context = {'request': request}
        result = url_replace(context, status=None, page=1)
        self.assertNotIn('status=', result)
        self.assertIn('page=1', result)
        self.assertIn('search=panadol', result)

    def test_url_remove_param_dynamic(self):
        request = self.factory.get('/sales/orders/?status=pending&date_from=2026-01-01&page=3')
        context = {'request': request}
        result = url_remove_param(context, 'status', page=1)
        self.assertNotIn('status=', result)
        self.assertIn('page=1', result)
        self.assertIn('date_from=2026-01-01', result)

    def test_smart_page_range_few_pages(self):
        paginator = Paginator(list(range(50)), 10)  # 5 pages
        pages = smart_page_range(paginator, current_page=2)
        self.assertEqual(pages, [1, 2, 3, 4, 5])

    def test_smart_page_range_with_ellipsis(self):
        paginator = Paginator(list(range(300)), 15)  # 20 pages
        pages = smart_page_range(paginator, current_page=10, on_each_side=2, on_ends=1)
        # Should start with [1, '...'], have [8, 9, 10, 11, 12], and end with ['...', 20]
        self.assertEqual(pages[0], 1)
        self.assertEqual(pages[1], '...')
        self.assertIn(10, pages)
        self.assertEqual(pages[-2], '...')
        self.assertEqual(pages[-1], 20)

    def test_template_rendering_components(self):
        # Test rendering of active_filters template directly
        request = self.factory.get('/contacts/?type=customer&status=active')
        template_str = """
        {% load erp_tags %}
        {% include 'components/active_filters.html' %}
        """
        template = Template(template_str)
        context = Context({
            'request': request,
            'active_filters': [
                {'label': 'نوع جهة الاتصال', 'value': 'عميل', 'param': 'type'},
                {'label': 'الحالة', 'value': 'نشط', 'param': 'status'}
            ]
        })
        rendered = template.render(context)
        self.assertIn('الفلاتر النشطة', rendered)
        self.assertIn('نوع جهة الاتصال', rendered)
        self.assertIn('عميل', rendered)
        self.assertIn('إعادة تعيين الكل', rendered)
