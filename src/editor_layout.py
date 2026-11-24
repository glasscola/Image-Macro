"""Place editor controls on additional rows as their measured widths grow."""
import tkinter as tk


def wrap_controls(parent, controls, *, equal_width=False, gap=8):
    previous = None
    lines = []

    def arrange(width):
        nonlocal previous
        sizes = [control.winfo_reqwidth() + gap for control in controls]
        if equal_width:
            sizes = [max(sizes)] * len(sizes)
        rows = [[]]
        remaining = width + gap
        for index,size in enumerate(sizes):
            if rows[-1] and size > remaining:
                rows.append([])
                remaining = width + gap
            rows[-1].append(index)
            remaining -= size
        if rows == previous:
            return
        previous = rows
        while len(lines)<len(rows):
            lines.append(tk.Frame(parent,bg=parent['bg']))
        for control in controls:
            control.grid_forget()
        for line in lines:
            line.pack_forget()
        for row,indices in enumerate(rows):
            line=lines[row]
            line.pack(fill='x')
            for column in range(len(controls)):
                line.grid_columnconfigure(column,weight=0,uniform='')
            for column,index in enumerate(indices):
                padding=(0,gap if column<len(indices)-1 else 0)
                if equal_width and len(indices)==2:
                    padding=(0,gap//2) if column==0 else (gap//2,0)
                controls[index].grid(in_=line,row=0,column=column,sticky='ew' if equal_width else 'w',
                                     padx=padding,pady=(0,5))
                controls[index].lift()
                if equal_width:
                    line.grid_columnconfigure(column,weight=1,uniform='controls')

    parent.bind('<Configure>',lambda event:arrange(event.width),add='+')
    parent.after_idle(lambda:arrange(parent.winfo_width()) if parent.winfo_exists() else None)
