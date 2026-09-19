"""Tkinter 데스크톱 GUI.

화면 구성은 지시서 §11(업로드/설정 화면), §12(결과 화면)를 그대로 따른다.
무거운 작업(전사/AI분석/렌더링)은 백그라운드 스레드에서 돌리고, 진행 상황은
큐를 통해 메인 스레드(Tk 이벤트 루프)로 전달해 화면을 갱신한다.
"""

from __future__ import annotations

import os
import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from . import secrets as secrets_mod
from .config import load_config, save_config
from .pipeline import PipelineOptions, PipelineResult, run_pipeline
from .utils import fmt_mmss, zip_folder

COUNT_OPTIONS = [1, 3, 5, 10, 20]
LENGTH_OPTIONS = [30, 45, 60, 90, 120]


class SettingsDialog(tk.Toplevel):
    """API 키 + 평가 가중치(config.json) 편집 창 (지시서 §4: 가중치는 설정 파일에서 변경 가능)."""

    WEIGHT_LABELS = {
        "learning_value": "학습 가치",
        "concept_importance": "핵심 개념성",
        "standalone_understanding": "독립적 이해 가능성",
        "completeness": "설명의 완결성",
        "explanation_quality": "설명 품질",
        "example_problem_value": "예시/문제풀이 가치",
        "exam_practical_relevance": "시험/실무 연관성",
        "clarity": "명확성",
    }

    def __init__(self, master, cfg: dict):
        super().__init__(master)
        self.title("설정")
        self.geometry("460x560")
        self.cfg = cfg
        self.resizable(False, True)

        pad = {"padx": 12, "pady": 6}

        api_frame = ttk.LabelFrame(self, text="Anthropic API 키")
        api_frame.pack(fill="x", **pad)
        self.api_key_var = tk.StringVar(value=secrets_mod.get_api_key() or "")
        ttk.Entry(api_frame, textvariable=self.api_key_var, show="*").pack(fill="x", padx=8, pady=8)
        ttk.Label(
            api_frame,
            text="console.anthropic.com 에서 발급. 이 PC에만 로컬 저장됩니다.",
            foreground="#666",
        ).pack(anchor="w", padx=8, pady=(0, 8))

        weight_frame = ttk.LabelFrame(self, text="평가 기준 가중치 (%) — 합계는 자동 정규화됩니다")
        weight_frame.pack(fill="x", **pad)
        self.weight_vars: dict[str, tk.DoubleVar] = {}
        for key, label in self.WEIGHT_LABELS.items():
            row = ttk.Frame(weight_frame)
            row.pack(fill="x", padx=8, pady=2)
            ttk.Label(row, text=label, width=18).pack(side="left")
            var = tk.DoubleVar(value=round(cfg["weights"].get(key, 0) * 100, 1))
            self.weight_vars[key] = var
            ttk.Spinbox(row, from_=0, to=100, increment=1, textvariable=var, width=8).pack(side="left")

        misc_frame = ttk.LabelFrame(self, text="기타")
        misc_frame.pack(fill="x", **pad)

        row = ttk.Frame(misc_frame)
        row.pack(fill="x", padx=8, pady=4)
        ttk.Label(row, text="최소 통과 점수(0~100)", width=20).pack(side="left")
        self.min_score_var = tk.IntVar(value=cfg.get("min_shorts_score", 70))
        ttk.Spinbox(row, from_=0, to=100, textvariable=self.min_score_var, width=8).pack(side="left")

        row = ttk.Frame(misc_frame)
        row.pack(fill="x", padx=8, pady=4)
        ttk.Label(row, text="Whisper 모델", width=20).pack(side="left")
        self.whisper_model_var = tk.StringVar(value=cfg.get("whisper_model", "medium"))
        ttk.Combobox(
            row, textvariable=self.whisper_model_var,
            values=["tiny", "base", "small", "medium", "large"], width=10, state="readonly",
        ).pack(side="left")

        btns = ttk.Frame(self)
        btns.pack(fill="x", padx=12, pady=12)
        ttk.Button(btns, text="저장", command=self._save).pack(side="right", padx=4)
        ttk.Button(btns, text="취소", command=self.destroy).pack(side="right")

    def _save(self):
        key = self.api_key_var.get().strip()
        if key:
            secrets_mod.save_api_key(key)

        raw_weights = {k: max(0.0, v.get()) for k, v in self.weight_vars.items()}
        total = sum(raw_weights.values()) or 1.0
        self.cfg["weights"] = {k: v / total for k, v in raw_weights.items()}
        self.cfg["min_shorts_score"] = self.min_score_var.get()
        self.cfg["whisper_model"] = self.whisper_model_var.get()
        save_config(self.cfg)
        messagebox.showinfo("설정", "저장되었습니다.")
        self.destroy()


