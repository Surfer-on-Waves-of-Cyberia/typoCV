import argparse
import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path


def _norm_tag(tag: str) -> str:
    t = tag.strip().lower()
    return t if t.startswith("#") else f"#{t}"


def _clean_text(text: str) -> str:
    cleaned = re.sub(r"\[TODO[^\]]*\]", "", text or "")
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip(" –—-")
    return cleaned.strip()


def score_obj(obj: dict, tag_weights: dict) -> float:
    base = float(obj.get("priority", obj.get("weight", 2))) * 2.5
    norm_weights = {_norm_tag(k): float(v) for k, v in tag_weights.items()}
    tags = [_norm_tag(t) for t in obj.get("tags", [])]

    matched = [norm_weights[t] for t in tags if t in norm_weights]
    tag_bonus = sum(matched) * 0.55 if matched else 0.0

    raw_heading = " ".join(
        str(obj.get(k, "")) for k in ("name", "title", "role_de", "degree_de")
    )
    todo_penalty = -1.5 if "[TODO" in raw_heading else 0.0
    return base + tag_bonus + todo_penalty


def select_items(
    items: list[dict],
    tag_weights: dict,
    limit: int | None,
    prefer_ids: list[str] | None = None,
    unfiltered: bool = False,
) -> list[dict]:
    if unfiltered:
        return list(items)

    prefer_ids = prefer_ids or []
    pref_rank = {item_id: idx for idx, item_id in enumerate(prefer_ids)}

    candidates = []
    for idx, item in enumerate(items):
        if not item.get("default_visible", True) and item.get("id") not in pref_rank:
            continue
        candidates.append((idx, item))

    def sort_key(pair: tuple[int, dict]):
        orig_idx, item = pair
        item_id = item.get("id")
        has_pref = 0 if item_id in pref_rank else 1
        pref_pos = pref_rank.get(item_id, 999)
        return (has_pref, pref_pos, -score_obj(item, tag_weights), orig_idx)

    ranked = [item for _, item in sorted(candidates, key=sort_key)]
    return ranked if limit is None else ranked[:limit]


def _select_sub_bullets(sub_items: list, tag_weights: dict, max_bullets: int = 2) -> list[str]:
    scored = []
    for idx, b in enumerate(sub_items or []):
        if isinstance(b, str):
            txt = _clean_text(b)
            if txt:
                scored.append((0.0, idx, txt))
            continue
        if not b.get("default_visible", True):
            continue
        txt = _clean_text(str(b.get("text", "")))
        if txt:
            scored.append((score_obj(b, tag_weights), idx, txt))

    scored.sort(key=lambda x: (-x[0], x[1]))
    return [txt for _, _, txt in scored[:max_bullets]]


def _format_period(period_field) -> str:
    if isinstance(period_field, dict):
        if period_field.get("display_de"):
            return str(period_field["display_de"])
        start = period_field.get("start") or ""
        end = period_field.get("end") or ("heute" if period_field.get("is_current") else "")
        return f"{start} – {end}".strip(" –")
    return str(period_field or "")


def render_table_rows(items: list[dict], kind: str, tag_weights: dict) -> str:
    rows = []
    for item in items:
        period = _format_period(item.get("period"))

        if kind == "education":
            title = _clean_text(item.get("degree_de") or item.get("title", ""))
            org = _clean_text(item.get("institution") or item.get("org", ""))
            sub_list = item.get("highlights_de") or item.get("bullets", [])
            extra_line = ""
            gpa = item.get("gpa")
            if isinstance(gpa, dict) and gpa.get("default_visible") and gpa.get("value") is not None:
                val = str(gpa["value"]).replace(".", ",")
                extra_line = f'<p class="summary">Schnitt: <strong>{val}</strong></p>'

        elif kind == "experience":
            title = _clean_text(item.get("role_de") or item.get("title", ""))
            org = _clean_text(item.get("organization") or item.get("org", ""))
            sub_list = item.get("bullets_de") or item.get("bullets", [])
            extra_line = ""

        else:
            title = _clean_text(item.get("name") or item.get("title", ""))
            org = _clean_text(item.get("context_de") or item.get("org", ""))
            sub_list = item.get("bullets_de") or item.get("bullets", [])
            stack = [_clean_text(s) for s in (item.get("tech_stack") or []) if _clean_text(s)]
            extra_line = (
                f'<p class="summary"><strong>Stack:</strong> {", ".join(stack[:6])}</p>'
                if stack
                else ""
            )

        org_html = f' <span class="org">— {org}</span>' if org else ""
        bullets = _select_sub_bullets(sub_list, tag_weights, max_bullets=2)
        bullets_html = (
            "<ul>" + "".join(f"<li>{b}</li>" for b in bullets) + "</ul>"
            if bullets
            else ""
        )

        body = "\n".join(
            part
            for part in [f'<div class="title">{title}{org_html}</div>', extra_line, bullets_html]
            if part
        )

        rows.append(
            f"""<table class="row-tbl">
  <tr>
    <td class="col-date">{period}</td>
    <td class="col-body">
      {body}
    </td>
  </tr>
</table>"""
        )
    return "\n".join(rows)


