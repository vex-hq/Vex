# Live Agent Demo Page — Design

## Goal

A dedicated `/demo` page on the landing app showing a scripted 30-60 second animation of a support ticket classifier agent. Vex catches drift and auto-corrects in real-time. No real API calls — all hardcoded data with CSS animations.

## Three Phases

### Phase 1: Normal Operation (~15s)
- Left panel: incoming support tickets appear one at a time (typewriter/fade-in effect)
- Right panel: Vex dashboard showing classification results with green "pass" badges, confidence 0.95+
- 3-4 tickets classified correctly: "Can't login" → Technical, "Refund request" → Billing, etc.

### Phase 2: Drift Injection (~15s)
- Visual indicator: "Model drift detected" — confidence starts dropping
- 1-2 tickets get misclassified: "Payment failed" → Technical (should be Billing)
- Right panel shows amber "flag" badge, confidence drops to 0.6
- Vex terminal log: `drift_score: 0.45 → action: flag`

### Phase 3: Auto-Correction (~15s)
- Vex catches drift, triggers correction cascade
- Terminal: L1 prompt refinement → re-classify → confidence back to 0.92
- Corrected output replaces wrong one with green "corrected" badge
- Summary: "3 issues caught, 2 auto-corrected, 0 reached production"

## Visual Design

- Dark theme matching landing page (`#0a0a0a` bg, `#161616` cards, emerald accent)
- Split layout: left = ticket feed, right = Vex monitoring panel
- CSS animations only — `IntersectionObserver` + staggered reveals + `setInterval` cadence (same pattern as existing `how-it-works.tsx`)
- Auto-plays on scroll into view, with a "Replay" button
- Monospace terminal-style log at the bottom of the right panel
- Typography: Inter for UI, JetBrains Mono for terminal/code

## Page Structure

```
/demo
├── Hero: "Watch Vex Protect an Agent in Real-Time" + subtitle
├── Live Demo: the interactive split-panel animation
├── Key Takeaways: 3 cards (Detect, Correct, Zero downtime)
└── CTA: "Start protecting your agents" → signup
```

## Technical Approach

- New page: `apps/landing/app/demo/page.tsx` (server component, metadata)
- New component: `apps/landing/app/demo/_components/live-demo.tsx` (client component, all animation logic)
- Scripted data: array of ticket objects with phase, classification, confidence, isCorrect, correctedTo fields
- Animation: `IntersectionObserver` triggers playback, `setInterval` at ~600ms advances through the sequence
- Replay: reset state index to 0, re-trigger interval
- No new dependencies — CSS animations + React state only

## Non-Goals

- Real API calls to Vex backend
- Configurable demo scenarios
- Mobile-optimized layout (responsive but simplified on mobile)