class UploadScreen(ttk.Frame):
    def __init__(self, master, app: "App"):
        super().__init__(master, padding=20)
        self.app = app
        cfg = app.cfg

        ttk.Label(self, text="교육 영상 업로드", font=("Malgun Gothic", 16, "bold")).pack(anchor="w", pady=(0, 16))

        file_row = ttk.Frame(self)
        file_row.pack(fill="x", pady=6)
        self.file_var = tk.StringVar(value="선택된 파일 없음")
        ttk.Button(file_row, text="영상 파일 선택", command=self._pick_file).pack(side="left")
        ttk.Label(file_row, textvariable=self.file_var, foreground="#444").pack(side="left", padx=10)

        count_row = ttk.Frame(self)
        count_row.pack(fill="x", pady=10)
        ttk.Label(count_row, text="생성할 쇼츠 개수").pack(side="left")
        self.count_var = tk.IntVar(value=cfg.get("shorts_count_default", 5))
        ttk.Combobox(
            count_row, textvariable=self.count_var, values=COUNT_OPTIONS, width=8,
        ).pack(side="left", padx=10)
        ttk.Label(count_row, text="(직접 입력 가능, 기본 5개)", foreground="#888").pack(side="left")

        length_row = ttk.Frame(self)
        length_row.pack(fill="x", pady=10)
        ttk.Label(length_row, text="쇼츠 최대 길이(초)").pack(side="left")
        self.length_var = tk.IntVar(value=cfg.get("max_length_default", 60))
        ttk.Combobox(
            length_row, textvariable=self.length_var, values=LENGTH_OPTIONS, width=8,
        ).pack(side="left", padx=10)
        ttk.Label(length_row, text="(직접 입력 가능, 기본 60초)", foreground="#888").pack(side="left")

        self.subtitle_var = tk.BooleanVar(value=cfg.get("subtitle_enabled_default", True))
        ttk.Checkbutton(self, text="자막 자동 생성", variable=self.subtitle_var).pack(anchor="w", pady=4)

        self.vertical_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(self, text="세로형 9:16 사용", variable=self.vertical_var).pack(anchor="w", pady=4)

        ai_row = ttk.Frame(self)
        ai_row.pack(fill="x", pady=10)
        ttk.Label(ai_row, text="AI 분석 기준").pack(side="left")
        ai_combo = ttk.Combobox(ai_row, values=["교육 콘텐츠"], state="readonly", width=16)
        ai_combo.pack(side="left", padx=10)
        ai_combo.current(0)
        ttk.Label(
            ai_row, text="(학습 가치·핵심 개념·이해 가능성 중심으로 평가)", foreground="#888"
        ).pack(side="left")

        ttk.Button(self, text="설정 (API 키 / 가중치)", command=self._open_settings).pack(anchor="w", pady=(10, 0))

        self.start_btn = ttk.Button(self, text="쇼츠 생성 시작", command=self._start)
        self.start_btn.pack(anchor="w", pady=(16, 8))

        self.progress = ttk.Progressbar(self, mode="determinate", maximum=100)
        self.progress.pack(fill="x", pady=6)

        self.log_var = tk.StringVar(value="")
        ttk.Label(self, textvariable=self.log_var, foreground="#333", wraplength=560).pack(anchor="w")

        self.video_path: str | None = None

    def _pick_file(self):
        path = filedialog.askopenfilename(
            title="교육 영상 선택",
            filetypes=[("영상 파일", "*.mp4 *.mkv *.mov *.avi *.webm *.m4v"), ("모든 파일", "*.*")],
        )
        if path:
            self.video_path = path
            self.file_var.set(os.path.basename(path))

    def _open_settings(self):
        SettingsDialog(self, self.app.cfg)

    def _start(self):
        if not self.video_path:
            messagebox.showwarning("영상 선택 필요", "먼저 영상 파일을 선택하세요.")
            return
        try:
            count = int(self.count_var.get())
            length = int(self.length_var.get())
        except (tk.TclError, ValueError):
            messagebox.showwarning("입력 오류", "쇼츠 개수와 최대 길이는 숫자로 입력하세요.")
            return
        if count <= 0 or length <= 0:
            messagebox.showwarning("입력 오류", "쇼츠 개수와 최대 길이는 1 이상이어야 합니다.")
            return

        if not secrets_mod.get_api_key() and not os.environ.get("ANTHROPIC_API_KEY"):
            messagebox.showwarning("API 키 필요", "먼저 '설정'에서 Anthropic API 키를 입력하세요.")
            return

        self.start_btn.config(state="disabled")
        self.progress["value"] = 0
        self.log_var.set("시작합니다...")

        options = PipelineOptions(
            video_path=self.video_path,
            shorts_count=count,
            max_length_seconds=length,
            subtitles_enabled=self.subtitle_var.get(),
            vertical_enabled=self.vertical_var.get(),
        )
        self.app.run_pipeline_async(options, self._on_progress, self._on_done, self._on_error)

    def _on_progress(self, msg: str, pct: float):
        self.log_var.set(msg)
        if pct >= 0:
            self.progress["value"] = pct * 100

    def _on_done(self, result: PipelineResult):
        self.start_btn.config(state="normal")
        if not result.shorts:
            messagebox.showinfo(
                "결과 없음",
                f"교육적 가치 기준(최소 점수 {self.app.cfg.get('min_shorts_score', 70)}점)을 만족하는 "
                f"구간을 찾지 못했습니다. 분석된 후보는 {result.candidates_found}개였습니다.\n"
                "설정에서 최소 점수를 낮추거나 다른 영상으로 시도해보세요.",
            )
            return
        self.app.show_results(result)

    def _on_error(self, err: Exception):
        self.start_btn.config(state="normal")
        messagebox.showerror("오류 발생", str(err))


