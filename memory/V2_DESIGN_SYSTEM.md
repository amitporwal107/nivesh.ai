# Nivesh Copilot V2 — Design System & UI Implementation Guide
**Version:** 2.0 FINAL  
**Date:** April 2026  
**Status:** Ready for Implementation

---

## 🎨 DESIGN SYSTEM OVERVIEW

### Theme & Philosophy
- **Domain:** Finance / Wealth Management
- **Theme:** Light
- **Archetype:** Swiss & High-Contrast combined with Mobile-First Utility
- **Core Principle:** "Financial to-do list" — NOT an analytics dashboard
- **Goal:** Extreme clarity, maximum thumb-target sizes, stark semantic colors to drive action

---

## 🎨 COLOR PALETTE

### Base Colors
```css
Background: #FAF9F6  (Off-white, warm)
Surface:    #FFFFFF  (Pure white cards)
```

### Text Colors
```css
Primary:    text-slate-900  (Main text)
Secondary:  text-slate-600  (Descriptions)
Tertiary:   text-slate-400  (Meta info)
```

### Semantic Colors (Action Types)

#### 🔴 URGENT / EXIT
```css
Background:  bg-red-600
Text:        text-white
Light BG:    bg-red-50
Border:      border-red-200
```
**Usage:** EXIT actions, critical issues

#### 🟡 WARNING / SWITCH
```css
Background:  bg-amber-500
Text:        text-slate-900
Light BG:    bg-amber-50
Border:      border-amber-200
```
**Usage:** SWITCH actions, moderate issues

#### 🟢 GOOD / ADD
```css
Background:  bg-emerald-600
Text:        text-white
Light BG:    bg-emerald-50
Border:      border-emerald-200
```
**Usage:** ADD actions, completed states, positive signals

---

## 📝 TYPOGRAPHY

### Font Families
```css
Headings: 'Outfit', sans-serif
Body:     'Manrope', sans-serif
```

### Hierarchy

#### ₹ Amounts (Largest — Hero element)
```css
text-5xl sm:text-6xl 
font-black 
tracking-tighter 
text-slate-900
```
**Example:** ₹4,80,000

#### Action Titles
```css
text-xl sm:text-2xl 
font-bold 
tracking-tight 
text-slate-900
```
**Example:** "Reduce overlap in large cap funds"

#### Reasons / Descriptions
```css
text-sm sm:text-base 
font-medium 
text-slate-600
```
**Example:** "60% duplication"

#### Impact / Meta
```css
text-sm 
text-slate-500
```
**Example:** "✔ Better diversification"

### Typography Rules
✅ Left-align everything (no center-align for financial data)  
✅ Use extremely tight tracking on massive numbers (₹ amounts)  
❌ No generic fonts like Inter or Roboto

---

## 📐 SPACING & LAYOUT

### Container
```css
max-w-md 
mx-auto 
min-h-screen 
pb-32        /* Space for sticky bottom bar */
pt-24        /* Space for sticky header */
```

### Card Design
```css
Padding:       p-5 sm:p-6    (20-24px)
Border Radius: rounded-2xl
Gap:           gap-4 sm:gap-5
Border:        border border-slate-200
Shadow:        shadow-sm
```

### Buttons (Touch-Friendly)
```css
Height:        min-h-[56px]   (Optimal for thumb)
Border Radius: rounded-xl
Padding:       px-6 py-4
Font:          text-lg font-semibold
```
**Critical:** Button height MUST be ≥ 48px (56px optimal)

### Layout Rules
✅ Mobile-first (max-w-md container)  
✅ Full-width cards on mobile  
✅ Generous padding (p-5 or p-6)  
✅ 1-hand thumb usage  
❌ NO multi-column layouts on mobile  
❌ NO dense tables or dashboard grids

---

## 🧩 COMPONENTS SPECIFICATION

### 1. Header & Version Toggle

**Type:** Top Navigation  
**Position:** Fixed top  
**Classes:**
```css
flex justify-between items-center 
p-4 
bg-[#FAF9F6]
```

