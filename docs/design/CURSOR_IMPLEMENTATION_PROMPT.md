# Cursor Implementation Prompt --- Operational Dashboard Visual System

Use this prompt when asking Cursor to implement or refactor dashboard
UI.

## Role

Act as a senior frontend engineer, UI engineer, and design-system
implementer.

The dashboard is an existing operational product. Do not replace
functional behavior, business logic, data flow, APIs, routing,
authentication, or existing operational functionality unless explicitly
requested.

Your job is to apply the visual design system and art direction defined
in:

-   `DESIGN_SYSTEM.md`
-   `UI_ART_DIRECTION.md`

These two files are the visual source of truth.

------------------------------------------------------------------------

## Implementation Rules

### 1. Inspect before changing

Before writing code:

-   Inspect the existing project structure.
-   Identify the frontend framework.
-   Identify the styling system.
-   Identify existing component libraries.
-   Identify reusable layout/components.
-   Identify routing.
-   Identify existing dashboard pages.
-   Identify current theme/token files.

Do not create duplicate components when reusable components already
exist.

------------------------------------------------------------------------

### 2. Preserve functionality

Do not break:

-   API calls
-   State management
-   Authentication
-   Routing
-   Forms
-   Tables
-   Filters
-   Charts
-   Search
-   Pagination
-   Existing business logic

Visual refactoring must be non-destructive.

------------------------------------------------------------------------

### 3. Establish tokens first

Before redesigning individual pages, implement or consolidate:

-   colors
-   typography
-   spacing
-   borders
-   radius
-   shadows
-   motion
-   decoration tokens

Use CSS variables, theme tokens, or the project's equivalent
architecture.

Do not scatter hardcoded values throughout components.

------------------------------------------------------------------------

### 4. Build the decoration system

Create a reusable geometric decoration component/system.

It should support:

``` text
type
color
size
rotation
position
opacity
zIndex
animation
delay
```

Possible types:

``` text
square
circle
half-circle
arc
capsule
outline-square
outline-circle
line
dots
grid
cube
extruded-cube
fragment
```

Do not hardcode individual decorative SVG fragments into unrelated
pages.

------------------------------------------------------------------------

### 5. Implement controlled randomization

Create a deterministic/context-aware decoration selection mechanism.

The result should be varied, but it should not change every render.

Avoid using uncontrolled `Math.random()` during rendering.

Prefer:

-   deterministic seeded selection
-   stable component identifiers
-   predefined decoration variants
-   safe placement zones

The visual result should remain stable between renders.

------------------------------------------------------------------------

### 6. Decoration density

Use approximately:

``` text
35% none
40% one
20% two
5% three-to-five
```

Adapt density based on component type.

Dense tables and forms should receive little or no decoration.

Large feature panels may receive more.

------------------------------------------------------------------------

### 7. Collision safety

Decorations must not overlap:

-   important text
-   buttons
-   inputs
-   charts
-   tables
-   navigation
-   alerts
-   interactive controls

Use safe placement zones and overflow handling.

------------------------------------------------------------------------

### 8. Animation

Implement ambient animations:

``` text
float
drift
rotate
pulse
orbit
micro-shift
```

Use slow durations around 4--12 seconds.

Use different delays and durations.

Animations must be subtle.

Respect:

``` css
prefers-reduced-motion: reduce
```

------------------------------------------------------------------------

### 9. Responsive behavior

Desktop:

full decoration system

Tablet:

reduce decoration

Mobile:

strongly reduce decoration and eliminate risky overlaps

Never allow decoration to create horizontal overflow.

------------------------------------------------------------------------

### 10. Component variants

Prefer variants over one-off styling.

Examples:

``` text
Card:
default
minimal
lime
orange
blue
dark
featured

Button:
primary
secondary
accent
ghost
danger

Decoration:
small
medium
large
outline
filled
3D
```

------------------------------------------------------------------------

### 11. Preserve project conventions

Follow the project's existing:

-   naming conventions
-   file structure
-   state management
-   styling methodology
-   TypeScript conventions
-   linting
-   formatting
-   testing
-   component patterns

Do not introduce a new framework or library without a clear reason.

------------------------------------------------------------------------

### 12. Visual QA

After implementation:

-   Check desktop.
-   Check tablet.
-   Check mobile.
-   Check dense data screens.
-   Check long text.
-   Check loading states.
-   Check empty states.
-   Check error states.
-   Check keyboard focus.
-   Check reduced motion.
-   Check decoration collisions.
-   Check overflow.

------------------------------------------------------------------------

## Implementation Objective

Do not merely make the dashboard colorful.

Make it feel like a coherent, production-ready product whose visual
identity is encoded in reusable components and tokens.

The final result should preserve all existing operational functionality
while introducing:

-   Neo-Brutalist structure
-   Neo-Memphis geometric personality
-   Editorial composition
-   Strong typography
-   Cream + navy foundation
-   Lime/orange/blue accents
-   Controlled geometric decoration
-   Subtle ambient animation
-   Responsive behavior
-   Accessible interaction
-   Consistent reusable design tokens

The reference image is inspiration only. Do not clone it.
