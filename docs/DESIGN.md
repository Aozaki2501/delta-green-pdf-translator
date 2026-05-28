# DESIGN.md

Design system for the Delta Green PDF Translator web UI.

This project should feel like a restricted translation terminal for a conspiracy-horror archive: functional, dark, quiet, slightly hostile, but still readable for long translation jobs.

## 1. Visual Theme And Atmosphere

Primary references:
- VoltAgent-style dark AI-agent interface: void-black canvas, emerald accent, terminal-native surfaces.
- Warp/OpenCode-style developer utility: command-line clarity, task progress, precise status readouts.
- Delta Green tone: occult bureaucracy, field documents, classified systems, and "welcome to the apocalypse" dread.

The interface is not a landing page. It is an operator console.

Mood:
- restricted
- technical
- readable
- procedural
- black-site archive
- low-noise terminal

Avoid:
- playful SaaS dashboards
- pastel gradients
- rounded marketing cards
- decorative blobs
- generic AI chat UI
- hero imagery unless specifically requested

## 2. Color Palette

Core colors:

| Token | Hex | Use |
| --- | --- | --- |
| `void` | `#050605` | App background |
| `panel` | `#0A0E0A` | Sidebar, upload regions, tool panels |
| `panel-2` | `#101710` | Progress surfaces, secondary panels |
| `line` | `#1D3A25` | Borders, separators |
| `line-hot` | `#33FF66` | Active border, primary action |
| `text` | `#C8D6C8` | Body text |
| `text-dim` | `#7F927F` | Captions, helper text |
| `green` | `#33FF66` | Primary signal |
| `green-soft` | `#9CFFB5` | Hover text, positive metric |
| `red` | `#FF3B3B` | Errors, destructive warnings |
| `amber` | `#F2C14E` | Warnings, waiting states |
| `blue` | `#57A6FF` | Links, downloads |

Rules:
- Green is the primary system signal, not a decoration.
- Red is reserved for true errors and horror-document headings.
- Use amber sparingly for waiting or retry states.
- Do not use large gradients as a background.
- Do not let the UI become a single flat green-on-black wall; use dim text and border hierarchy.

## 3. Typography

Web UI:
- Primary UI font: system monospace stack, `Courier Prime`, `Consolas`, `Courier New`, monospace.
- Display/terminal title font: `VT323` or similar square terminal display.
- Chinese text must remain readable. Do not use ultra-thin weights for Chinese.

Hierarchy:

| Role | Size | Weight | Notes |
| --- | --- | --- | --- |
| App title | 36-44px | normal | Terminal display, uppercase |
| Section title | 22-28px | normal/bold | Short labels only |
| Panel title | 16-18px | bold | Operational headings |
| Body | 14-16px | regular | High contrast |
| Caption | 12-13px | regular | Dim, not tiny |
| Metric value | 22-30px | bold | Tabular if possible |

Copy style:
- Use operational labels: "PDF", "Glossary", "Progress", "Output".
- Use concrete status: "Translating page 12/80", "Retrying", "Using glossary.tsv".
- Avoid marketing claims or inspirational phrasing.

## 4. Layout Principles

The app should open directly to the working surface.

Default structure:
1. Header band: restricted system identity and short status line.
2. Sidebar: configuration controls.
3. Main column: upload inputs, task progress, output downloads.
4. Progress section: download-manager style with elapsed time, ETA, speed, cost.

Spacing:
- Page max width: 1200-1280px.
- Sidebar remains dense and predictable.
- Main content uses vertical rhythm, not floating cards.
- Use 1px borders, square corners, and narrow dividers.
- Cards are allowed only for metrics, repeated outputs, and task panels.

Never use:
- nested cards
- oversized landing-page hero
- decorative stat strips
- multiple floating panels with the same weight
- random pill labels

## 5. Components

### Buttons

Primary button:
- black background
- green border
- green text
- square corners
- hover: green fill, black text
- label should be a command: "START TRANSLATION", "DOWNLOAD WORD"

Secondary button:
- panel background
- dim border
- text color `text`
- hover border `green`

### Inputs

Inputs should look like terminal fields:
- panel background
- 1px border
- square corners
- green focus outline
- labels above controls
- helper captions below controls

### File Upload

Upload regions:
- dashed border
- panel background
- no rounded dropzone blob
- clear file type label
- show whether default glossary is active

### Metrics

Metrics are compact and utilitarian:
- Progress
- Elapsed
- ETA
- Speed
- Cost

They should read like a download manager, not analytics cards.

### Progress

Progress bar:
- thin to medium height
- green fill
- text format:
  `12/80 pages (15%) | elapsed 2m 10s | remaining 12m 8s`

Status line:
- monospace
- latest page
- current cost
- retry/failure state when applicable

## 6. Motion

Use motion only if the framework supports it cleanly.

Allowed:
- subtle progress updates
- blink/cursor accent for terminal headers
- soft hover state
- brief completion state

Avoid:
- heavy animations
- decorative scanning beams
- glitch effects that reduce readability
- noisy flashing

## 7. Delta Green Specific Design Language

Use the feeling of classified operational material, not official trade dress.

Allowed:
- "RESTRICTED" labels
- terminal wording
- dossier-like hierarchy
- sparse green linework
- red warning states
- black-site vocabulary

Avoid:
- copying official Delta Green logos
- imitating exact book covers or official page layouts
- using official art unless the user provides it and usage is appropriate
- making the UI look like an official Arc Dream product

Tone:
- "operator input"
- "translation protocol"
- "archive extraction"
- "progress file"
- "output package"

## 8. Word Output Design

Word output is a reading artifact, not a marketing page.

Current target:
- double-column body
- running header:
  - left: `// 绿色三角洲 //`
  - right: `// document section //`
- centered page number footer
- body 12pt, 1.5 line spacing
- clear red Heading 2
- black Heading 3
- strong paragraph readability over page density

Use the Word document to help proofreading:
- preserve headings
- avoid compressed paragraphs
- keep page breaks around reading-page groups
- do not over-style normal body text

## 9. Do And Don't

Do:
- make the interface feel like a serious tool
- preserve dark terminal atmosphere
- keep every panel functional
- make progress and output states obvious
- use readable Chinese text
- use restrained green accents

Don't:
- build a homepage
- add decorative images just for mood
- use bubbly cards
- hide task status
- make small low-contrast captions
- use color where a label or structure would be clearer

## 10. Agent Prompt Guide

When changing UI, use this prompt:

> Use `DESIGN.md`. Build a restricted terminal-style translation workstation inspired by VoltAgent/Warp-style developer tools and Delta Green's conspiracy-horror tone. Keep it operational, dark, square-cornered, readable, and progress-focused. Avoid marketing layout, generic cards, gradients, and decorative clutter.

When changing Word output:

> Preserve the DG reading artifact style: double-column body, running header, centered page numbers, body 12pt with 1.5 line spacing, red Heading 2, black Heading 3, and comfortable proofreading density.
