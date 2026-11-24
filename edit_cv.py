import argparse
import json
import os
import platform
import re
import shutil
import subprocess
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path


AVAILABLE_SECTIONS = [
    "education",
    "experience",
    "projects",
    "skills.programming_languages",
    "skills.frameworks_protocols_and_architecture",
    "skills.linux_devops_and_tools",
    "skills.media_ui_and_creative_tech",
    "skills.languages",
]


def _slugify_id(prefix: str, label: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", (label or "item").lower()).strip("_")
    slug = slug[:28] or "item"
    stamp = datetime.now().strftime("%m%d%H%M")
    return f"{prefix}_{slug}_{stamp}"


def _parse_tags(raw: str) -> list[str]:
    parts = [p.strip().lower() for p in re.split(r"[,\s]+", raw or "") if p.strip()]
    out = []
    for p in parts:
        tag = p if p.startswith("#") else f"#{p}"
        if tag not in out:
            out.append(tag)
    return out


def _parse_bullets(raw: str, tags: list[str], priority: int) -> list[dict]:
    lines = [ln.strip(" •-–—\t") for ln in (raw or "").splitlines() if ln.strip()]
    return [
        {
            "text": ln,
            "tags": list(tags),
            "priority": priority,
            "default_visible": True,
        }
        for ln in lines
    ]


class CvStore:
    """Чистий шар роботи з даними 0.5.0 JSON (без залежності від GUI/TUI)."""

    def __init__(self, path: Path):
        self.path = path
        self.data: dict = {}
        self.load()

    def load(self) -> dict:
        if self.path.exists():
            self.data = json.loads(self.path.read_text(encoding="utf-8"))
        else:
            self.data = {
                "meta": {"version": "0.5.0", "language_default": "de"},
                "personal": {},
                "education": [],
                "experience": [],
                "projects": [],
                "skills": {},
                "manual_selection": {},
            }
        return self.data

    def save(self, make_backup: bool = True) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if make_backup and self.path.exists():
            bak_path = self.path.with_suffix(self.path.suffix + ".bak")
            shutil.copy2(self.path, bak_path)

        tmp_path = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp_path.write_text(
            json.dumps(self.data, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        tmp_path.replace(self.path)

    def get_collection(self, section: str) -> list[dict]:
        if section.startswith("skills."):
            bucket = section.split(".", 1)[1]
            skills = self.data.setdefault("skills", {})
            return skills.setdefault(bucket, [])
        return self.data.setdefault(section, [])

    @staticmethod
    def item_key(section: str, index: int, item: dict) -> str:
        if isinstance(item, dict) and item.get("id"):
            return str(item["id"])
        return f"{section}:{index}"

    def get_manual_set(self, section: str) -> set[str]:
        ms = self.data.setdefault("manual_selection", {})
        bucket = ms.setdefault(section, [])
        return {str(x) for x in bucket}

    def is_manually_selected(self, section: str, index: int, item: dict) -> bool:
        manual_set = self.get_manual_set(section)
        key = self.item_key(section, index, item)
        return key in manual_set or str(index) in manual_set

    def toggle_manual_item(self, section: str, index: int) -> bool:
        col = self.get_collection(section)
        if not (0 <= index < len(col)):
            return False
        item = col[index]
        key = self.item_key(section, index, item)
        ms = self.data.setdefault("manual_selection", {})
        bucket = [str(x) for x in ms.setdefault(section, [])]

        if key in bucket or str(index) in bucket:
            bucket = [x for x in bucket if x not in {key, str(index)}]
            checked = False
        else:
            bucket.append(key)
            checked = True

        ms[section] = bucket
        return checked

    @staticmethod
    def item_title(section: str, item: dict) -> str:
        if section == "education":
            return item.get("degree_de") or item.get("title") or item.get("id", "")
        if section == "experience":
            return item.get("role_de") or item.get("title") or item.get("id", "")
        if section == "projects":
            return item.get("name") or item.get("title") or item.get("id", "")
        if section == "skills.languages":
            lang = item.get("language_de") or item.get("name") or ""
            lvl = item.get("level_de") or ""
            return f"{lang} ({lvl})".strip(" ()")
        return item.get("name") or item.get("title") or item.get("id", "")

    @staticmethod
    def item_org_or_meta(section: str, item: dict) -> str:
        if section == "education":
            return item.get("institution") or ""
        if section == "experience":
            return item.get("organization") or ""
        if section == "projects":
            return item.get("context_de") or ", ".join(item.get("tech_stack") or [])
        if section.startswith("skills."):
            return item.get("level_de") or ""
        return ""

    @staticmethod
    def item_period_str(item: dict) -> str:
        p = item.get("period")
        if isinstance(p, dict):
            return p.get("display_de") or f"{p.get('start', '')} – {p.get('end', '')}".strip(" –")
        return str(p or "")

    @staticmethod
    def item_bullets_text(section: str, item: dict) -> str:
        sub_key = "highlights_de" if section == "education" else "bullets_de"
        subs = item.get(sub_key) or item.get("bullets") or []
        lines = []
        for s in subs:
            if isinstance(s, dict) and s.get("text"):
                lines.append(s["text"])
            elif isinstance(s, str) and s.strip():
                lines.append(s.strip())
        return "\n".join(lines)

    def add_item(self, section: str, payload: dict) -> dict:
        col = self.get_collection(section)
        priority = int(payload.get("priority", 2))
        tags = payload.get("tags") if isinstance(payload.get("tags"), list) else _parse_tags(payload.get("tags", ""))
        visible = bool(payload.get("default_visible", True))

        title = (payload.get("title") or "").strip()
        org = (payload.get("org") or "").strip()
        period_disp = (payload.get("period") or "").strip()
        bullets = _parse_bullets(payload.get("bullets", ""), tags, priority)

        if section == "education":
            new_item = {
                "id": payload.get("id") or _slugify_id("edu", title),
                "degree_de": title,
                "institution": org,
                "location": payload.get("location", "Fulda, Deutschland"),
                "period": {
                    "start": period_disp,
                    "end": None,
                    "is_current": False,
                    "display_de": period_disp,
                },
                "highlights_de": bullets,
                "tags": tags,
                "priority": priority,
                "default_visible": visible,
            }
        elif section == "experience":
            new_item = {
                "id": payload.get("id") or _slugify_id("exp", title),
                "role_de": title,
                "organization": org,
                "location": payload.get("location", "Fulda, Deutschland"),
                "period": {
                    "start": period_disp,
                    "end": None,
                    "is_current": False,
                    "display_de": period_disp,
                },
                "bullets_de": bullets,
                "tags": tags,
                "priority": priority,
                "default_visible": visible,
            }
        elif section == "projects":
            stack = [x.strip() for x in (payload.get("stack") or "").split(",") if x.strip()]
            new_item = {
                "id": payload.get("id") or _slugify_id("proj", title),
                "name": title,
                "context_de": org,
                "period": {
                    "start": period_disp,
                    "end": None,
                    "is_current": True,
                    "display_de": period_disp,
                },
                "tech_stack": stack,
                "bullets_de": bullets,
                "tags": tags,
                "priority": priority,
                "default_visible": visible,
            }
        elif section == "skills.languages":
            new_item = {
                "language_de": title,
                "level_de": org,
                "priority": priority,
                "default_visible": visible,
            }
        else:
            new_item = {
                "name": title,
                "level_de": org,
                "tags": tags,
                "priority": priority,
                "default_visible": visible,
            }

        col.append(new_item)
        return new_item

    def update_item(self, section: str, index: int, payload: dict) -> dict:
        col = self.get_collection(section)
        item = col[index]

        priority = int(payload.get("priority", item.get("priority", 2)))
        tags = (
            payload["tags"]
            if isinstance(payload.get("tags"), list)
            else _parse_tags(payload.get("tags", ", ".join(item.get("tags") or [])))
        )
        visible = bool(payload.get("default_visible", item.get("default_visible", True)))
        title = (payload.get("title") if payload.get("title") is not None else self.item_title(section, item)).strip()
        org = (payload.get("org") if payload.get("org") is not None else self.item_org_or_meta(section, item)).strip()
        period_disp = (
            payload.get("period") if payload.get("period") is not None else self.item_period_str(item)
        ).strip()

        item["priority"] = priority
        item["default_visible"] = visible
        if "tags" in item or not section.startswith("skills.languages"):
            item["tags"] = tags

        if section == "education":
            item["degree_de"] = title
            item["institution"] = org
            if isinstance(item.get("period"), dict):
                item["period"]["display_de"] = period_disp
            if "bullets" in payload:
                item["highlights_de"] = _parse_bullets(payload["bullets"], tags, priority)
        elif section == "experience":
            item["role_de"] = title
            item["organization"] = org
            if isinstance(item.get("period"), dict):
                item["period"]["display_de"] = period_disp
            if "bullets" in payload:
                item["bullets_de"] = _parse_bullets(payload["bullets"], tags, priority)
        elif section == "projects":
            item["name"] = title
            item["context_de"] = org
            if isinstance(item.get("period"), dict):
                item["period"]["display_de"] = period_disp
            if "stack" in payload:
                item["tech_stack"] = [x.strip() for x in payload["stack"].split(",") if x.strip()]
            if "bullets" in payload:
                item["bullets_de"] = _parse_bullets(payload["bullets"], tags, priority)
        elif section == "skills.languages":
            item["language_de"] = title
            item["level_de"] = org
        else:
            item["name"] = title
            item["level_de"] = org

        return item

    def delete_item(self, section: str, index: int) -> dict:
        col = self.get_collection(section)
        removed = col.pop(index)
        key = self.item_key(section, index, removed)
        ms = self.data.get("manual_selection")
        if isinstance(ms, dict) and isinstance(ms.get(section), list):
            ms[section] = [str(x) for x in ms[section] if str(x) != key]
        return removed

    @staticmethod
    def _open_file(file_path: Path) -> None:
        target = str(file_path.resolve())
        system = platform.system()

        if system == "Linux":
            opener = shutil.which("xdg-open")
            if not opener:
                raise RuntimeError("Не знайдено 'xdg-open' для відкриття файлу.")
            subprocess.Popen(
                [opener, target],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        elif system == "Darwin":
            subprocess.Popen(["open", target], start_new_session=True)
        elif system == "Windows":
            os.startfile(target)  # type: ignore[attr-defined]
        else:
            raise RuntimeError(f"Непідтримувана ОС для авто-відкриття: {system}")

    def available_templates(self) -> list[str]:
        base_dir = self.path.resolve().parent
        found: list[str] = []
        for search_dir in (Path.cwd() / "templates", base_dir / "templates"):
            if search_dir.is_dir():
                for p in sorted(search_dir.glob("*.html")):
                    name = p.stem
                    if name not in found:
                        found.append(name)
        for fallback in ("swiss_grid", "tty_term"):
            if fallback not in found:
                found.append(fallback)
        return found

    def available_profiles(self) -> list[str]:
        base_dir = self.path.resolve().parent
        found: list[str] = []
        for search_dir in (Path.cwd() / "profiles", base_dir / "profiles"):
            if search_dir.is_dir():
                for p in sorted(search_dir.glob("*.json")):
                    name = p.stem
                    if name not in found:
                        found.append(name)
        return found

    def load_profile(self, profile_name: str | None) -> dict:
        if not profile_name:
            return {}
        base_dir = self.path.resolve().parent
        candidates = [
            Path.cwd() / "profiles" / f"{profile_name}.json",
            base_dir / "profiles" / f"{profile_name}.json",
            Path(profile_name),
        ]
        for cand in candidates:
            if cand.exists() and cand.is_file():
                return json.loads(cand.read_text(encoding="utf-8"))
        return {}

    def build_and_open(
        self,
        out_dir: Path = Path("out"),
        template: str | None = None,
        profile: str | None = None,
        manual: bool = False,
        script_candidates: tuple[str, ...] = ("build_cv.py", "build.py"),
    ) -> Path:
        base_dir = self.path.resolve().parent
        script_path: Path | None = None

        for name in script_candidates:
            for candidate in (Path.cwd() / name, base_dir / name):
                if candidate.exists():
                    script_path = candidate
                    break
            if script_path:
                break

        if not script_path:
            raise FileNotFoundError(
                f"Не знайдено скрипт збірки ({', '.join(script_candidates)})."
            )

        resolved_out = out_dir if out_dir.is_absolute() else (Path.cwd() / out_dir)
        pdf_path = resolved_out / "cv.pdf"

        cmd = [
            "python3",
            str(script_path),
            "--cv",
            str(self.path.resolve()),
            "--out-dir",
            str(resolved_out),
        ]
        if manual:
            cmd.append("--manual")
        elif profile and profile != "(default)":
            cmd.extend(["--profile", profile])
        else:
            cmd.append("--all")
        if template:
            cmd.extend(["--template", template])

        res = subprocess.run(
            cmd,
            cwd=str(script_path.parent),
            capture_output=True,
            text=True,
            timeout=60,
        )
        if res.returncode != 0:
            details = (res.stderr or res.stdout or "").strip()
            msg = f"Скрипт збірки завершився з кодом {res.returncode}."
            if details:
                msg = f"{msg}\n\n{details[-1200:]}"
            raise RuntimeError(msg)

        if not pdf_path.exists():
            raise FileNotFoundError(f"Збірка завершилась, але файл не знайдено: {pdf_path}")

        self._open_file(pdf_path)
        return pdf_path


class UIAdapter(ABC):
    """Абстрактний інтерфейс фронтенду: GUI, TUI чи CLI."""

    def __init__(self, store: CvStore):
        self.store = store

    @abstractmethod
    def run(self) -> None:
        raise NotImplementedError


class TkGuiAdapter(UIAdapter):
    """Легкий GUI на tkinter (працює без сторонніх залежностей)."""

    def run(self) -> None:
        import tkinter as tk
        from tkinter import messagebox, ttk

        root = tk.Tk()
        root.title(f"typoCV 0.5.0 Editor — {self.store.path.name}")
        root.geometry("980x620")

        current_section = tk.StringVar(value="experience")
        manual_mode = tk.BooleanVar(value=bool(self.store.data.get("manual_selection")))
        selected_idx: int | None = None

        top_bar = ttk.Frame(root, padding=8)
        top_bar.pack(fill=tk.X)

        ttk.Label(top_bar, text="Розділ:").pack(side=tk.LEFT)
        sec_combo = ttk.Combobox(
            top_bar,
            textvariable=current_section,
            values=AVAILABLE_SECTIONS,
            state="readonly",
            width=34,
        )
        sec_combo.pack(side=tk.LEFT, padx=6)

        ttk.Button(top_bar, text="+ Новий запис", command=lambda: clear_form()).pack(side=tk.LEFT, padx=3)
        ttk.Button(top_bar, text="Зберегти запис", command=lambda: save_current()).pack(side=tk.LEFT, padx=3)
        ttk.Button(top_bar, text="Видалити", command=lambda: delete_current()).pack(side=tk.LEFT, padx=3)
        ttk.Button(top_bar, text="Toggle [x]", command=lambda: toggle_selected()).pack(side=tk.LEFT, padx=3)
        ttk.Checkbutton(
            top_bar,
            text="Manual mode",
            variable=manual_mode,
            command=lambda: refresh_list(),
        ).pack(side=tk.LEFT, padx=(8, 4))

        ttk.Button(top_bar, text="Записати JSON", command=lambda: persist_json()).pack(side=tk.RIGHT, padx=4)

        main_pane = ttk.PanedWindow(root, orient=tk.HORIZONTAL)
        main_pane.pack(fill=tk.BOTH, expand=True, padx=8, pady=6)

        left_frame = ttk.Frame(main_pane, padding=4)
        listbox = tk.Listbox(left_frame, width=42)
        listbox.pack(fill=tk.BOTH, expand=True)
        main_pane.add(left_frame, weight=1)

        form = ttk.Frame(main_pane, padding=8)
        main_pane.add(form, weight=2)

        v_title = tk.StringVar()
        v_org = tk.StringVar()
        v_period = tk.StringVar()
        v_stack = tk.StringVar()
        v_tags = tk.StringVar(value="#media-audio, #comms-docs")
        v_prio = tk.IntVar(value=2)
        v_vis = tk.BooleanVar(value=True)

        def add_row(label: str, widget: tk.Widget, row: int) -> None:
            ttk.Label(form, text=label).grid(row=row, column=0, sticky=tk.W, pady=3, padx=(0, 8))
            widget.grid(row=row, column=1, sticky=tk.EW, pady=3)

        form.columnconfigure(1, weight=1)
        add_row("Заголовок / Роль / Назва:", ttk.Entry(form, textvariable=v_title), 0)
        add_row("Організація / Рівень / Контекст:", ttk.Entry(form, textvariable=v_org), 1)
        add_row("Період (display_de):", ttk.Entry(form, textvariable=v_period), 2)
        add_row("Tech stack (через кому):", ttk.Entry(form, textvariable=v_stack), 3)
        add_row("Теги:", ttk.Entry(form, textvariable=v_tags), 4)
        add_row("Priority (1–3):", ttk.Spinbox(form, from_=1, to=3, textvariable=v_prio, width=6), 5)

        txt_bullets = tk.Text(form, height=9, wrap=tk.WORD)
        add_row("Пункти (по 1 на рядок):", txt_bullets, 6)

        ttk.Checkbutton(form, text="default_visible (показувати за замовчуванням)", variable=v_vis).grid(
            row=7, column=1, sticky=tk.W, pady=4
        )

        templates = self.store.available_templates()
        default_tpl = "swiss_grid" if "swiss_grid" in templates else templates[0]
        current_template = tk.StringVar(value=default_tpl)

        ttk.Label(top_bar, text="Темплейт:").pack(side=tk.LEFT, padx=(8, 2))
        tpl_combo = ttk.Combobox(
            top_bar,
            textvariable=current_template,
            values=templates,
            state="readonly",
            width=15,
        )
        tpl_combo.pack(side=tk.LEFT, padx=(0, 6))

        profiles = ["(default)"] + self.store.available_profiles()
        current_profile = tk.StringVar(value=profiles[0])

        ttk.Label(top_bar, text="Лінза:").pack(side=tk.LEFT, padx=(4, 2))
        prof_combo = ttk.Combobox(
            top_bar,
            textvariable=current_profile,
            values=profiles,
            state="readonly",
            width=18,
        )
        prof_combo.pack(side=tk.LEFT, padx=(0, 6))

        def on_profile_change(_event=None) -> None:
            prof_name = current_profile.get()
            if prof_name == "(default)":
                return
            prof_data = self.store.load_profile(prof_name)
            tpl = prof_data.get("template")
            if tpl and tpl in templates:
                current_template.set(tpl)

        prof_combo.bind("<<ComboboxSelected>>", on_profile_change)

        def refresh_list(preserve_idx: int | None = None) -> None:
            nonlocal selected_idx
            listbox.delete(0, tk.END)
            sec = current_section.get()
            col = self.store.get_collection(sec)
            show_checks = bool(manual_mode.get())

            for i, item in enumerate(col):
                mark = ""
                if show_checks:
                    mark = "[x] " if self.store.is_manually_selected(sec, i, item) else "[ ] "
                vis_mark = "" if item.get("default_visible", True) else " [hidden]"
                t = self.store.item_title(sec, item)
                listbox.insert(tk.END, f"{mark}{i + 1}. {t}{vis_mark}")

            if preserve_idx is not None and 0 <= preserve_idx < len(col):
                listbox.selection_set(preserve_idx)
                listbox.see(preserve_idx)
                selected_idx = preserve_idx
            else:
                selected_idx = None

        def toggle_selected() -> None:
            sel = listbox.curselection()
            idx = sel[0] if sel else selected_idx
            if idx is None:
                messagebox.showwarning("Увага", "Обери запис у списку.")
                return
            sec = current_section.get()
            self.store.toggle_manual_item(sec, idx)
            if not manual_mode.get():
                manual_mode.set(True)
            refresh_list(preserve_idx=idx)

        def on_double_click(_event=None) -> None:
            sel = listbox.curselection()
            if not sel:
                return
            idx = sel[0]
            sec = current_section.get()
            self.store.toggle_manual_item(sec, idx)
            if not manual_mode.get():
                manual_mode.set(True)
            refresh_list(preserve_idx=idx)

        def clear_form() -> None:
            nonlocal selected_idx
            selected_idx = None
            listbox.selection_clear(0, tk.END)
            v_title.set("")
            v_org.set("")
            v_period.set("")
            v_stack.set("")
            v_tags.set("#media-audio, #comms-docs")
            v_prio.set(2)
            v_vis.set(True)
            txt_bullets.delete("1.0", tk.END)

        def on_select(_event=None) -> None:
            nonlocal selected_idx
            sel = listbox.curselection()
            if not sel:
                return
            idx = sel[0]
            col = self.store.get_collection(current_section.get())
            if idx >= len(col):
                return
            selected_idx = idx
            item = col[idx]
            sec = current_section.get()

            v_title.set(self.store.item_title(sec, item))
            v_org.set(self.store.item_org_or_meta(sec, item))
            v_period.set(self.store.item_period_str(item))
            v_stack.set(", ".join(item.get("tech_stack") or []))
            v_tags.set(", ".join(item.get("tags") or []))
            v_prio.set(int(item.get("priority", 2)))
            v_vis.set(bool(item.get("default_visible", True)))
            txt_bullets.delete("1.0", tk.END)
            txt_bullets.insert("1.0", self.store.item_bullets_text(sec, item))

        def collect_payload() -> dict:
            return {
                "title": v_title.get(),
                "org": v_org.get(),
                "period": v_period.get(),
                "stack": v_stack.get(),
                "tags": v_tags.get(),
                "priority": int(v_prio.get()),
                "default_visible": bool(v_vis.get()),
                "bullets": txt_bullets.get("1.0", tk.END),
            }

        def save_current() -> None:
            payload = collect_payload()
            if not payload["title"].strip():
                messagebox.showwarning("Увага", "Заголовок/назва не може бути порожньою.")
                return
            sec = current_section.get()
            if selected_idx is None:
                self.store.add_item(sec, payload)
                refresh_list()
            else:
                self.store.update_item(sec, selected_idx, payload)
                refresh_list(preserve_idx=selected_idx)
            messagebox.showinfo("Готово", "Зміни застосовано в пам'яті. Натисни 'Записати JSON'.")

        def delete_current() -> None:
            if selected_idx is None:
                messagebox.showwarning("Увага", "Обери запис у списку.")
                return
            sec = current_section.get()
            removed = self.store.delete_item(sec, selected_idx)
            title = self.store.item_title(sec, removed)
            refresh_list()
            clear_form()
            messagebox.showinfo("Видалено", f"Видалено: {title}. Натисни 'Записати JSON'.")

        def persist_json() -> None:
            self.store.save(make_backup=True)
            messagebox.showinfo("Збережено", f"Файл оновлено: {self.store.path}")

        def build_and_preview() -> None:
            if not root.winfo_exists():
                return
            try:
                self.store.save(make_backup=True)
                selected_prof = (
                    None if current_profile.get() == "(default)" else current_profile.get()
                )
                is_manual = bool(manual_mode.get())
                pdf_file = self.store.build_and_open(
                    template=current_template.get(),
                    profile=selected_prof,
                    manual=is_manual,
                )
                mode_label = "manual" if is_manual else current_profile.get()
                if root.winfo_exists():
                    messagebox.showinfo(
                        "Готово",
                        f"PDF ({current_template.get()} / {mode_label}) згенеровано та відкрито:\n{pdf_file}",
                    )
            except subprocess.CalledProcessError as exc:
                if root.winfo_exists():
                    messagebox.showerror(
                        "Помилка збірки",
                        f"Скрипт збірки завершився з кодом {exc.returncode}.",
                    )
            except Exception as exc:
                if root.winfo_exists():
                    messagebox.showerror("Помилка", str(exc))

        ttk.Button(top_bar, text="Побудувати", command=build_and_preview).pack(
            side=tk.RIGHT, padx=4
        )

        listbox.bind("<<ListboxSelect>>", on_select)
        listbox.bind("<Double-Button-1>", on_double_click)
        sec_combo.bind("<<ComboboxSelected>>", lambda _e: (refresh_list(), clear_form()))

        refresh_list()
        root.mainloop()


class CliAdapter(UIAdapter):
    """Простий інтерактивний CLI-адаптер на тій самій моделі CvStore."""

    def run(self) -> None:
        print(f"typoCV 0.5.0 Editor (CLI) -> {self.store.path}")
        manual_mode = bool(self.store.data.get("manual_selection"))
        while True:
            print(f"\nРозділи [manual={manual_mode}]:")
            for i, sec in enumerate(AVAILABLE_SECTIONS, 1):
                print(f"  {i}. {sec}")
            choice = input(
                "Обери номер розділу ('m' toggle manual mode, 's' зберегти, 'q' вихід): "
            ).strip().lower()
            if choice == "q":
                break
            if choice == "m":
                manual_mode = not manual_mode
                print(f"Manual mode: {manual_mode}")
                continue
            if choice == "s":
                self.store.save(make_backup=True)
                print("Збережено.")
                continue
            if not choice.isdigit() or not (1 <= int(choice) <= len(AVAILABLE_SECTIONS)):
                print("Невірний вибір.")
                continue

            sec = AVAILABLE_SECTIONS[int(choice) - 1]
            col = self.store.get_collection(sec)
            for idx, item in enumerate(col):
                mark = ""
                if manual_mode:
                    mark = "[x] " if self.store.is_manually_selected(sec, idx, item) else "[ ] "
                print(f"  [{idx}] {mark}{self.store.item_title(sec, item)} | {self.store.item_period_str(item)}")

            act = input(
                "Дія: [a] додати, [e] редагувати, [d] видалити, [t] toggle [x], [p] побудувати PDF, [b] назад: "
            ).strip().lower()

            if act == "t":
                raw_idx = input("Індекс запису для перемикання [x]: ").strip()
                if not raw_idx.isdigit() or not (0 <= int(raw_idx) < len(col)):
                    print("Невірний індекс.")
                    continue
                idx = int(raw_idx)
                state = self.store.toggle_manual_item(sec, idx)
                manual_mode = True
                print(f"{'[x]' if state else '[ ]'} {self.store.item_title(sec, col[idx])}")

            elif act == "a":
                raw_prio = input("Priority [1-3] (default 2): ").strip()
                priority = int(raw_prio) if raw_prio in {"1", "2", "3"} else 2
                payload = {
                    "title": input("Заголовок/Назва: "),
                    "org": input("Організація/Рівень/Контекст: "),
                    "period": input("Період (display_de): "),
                    "stack": input("Tech stack (через кому): ") if sec == "projects" else "",
                    "tags": input("Теги (напр. #media-audio, #comms-docs): "),
                    "priority": priority,
                    "bullets": input("Пункт (один рядок або кілька через \\n): ").replace("\\n", "\n"),
                    "default_visible": True,
                }
                self.store.add_item(sec, payload)
                print("Додано в буфер (не забудь 's' для запису в файл).")

            elif act == "e":
                raw_idx = input("Індекс запису: ").strip()
                if not raw_idx.isdigit() or not (0 <= int(raw_idx) < len(col)):
                    print("Невірний індекс.")
                    continue
                idx = int(raw_idx)
                cur = col[idx]

                new_title = input("Новий заголовок (Enter — лишити): ").strip() or None
                new_org = input("Нова орг/рівень (Enter — лишити): ").strip() or None
                new_period = input("Новий період (Enter — лишити): ").strip() or None
                new_tags = input("Нові теги (Enter — лишити): ").strip()
                raw_prio = input(f"Новий priority [1-3] (Enter — {cur.get('priority', 2)}): ").strip()
                priority = int(raw_prio) if raw_prio in {"1", "2", "3"} else int(cur.get("priority", 2))

                payload: dict = {
                    "title": new_title,
                    "org": new_org,
                    "period": new_period,
                    "priority": priority,
                }
                if new_tags:
                    payload["tags"] = new_tags
                if sec == "projects":
                    new_stack = input("Новий tech stack через кому (Enter — лишити): ").strip()
                    if new_stack:
                        payload["stack"] = new_stack

                self.store.update_item(sec, idx, payload)
                print("Оновлено в буфері.")

            elif act == "d":
                raw_idx = input("Індекс запису для видалення: ").strip()
                if not raw_idx.isdigit() or not (0 <= int(raw_idx) < len(col)):
                    print("Невірний індекс.")
                    continue
                idx = int(raw_idx)
                removed = self.store.delete_item(sec, idx)
                print(f"Видалено: {self.store.item_title(sec, removed)}")

            elif act == "p":
                profs = self.store.available_profiles()
                chosen_prof = None
                if profs and not manual_mode:
                    raw_prof = input(f"Лінза {profs} (Enter — без профілю): ").strip()
                    if raw_prof:
                        chosen_prof = raw_prof

                tpls = self.store.available_templates()
                chosen_tpl = input(f"Темплейт {tpls} (Enter = {tpls[0]}): ").strip() or tpls[0]

                self.store.save(make_backup=True)
                pdf_file = self.store.build_and_open(
                    template=chosen_tpl,
                    profile=chosen_prof,
                    manual=manual_mode,
                )
                mode_str = "manual" if manual_mode else (chosen_prof or "default")
                print(f"Зібрано та відкрито: {pdf_file} [режим: {mode_str}, шаблон: {chosen_tpl}]")


def main() -> None:
    parser = argparse.ArgumentParser(description="Інтерактивний редактор 0.5.0 JSON для typoCV")
    parser.add_argument(
        "--cv",
        default="cv_0.5.0.json" if Path("cv_0.5.0.json").exists() else "master_cv.json",
        help="Шлях до 0.5.0 JSON",
    )
    parser.add_argument(
        "--ui",
        choices=["gui", "cli"],
        default="gui",
        help="Режим інтерфейсу (gui або cli)",
    )
    args = parser.parse_args()

    store = CvStore(Path(args.cv))
    adapter: UIAdapter = CliAdapter(store) if args.ui == "cli" else TkGuiAdapter(store)
    adapter.run()


if __name__ == "__main__":
    main()