def _format_skills_bucket(
    skills_dict: dict, bucket_keys: list[str], tag_weights: dict, limit: int = 6
) -> str:
    collected = []
    for b_idx, bkey in enumerate(bucket_keys):
        for s_idx, sk in enumerate(skills_dict.get(bkey, [])):
            if not isinstance(sk, dict) or not sk.get("default_visible", True):
                continue
            name = _clean_text(sk.get("name", ""))
            if not name:
                continue
            collected.append((score_obj(sk, tag_weights), b_idx * 100 + s_idx, name))

    collected.sort(key=lambda x: (-x[0], x[1]))
    unique_names = []
    for _, _, name in collected:
        if name not in unique_names:
            unique_names.append(name)
        if len(unique_names) >= limit:
            break
    return ", ".join(unique_names)


def _format_languages(skills_dict: dict) -> str:
    entries = []
    for idx, item in enumerate(skills_dict.get("languages", [])):
        if not isinstance(item, dict) or not item.get("default_visible", True):
            continue
        lang = _clean_text(item.get("language_de") or item.get("name", ""))
        lvl = _clean_text(item.get("level_de", ""))
        if lang:
            prio = float(item.get("priority", 2))
            label = f"{lang} ({lvl})" if lvl else lang
            entries.append((-prio, idx, label))
    entries.sort()
    return ", ".join(x[2] for x in entries)


def render_html(
    template_str: str,
    cv: dict,
    prof: dict,
    weights: dict,
    limits: dict,
    unfiltered: bool = False,
) -> str:
    personal = cv.get("personal", {})
    contact = personal.get("contact", {})
    addr = personal.get("address", {})
    links = personal.get("links", {})
    license_obj = personal.get("drivers_license", {})
    skills = cv.get("skills", {})

    location_str = ", ".join(p for p in [addr.get("postal_code"), addr.get("city")] if p)
    license_str = ""
    if isinstance(license_obj, dict) and license_obj.get("default_visible"):
        license_str = _clean_text(license_obj.get("notes_de", ""))

    edu_items = select_items(
        cv.get("education", []),
        weights,
        None if unfiltered else limits.get("education", 3),
        prefer_ids=prof.get("prefer_education", []),
        unfiltered=unfiltered,
    )
    exp_items = select_items(
        cv.get("experience", []),
        weights,
        None if unfiltered else limits.get("experience", 3),
        prefer_ids=prof.get("prefer_experience", []),
        unfiltered=unfiltered,
    )
    proj_items = select_items(
        cv.get("projects", []),
        weights,
        None if unfiltered else limits.get("projects", 5),
        prefer_ids=prof.get("prefer_projects", []),
        unfiltered=unfiltered,
    )

    notes_raw = cv.get("meta", {}).get("notes", "")
    projects_note = (
        "Auswahl aus aktuellen Hochschul- & Eigenprojekten (GitHub & Audio/Video-Links oben)."
        if "[TODO" in notes_raw
        else _clean_text(notes_raw)
    )

    media_limit = 999 if unfiltered else 4
    tech_limit = 999 if unfiltered else 7
    docs_limit = 999 if unfiltered else 4

    replacements = {
        "{{NAME}}": _clean_text(personal.get("full_name", "")),
        "{{LOCATION}}": location_str,
        "{{PHONE}}": _clean_text(contact.get("phone", "")),
        "{{EMAIL}}": _clean_text(contact.get("email", "")),
        "{{GITHUB}}": _clean_text(links.get("github") or ""),
        "{{VIDEO}}": _clean_text(links.get("youtube_film_collab") or ""),
        "{{LICENSE}}": license_str,
        "{{TARGET_ROLE}}": "" if unfiltered else _clean_text(prof.get("target_role", "")),
        "{{EDUCATION_HTML}}": render_table_rows(edu_items, "education", weights),
        "{{EXPERIENCE_HTML}}": render_table_rows(exp_items, "experience", weights),
        "{{PROJECTS_HTML}}": render_table_rows(proj_items, "projects", weights),
        "{{PROJECTS_NOTE}}": projects_note,
        "{{SKILLS_MEDIA}}": _format_skills_bucket(
            skills, ["media_ui_and_creative_tech"], weights, limit=media_limit
        ),
        "{{SKILLS_TECH}}": _format_skills_bucket(
            skills,
            [
                "programming_languages",
                "frameworks_protocols_and_architecture",
                "linux_devops_and_tools",
            ],
            weights,
            limit=tech_limit,
        ),
        "{{SKILLS_DOCS}}": _format_skills_bucket(
            skills, ["frameworks_protocols_and_architecture"], weights, limit=docs_limit
        ),
        "{{SKILLS_LANG}}": _format_languages(skills),
    }

    out = template_str
    for key, val in replacements.items():
        out = out.replace(key, str(val))
    return out


