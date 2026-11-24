"""Tab strip and project editing for independent workflows."""
import tkinter as tk
from tkinter import messagebox, simpledialog

import core
from editor_menu import open_editor_menu
from macro_tabs import MAX_TABS, tab_count, tab_name, tab_steps


class TabEditor:
    active_tab = 0

    @property
    def tab_steps(self):
        return tab_steps(self.project, self.active_tab)

    @property
    def tab_options(self):
        return self.project if self.active_tab == 0 else self.project['tabs'][self.active_tab - 1]

    def build_tabs(self, parent, background, ink, blue):
        self.tab_strip = tk.Frame(parent, bg=background)
        self.tab_strip.pack(fill='x', pady=(0, 7))
        self.tab_bar = tk.Frame(self.tab_strip, bg=background)
        self.tab_bar.pack(side='left', fill='x', expand=True)
        self.tab_add = self.button(self.tab_strip, '＋', self.add_tab)
        self.tab_add.pack(side='left', padx=(5, 0))
        self.tab_menu = self.button(self.tab_strip, '⋯', self.open_tab_menu)
        self.tab_menu.pack(side='left', padx=(4, 0))
        for button in (self.tab_add, self.tab_menu):
            button.configure(padx=8, pady=4)
        self.tab_colors = ink, blue
        self.tab_status = {}
        self.tab_current = {}
        self.tab_cycles = {}
        self.tab_buttons = {}

    def render_tabs(self):
        count = tab_count(self.project)
        for button in self.tab_buttons.values():
            button.destroy()
        self.tab_buttons.clear()
        for index in range(MAX_TABS):
            self.tab_bar.columnconfigure(index, weight=int(index < count), uniform='workflow')
        for index in range(count):
            button = self.button(self.tab_bar, '', lambda i=index: self.select_tab(i))
            button.configure(padx=3, pady=4)
            button.grid(row=0, column=index, sticky='ew', padx=(0, 3))
            self.tab_buttons[index] = button
            self.paint_tab(index)
        self.tab_add.configure(state='normal' if self.editable() and count < MAX_TABS else 'disabled')
        self.tab_menu.configure(state='normal' if self.editable() else 'disabled')

    def paint_tab(self, index):
        if index not in self.tab_buttons:
            return
        ink, blue = self.tab_colors
        selected = self.active_tab == index
        name = tab_name(self.project, index)
        name = name if len(name) <= 9 else name[:8] + '…'
        state = self.tab_status.get(index, '')
        button = self.tab_buttons[index]
        button.configure(text=f'{name}\n{state}' if state else name,
                         bg='#eaf0ff' if selected else '#ffffff',
                         fg='#a92743' if state == '오류' else blue if selected else ink,
                         highlightbackground=blue if selected else '#dae3ee',
                         state='disabled' if self.recorder or self.motion_recording else 'normal')

    def select_tab(self, index):
        if self.recorder or self.motion_recording or self.active_tab == index:
            return
        self.active_tab = index
        self.selected.clear()
        self.drag = None
        self.current = self.tab_current.get(index)
        self.cycle_caption = self.tab_cycles.get(index, '')
        self.last_wait_state = None
        self.canvas.yview_moveto(0)
        self.render()

    def available_tab_name(self):
        names = {tab_name(self.project, index) for index in range(tab_count(self.project))}
        return next(f'작업 {number}' for number in range(1, MAX_TABS + 1)
                    if f'작업 {number}' not in names)

    def add_tab(self):
        if self.editable() and tab_count(self.project) < MAX_TABS:
            self.snapshot()
            self.project.setdefault('tabs', []).append({'name': self.available_tab_name(), 'steps': []})
            self.select_tab(tab_count(self.project) - 1)

    def open_tab_menu(self):
        if not self.editable():
            return
        entries = [
            ('현재 탭만 실행', lambda: self.run(current_only=True),
             any(step['enabled'] for step in self.tab_steps), False),
            ('탭 이름 변경…', self.rename_tab, True, False),
            ('탭 닫기', self.remove_tab, tab_count(self.project) > 1, False),
        ]
        open_editor_menu(self, self.tab_menu, entries)

    def rename_tab(self):
        name = simpledialog.askstring('탭 이름 변경', '탭 이름 (최대 32자)',
                                     initialvalue=tab_name(self.project, self.active_tab), parent=self)
        if not name or not name.strip() or len(name.strip()) > 32:
            return
        self.snapshot()
        self.tab_options['name' if self.active_tab else 'first_tab_name'] = name.strip()
        self.render()

    def remove_tab(self):
        if not self.editable() or tab_count(self.project) < 2:
            return
        if self.tab_steps and not messagebox.askyesno('탭 닫기', '이 탭과 안의 단계를 삭제할까요?', parent=self):
            return
        self.snapshot()
        tabs = self.project['tabs']
        if self.active_tab:
            tabs.pop(self.active_tab - 1)
        else:
            first = tabs.pop(0)
            self.project['steps'] = first['steps']
            self.project['first_tab_name'] = first['name']
            for key in ('workflow_repeats', 'repeat_on_reappear', 'routes', 'ranges', 'repeat_enabled'):
                self.project.pop(key, None)
                if key in first:
                    self.project[key] = first[key]
        self.active_tab = min(self.active_tab, tab_count(self.project) - 1)
        self.selected.clear()
        self.tab_status.clear()
        self.tab_current.clear()
        self.tab_cycles.clear()
        self.states.clear()
        self.current = None
        self.render()

    def move_stage_to_tab(self, step, index):
        nodes = {node['id'] for node in core.walk([step])}
        def crosses(node):
            return bool(node['source']) and ((node['id'] in nodes) != (node['source'] in nodes))
        if any(crosses(node) for node in core.walk(self.tab_steps)):
            messagebox.showinfo('단계 이동', '다른 단계의 인식 결과와 연결되어 있습니다.', parent=self)
            return
        self.snapshot()
        if index == tab_count(self.project):
            self.project.setdefault('tabs', []).append({'name': self.available_tab_name(), 'steps': []})
        self.tab_steps.remove(step)
        tab_steps(self.project, index).append(step)
        self.select_tab(index)

    def clear_tab_run(self):
        self.tab_status.clear()
        self.tab_current.clear()
        self.tab_cycles.clear()
        self.current = None
        self.cycle_caption = ''

    def tab_run_event(self, index, kind, value):
        visible = index == self.active_tab
        name = tab_name(self.project, index)
        if kind == 'state':
            self.tab_status[index] = value
            if value == '정지됨':
                uid = self.tab_current.get(index)
                if uid and self.states.get(uid, ('',))[0] in ('running', 'paused'):
                    self.set_state(uid,'stopped','■ 정지됨')
            self.event('log', f'[{name}] {value}')
        elif kind == 'log':
            self.event(kind, f'[{name}] {value}')
            return
        elif kind == 'workflow_iteration':
            n, total = value
            self.tab_cycles[index] = f'전체 {n}/{total}회 · ' if total else f'전체 {n}회차 · '
            for node in core.walk(tab_steps(self.project, index)):
                self.states.pop(node['id'],None)
            if visible:
                self.cycle_caption=self.tab_cycles[index]
                for uid in self.rows:
                    self.paint(uid)
            return
        elif kind == 'active':
            self.tab_current[index] = value
            node = next(node for node in core.walk(tab_steps(self.project,index)) if node['id']==value)
            watching = node['kind'] in ('image','find','wait','condition')
            self.tab_status[index] = '감시 중' if watching else '동작 중'
            if not visible:
                self.set_state(value,'running','이미지 찾는 중' if watching else '실행 중')
        elif kind in ('waiting','image_iteration','step_done','step_skipped','step_error','iteration'):
            if kind == 'waiting':
                self.tab_status[index] = '감시 중'
            if not visible:
                self.update_hidden_step(index,kind,value)
        if kind != 'state' and (visible or kind in ('input_blocked','input_clear')):
            self.event(kind,value)
        self.paint_tab(index)

    def update_hidden_step(self, index, kind, value):
        if kind == 'waiting':
            self.set_state(value[0],'running',f'대기 중 · {value[1]}초')
        elif kind == 'image_iteration':
            self.set_state(value[0],'running',f'{value[1]}회째 반복 중')
        elif kind == 'step_done':
            self.set_state(value,'done','✓ 완료')
        elif kind == 'step_skipped':
            self.set_state(value,'stopped','동작 건너뜀')
        elif kind == 'step_error':
            self.set_state(value[0],'error','! 실패')
            self.last_error = f'{tab_name(self.project,index)} · {value[1]}'
        elif kind == 'iteration':
            loop = next(node for node in core.walk(tab_steps(self.project,index)) if node['id']==value[0])
            for child in core.walk(loop['children']):
                self.states.pop(child['id'],None)
            self.set_state(value[0],'running',f'{value[1]} / {value[2]}회')
