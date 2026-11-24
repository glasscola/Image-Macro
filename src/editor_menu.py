"""Compact toolbar menus styled with the editor's buttons."""
import tkinter as tk

from desktop import monitors
from screen_ui import user


def open_editor_menu(app, anchor, entries):
    owner = anchor.winfo_toplevel()
    previous_grab = app.grab_current()
    window = tk.Toplevel(owner)
    window.withdraw()
    window.transient(owner)
    window.overrideredirect(True)
    panel = tk.Frame(window,bg='#ffffff',padx=5,pady=5,
                     highlightthickness=1,highlightbackground='#dae3ee')
    panel.pack(fill='both',expand=True)
    choices = []

    def dismiss():
        window.destroy()
        if previous_grab is not None and previous_grab.winfo_exists():
            previous_grab.grab_set()
        anchor.focus_set()

    def invoke(command):
        dismiss()
        command()

    for label,command,enabled,selected in entries:
        button = app.button(panel,label,lambda action=command:invoke(action))
        button.configure(anchor='w',state='normal' if enabled else 'disabled',
                         bg='#eaf0ff' if selected else '#ffffff',highlightthickness=0)
        button.pack(fill='x')
        if enabled:
            choices.append(button)
            button.bind('<Return>',lambda event:event.widget.invoke())

    def dismiss_outside(event):
        if not (window.winfo_rootx() <= event.x_root < window.winfo_rootx()+window.winfo_width()
                and window.winfo_rooty() <= event.y_root < window.winfo_rooty()+window.winfo_height()):
            dismiss()

    def move_focus(delta):
        if choices:
            current = window.focus_get()
            index = choices.index(current) if current in choices else -1
            choices[(index+delta)%len(choices)].focus_set()
        return 'break'

    window.bind('<ButtonPress-1>',dismiss_outside)
    window.bind('<Escape>',lambda _:dismiss())
    window.bind('<Up>',lambda _:move_focus(-1))
    window.bind('<Down>',lambda _:move_focus(1))
    window.update_idletasks()
    x = anchor.winfo_rootx()
    y = anchor.winfo_rooty()+anchor.winfo_height()+4
    width,height = window.winfo_reqwidth(),window.winfo_reqheight()
    for display in monitors():
        left,top,w,h = display['rect']
        if left<=x<left+w and top<=anchor.winfo_rooty()<top+h:
            x = min(x,left+w-width)
            if y+height>top+h:
                y = max(top,anchor.winfo_rooty()-height-4)
            break
    window.deiconify()
    window.update_idletasks()
    handle = user.GetAncestor(window.winfo_id(),2)
    user.SetWindowPos(handle,0,x,y,width,height,0x0014)
    window.grab_set()
    (choices[0] if choices else window).focus_set()
    return window
