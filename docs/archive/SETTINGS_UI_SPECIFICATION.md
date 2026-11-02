# Settings UI & Visual Specification

> **System**: WEA Pharma ERP  
> **Module**: Settings, Users, and Permissions  
> **Source Base URL**: `https://weapharma.bricks-rep.com/`  
> **Date**: October 2026

---

## 1. Visual Design Tokens & Palette

### 1.1 Color System
- **Primary Brand Teal**: `#27bebe` (Used for active navigation links, primary buttons, section titles, active toggles).
- **Brand Teal Hover**: `#1fa8a8`
- **Brand Teal Light Tints**:
  - 50: `#f0fdfd`
  - 100: `#e6f7f7` (used for item card backgrounds in Expenses, Requests, Agreements)
  - 200: `#bfeeed`
- **Surface & Background**:
  - Page Background: `#f8fafc` (slate-50)
  - Card & Container Surface: `#ffffff` (white)
  - Card Border: `#e2e8f0` (slate-200) / `#cbd5e1` (slate-300)
- **Typography & Neutrals**:
  - Headings / Main Text: `#0f172a` (slate-900)
  - Body Text: `#334155` (slate-700)
  - Muted / Labels: `#64748b` (slate-500)
  - Disabled State: `#94a3b8` (slate-400)
- **Status Badges**:
  - Success / Active: `#059669` (emerald-600) / `#ecfdf5`
  - Required / Alert: `#d97706` (amber-600) / `#fffbeb`
  - Locked / Core: `#64748b` (slate-500) / `#f1f5f9`
  - Filterable: `#10b981` (emerald-500) / `#d1fae5`

### 1.2 Typography & Layout
- **Font Family**: `'Cairo', sans-serif`
- **Direction**: Right-to-Left (`dir="rtl"`)
- **Spacing Scale**: 4px base (p-3: 12px, p-4: 16px, p-6: 24px)
- **Border Radius**:
  - Buttons / Inputs: `rounded-lg` (8px)
  - Cards / Modals: `rounded-xl` (12px) to `rounded-2xl` (16px)
  - Floating Action Button: `rounded-full`

---

## 2. Layout Structure

### 2.1 Topbar & Breadcrumb
- Fixed height: `h-16` (64px) with sticky top positioning (`sticky top-0 z-30`).
- Background: `bg-white` with bottom border `border-b border-slate-200`.
- Breadcrumb display:
  - Format: `الرئيسية / الإعدادات / [اسم الصفحة]`
  - Font: `text-xs sm:text-sm text-slate-500 font-medium`.

### 2.2 Page Header
- Page Title: `text-xl sm:text-2xl font-bold text-[#27bebe] mb-4`.
- Actions row:
  - Add button (e.g. `اضف مستخدم`, `إنشاء دور`, `أضف نوع جديد`):
    - Background: `bg-[#27bebe]` with hover `bg-[#1fa8a8]`
    - Text: `text-white font-bold text-xs sm:text-sm`
    - Radius: `rounded-lg`
    - Height: `h-10`
    - Shadow: `shadow-sm shadow-teal-500/20`
  - Secondary buttons (e.g. `تصدير البيانات`):
    - Variant 1 (Teal): `bg-[#27bebe] text-white`
    - Variant 2 (Outlined/White): `bg-white border border-slate-300 text-slate-700 hover:bg-slate-50`

---

## 3. UI Component Specifications

### 3.1 Tables (Users, Roles)
- Container: `bg-white rounded-xl border border-slate-200 shadow-sm overflow-hidden`.
- Table Header:
  - Background: `bg-slate-50/80 border-b border-slate-200`.
  - Text: `text-xs font-bold text-slate-600 uppercase py-3.5 px-4 text-right`.
- Table Body Rows:
  - Height: `h-14` (56px) minimum for touch friendliness.
  - Alternating / Hover: `hover:bg-slate-50/60 transition-colors border-b border-slate-100`.
  - Primary text: `text-sm font-semibold text-slate-900` (User/Role name as teal/blue clickable link).
  - Status column: Checkmark icon `✓` in emerald/teal for active.
  - Action column: Inline action icons (pencil for edit, copy for duplicate, trash for delete).

### 3.2 Add User Modal (`إضافة مستخدم جديد`)
- Backdrop: `fixed inset-0 bg-slate-900/40 backdrop-blur-xs z-50 flex items-center justify-center p-4`.
- Modal Box: `bg-white rounded-2xl shadow-2xl max-w-lg w-full p-6 border border-slate-100`.
- Header:
  - Title: `text-lg font-bold text-[#27bebe]` ("إضافة مستخدم جديد").
  - Close button: `text-slate-400 hover:text-slate-600`.
- Form Controls:
  - Label: `block text-xs font-semibold text-slate-600 mb-1.5`.
  - Input field: `w-full px-3.5 py-2.5 bg-slate-50 border border-slate-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-[#27bebe] focus:border-transparent transition-all`.
  - Dropdown select: `w-full px-3.5 py-2.5 bg-slate-50 border border-slate-300 rounded-lg text-sm focus:ring-2 focus:ring-[#27bebe]`.
- Submit Button:
  - Normal: `bg-[#27bebe] hover:bg-[#1fa8a8] text-white font-bold py-2.5 px-6 rounded-lg text-sm shadow-md shadow-teal-500/20`.
  - Disabled: `bg-slate-200 text-slate-400 cursor-not-allowed`.

### 3.3 Card List Items (Expenses, Approvals, Agreements, Tickets)
- Container: `space-y-3 max-w-2xl`.
- Card Item:
  - Background: `#e6f7f7` (light teal tint matching reference ERP) or `bg-white border border-slate-200`.
  - Padding: `p-4 rounded-xl flex items-center justify-between shadow-xs hover:shadow-sm transition-all`.
  - Right content: Title in bold text + optional unit subtitle (`الوحدة: `).
  - Left content: Action buttons:
    - Edit: Pencil icon in slate/teal.
    - Delete: Red trash icon.
    - Default badge: Pill badge `افتراضي` in teal `#27bebe` with white text.

### 3.4 Switches & Toggles (Settings, Roles)
- Reference ERP switch style:
  - Track: `w-11 h-6 bg-slate-300 rounded-full transition-colors relative cursor-pointer`.
  - Active track: `bg-[#27bebe]`.
  - Thumb: `w-5 h-5 bg-white rounded-full shadow-md transform transition-transform absolute top-0.5 right-0.5`.
  - Active thumb: `translate-x-[-20px]`.

### 3.5 Floating Action Button (FAB)
- Position: `fixed bottom-4 left-4 z-40` (on mobile: `bottom-20 left-4`).
- Dimensions: `w-14 h-14` (56x56px) rounded-full.
- Background: `bg-[#27bebe] hover:bg-[#1fa8a8] text-white`.
- Shadow: `shadow-lg shadow-teal-500/30`.
- Icon: Material Symbol `add` (32px).