**Structure:**
```jsx
<header>
  <div className="flex items-center gap-2">
    <Logo />
    <h1>Nivesh.AI</h1>
  </div>
  <div className="flex items-center gap-3">
    <VersionToggle />  {/* Dropdown: V2 / V1 */}
    <Avatar />
  </div>
</header>
```

**Version Toggle (Shadcn Select/DropdownMenu):**
- Option 1: "◉ V2: Action Plan View" (selected)
- Option 2: "○ V1: Dashboard View (Classic)"

---

### 2. Sticky Action Plan (Header)

**Type:** Progress Tracker  
**Position:** Sticky top  
**Classes:**
```css
sticky top-0 z-40 
bg-white/90 backdrop-blur-xl 
border-b border-slate-200 
p-4 shadow-sm
```

**Structure:**
```jsx
<div className="sticky-action-plan">
  {/* Title */}
  <h2 className="text-xl font-bold">
    Fix Your Portfolio (3 steps)
  </h2>
  
  {/* Quick Summary (collapsed state) */}
  <p className="text-sm text-slate-600">
    1. Sell ₹4.8L • 2. Switch ₹13L • 3. Add ₹15L
  </p>
  
  {/* Progress Indicator */}
  <div className="flex items-center gap-2 mt-2">
    <span className="text-slate-900">●</span>
    <span className="text-slate-300">○</span>
    <span className="text-slate-300">○</span>
    <span className="text-sm text-slate-600 ml-2">
      1/3 completed
    </span>
  </div>
  
  {/* Collapse/Expand toggle */}
  <button className="text-sm text-slate-500">
    {isExpanded ? "Collapse ▲" : "Expand ▼"}
  </button>
</div>
```

**Behavior:**
- Collapsible to save vertical space on scroll
- Backdrop blur effect for depth

---

### 3. Action Cards (Main Content)

**Type:** Interactive Cards  
**Classes:**
```css
w-full 
bg-white 
border border-slate-200 
rounded-2xl 
p-5 
mb-4 
shadow-sm
```

**Structure:**
```jsx
<div className="action-card" data-testid="action-card-exit-1">
  {/* Top Row: Type Indicator */}
  <div className="flex items-center gap-2 mb-2">
    <span className="w-3 h-3 rounded-full bg-red-600"></span>
    <span className="text-xs font-semibold text-red-600 uppercase tracking-wide">
      SELL
    </span>
  </div>
  
  {/* Amount (Hero element) */}
  <h3 className="text-5xl sm:text-6xl font-black tracking-tighter text-slate-900 mb-2">
    ₹4.8L
  </h3>
  
  {/* Title */}
  <h4 className="text-xl sm:text-2xl font-bold tracking-tight text-slate-900 mb-1">
    Reduce overlap in large cap funds
  </h4>
  
  {/* Reason (1 line) */}
  <p className="text-sm sm:text-base font-medium text-slate-600 mb-2">
    60% duplication
  </p>
  
  {/* Impact (max 2 bullets) */}
  <div className="flex flex-col gap-1 mb-4">
    <p className="text-sm text-slate-500">
      ✔ Better diversification
    </p>
    <p className="text-sm text-slate-500">
      ✔ Lower portfolio risk
    </p>
  </div>
  
  {/* Tax Info */}
  <div className="bg-slate-50 rounded-lg p-3 mb-4">
    <p className="text-sm text-slate-600">
      Tax: <span className="font-semibold text-slate-900">₹0</span> (LTCG exempt)
    </p>
  </div>
  
  {/* CTA Button (Full width, 56px height) */}
  <button 
    className="w-full min-h-[56px] bg-red-600 text-white text-lg font-semibold rounded-xl px-6 py-4 active:scale-[0.98] transition-transform duration-200"
    data-testid="mark-done-button-sell"
  >
    Mark as Done
  </button>
</div>
```

**States:**

**PENDING:**
- Full opacity
- CTA button active with semantic color

