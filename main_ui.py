import queue
import subprocess
import threading
import tkinter as tk
from pathlib import Path
from datetime import datetime, timedelta
from tkinter import filedialog, messagebox, simpledialog, ttk

from backend_db import BackendEngine
from desktop_bridge import extract_image, prepare_tasks, save_confirmed, save_extraction, update_confirmed
from desktop_reminders import ReminderService


class DraftReview(tk.Toplevel):
    FIELDS = (
        ('title', '事件名稱'), ('date', '開始日期 YYYY-MM-DD'),
        ('end_date', '結束日期（單日留白）'), ('weekdays', '每週活動日1至7，逗號分隔；單次留白'),
        ('start_time', '開始時間 HH:MM（未知留白）'),
        ('end_time', '結束時間 HH:MM（未知留白）'), ('location', '地點'),
    )

    def __init__(self, app, result, path=None, task_id=None):
        super().__init__(app.root)
        self.app, self.events = app, result['events']
        self.task_id = task_id
        self.index, self.saved = 0, 0
        self.title('編輯任務' if task_id else '確認辨識草稿')
        self.geometry('800x740')
        self.transient(app.root)
        self.protocol('WM_DELETE_WINDOW', self.finish)
        self.grab_set()
        frame = ttk.Frame(self, padding=16)
        frame.pack(fill='both', expand=True)
        self.heading = ttk.Label(frame, font=('Arial', 15, 'bold'))
        self.heading.pack(anchor='w')
        if path:
            ttk.Label(frame, text=Path(path).name).pack(anchor='w', pady=6)
            ttk.Button(frame, text='查看原圖', command=lambda: self.show_image(path)).pack(anchor='w')
        self.alerts = tk.Text(frame, height=6, wrap='word', font=('Arial', 12))
        self.alerts.pack(fill='x', pady=10)
        form = ttk.Frame(frame)
        form.pack(fill='x')
        form.columnconfigure(1, weight=1)
        self.variables = {}
        for row, (key, label) in enumerate(self.FIELDS):
            if task_id and key in ('end_date', 'weekdays'):
                continue
            ttk.Label(form, text=label).grid(row=row, column=0, sticky='w', pady=5, padx=(0, 10))
            variable = tk.StringVar(self)
            self.variables[key] = variable
            ttk.Entry(form, textvariable=variable).grid(row=row, column=1, sticky='ew', pady=5)
        self.date_hint = ttk.Label(frame)
        self.date_hint.pack(anchor='w', pady=(8, 0))
        self.variables['date'].trace_add('write', self.update_date_hint)
        self.expand = tk.BooleanVar(self, False)
        if not task_id:
            ttk.Checkbutton(frame, text='將日期範圍依每週規則展開為單日任務（最多366天）', variable=self.expand).pack(anchor='w', pady=(12, 4))
        self.confirmed = tk.BooleanVar(self, False)
        ttk.Checkbutton(frame, text='我已對照原圖，確認年份、日期、時間、地點與重複規則', variable=self.confirmed).pack(anchor='w', pady=5)
        ttk.Label(frame, text='修改日期或時間會取消舊提醒，儲存後請重新設定。' if task_id else '同一活動的報名文案可能被多抓；可略過多餘草稿。').pack(anchor='w', pady=5)
        buttons = ttk.Frame(frame)
        buttons.pack(fill='x', pady=12)
        ttk.Button(buttons, text='儲存修改' if task_id else '確認儲存並看下一筆', command=self.save).pack(side='left')
        if not task_id:
            ttk.Button(buttons, text='略過這筆', command=self.next).pack(side='left', padx=8)
        ttk.Button(buttons, text='結束確認', command=self.finish).pack(side='right')
        self.display()

    def display(self):
        event = self.events[self.index]
        self.heading.configure(text='編輯已儲存任務' if self.task_id else f'草稿 {self.index + 1} / {len(self.events)}　已儲存 {self.saved} 筆任務')
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
        if event.get('date_issues'):
            notes.append('部分日期或重複規則需要人工確認；請對照原圖補齊或修正。')
        if not notes:
            notes.append('請確認名稱、日期、時間與地點；未知時間可以留白。')
        notes.append('儲存後可選取任務、設定提醒；提醒需保持 App 開啟。')
        self.alerts.configure(state='normal')
        self.alerts.delete('1.0', 'end')
        self.alerts.insert('1.0', '\n'.join(notes))
        self.alerts.configure(state='disabled')

    def update_date_hint(self, *_):
        try:
            value = datetime.strptime(self.variables['date'].get(), '%Y-%m-%d')
            self.date_hint.configure(text='日期確認：星期' + '一二三四五六日'[value.weekday()])
        except ValueError:
            self.date_hint.configure(text='請填完整日期，星期會自動顯示。')

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
            if self.task_id:
                cancelled = update_confirmed(self.app.engine, self.task_id, fields)
                self.saved = 1
                self.app.load_tasks()
                if cancelled:
                    messagebox.showinfo('提醒已取消', f'時間已修改，已取消 {cancelled} 筆舊提醒，請重新設定。', parent=self)
                self.finish()
                return
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
        self.app.status.set(('任務修改已儲存。' if self.saved else '已取消編輯。') if self.task_id else f'草稿確認結束，本次儲存 {self.saved} 筆任務。')
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
        self.reminders = ReminderService(self.engine)
        tk.Label(root, text='AI Syllabus To-Do List & Reminder', font=('Arial', 18, 'bold'), bg='#F5F0E6', fg='#232F5B').pack(pady=15)
        toolbar = ttk.Frame(root)
        toolbar.pack(fill='x', padx=20)
        self.import_button = ttk.Button(toolbar, text='匯入圖片', command=self.choose_image)
        self.import_button.pack(side='left', padx=(0, 8))
        for label, command in (('重新整理', self.load_tasks), ('編輯任務', self.edit_selected), ('切換完成狀態', self.toggle_selected), ('刪除任務', self.delete_selected)):
            ttk.Button(toolbar, text=label, command=command).pack(side='left', padx=(0, 8))
        reminders_bar = ttk.Frame(root)
        reminders_bar.pack(fill='x', padx=20, pady=(8, 0))
        for label, command in (('設定提醒', self.set_reminder), ('10秒後測試提醒', self.test_reminder), ('取消未觸發提醒', self.cancel_reminders)):
            ttk.Button(reminders_bar, text=label, command=command).pack(side='left', padx=(0, 8))
        ttk.Label(root, text='提醒需保持 App 開啟；關閉或休眠期間不會跳出，重開或喚醒後補提醒。').pack(anchor='w', padx=20, pady=(6, 0))
        frame = ttk.Frame(root)
        frame.pack(fill='both', expand=True, padx=20, pady=15)
        columns = ('status', 'title', 'date', 'time', 'location')
        self.tree = ttk.Treeview(frame, columns=columns, show='headings', selectmode='browse')
        self.tree.bind('<Double-1>', lambda _: self.edit_selected())
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
        root.after(1000, self.check_reminders)

    def load_tasks(self):
        try:
            tasks = self.engine.get_all_tasks()
            for row in self.tree.get_children():
                self.tree.delete(row)
            for task in tasks:
                times = '～'.join(x for x in (task['start_time'], task['end_time']) if x)
                try:
                    day = datetime.strptime(task['due_date'], '%Y-%m-%d')
                    date_label = task['due_date'] + '（' + '一二三四五六日'[day.weekday()] + '）'
                except ValueError:
                    date_label = task['due_date']
                self.tree.insert('', 'end', iid=task['task_id'], values=('已完成' if task['status'] == 'Completed' else '待辦', task['title'], date_label, times, task['location'] or ''))
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
                status = self.engine.toggle_task_status(task_id)
                if status == 'Completed':
                    self.reminders.cancel(task_id)
                    self.status.set('任務已完成，未觸發的提醒已取消。')
                self.load_tasks()
            except Exception as error:
                messagebox.showerror('更新失敗', str(error), parent=self.root)

    def edit_selected(self):
        if self.review is not None:
            return
        task_id = self.selected_id()
        if task_id is None:
            return
        try:
            task = self.engine.get_task_by_id(task_id)
            if task is None:
                raise ValueError('任務不存在，請重新整理')
            event = dict(task, date=task['due_date'])
            self.review = DraftReview(self, {'events': [event]}, task_id=task_id)
        except Exception as error:
            messagebox.showerror('無法編輯', str(error), parent=self.root)

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
        try:
            pending = self.reminders.pending()
        except Exception as error:
            messagebox.showerror('讀取提醒失敗', str(error), parent=self.root)
            return
        if pending and not messagebox.askyesno('尚有提醒', '尚有未觸發的提醒。App 關閉期間不會跳出提醒，重開後會補提醒。確定關閉？', parent=self.root):
            return
        self.closed = True
        self.root.destroy()

    def set_reminder(self):
        task_id = self.selected_id()
        if task_id is None:
            return
        try:
            task = self.engine.get_task_by_id(task_id)
            if not task or task['status'] != 'Pending':
                raise ValueError('請選取待辦任務；已完成任務請先切換為待辦。')
            default = datetime.now() + timedelta(minutes=5)
            if task['start_time']:
                try:
                    proposed = datetime.strptime(task['due_date'] + ' ' + task['start_time'], '%Y-%m-%d %H:%M') - timedelta(minutes=15)
                    if proposed > datetime.now():
                        default = proposed
                except ValueError:
                    pass
            current = self.reminders.pending(task_id)
            previous = '\n'.join(row['alert_time'] for row in current) or '尚無'
            value = simpledialog.askstring(
                '設定提醒',
                f"任務：{task['title']}\n現有提醒：{previous}\n\n輸入本機時間 YYYY-MM-DD HH:MM\n儲存會取代這筆任務所有未觸發提醒。",
                initialvalue=default.strftime('%Y-%m-%d %H:%M'), parent=self.root)
            if value is None:
                return
            self.reminders.schedule_at(task_id, value)
            self.status.set('提醒已儲存：' + value + '；請保持 App 開啟。')
        except Exception as error:
            messagebox.showerror('無法設定提醒', str(error), parent=self.root)

    def test_reminder(self):
        task_id = self.selected_id()
        if task_id is None:
            return
        try:
            self.reminders.schedule_test(task_id)
            self.status.set('測試提醒已排程，請保持 App 開啟，等待約10秒。')
        except Exception as error:
            messagebox.showerror('無法測試提醒', str(error), parent=self.root)

    def cancel_reminders(self):
        task_id = self.selected_id()
        if task_id is None:
            return
        if not messagebox.askyesno('取消提醒', '確定取消這筆任務所有未觸發提醒？', parent=self.root):
            return
        try:
            count = self.reminders.cancel(task_id)
            self.status.set(f'已取消 {count} 筆提醒。')
        except Exception as error:
            messagebox.showerror('取消失敗', str(error), parent=self.root)

    def check_reminders(self):
        if self.closed:
            return
        try:
            due = self.reminders.due()
            if due:
                chunks = [f"{row['alert_time']}\n{row['message']}" for row in due[:5]]
                if len(due) > 5:
                    chunks.append(f'另有 {len(due) - 5} 筆到期提醒，將於下一次顯示。')
                messagebox.showinfo('任務提醒', '\n\n'.join(chunks), parent=self.review or self.root)
                self.reminders.acknowledge([row['reminder_id'] for row in due[:5]])
                self.status.set(f'已顯示 {min(5, len(due))} 筆提醒。')
        except Exception as error:
            self.status.set(f'提醒讀取或確認失敗，稍後重試：{error}')
        if not self.closed:
            self.root.after(1000, self.check_reminders)


if __name__ == '__main__':
    root = tk.Tk()
    app = SyllabusToDoApp(root)
    root.mainloop()
