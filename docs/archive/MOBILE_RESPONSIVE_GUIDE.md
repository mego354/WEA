# Mobile Usability & Responsive Design Standards

## 1. Principles

The ERP application is built with a **mobile-first, native-app feel** that adapts seamlessly from ultra-narrow smartphones (320px) to ultra-wide desktop monitors (1440px+).

Key Principles:
1. **Never Shrink Desktop Pages Blindly**: Reorganize content hierarchically for touch and vertical flow.
2. **Prevent Horizontal Page Overflow**: No full-page horizontal scrolling. Data tables are enclosed in strictly bounded, scrollable container boxes (`.overflow-x-auto`).
3. **Minimum 44px Touch Targets**: Buttons, input fields, dropdowns, and pagination controls comply with Apple and Google touch ergonomics (minimum 44 × 44 CSS pixels).
4. **Cohesive Arabic RTL Experience**: Visual direction, icons, pagination arrows, drawer slide-overs, and typography adhere strictly to right-to-left layout rules.

---

## 2. Tested Viewport Matrix

All core screens have been validated across the required viewport matrix:

| Device Category | Target Viewport | Validated Screen | Verified Behavior |
| :--- | :--- | :--- | :--- |
| **Narrow Mobile** | 320 × 568 px | Purchases List | Zero page overflow. Table scrolls smoothly inside container. Action buttons wrap vertically without truncation. |
| **iPhone Standard** | 375 × 812 px | Contacts List | Bottom navigation bar fixed to screen bottom. Quick action FAB button accessible. Mobile drawer slides cleanly. |
| **iPhone 14 / Modern** | 390 × 844 px | Sales Orders List | Status pill chips horizontally scrollable without page blowout. Filter drawer accessible. |
| **Large Smartphone** | 430 × 932 px | Activities & Visits | Summary KPI cards wrap to 2 columns. Table/Cards toggle provides card-based view for easy touch reading. |
| **Tablet Portrait** | 768 × 1024 px | Treasury Payments | Multi-column grid layout, side margins optimized, action buttons inline. |
| **Desktop / Laptop** | 1024 × 768 px | Inventory Stock | Full data table visible, secondary columns displayed, breadcrumb navigation. |
| **Wide Desktop** | 1440 × 900 px | Catalog Products | Collapsible sidebar, full width utilization, multi-column metrics. |

---

## 3. Mobile Navigation Architecture

The ERP provides two complementary mobile navigation systems:

1. **Bottom Navigation Bar (Quick Access)**:
   - Fixed at the bottom of viewport (`z-40 md:hidden`).
   - 5 primary destinations:
     * الرئيسية (Home)
     * جهات الاتصال (Contacts)
     * المنتجات (Catalog)
     * المشتريات (Purchases)
     * القائمة (More Menu / Drawer Toggle)
   - Active page indicator with `#27bebe` highlight and soft teal background.

2. **Mobile Slide-Over Navigation Drawer**:
   - Slides smoothly from the right side (RTL convention) with backdrop blur overlay.
   - Houses the complete module hierarchy (Treasury, Inventory, Activities, Users, Settings).
   - Touch-friendly links with distinct icons, clear grouping, and an accessible close button (`X`).

---

## 4. Responsive Table & Card Patterns

- **Controlled Horizontal Overflow**:
  ```html
  <div class="bg-white border border-slate-200 rounded-xl overflow-hidden shadow-xs">
      <div class="overflow-x-auto">
          <table class="w-full text-right text-xs">
              ...
          </table>
      </div>
      {% include 'components/pagination.html' %}
  </div>
  ```
- **Table / Card View Toggle**:
  Pages with dense data (e.g. Contacts, Visits) provide an instant toggle between a traditional table and modern touch-friendly cards for mobile users.
- **Sticky Column Headers**:
  Table headers use `bg-slate-50/90 select-none` to remain legible during touch scrolling.