class ResultCard(ttk.Frame):
    def __init__(self, master, index: int, result_item):
        super().__init__(master, padding=10, relief="groove", borderwidth=1)
        c = result_item.candidate

        top = ttk.Frame(self)
        top.pack(fill="x")
        ttk.Label(top, text=f"{index:02d}", font=("Malgun Gothic", 12, "bold")).pack(side="left")
        ttk.Label(top, text=f'"{c.title}"', font=("Malgun Gothic", 12, "bold")).pack(side="left", padx=8)

        info = (
            f"{result_item.actual_duration:.0f}초 · 교육 유형: {c.content_type} · "
            f"학습 가치(Shorts Score): {c.shorts_score:.0f}점"
        )
        ttk.Label(self, text=info, foreground="#444").pack(anchor="w", pady=(4, 0))
        ttk.Label(self, text=f"핵심 개념: {c.key_concept}", foreground="#444").pack(anchor="w")
        ttk.Label(self, text=f"선정 이유: {c.reason}", foreground="#666", wraplength=640).pack(anchor="w", pady=(2, 6))

        btn_row = ttk.Frame(self)
        btn_row.pack(fill="x")
        ttk.Button(btn_row, text="▶ 미리보기", command=lambda: self._preview(result_item.output_path)).pack(side="left")
        ttk.Button(
            btn_row, text="폴더에서 보기",
            command=lambda: os.startfile(os.path.dirname(result_item.output_path)),  # type: ignore[attr-defined]
        ).pack(side="left", padx=6)

    def _preview(self, path: str):
        try:
            os.startfile(path)  # type: ignore[attr-defined]
        except OSError as e:
            messagebox.showerror("재생 오류", f"기본 재생 프로그램으로 열 수 없습니다: {e}")


