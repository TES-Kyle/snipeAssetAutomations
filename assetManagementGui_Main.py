from Utilities.labelPrinting import sendToPrinter
from Utilities.otherApiBits import getAssetInfo
from Utilities.settings import settingsMenu
from assetManagementFunctionsRouting import func_list, func_listTXT
import tkinter as tk
from tkinter import messagebox
import os
import re


def labelPrint():
    if os.path.isfile(str(os.path.dirname(os.path.realpath(__file__))) + "Utilities/" + "barcode-label.jpg"):
        sendToPrinter(str(os.path.dirname(os.path.realpath(__file__))) + "Utilities/" + "barcode-label.jpg")


class MainApp:
    def __init__(self, rootWindow):
        self.root = rootWindow
        self.root.title("Asset Management Gui")
        self.root.state('zoomed')  # This line makes the window fullscreen

        main_frame = tk.Frame(rootWindow)
        main_frame.place(relx=0.5, rely=0.5, anchor='center')

        self.asset_entry = tk.Entry(main_frame, font=('Arial', 20), width=30)
        self.asset_entry.pack(pady=20)
        self.asset_entry.bind('<Return>', self.process_asset)
        self.asset_entry.focus_set()

        button_frame = tk.Frame(main_frame)

        button_frame.pack(padx=10, pady=20, anchor='center')
        self.enter_button = tk.Button(button_frame, text="Enter", command=self.process_asset, font=('Arial', 20))
        self.enter_button.pack(side='left', padx=20, pady=20)
        self.reprint_button = tk.Button(button_frame, text="Print Label", command=labelPrint, font=('Arial', 20))
        self.reprint_button.pack(side='left', padx=20, pady=20)

        func_frame = tk.LabelFrame(main_frame, text='Functions', font=('Arial', 20))  # LabelFrame to have a box around
        func_frame.pack(pady=20)

        self.func_var = tk.IntVar(value=-1)
        for i in range(len(func_listTXT)):
            row, col = divmod(i, 4)
            lf = tk.Frame(func_frame)
            rb = tk.Radiobutton(lf, text=func_listTXT[i], variable=self.func_var, value=i, font=('Arial', 20))
            rb.pack(anchor='w')
            lf.grid(row=row, column=col, padx=10, pady=10)  # use grid for arranging in rows of 4

        self.clear_button = tk.Button(main_frame, text="Clear", command=self.clear_radiobuttons, font=('Arial', 20))
        self.clear_button.pack(pady=20)

        self.result_text = tk.StringVar()
        self.result_label = tk.Label(main_frame, textvariable=self.result_text, font=('Arial', 20))
        self.result_label.pack(pady=20)

        settings_frame = tk.Frame(rootWindow)
        settings_frame.place(relx=1.0, rely=0.0, anchor='ne')
        self.settings_button = tk.Button(settings_frame, text="⚙️", command=settingsMenu, font=('Arial', 20))
        self.settings_button.pack(padx=20, pady=20)

    def clear_radiobuttons(self):
        self.func_var.set(-1)

    def process_asset(self, event=None):
        asset_tag = self.asset_entry.get()
        self.asset_entry.delete(0, tk.END)
        if re.match("^\d{4}$", asset_tag):
            if self.func_var.get() != -1:
                result = func_list[self.func_var.get()](asset_tag)
                self.result_text.set(result)
            else:
                SecondWindow(self.root, asset_tag)
        else:
            messagebox.showerror("Error", "Dumb dumb, only 4 digit numbers")


class SecondWindow:
    def __init__(self, parent, asset_tag):
        self.top = tk.Toplevel(parent)
        self.top.title("Asset Management Gui")

        var_list, junk = getAssetInfo(asset_tag)

        self.check_vars = []  # list to store checkbutton variables

        self.var_frame = tk.Frame(self.top)  # create a frame for the variables
        self.var_frame.pack(side="top", fill="both", expand=True)

        for i, (name, value) in enumerate(var_list):
            check_var = tk.BooleanVar()  # create a variable to link to the checkbutton
            if i != 0:
                check_button = tk.Checkbutton(self.var_frame, variable=check_var)
                check_button.grid(row=i, column=0, sticky='ew')  # add the checkbutton to the grid

            label_name = tk.Label(self.var_frame, text=name, relief='solid', borderwidth=1, anchor='e')
            label_name.grid(row=i, column=1, sticky='ew', padx=5, pady=5)  # add the name label to the grid

            label_value = tk.Label(self.var_frame, text=value, relief='solid', borderwidth=1, anchor='w')
            label_value.grid(row=i, column=2, sticky='ew', padx=5, pady=5)  # add the value label to the grid

            self.check_vars.append((check_var, value))  # add the variable to the list

        self.var_frame.grid_columnconfigure(0, weight=1)
        self.var_frame.grid_columnconfigure(1, weight=1)
        self.var_frame.grid_columnconfigure(2, weight=1)

        self.button_frame = tk.Frame(self.top)
        self.button_frame.pack(side="bottom", fill="both")

        for i in range(len(func_list)):
            row, col = divmod(i, 4)
            button = tk.Button(self.button_frame, text=func_listTXT[i],
                               command=lambda j=i: self.run_func(j, asset_tag), height=2)
            button.grid(row=row, column=col, sticky='ew')

        close_button = tk.Button(self.button_frame, text="Close", command=self.top.destroy)
        close_button.grid(row=2, column=1, columnspan=2, sticky='ew')

        # Update window size
        self.top.update()
        width = self.top.winfo_width()
        height = self.top.winfo_height()

        # Get screen size
        screen_width = self.top.winfo_screenwidth()
        screen_height = self.top.winfo_screenheight()

        # Calculate position of window in pixels for centering
        x = (screen_width / 2) - (width / 2)
        y = (screen_height / 2) - (height / 2)

        # Set the position of the window to the center of the screen
        self.top.geometry(f"{width}x{height}+{int(x)}+{int(y)}")

    def run_func(self, func_index, asset_tag):
        checked_vars = [value for var, value in self.check_vars if var.get()]
        # Prepend asset_tag to the list
        checked_vars.insert(0, asset_tag)
        print("Checked variables:", checked_vars)
        result = func_list[func_index](asset_tag, checked_vars)
        self.top.destroy()
        app.result_text.set(result)


root = tk.Tk()
root.geometry("400x240")
app = MainApp(root)
root.mainloop()