**COMPLETED:**
```jsx
<div className="action-card opacity-60" data-testid="action-card-completed">
  {/* ... card content ... */}
  
  {/* Completed state */}
  <div className="flex items-center gap-2 text-emerald-600 mb-2">
    <CheckCircle size={20} />
    <span className="text-sm font-semibold">Completed on Apr 20, 2026</span>
  </div>
  
  {/* Disabled button */}
  <button 
    className="w-full min-h-[56px] bg-slate-200 text-slate-500 text-lg font-semibold rounded-xl px-6 py-4 cursor-not-allowed"
    disabled
  >
    ✓ Completed
  </button>
</div>
```

**SKIPPED:**
```jsx
<div className="action-card opacity-40" data-testid="action-card-skipped">
  {/* ... card content ... */}
  
  <button 
    className="w-full min-h-[56px] bg-white border-2 border-slate-300 text-slate-600 text-lg font-semibold rounded-xl px-6 py-4"
    data-testid="undo-skip-button"
  >
    Undo Skip
  </button>
</div>
```

**Animation:**
```css
opacity-0 
animate-in fade-in slide-in-from-bottom-4 
duration-500 
fill-mode-forwards
```
**Stagger:** Use `delay-100`, `delay-200` for sequential cards

---

### 4. Portfolio Signals (Collapsible Accordion)

**Type:** Shadcn Accordion  
**Position:** Below action cards  
**Classes:**
```css
bg-white 
rounded-2xl 
border border-slate-200 
mt-8
```

**Structure (Collapsed):**
```jsx
<Accordion type="single" collapsible className="w-full">
  <AccordionItem value="signals">
    <AccordionTrigger className="px-5 py-4">
      <div className="flex items-center gap-3">
        <h3 className="text-lg font-semibold">Portfolio Signals</h3>
        <span className="text-xs text-slate-500">(3 detected)</span>
      </div>
    </AccordionTrigger>
    
    <AccordionContent className="px-5 pb-4">
      {/* Signal Cards */}
      <div className="space-y-3">
        {/* Signal 1 */}
        <div className="flex items-start gap-3 p-3 bg-red-50 rounded-lg border border-red-200">
          <span className="text-lg">🔴</span>
          <div className="flex-1">
            <h4 className="text-sm font-semibold text-slate-900">High Overlap</h4>
            <p className="text-xs text-slate-600">₹4.8L locked in duplicates</p>
          </div>
          <button className="text-xs text-red-600 font-medium">View</button>
        </div>
        
        {/* Signal 2 */}
        <div className="flex items-start gap-3 p-3 bg-amber-50 rounded-lg border border-amber-200">
          <span className="text-lg">🟡</span>
          <div className="flex-1">
            <h4 className="text-sm font-semibold text-slate-900">Overexposure</h4>
            <p className="text-xs text-slate-600">35% in Financial sector</p>
          </div>
          <button className="text-xs text-amber-600 font-medium">View</button>
        </div>
        
        {/* Signal 3 */}
        <div className="flex items-start gap-3 p-3 bg-slate-50 rounded-lg border border-slate-200">
          <span className="text-lg">🟢</span>
          <div className="flex-1">
            <h4 className="text-sm font-semibold text-slate-900">Performance Issues</h4>
            <p className="text-xs text-slate-600">1 underperforming fund</p>
          </div>
          <button className="text-xs text-slate-600 font-medium">View</button>
        </div>
      </div>
    </AccordionContent>
  </AccordionItem>
</Accordion>
```

