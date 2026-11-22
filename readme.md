# typoCV

A lightweight, plain-text CV generator and editor built around a single structured JSON source. Instead of maintaining multiple divergent resume files, `typoCV` uses weighted tag profiles ("lenses") and modular HTML/CSS templates to render tailored PDF resumes on demand.

## Features

- **Single Source of Truth:** Store education, experience, projects and skills once in JSON with priority levels, tags, and visibility flags.
- **Role-Based Lenses:** Filter and rank entries dynamically via JSON profiles (`profiles/`) or render the complete unfiltered dataset with `--all`.
- **Decoupled Architecture:** `CvStore` handles data persistence and build orchestration independently of the interactive `tkinter` GUI and CLI frontends.
- **Zero Heavy Dependencies:** Runs on standard Python 3 and exports PDFs via headless browser (`chromium`/`firefox`) or `weasyprint`.

## Project Structure

- `build_cv.py` — Core scoring, filtering, HTML rendering, and PDF export pipeline.
- `edit_cv.py` — GUI (`--ui gui`) and CLI (`--ui cli`) editor for managing CV entries and triggering builds.
- `cv.example.json` — Anonymized sample dataset following the established JSON schema.
- `profiles/` — Tag weightings and section limits for specific target roles.
- `templates/` — Print-ready HTML/CSS layouts (`swiss_grid`, `tty_term`, `editorial_folio`, etc.).

## Quick Start

1. Copy the example dataset to create your local working file (ignored by Git):

   ```bash
   cp cv.example.json master_cv_0.5.0.json
   ```

2. Launch the interactive editor (GUI by default):

   ```bash
   python3 edit_cv.py --cv master_cv_0.5.0.json
   ```

3. Or build a PDF directly from the command line:

   ```bash
   python3 build_cv.py --cv master_cv_0.5.0.json --profile profiles/python_tooling_demo.json --template swiss_grid
   ```

## Roadmap & Future Tasks

    - [ ] **Editors:** Dedicated editors for profiles ("lenses"), visual themes/templates, and direct post-build adjustments on the resulting resume.

    - [ ] **Interview Mascots:** Adding interactive mascots/characters to guide data collection and questionnaire-based entry creation.

    - [ ] **Workflow Modes:** Manual intuitive editing (with and without optional AI assistance) alongside an emergency "due yesterday" fast-track mode.

    - [ ] **Dates & Deadlines:** Tracking application dates, deadlines, and reminders.

    - [ ] **Cross-Platform Apps & AI Styling:** Evolving toward desktop (likely Java) and mobile (likely Kotlin) applications with optional AI-assisted styling integrations (with optional local setup and cloud ).

## Weighting System & Profile Intuitiveness

*Documentation in progress — outlining how tag weights, priority levels, and section limits interact.*

## Vision

Freeing up human time and energy from repetitive bureaucratic formatting.

Keeping tools straightforward, self-directed, and in service of people rather than busywork.

## License

This project is licensed under the [MIT License](license.md).