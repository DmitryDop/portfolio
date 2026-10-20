---
name: portfolio-case-builder
description: >
  Prepare, edit, design and implement portfolio case studies for the Dopler portfolio.
  Use for case audits, case content, Figma case layouts, handoff, and safe implementation.
  Work from docs/portfolio/case-template.md and docs/portfolio/editorial-guide.md;
  preserve the project's existing patterns, AGENTS.md and production workflows.
---

# Portfolio Case Builder

## Mission and scope

Create or update **individual portfolio case pages** in the `portfolio` repository. A case should tell a clear, factually grounded story and fit the site's established visual language without forcing every story into the same layout.

This skill is **not** a deploy, rollback, Git publication, or general site redesign skill. Do not modify the homepage or unrelated pages unless the user explicitly asks. Do not assume the repository has a formal design system.

## Source of truth (priority)

1. The user's latest explicit instructions and approved decisions for the current case.
2. Repository-level and directory-level `AGENTS.md` and other binding project instructions, especially production safety rules.
3. `docs/portfolio/case-template.md` for case structure, content schema, media and Figma handoff.
4. `docs/portfolio/editorial-guide.md` for voice, factual integrity and editing.
5. Existing live case pages, components, styles and patterns in this repository.
6. Existing `humanizer` skill, **if available**, as a supporting editorial check—not an authority.

If a referenced file is missing, **report the absence** and continue only with confirmed rules. Never invent its contents. If sources conflict, respect `AGENTS.md` and production restrictions; ask the user to resolve substantive creative conflicts before making irreversible changes.

## Operating principles

- **Facts before polish.** Do not invent research, interviews, metrics, launch outcomes, team responsibilities, integrations or business impact.
- **Authorial accuracy.** Separate the designer's contribution from team effort, assumptions from evidence, and delivered work from concepts.
- **No mandatory section count.** Select blocks to serve the story; reuse site patterns where useful and design new ones where warranted.
- **No automatic rewriting after approval.** Treat approved copy as immutable, including headings, labels and CTA wording. Suggest changes separately for approval. Preserve approved text character for character, including punctuation and whitespace; do not apply automatic typography changes from Codex/Claude guidance to it.
- **Native Figma layers.** When Figma work is authorized and tooling supports it, produce editable text, frames, components and image placeholders—not a flat screenshot presented as an editable layout.
- **Desktop-first by default.** Prepare the approved desktop composition; derive responsive behavior during implementation using the project's current approach. Don't fabricate fully designed breakpoints unless requested.
- **No silent publishing.** Never commit, push, deploy, trigger release or mutate production unless the user explicitly authorizes that specific action and project safety rules allow it.
- **Minimum-change policy.** Keep all work scoped to the current case and approved supporting files.

## Workflow

### 0. Establish context and safe scope

- Confirm repository root, branch, working tree status, and applicable `AGENTS.md` instructions before edits.
- Read the two documents in `docs/portfolio/` and inspect relevant case examples and reusable site styles.
- Check whether target case files or Figma frames already exist to avoid duplicates.
- Identify exactly which files and design frames may change. Preserve unrelated staged and untracked changes.
- If the user wants an audit or draft only, **do not modify the site**.

### 1. Audit / narrative brief

Record, as applicable:

- Project name, product category, audience and context.
- Problem, constraints, the designer's role, collaborators, and decisions.
- Work performed, selected screens or artifacts, and measured or observable outcome.
- Source for each material factual claim and gaps requiring confirmation.
- Visual assets currently available, including origin, formats and rights when relevant.
- Relevant existing case patterns and unique blocks proposed for this story.

Do not convert missing information into fictitious certainty. Offer a reasonable structure with open questions clearly marked.

### 2. Content draft and editorial review

- Store case-specific content at `docs/portfolio/cases/<slug>/content.md`; create it only within the explicitly approved case scope.
- Use `case-template.md` as a flexible structure, not a fixed number of sections.
- Prioritize concrete action and clear cause/effect over generic marketing language.
- Differentiate concise captions, case narrative, navigation labels and CTA copy.
- Apply `editorial-guide.md` first; optionally run the installed Humanizer for suggestions, then verify every proposed change against facts and voice.
- Mark missing facts with `[УТОЧНИТЬ]` in `draft`; resolve these markers before `content-approved` and never publish them.
- Request the user's approval of final wording. Once explicitly approved, record the version with status `content-approved` and freeze copy for subsequent stages.