**Expanded State (Signal Details):**
```jsx
<div className="signal-detail p-4 bg-white border border-slate-200 rounded-xl">
  <h4 className="text-lg font-bold text-slate-900 mb-2">
    🔴 High Overlap / Redundancy
  </h4>
  
  <p className="text-sm text-slate-600 mb-3">
    2 of your mutual funds hold 95% similar stocks
  </p>
  
  <div className="bg-red-50 rounded-lg p-3 mb-3">
    <p className="text-sm font-semibold text-red-800">
      Impact: ₹4,80,000 locked in duplicate holdings
    </p>
  </div>
  
  <div className="space-y-2 mb-3">
    <p className="text-xs font-semibold text-slate-700">Affected Assets:</p>
    <ul className="text-xs text-slate-600 space-y-1">
      <li>• HDFC Flexi Cap Direct (₹4.8L)</li>
      <li>• HDFC Flexi Cap Regular (₹4.5L)</li>
    </ul>
  </div>
  
  <div className="bg-slate-50 rounded-lg p-3">
    <p className="text-xs text-slate-600">
      <span className="font-semibold">Recommended:</span> Exit one of the overlapping funds
      → See Action 1
    </p>
  </div>
</div>
```

**Rules:**
- Default state: Collapsed
- No heavy charts initially (text-based summaries)
- Clean and data-focused

---

### 5. Bottom Action Bar (Sticky Footer)

**Type:** Sticky Footer  
**Position:** Fixed bottom  
**Classes:**
```css
fixed bottom-0 left-0 right-0 z-50 
bg-white/90 backdrop-blur-xl 
border-t border-slate-200 
p-4 flex gap-3 pb-8
```

**Structure:**
```jsx
<div className="bottom-action-bar">
  {/* Update Plan (Ghost button) */}
  <button 
    className="flex-1 h-14 border-2 border-slate-300 text-slate-700 font-semibold rounded-xl active:scale-[0.98] transition-transform"
    data-testid="update-plan-button"
  >
    Update Plan
  </button>
  
  {/* Simulate (Primary button) */}
  <button 
    className="flex-1 h-14 bg-slate-900 text-white font-semibold rounded-xl active:scale-[0.98] transition-transform"
    data-testid="simulate-button"
  >
    Simulate
  </button>
</div>
```

**Rules:**
- Thumb-friendly zone
- Both buttons h-14 (56px) for easy reachability
- Backdrop blur for depth

---

### 6. Loading States (Skeleton Loaders)

**Type:** Shadcn Skeleton  
**Goal:** < 2s perceived load time

**Structure:**
```jsx
import { Skeleton } from "@/components/ui/skeleton"

<div className="space-y-4">
  {/* Skeleton for Action Card */}
  <div className="w-full bg-white border border-slate-200 rounded-2xl p-5">
    <Skeleton className="h-4 w-20 mb-2" />
    <Skeleton className="h-16 w-40 mb-2" />
    <Skeleton className="h-6 w-full mb-2" />
    <Skeleton className="h-4 w-3/4 mb-4" />
    <Skeleton className="h-14 w-full" />
  </div>
  
  {/* Repeat for multiple cards */}
</div>
```

---

## 🎭 MOTION & INTERACTIONS

### Button Interactions
```css
active:scale-[0.98] 
transition-transform duration-200
```

### Card Entrance Animation
```css
opacity-0 
animate-in fade-in slide-in-from-bottom-4 
duration-500 
fill-mode-forwards
```

### Stagger Effect
```jsx
<div style={{ animationDelay: '100ms' }}>Card 1</div>
<div style={{ animationDelay: '200ms' }}>Card 2</div>
<div style={{ animationDelay: '300ms' }}>Card 3</div>
```

### Collapsible Transitions
Use smooth height transitions for Accordions and Sticky Plan

---

## 🎨 ICONS & MEDIA

### Icon Library
**Phosphor Icons React:** `@phosphor-icons/react`

**Weight:** Duotone (premium look) or Regular (high clarity)  
**Size in buttons:** 24px

**Example Usage:**
```jsx
import { CheckCircle, Warning, Plus } from "@phosphor-icons/react"

<CheckCircle size={24} weight="duotone" />
```

### Media Assets

**Success Icon (3D):**
```
URL: https://static.prod-images.emergentagent.com/jobs/4e9376a1-4655-428d-b72e-6348a2e38dbd/images/7017bf4543cd786cb8a11a1f4f247b4073dd7ac9e36a5e466259328114f424b4.png
Usage: Show when all actions completed
```