def export_pdf(html_path: Path, pdf_path: Path) -> None:
    pdf_abs = str(pdf_path.resolve())
    html_uri = html_path.resolve().as_uri()

    if shutil.which("weasyprint"):
        subprocess.run(["weasyprint", str(html_path), pdf_abs], check=True, timeout=30)
        return

    for browser in ("chromium", "chromium-browser", "google-chrome"):
        if shutil.which(browser):
            subprocess.run(
                [
                    browser,
                    "--headless",
                    "--no-sandbox",
                    f"--print-to-pdf={pdf_abs}",
                    html_uri,
                ],
                check=True,
                timeout=30,
            )
            return

    if shutil.which("firefox"):
        with tempfile.TemporaryDirectory(prefix="typocv_ff_") as tmp_profile:
            env = {
                **os.environ,
                "NO_AT_BRIDGE": "1",
                "MOZ_DISABLE_RDD_WEBRTC": "1",
                "LIBGL_ALWAYS_SOFTWARE": "1",
            }
            subprocess.run(
                [
                    "firefox",
                    "--headless",
                    "--no-remote",
                    "--profile",
                    tmp_profile,
                    "--print-to-pdf",
                    pdf_abs,
                    html_uri,
                ],
                env=env,
                check=True,
                timeout=30,
            )
        return

    if shutil.which("wkhtmltopdf"):
        subprocess.run(["wkhtmltopdf", str(html_path), pdf_abs], check=True, timeout=30)
        return

    raise RuntimeError(
        "Kein PDF-Renderer gefunden (weasyprint, chromium, chrome, firefox oder wkhtmltopdf)."
    )


def main() -> None:
    candidates = [
        Path("cv_0.5.0.json"),
        Path("master_cv.json"),
        Path("../cv_0.5.0.json"),
        Path("../master_cv.json"),
        Path("../master_cv_0.5.0.json"),
    ]
    default_cv = next((p for p in candidates if p.exists()), Path("cv_0.5.0.json"))

    parser = argparse.ArgumentParser()
    parser.add_argument("--cv", default=str(default_cv), help="Pfad zur JSON-Basisdaten-Datei")
    parser.add_argument("--profile", default="profiles/media_praktikum_de.json")
    parser.add_argument("--template", help="Überschreibt das Template aus dem Profil")
    parser.add_argument("--out-dir", default="out")
    parser.add_argument("--all", action="store_true", help="Alle Einträge ohne Filter und Limits ausgeben")
    args = parser.parse_args()

    cv_path = Path(args.cv)
    if not cv_path.exists():
        raise FileNotFoundError(
            f"JSON-Datei nicht gefunden: {cv_path} (aktuelles Verzeichnis: {Path.cwd()})"
        )

    profile_path = Path(args.profile)
    cv = json.loads(cv_path.read_text(encoding="utf-8"))
    prof = json.loads(profile_path.read_text(encoding="utf-8")) if profile_path.exists() else {}

    weights = prof.get("tag_weights", {})
    limits = prof.get("limits", {})

    template_name = args.template or prof.get("template", "swiss_grid")
    template_path = Path("templates") / f"{template_name}.html"
    if not template_path.exists():
        raise FileNotFoundError(f"Template nicht gefunden: {template_path}")

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    html = render_html(
        template_path.read_text(encoding="utf-8"),
        cv,
        prof,
        weights,
        limits,
        unfiltered=args.all,
    )
    html_file = out_dir / "cv.html"
    pdf_file = out_dir / "cv.pdf"

    html_file.write_text(html, encoding="utf-8")
    export_pdf(html_file, pdf_file)
    print(f"Fertig: {pdf_file} (Quelle: {cv_path.name}, Template: {template_name})")


if __name__ == "__main__":
    main()