**Humanizer rules (Codex and Claude Code):** Do not install or update it automatically. Analyze only a temporary copy of `draft` content in an authorized location; never pass the source file as its write target. Show proposed edits as a unified diff against the unchanged source and verify facts and voice. Only the editing agent may apply the explicitly approved changes to the source after user approval; Humanizer must never write to it. Do not run Humanizer on `content-approved` content. For revisions, first obtain approval to return to `draft`, then repeat this process. These rules take priority over Humanizer's default file mode for portfolio content.

### 3. Figma handoff and editable design

- Require an approved content draft before final design; exploratory wireframes may use clearly marked provisional copy.
- Derive spacing, typography, image treatment, grids and responsive intent from real site examples. Do **not** invent a full token system.
- Map content into a layout plan: hero, ordered narrative sections, media, optional special blocks, conclusion and CTA.
- Note for each block its text, visual role, asset/placeholder, intended interaction, and links/CTA destinations.
- When Figma tools are connected and editing is allowed, create or update editable desktop frames. Use real text layers and editable geometry; label placeholders explicitly. Check that key layers are editable.
- For missing images or video, use named placeholders with aspect ratio and asset requirements; do not fabricate finished assets or substitute generated visuals without a request.
- Review the proposed Figma design with the user. Do not call it approved without explicit confirmation.
- If Figma is inaccessible or cannot create native/editable layers, report the limitation and provide a content/layout specification instead; **never** claim a screenshot is a native Figma design.

### 4. Implementation handoff

Proceed **only after explicit approval** of design and implementation scope.

- Implement using existing HTML/CSS/JS or the framework actually present in the repository; do not assume a new stack.
- Reuse verified existing patterns where appropriate; keep novel layouts case-specific and maintainable.
- Preserve approved copy exactly. Verify CTA links and any outbound URLs with the user or reliable project information; do not guess destinations.
- Implement responsive layouts based on desktop design and established site behavior; test real narrow and wide widths rather than relying solely on visual extrapolation.
- Preserve accessibility basics: semantic headings, keyboard navigation, focus, contrast, alt text, reduced-motion behavior when applicable.
- Check asset paths, image loading, video fallback, links, and console output as available.
- Run the repository's relevant existing checks. Report checks not run or tools unavailable; do not invent passing results.

### 5. Review and delivery

Report in a compact handoff:

1. What was prepared or changed (file paths and Figma links/node IDs if available).
2. Copy status: `draft` / `content-approved`; list unresolved facts as `[УТОЧНИТЬ]` separately.
3. Design status: `not started` / `design-review` / `design-approved`.
4. What was tested, actual outcomes, and remaining issues.
5. What requires the user's next decision or authorization.
6. Explicit confirmation that commit, push and deploy were **not** performed, unless individually authorized and actually completed.

## Hard safety boundaries

- Read and respect all applicable `AGENTS.md` files. Never overwrite or weaken those instructions.
- Do **not** execute, edit, bypass or reconfigure `.deploy/`, deploy/rollback/baseline skills, production scripts, server access, credentials or CI/CD unless expressly tasked under their own governing workflows.
- Do **not** run `git add`, `git commit`, `git push`, destructive resets, cleaning or branch rewrites by default.
- Do **not** change production metadata or publish generated content automatically.
- Do **not** alter other case pages or shared styles beyond explicitly approved scope.
- Do **not** silently overwrite a case's existing Figma frames or approved content.
- If instructions are ambiguous, favor a read-only audit or scoped draft rather than a risky mutation.

## Definition of done by stage

- **Content:** fact-checked to the extent evidence is available, editorially reviewed, with explicit status and unresolved claims visible.
- **Figma:** content mapped to editable frames, placeholders labeled, layout reviewed, and user approval recorded before implementation.
- **Implementation:** scope-respecting code changes, responsive and link checks reported, no hidden deployment.

## Activation examples

- “Собери новый кейс DIAMOND по нашему шаблону.”
- “Проверь текст кейса по editorial-guide и Humanizer, не переписывая утверждённое.”
- “Подготовь редактируемые фреймы кейса в Figma на основе утверждённого content.md.”
- “Передай согласованный кейс в вёрстку без commit, push и deploy.”
