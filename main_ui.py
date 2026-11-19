import queue
import subprocess
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from backend_db import BackendEngine
from desktop_bridge import extract_image, prepare_tasks, save_confirmed, save_extraction


class DraftReview(tk.Toplevel):
    FIELDS = (
        ('title', '事件名稱'), ('date', '開始日期 YYYY-MM-DD'),
        ('end_date', '結束日期（單日留白）'), ('weekdays', '每週活動日1至7，逗號分隔；單次留白'),
        ('start_time', '開始時間 HH:MM（未知留白）'),
        ('end_time', '結束時間 HH:MM（未知留白）'), ('location', '地點'),
    )

    def __init__(self, app, result, path):
        super().__init__(app.root)
        self.app, self.events = app, result['events']
        self.index, self.saved = 0, 0
        self.title('確認辨識草稿')
        self.geometry('800x740')
        self.transient(app.root)
        self.protocol('WM_DELETE_WINDOW', self.finish)
        self.grab_set()
        frame = ttk.Frame(self, padding=16)
        frame.pack(fill='both', expand=True)
        self.heading = ttk.Label(frame, font=('Arial', 15, 'bold'))
        self.heading.pack(anchor='w')
        ttk.Label(frame, text=Path(path).name).pack(anchor='w', pady=6)
        ttk.Button(frame, text='查看原圖', command=lambda: self.show_image(path)).pack(anchor='w')
        self.alerts = tk.Text(frame, height=6, wrap='word', font=('Arial', 12))
        self.alerts.pack(fill='x', pady=10)
        form = ttk.Frame(frame)
        form.pack(fill='x')
        form.columnconfigure(1, weight=1)
        self.variables = {}
        for row, (key, label) in enumerate(self.FIELDS):
            ttk.Label(form, text=label).grid(row=row, column=0, sticky='w', pady=5, padx=(0, 10))
            variable = tk.StringVar(self)
            self.variables[key] = variable
            ttk.Entry(form, textvariable=variable).grid(row=row, column=1, sticky='ew', pady=5)
        self.expand = tk.BooleanVar(self, False)
        ttk.Checkbutton(frame, text='將日期範圍依每週規則展開為單日任務（最多366天）', variable=self.expand).pack(anchor='w', pady=(12, 4))
        self.confirmed = tk.BooleanVar(self, False)
        ttk.Checkbutton(frame, text='我已對照原圖，確認年份、日期、時間、地點與重複規則', variable=self.confirmed).pack(anchor='w', pady=5)
        ttk.Label(frame, text='同一活動的報名文案可能被多抓；可略過多餘草稿。').pack(anchor='w', pady=5)
        buttons = ttk.Frame(frame)
        buttons.pack(fill='x', pady=12)
        ttk.Button(buttons, text='確認儲存並看下一筆', command=self.save).pack(side='left')
        ttk.Button(buttons, text='略過這筆', command=self.next).pack(side='left', padx=8)
        ttk.Button(buttons, text='結束確認', command=self.finish).pack(side='right')
        self.display()

    def display(self):
        event = self.events[self.index]
        self.heading.configure(text=f'草稿 {self.index + 1} / {len(self.events)}　已儲存 {self.saved} 筆任務')
        for key, variable in self.variables.items():
            value = event.get(key)
            if key == 'weekdays' and isinstance(value, list):
                value = ','.join(map(str, value))
            variable.set('' if value is None else str(value))
        self.confirmed.set(False)
        self.expand.set(False)
        notes = []
        if event.get('year_inferred'):
            notes.append('年份為系統推定，並非圖片提供；請確認。')
        if event.get('unconfirmed_weekdays') is not None:
            notes.append(f"未確認的每週規則：{event['unconfirmed_weekdays']}；請依原圖補填或清除。")
        notes.extend(str(x) for x in event.get('date_issues', []))
        notes.extend(str(x) for x in event.get('date_notes', []))
        notes.append('本階段儲存任務清單，通知排程尚未啟用。')
        self.alerts.configure(state='normal')
        self.alerts.delete('1.0', 'end')
        self.alerts.insert('1.0', '\n'.join(notes))
        self.alerts.configure(state='disabled')

    def show_image(self, path):
        try:
            subprocess.Popen(['/usr/bin/open', str(Path(path).resolve())])
        except OSError as error:
            messagebox.showerror('無法開啟原圖', str(error), parent=self)

    def save(self):
        if not self.confirmed.get():
            messagebox.showinfo('請確認草稿', '請先對照原圖，勾選確認欄位。', parent=self)
            return
        fields = {key: variable.get() for key, variable in self.variables.items()}
        try:
            tasks = prepare_tasks(fields, self.expand.get())
            if len(tasks) > 1 and not messagebox.askyesno('確認範圍', f'會新增 {len(tasks)} 筆單日任務，確定儲存？', parent=self):
                return
            ids = save_confirmed(self.app.engine, fields, self.expand.get())
        except Exception as error:
            messagebox.showerror('無法儲存', str(error), parent=self)
            return
        self.saved += len(ids)
        self.app.load_tasks()
        self.next()

    def next(self):
        self.index += 1
        if self.index >= len(self.events):
            self.finish()
        else:
            self.display()

    def finish(self):
        self.app.status.set(f'草稿確認結束，本次儲存 {self.saved} 筆任務。')
        self.app.review = None
        self.destroy()


