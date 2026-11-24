"""Inline action picker and repeat-range interaction for the workflow list."""
import tkinter as tk

import core
from editor_layout import wrap_controls


class WorkflowEditor:
    def show_picker(self, host, owner=None, at=None, *, stages=False):
        if not self.editable():
            return
        if self.picker is not None and self.picker.winfo_exists():
            same_place = self.picker.master is host
            self.picker.destroy()
            if same_place:
                return
        panel = tk.Frame(host, bg='#edf3ff', padx=12, pady=10)
        self.picker = panel
        panel.pack(fill='x', pady=(7, 0))
        if at is None:
            items = owner['children'] if owner else self.tab_steps
            at = (items, len(items))
        title = '다음 단계에 추가' if stages else '이 이미지가 보이면 실행'
        tk.Label(panel, text=title, bg='#edf3ff', fg='#17304e',
                 font=('맑은 고딕', 10, 'bold')).pack(anchor='w')
        inputs = tk.Frame(panel, bg='#edf3ff')
        inputs.pack(fill='x', pady=(6, 0))
        controls = []

        def add(text, cmd, primary=False):
            def invoke():
                panel.destroy()
                cmd()
            controls.append(self.button(inputs,text,invoke,primary))

        if stages:
            add('이미지 캡처', lambda: self.capture_target(at=at), primary=True)
            add('이미지 파일 열기', lambda: self.import_images(at))
        else:
            add('찾은 이미지 클릭', lambda: self.add_detected_click(owner), primary=True)
        add('마우스·키보드 녹화', lambda: self.toggle_record(at))
        for text, kind in [('화면 위치 클릭', 'point'), ('마우스 이동', 'point_move'),
                           ('끌어 놓기', 'drag'), ('휠 굴리기', 'scroll')]:
            add(text, lambda k=kind: self.pick_motion(k, at=at))
        add('키·단축키 누르기', lambda: self.key_dialog(at=at))
        add('글자 입력', lambda: self.text_dialog(at=at))
        add('잠시 기다리기', lambda: self.add_delay(at))
        wrap_controls(inputs,controls)
        if host is not self.next_stage:
            self.after_idle(lambda: self.reveal_widget(panel) if panel.winfo_exists() else None)

    def reveal_widget(self, widget):
        self.update_idletasks()
        bottom = widget.winfo_rooty() - self.list.winfo_rooty() + widget.winfo_height()
        height = self.canvas.winfo_height()
        if bottom > self.canvas.canvasy(height):
            self.canvas.yview_moveto(max(0, bottom-height+14) / max(1, self.list.winfo_height()))

    def add_delay(self, at):
        from tkinter import simpledialog
        seconds = simpledialog.askfloat('잠시 기다리기', '몇 초 동안 기다릴까요?',
                                         initialvalue=1, minvalue=0, maxvalue=3600, parent=self)
        if seconds is not None:
            step = core.step('delay')
            step['seconds'] = seconds
            self.insert(step, at)

    def add_detected_click(self, owner):
        step = core.step('click')
        step.update(source=owner['id'], configured_target=True)
        self.insert(step, (owner['children'], len(owner['children'])))