class ResultsScreen(ttk.Frame):
    def __init__(self, master, app: "App", result: PipelineResult):
        super().__init__(master, padding=20)
        self.app = app
        self.result = result

        header = ttk.Frame(self)
        header.pack(fill="x", pady=(0, 12))
        ttk.Label(header, text="생성 완료", font=("Malgun Gothic", 16, "bold")).pack(side="left")
        ttk.Label(header, text=f"총 {len(result.shorts)}개", foreground="#444").pack(side="left", padx=10)

        canvas = tk.Canvas(self, highlightthickness=0)
        scrollbar = ttk.Scrollbar(self, orient="vertical", command=canvas.yview)
        list_frame = ttk.Frame(canvas)
        list_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=list_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        for i, item in enumerate(result.shorts, start=1):
            card = ResultCard(list_frame, i, item)
            card.pack(fill="x", pady=6, padx=2)

        bottom = ttk.Frame(self)
        bottom.pack(fill="x", pady=(12, 0))
        ttk.Button(bottom, text="전체 다운로드 (zip으로 저장)", command=self._download_all).pack(side="left")
        ttk.Button(bottom, text="결과 폴더 열기", command=lambda: os.startfile(result.output_dir)).pack(side="left", padx=6)  # type: ignore[attr-defined]
        ttk.Button(bottom, text="새 영상으로 다시 시작", command=self.app.show_upload).pack(side="right")

    def _download_all(self):
        dest = filedialog.asksaveasfilename(
            title="전체 쇼츠 zip으로 저장",
            defaultextension=".zip",
            filetypes=[("ZIP 파일", "*.zip")],
            initialfile=os.path.basename(self.result.output_dir) + ".zip",
        )
        if not dest:
            return
        zip_folder(self.result.output_dir, dest)
        messagebox.showinfo("완료", f"저장되었습니다:\n{dest}")


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("교육 쇼츠 자동 생성기")
        self.geometry("720x760")
        self.minsize(640, 600)

        self.cfg = load_config()
        self._queue: "queue.Queue" = queue.Queue()

        self.container = ttk.Frame(self)
        self.container.pack(fill="both", expand=True)
        self.current_screen: ttk.Frame | None = None

        self.show_upload()
        self.after(100, self._poll_queue)

    def _clear(self):
        if self.current_screen is not None:
            self.current_screen.destroy()

    def show_upload(self):
        self._clear()
        self.current_screen = UploadScreen(self.container, self)
        self.current_screen.pack(fill="both", expand=True)

    def show_results(self, result: PipelineResult):
        self._clear()
        self.current_screen = ResultsScreen(self.container, self, result)
        self.current_screen.pack(fill="both", expand=True)

    def run_pipeline_async(self, options: PipelineOptions, on_progress, on_done, on_error):
        def worker():
            try:
                result = run_pipeline(
                    options, self.cfg,
                    progress=lambda msg, pct: self._queue.put(("progress", msg, pct)),
                )
                self._queue.put(("done", result))
            except Exception as e:  # noqa: BLE001
                self._queue.put(("error", e))

        self._on_progress_cb = on_progress
        self._on_done_cb = on_done
        self._on_error_cb = on_error
        threading.Thread(target=worker, daemon=True).start()

    def _poll_queue(self):
        try:
            while True:
                item = self._queue.get_nowait()
                if item[0] == "progress":
                    self._on_progress_cb(item[1], item[2])
                elif item[0] == "done":
                    self._on_done_cb(item[1])
                elif item[0] == "error":
                    self._on_error_cb(item[1])
        except queue.Empty:
            pass
        self.after(100, self._poll_queue)


def main():
    app = App()
    app.mainloop()
