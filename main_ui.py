import tkinter as tk
from tkinter import messagebox, ttk

class SyllabusToDoApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Campus AI Syllabus To-Do Assistant (MVP)")
        self.root.geometry("780x520")
        self.root.configure(bg="#F5F0E6")

        header = tk.Label(self.root, text="AI Syllabus To-Do List & Reminder",
                          font=("Arial", 18, "bold"), bg="#F5F0E6", fg="#232F5B")
        header.pack(pady=12)

        list_frame = tk.Frame(self.root, bg="#F5F0E6")
        list_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=10)

        columns = ("id", "status", "event", "date", "time", "location")
        self.tree = ttk.Treeview(list_frame, columns=columns, show="headings", height=12)
        self.tree.heading("id", text="ID")
        self.tree.heading("status", text="狀態")
        self.tree.heading("event", text="事件 / 考試與作業名稱")
        self.tree.heading("date", text="日期")
        self.tree.heading("time", text="時間")
        self.tree.heading("location", text="地點")
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

if __name__ == "__main__":
    root = tk.Tk()
    app = SyllabusToDoApp(root)
    root.mainloop()