class SyllabusToDoApp:
    def __init__(self, root):
        self.root, self.review = root, None
        self.busy, self.closed = False, False
        self.messages = queue.Queue()
        root.title('Campus AI Syllabus To-Do Assistant')
        root.geometry('1050x620')
        root.configure(bg='#F5F0E6')
        root.protocol('WM_DELETE_WINDOW', self.close)
        database = Path(__file__).resolve().with_name('offline_assistant.db')
        self.engine = BackendEngine(db_path=str(database))
        tk.Label(root, text='AI Syllabus To-Do List & Reminder', font=('Arial', 18, 'bold'), bg='#F5F0E6', fg='#232F5B').pack(pady=15)
        toolbar = ttk.Frame(root)
        toolbar.pack(fill='x', padx=20)
        self.import_button = ttk.Button(toolbar, text='匯入圖片', command=self.choose_image)
        self.import_button.pack(side='left', padx=(0, 8))
        for label, command in (('重新整理', self.load_tasks), ('切換完成狀態', self.toggle_selected), ('刪除任務', self.delete_selected)):
            ttk.Button(toolbar, text=label, command=command).pack(side='left', padx=(0, 8))
        frame = ttk.Frame(root)
        frame.pack(fill='both', expand=True, padx=20, pady=15)
        columns = ('status', 'title', 'date', 'time', 'location')
        self.tree = ttk.Treeview(frame, columns=columns, show='headings', selectmode='browse')
        for key, label in zip(columns, ('狀態', '事件名稱', '日期', '時間', '地點')):
            self.tree.heading(key, text=label)
            self.tree.column(key, width=250 if key == 'title' else 140)
        scroll = ttk.Scrollbar(frame, orient='vertical', command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side='left', fill='both', expand=True)
        scroll.pack(side='right', fill='y')
        self.summary = ttk.Label(root)
        self.summary.pack(anchor='w', padx=20)
        self.status = tk.StringVar(root, '匯入圖片後，確認草稿再加入清單。')
        ttk.Label(root, textvariable=self.status, wraplength=1000).pack(anchor='w', padx=20, pady=(4, 12))
        self.load_tasks()
        root.after(150, self.poll)

    def load_tasks(self):
        try:
            tasks = self.engine.get_all_tasks()
            for row in self.tree.get_children():
                self.tree.delete(row)
            for task in tasks:
                times = '～'.join(x for x in (task['start_time'], task['end_time']) if x)
                self.tree.insert('', 'end', iid=task['task_id'], values=('已完成' if task['status'] == 'Completed' else '待辦', task['title'], task['due_date'], times, task['location'] or ''))
            self.summary.configure(text=f'共 {len(tasks)} 筆任務')
        except Exception as error:
            messagebox.showerror('讀取失敗', str(error), parent=self.root)

    def choose_image(self):
        if self.busy or self.review is not None:
            return
        path = filedialog.askopenfilename(parent=self.root, title='選擇活動圖片', filetypes=[('圖片', '*.png *.jpg *.jpeg *.PNG *.JPG *.JPEG')])
        if not path:
            return
        self.busy = True
        self.import_button.configure(state='disabled')
        self.status.set('正在辨識圖片，通常需要約30秒；第一次載入可能更久。')

        def worker():
            try:
                result = extract_image(path)
                if not isinstance(result, dict) or not isinstance(result.get('events'), list) or not all(isinstance(e, dict) for e in result['events']):
                    raise ValueError('辨識輸出格式不完整')
            except Exception as error:
                self.messages.put(('error', str(error), path))
                return
            try:
                save_extraction(result)
                warning = None
            except OSError as error:
                warning = f'辨識成功，但結果紀錄無法保存：{error}'
            self.messages.put(('success', (result, warning), path))

        threading.Thread(target=worker, daemon=True).start()

    def poll(self):
        if self.closed:
            return
        try:
            kind, value, path = self.messages.get_nowait()
        except queue.Empty:
            pass
        else:
            self.busy = False
            self.import_button.configure(state='normal')
            if kind == 'error':
                self.status.set('辨識失敗，沒有儲存任何任務。')
                messagebox.showerror('辨識失敗', f'請確認 Ollama 已啟動，且已下載 qwen2.5vl:3b。\n\n{value}', parent=self.root)
            else:
                result, warning = value
                if warning:
                    messagebox.showwarning('紀錄未保存', warning, parent=self.root)
                if not result['events']:
                    self.status.set('沒有找到活動；請換一張清楚的圖片。')
                else:
                    self.status.set(f"辨識出 {len(result['events'])} 筆草稿，等待確認。")
                    self.review = DraftReview(self, result, path)
        self.root.after(150, self.poll)

    def selected_id(self):
        selected = self.tree.selection()
        if not selected:
            messagebox.showinfo('請選擇任務', '先點選清單中的一筆任務。', parent=self.root)
            return None
        return selected[0]

    def toggle_selected(self):
        task_id = self.selected_id()
        if task_id is not None:
            try:
                self.engine.toggle_task_status(task_id)
                self.load_tasks()
            except Exception as error:
                messagebox.showerror('更新失敗', str(error), parent=self.root)

    def delete_selected(self):
        task_id = self.selected_id()
        if task_id is not None and messagebox.askyesno('刪除任務', '確定刪除選取任務？', parent=self.root):
            try:
                self.engine.delete_task(task_id)
                self.load_tasks()
            except Exception as error:
                messagebox.showerror('刪除失敗', str(error), parent=self.root)

    def close(self):
        if self.review is not None:
            messagebox.showinfo('尚有草稿', '請先儲存或結束草稿確認。', parent=self.review)
            return
        if self.busy and not messagebox.askyesno('辨識進行中', '關閉視窗將不保留本次辨識草稿，確定關閉？', parent=self.root):
            return
        self.closed = True
        self.root.destroy()


if __name__ == '__main__':
    root = tk.Tk()
    app = SyllabusToDoApp(root)
    root.mainloop()