**User Avatar:**
```
URL: https://images.pexels.com/photos/6146051/pexels-photo-6146051.jpeg?auto=compress&cs=tinysrgb&dpr=2&h=650&w=940
Usage: Header profile section
```

---

## 🧪 TESTING REQUIREMENTS

### Data TestID Attributes
**All interactive and key informational elements MUST include:**
```jsx
data-testid="mark-done-button-sell"
data-testid="action-card-exit-1"
data-testid="update-plan-button"
data-testid="signals-accordion"
```

**Format:** kebab-case, role-based

---

## 📱 STATE MANAGEMENT (UI States)

### No Plan State
```jsx
<div className="text-center p-8">
  <h3 className="text-xl font-bold mb-2">
    We found 3 improvements
  </h3>
  <button className="w-full min-h-[56px] bg-slate-900 text-white font-semibold rounded-xl">
    Generate Plan
  </button>
</div>
```

### Active Plan State
```jsx
<div className="sticky-action-plan">
  <p className="text-sm text-slate-600">
    Progress: 1/3 • Next: Sell ₹4.8L
  </p>
</div>
```

### Outdated Plan State
```jsx
<div className="bg-amber-50 border border-amber-200 rounded-xl p-4 mb-4">
  <p className="text-sm text-amber-800 mb-2">
    ℹ️ Plan needs update (portfolio changed)
  </p>
  <button className="text-sm font-semibold text-amber-600">
    Update Now
  </button>
</div>
```

### Completed State
```jsx
<div className="text-center p-8">
  <img src={successIconUrl} className="w-32 h-32 mx-auto mb-4" />
  <h3 className="text-2xl font-bold text-emerald-600 mb-2">
    All actions completed 🎉
  </h3>
  <p className="text-sm text-slate-600 mb-4">
    You've successfully optimized your portfolio!
  </p>
  <button className="w-full min-h-[56px] bg-slate-900 text-white font-semibold rounded-xl">
    Generate New Plan
  </button>
</div>
```

---

## 📋 IMPLEMENTATION CHECKLIST

### Phase 1: Setup
- [ ] Install fonts: Outfit, Manrope
- [ ] Install Phosphor Icons: `@phosphor-icons/react`
- [ ] Configure Tailwind with custom colors
- [ ] Set up Shadcn components (Accordion, Select, Skeleton)

### Phase 2: Components
- [ ] Header with Version Toggle
- [ ] Sticky Action Plan
- [ ] Action Card (3 states: PENDING, COMPLETED, SKIPPED)
- [ ] Progress Indicator
- [ ] Portfolio Signals (Accordion)
- [ ] Bottom Action Bar
- [ ] Loading Skeletons

### Phase 3: States
- [ ] No Plan state
- [ ] Active Plan state
- [ ] Outdated Plan state
- [ ] Completed state

### Phase 4: Polish
- [ ] Entrance animations (stagger effect)
- [ ] Button interactions (scale effect)
- [ ] Smooth transitions
- [ ] Test on mobile (thumb reachability)

### Phase 5: Testing
- [ ] Add data-testid to all interactive elements
- [ ] Test 1-hand usage
- [ ] Verify < 10s comprehension
- [ ] Verify < 3 taps to action
- [ ] Test on multiple screen sizes

---

## 🎯 GOLDEN RULES (NEVER VIOLATE)

1. **Button height ≥ 48px** (56px optimal)
2. **No multi-column layouts** on mobile
3. **Left-align all financial data** (never center)
4. **1 line for title, 1 line for reason**
5. **No paragraphs, no jargon**
6. **If user can't act in 1 thumb tap, redesign**
7. **Load time < 2s** (use skeleton loaders)
8. **Full-width cards** on mobile
9. **Card padding ≥ 20px** (p-5 minimum)
10. **₹ Amount is always the hero element** (largest font)

---

**Document Version:** 2.0 FINAL  
**Last Updated:** 2026-04-19  
**Author:** E1 Agent + Design Agent  
**Status:** ✅ Ready for Implementation

---

**Next Step:** Start building V2 UI using these specifications! 🚀
