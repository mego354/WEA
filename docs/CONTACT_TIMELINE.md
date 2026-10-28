# Contact Timeline Architecture & Paginated Modal

## 1. Executive Summary

This document describes the architectural enhancement of the Contact Timeline (`contacts/<id>/?tab=overview#timeline`). To maintain rapid initial page loads and a clutter-free overview, the contact detail page displays the **top 5 most recent activities** by default, with an interactive, paginated "View all" modal dialog supported by a dedicated JSON API endpoint.

---

## 2. Overview Tab Compact Timeline

In `contacts/views.py` (`contact_detail` view) and `templates/contacts/contact_detail.html`:
- **Top 5 Slice:**
  ```python
  activities_qs = contact.activities.select_related('performed_by').order_by('-created_at')
  total_timeline_count = activities_qs.count()
  recent_timeline = activities_qs[:5]
  ```
- **Visual Design:**
  - Compact vertical timeline with color-coded circular icons (stethoscope for visits, shopping cart for orders, phone for calls, notes for logs).
  - Relative and absolute timestamps in Arabic.
  - Performer attribution (representative or manager).
- **"View All" Trigger:**
  - Displays when activities exist.
  - Features count badge (e.g., `عرض جميع الأنشطة (42)`).
  - Launches `#timelineModal`.

---

## 3. "View All" Timeline Modal (`#timelineModal`)

The modal dialog provides an enterprise activity inspection experience:
- **Real-Time Search & Filtering:**
  - **Text search input:** Matches activity titles and notes.
  - **Activity type filter:** Filter by Visits, Sales Orders, Calls, Collections, Approvals, or Notes.
  - **Date bounds:** From date and to date filters.
- **Client-Side Debouncing:** 350ms debounced input to prevent excessive API requests.
- **Loading Indicators:** Inline spinner during asynchronous fetching.
- **Full Keyboard Navigation:** Supports `Escape` key to close.

---

## 4. Paginated JSON API Endpoint

### Route
`GET /contacts/<pk>/timeline/events/` (`contacts:contact_timeline_events`)

### Request Query Parameters
| Parameter | Type | Default | Description |
|---|---|---|---|
| `page` | `int` | `1` | Page number. |
| `per_page` | `int` | `10` | Records per page (capped at 50). |
| `q` | `string` | `""` | Search keyword for title and notes. |
| `activity_type`| `string` | `""` | Activity type filter. |
| `date_from` | `date` | `""` | Start date (`YYYY-MM-DD`). |
| `date_to` | `date` | `""` | End date (`YYYY-MM-DD`). |

### JSON Response Schema
```json
{
  "success": true,
  "events": [
    {
      "id": 142,
      "activity_type": "visit",
      "activity_type_display": "زيارة ميدانية",
      "title": "زيارة دورية للعيادة",
      "notes": "تم شرح صنف بنادول اكسترا ومناقشة عروض الكميات",
      "performed_by": "د. أحمد مندوب",
      "date": "2026-10-28",
      "time": "11:30 ص",
      "icon": "medical_services",
      "badge_color": "bg-teal-50 text-teal-700"
    }
  ],
  "page": 1,
  "per_page": 10,
  "total_pages": 4,
  "total_count": 35,
  "has_next": true,
  "has_prev": false
}
```

---

## 5. Automated Unit Test Verification

Covered in `contacts/tests_udf_todos_timeline.py` (`test_contact_timeline_top5_and_paginated_api`):
1. **Overview slice:** Confirms `len(res.context['recent_timeline']) == 5` and `total_timeline_count >= 8`.
2. **API pagination:** Validates `res.json()['events']` length, current `page`, and `has_next` boolean.
3. **Type filtering:** Verifies filtering by `activity_type=visit` only returns matching events.
