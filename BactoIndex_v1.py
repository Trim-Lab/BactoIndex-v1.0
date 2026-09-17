# -*- coding: utf-8 -*-
"""
Created on Tue Mar 17 13:15:30 2026

@author: martin varga
"""

# Standard Library
import copy
import os

# GUI & Webview
import customtkinter as ctk
import tkinter as tk
import mplcursors
from tkinter import filedialog, ttk
from tkinter.scrolledtext import ScrolledText
from functools import partial
import tksheet
from tkinter import messagebox

# Data
import numpy as np
import pandas as pd

# Plotting
import matplotlib.pyplot as plt
import seaborn as sns

from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.backends.backend_tkagg import NavigationToolbar2Tk

from scipy.signal import savgol_filter
from scipy.stats import trim_mean

import csv
from datetime import datetime

#This disable the interactive plots, no additional pop-up windows happen
plt.ioff()

import sys

IS_MAC = sys.platform == "darwin"




# ---- (Windows only) make the process DPI-aware before Tk is created ----
if sys.platform.startswith("win"):
    try:
        from ctypes import windll
        try:
            windll.shcore.SetProcessDpiAwareness(2)  # per-monitor v2
        except Exception:
            windll.shcore.SetProcessDpiAwareness(1)  # system
    except Exception:
        pass


class App(ctk.CTk):
    def __init__(self):
        super().__init__()

        # ---- unify scaling across Spyder/Jupyter/terminal ----
        # Option A: compute from monitor DPI (consistent, adaptive)
        #ppi = self.winfo_fpixels('1i')   # physical pixels per inch
        #self.tk.call('tk', 'scaling', ppi / 72.0)

        # ---- Scaling system -------------------------------------------------
        # IMPORTANT (Windows vs macOS):
        # CustomTkinter already applies automatic DPI awareness, and on Windows
        # the process is marked DPI-aware at startup (see the SetProcessDpiAwareness
        # block above). That means the OS-level display scaling (e.g. 125%/150%)
        # is ALREADY handled for us. Previously we also called
        #   tk.call("tk", "scaling", dpi/72)  and  ctk.set_widget/window_scaling(...)
        # on top of that, which stacked two or three scaling layers on Windows and
        # distorted the plots (wrong aspect ratio / cut off), while happening to
        # look fine on macOS. We now let CustomTkinter's automatic DPI handling do
        # the physical scaling on both platforms and keep our own factor neutral.
        #
        # ui_scale here is only a gentle *layout* factor for our figure sizes,
        # fonts and table sizes. It is deliberately kept at 1.0 (platform-neutral)
        # so figures have the same logical size on macOS and Windows; the physical
        # pixel scaling is CustomTkinter's job, not ours.
        self.ui_scale = 1.0

        # Matplotlib figures follow the same neutral factor.
        self.fig_scale = self.ui_scale

        # Screen-relative default size for wide data tables (tksheet), instead
        # of a fixed 1600x180. These live inside scrollable tabs.
        self.table_width = max(900, int(self.winfo_screenwidth() * 0.78))
        self.table_height = max(160, int(round(180 * self.ui_scale)))
        
        sns.set_theme(style="darkgrid")
        sns.set_palette("colorblind")

        # ---- Screen-aware plot text sizing ----------------------------------
        # seaborn's theme uses fairly large default font sizes, which look
        # Plot text sizing. These are point sizes (physical units), so they
        # stay visually consistent across screens regardless of resolution.
        # The figures themselves are responsive; the fonts deliberately do NOT
        # scale with screen width (scaling up on a large external monitor was
        # what made the text look oversized and get cut off). Keep them small.
        #
        # plot_font_base is the single master knob: lower = smaller everywhere.
        self.plot_font_base = 6.0

        # ---- One standard size for every analysis/filter plot ----------------
        # All plots use the SAME width and height (hence the same aspect ratio),
        # so the interface looks consistent no matter how many plots a tab has.
        # If a tab holds more plots than fit, the tab simply scrolls. ~3:2.
        self.plot_w_px = 480
        self.plot_h_px = 320
        b = self.plot_font_base
        plt.rcParams.update({
            "font.size":        b,
            "axes.titlesize":   b + 0.5,
            "axes.labelsize":   b,
            "xtick.labelsize":  b - 1.0,
            "ytick.labelsize":  b - 1.0,
            "legend.fontsize":  b - 1.0,
            "figure.titlesize": b + 1.0,
            # Bring titles and axis labels closer to the axes.
            "axes.titlepad":    3.0,
            "axes.labelpad":    2.0,
            "xtick.major.pad":  2.0,
            "ytick.major.pad":  2.0,
            # Thinner plot lines everywhere.
            "lines.linewidth":  1.0,
            # Centre all axes titles.
            "axes.titlelocation": "center",
        })

        ctk.set_appearance_mode('light')
        
        
        self.title('BactoIndex')
        self.protocol("WM_DELETE_WINDOW", self.close_window)   
        

        self.bind("<F11>", lambda e: self.fit_to_screen())

        self.dataset_count = 1

        self.notebook = ttk.Notebook(self)
        self.notebook.pack(expand=True, fill="both")

        self.tab2 = ctk.CTkFrame(self.notebook)
        self.tab3, self.scrollable_tab3_content = self.create_scrollable_tab(self.notebook)
        self.tab_filter, self.scrollable_tab_filter_content = self.create_scrollable_tab(self.notebook)
        self.tab4 = ctk.CTkFrame(self.notebook)   # ← Analysis page container
        self.tab5 = ctk.CTkFrame(self.notebook)
        self.tab_filter_table, self.scrollable_tab_filter_table = self.create_scrollable_tab(self.notebook)

        for frame, text in [(self.tab2, "Data handling"),
                            (self.tab3, "Raw Data"),
                            (self.tab_filter, "Filter"),
                            (self.tab4, "Analysis"),
                            (self.tab5, "Metadata"),
                            (self.tab_filter_table, "Filtered Data")]:
            self.notebook.add(frame, text=text)

        # 2) Build the analysis‐notebook inside tab4
        self.analysis_notebook = ttk.Notebook(self.tab4)
        self.analysis_notebook.pack(fill="both", expand=True, padx=10, pady=10)

        # 3) Now create and add the scrollable “Maximum slope” tab
        self.tab_slope_first, self.scrollable_tab_slope = self.create_scrollable_tab(self.analysis_notebook)
        self.analysis_notebook.add(self.tab_slope_first, text="Maximum slope")

        # 4) And finally the rest of your subtabs
        self.tab_max_growth, self.scrollable_tab_max_growth = self.create_scrollable_tab(self.analysis_notebook)
        self.analysis_notebook.add(self.tab_max_growth, text="Maximum growth")
        
        
        self.tab_auc, self.scrollable_tab_auc = self.create_scrollable_tab(self.analysis_notebook)
        self.analysis_notebook.add(self.tab_auc, text="AUC and Onset delay")
        
        self.tab_doubling, self.scrollable_doubling = self.create_scrollable_tab(self.analysis_notebook)
        self.analysis_notebook.add(self.tab_doubling, text="Doubling time")
        
        self.tab_score, self.scrollable_score = self.create_scrollable_tab(self.analysis_notebook)
        self.analysis_notebook.add(self.tab_score, text="Index")
        
        self.tab_slope_values, self.scrollable_slope_values = self.create_scrollable_tab(self.analysis_notebook)
        self.analysis_notebook.add(self.tab_slope_values, text="Maximum Slope Values")
        
        self.tab_mg_values, self.scrollable_mg_values = self.create_scrollable_tab(self.analysis_notebook)
        self.analysis_notebook.add(self.tab_mg_values, text="Maximum Growth Values")
        
        self.tab_auc_values_tables, self.scrollable_auc_values_tables = self.create_scrollable_tab(self.analysis_notebook)
        self.analysis_notebook.add(self.tab_auc_values_tables, text="AUC and Onset Dealy Values")
        
        self.tab_doubling_tables, self.scrollable_doubling_tables = self.create_scrollable_tab(self.analysis_notebook)
        self.analysis_notebook.add(self.tab_doubling_tables, text="Doubling Time Values")
        
        self.tab_score_tables, self.scrollable_score_tables = self.create_scrollable_tab(self.analysis_notebook)
        self.analysis_notebook.add(self.tab_score_tables, text="Index Values")
        
        
        self.max_vline_start = None
        self.max_vline_end = None
        self.max_vline_auc_one = None
        self.max_vline_auc_two = None
        self.max_vline_auc_three = None
        
        

        self.setup_tab2()
        
        self.update_idletasks()
        self.geometry(f"{self.winfo_screenwidth()}x{self.winfo_screenheight()}+0+0")

        
        self.mainloop()
        
    def close_window(self):
        if messagebox.askokcancel("Quit", "Are you sure you saved everything and want to exit?"):
            plt.close('all')
            self.quit()
            self.destroy()
        return
    
    def log_message(self, message):
        self.info_text_box.config(state="normal")
        self.info_text_box.insert(tk.END, message + "\n")
        self.info_text_box.see(tk.END)
        self.info_text_box.config(state="disabled")
        self.update_idletasks()
    
    def fit_to_screen(self):
        screen_w = self.winfo_screenwidth()
        screen_h = self.winfo_screenheight()

        self.geometry(f"{int(screen_w)}x{int(screen_h)}")

    # ---- Scaling helpers ---------------------------------------------------
    def sfont(self, size, weight=None):
        """Return an ("Arial", scaled_size[, weight]) font tuple.

        Font sizes are given in the original design points and scaled by the
        screen factor so text stays legible on both high- and low-DPI screens
        without per-OS branches.
        """
        scaled = max(7, int(round(size * self.ui_scale)))
        if weight:
            return ("Arial", scaled, weight)
        return ("Arial", scaled)

    def sfig(self, w, h):
        """Scale a matplotlib figsize (inches) by the screen factor."""
        return (w * self.fig_scale, h * self.fig_scale)

    def _savgol_params(self):
        """Return (window_length, polyorder) that are valid for savgol_filter.

        scipy requires polyorder < window_length, and window_length must be a
        positive integer. The two sliders can otherwise be set to an invalid
        combination (e.g. polyorder >= window size), which raises a ValueError
        and crashes the callback. This clamps the values to the nearest valid
        pair and keeps the displayed slider values in sync with what is applied.
        """
        try:
            window = int(self.window_variable.get())
        except (ValueError, AttributeError):
            window = 2
        try:
            polyorder = int(self.polyorder_variable.get())
        except (ValueError, AttributeError):
            polyorder = 1

        window = max(2, window)
        polyorder = max(0, polyorder)
        # polyorder must be strictly less than window_length.
        if polyorder >= window:
            clamped = window - 1
            # Only message when this actually changes the displayed value, so
            # it does not spam the log on every redraw.
            try:
                if int(self.polyorder_variable.get()) != clamped:
                    self.log_message(
                        f"Polynomial order must be smaller than the window size "
                        f"({window}); using {clamped} instead.")
            except Exception:
                pass
            polyorder = clamped
            # Reflect the clamp in the UI so the shown value matches reality.
            try:
                self.polyorder_variable.set(polyorder)
            except Exception:
                pass
        return window, polyorder

    def _run_calculation(self, button, calc_fn, label):
        """Run a (possibly slow) calculation with clear UI feedback.

        Disables the button and shows a 'Calculating ...' message so the user
        knows work is happening, forces the UI to repaint, runs calc_fn, then
        re-enables the button and reports completion. Any error is caught so the
        button is always usable again.
        """
        try:
            button.configure(state="disabled")
        except Exception:
            pass
        self.log_message(f"{label}: calculating, please wait ...")
        # Force the disabled state and message to appear before the blocking
        # work starts (otherwise Tk would only repaint afterwards).
        try:
            self.update_idletasks()
            self.update()
        except Exception:
            pass

        try:
            calc_fn()
            self.log_message(f"{label}: done.")
        except Exception as e:
            import traceback
            traceback.print_exc()
            self.log_message(f"{label}: failed - {e}")
            try:
                messagebox.showerror(label, f"{label} failed.\n\nDetails: {e}")
            except Exception:
                pass
        finally:
            try:
                button.configure(state="normal")
            except Exception:
                pass

    def _apply_savgol(self, data):
        """Apply savgol_filter with validated parameters."""
        window, polyorder = self._savgol_params()
        return savgol_filter(data, window_length=window, polyorder=polyorder,
                             mode=self.dropdown_filter_modes.get())

    def _make_canvas_responsive(self, canvas, fig, height_px=None, max_width_px=None):
        """Give every plot the SAME fixed size by fixing its grid cell.

        matplotlib's Tk backend always sizes the figure to fill its widget, and
        the widget fills its grid cell. So to make every plot identical we fix the
        plot's CELL to one standard pixel size: set the row and column the widget
        occupies to weight 0 with a minsize equal to the standard plot size. The
        cell is then exactly that size on every tab, the backend fills it, and
        constrained_layout, titles, axis labels and legends all render normally.
        Tabs with more plots than fit simply scroll.

        height_px / max_width_px are accepted for backwards compatibility and
        ignored, so every call site produces the identical size.
        """
        try:
            widget = canvas.get_tk_widget()
            info = widget.grid_info()
            parent = widget.master
            # Each plot occupies (possibly several) columns; size the columns it
            # spans so together they total the standard width, and its row to the
            # standard height. weight=0 keeps the cell from stretching.
            row = int(info.get("row", 0))
            col = int(info.get("column", 0))
            span = int(info.get("columnspan", 1))
            per_col = max(1, self.plot_w_px // span)
            for c in range(col, col + span):
                parent.grid_columnconfigure(c, minsize=per_col, weight=0)
            parent.grid_rowconfigure(row, minsize=self.plot_h_px, weight=0)
            # Make the figure start at the standard size too (the backend will
            # confirm it once the cell is realised).
            fig.set_dpi(100)
            fig.set_size_inches(self.plot_w_px / 100.0, self.plot_h_px / 100.0,
                                forward=False)
        except Exception:
            pass

    def _require_calc(self, attr, calc_label, switch_var=None):
        """Return True if a precomputed result exists, else warn and reset.

        Several analysis plots draw values that are only created (or filled in)
        after the corresponding 'Calculate ...' button is pressed. Selecting
        data before that used to crash with an AttributeError. This checks the
        required attribute exists AND is non-empty; if not it shows a message,
        unticks the switch that was just toggled, and returns False so the
        caller can stop cleanly.
        """
        value = getattr(self, attr, None)
        # Present and non-empty (an empty {} means 'calculate' has not run yet).
        if value is not None and (not hasattr(value, "__len__") or len(value) > 0):
            return True
        self.log_message(f"Press '{calc_label}' before selecting data here.")
        try:
            messagebox.showinfo("Calculate first",
                f"Please press '{calc_label}' before selecting data to plot.")
        except Exception:
            pass
        if switch_var is not None:
            try:
                switch_var.set(False)
            except Exception:
                pass
        return False

    def _legend(self, ax, where="right", **kwargs):
        """Draw an adaptive legend that does not shrink the plot.

        The legend is sized to the number of entries: as more curves are
        selected it wraps into more columns and the font steps down (with a
        floor) instead of growing in one direction and squeezing the axes.

        where="right"  -> outside, right of the axes (good for bar charts)
        where="bottom" -> outside, below the axes (good for many curves)
        Returns the Legend object, or None if there is nothing to label.
        """
        handles, labels = ax.get_legend_handles_labels()
        n = len(labels)
        if n == 0:
            # Remove any stale legend.
            old = ax.get_legend()
            if old is not None:
                old.remove()
            return None

        # Font steps down as entries increase, with a readable floor. Tracks
        # the screen-aware base so legends match the rest of the plot text.
        base = self.plot_font_base - 1.0
        if n <= 6:
            fs = base
        elif n <= 12:
            fs = base * 0.85
        elif n <= 24:
            fs = base * 0.72
        else:
            fs = base * 0.6
        fs = max(5.0, fs)

        if where == "bottom":
            # Wrap into more columns as entries grow so the legend stays short
            # (a few rows) instead of pushing tall enough to collapse the axes.
            if n <= 6:
                ncol = min(n, 3)
            elif n <= 16:
                ncol = 4
            elif n <= 36:
                ncol = 5
            else:
                ncol = 6
            return ax.legend(
                handles, labels,
                loc="upper center", bbox_to_anchor=(0.5, -0.18),
                ncol=ncol, fontsize=fs, borderaxespad=0.0,
                frameon=True, **kwargs)
        else:
            # Right side: wrap into extra columns once the list gets long so a
            # tall legend does not force the figure to shrink the axes.
            ncol = 1 if n <= 16 else 2 if n <= 32 else 3
            leg = ax.legend(
                handles, labels,
                loc="upper left", bbox_to_anchor=(1.02, 1.0),
                ncol=ncol, fontsize=fs, borderaxespad=0.0,
                frameon=True, **kwargs)
            # A right-side legend shrinks the axes to the left, which makes a
            # title that is centred on the axes look shifted left relative to
            # the whole figure. Recentre the title over the figure width.
            try:
                self._center_title_on_figure(ax)
            except Exception:
                pass
            return leg

    def _center_title_on_figure(self, ax):
        """Place the axes title centred over the whole figure, not the axes.

        Called after a right-side legend shrinks the axes so the title does not
        look left-shifted. Uses a draw callback so it stays centred after
        constrained_layout finishes positioning the axes.
        """
        fig = ax.figure

        def _recenter(*_):
            try:
                pos = ax.get_position()
                # Title x in axes coordinates that lands at figure centre 0.5.
                ax_center = pos.x0 + pos.width / 2.0
                offset = (0.5 - ax_center) / pos.width
                ax.title.set_x(0.5 + offset)
            except Exception:
                pass

        _recenter()
        # Re-apply after the figure is drawn/resized (constrained_layout moves
        # the axes), without stacking duplicate callbacks.
        if getattr(self, "_title_cb_axes", None) is None:
            self._title_cb_axes = set()
        if ax not in self._title_cb_axes:
            fig.canvas.mpl_connect("draw_event", lambda e, a=ax: self._recenter_title_safe(a))
            self._title_cb_axes.add(ax)

    def _recenter_title_safe(self, ax):
        try:
            pos = ax.get_position()
            ax_center = pos.x0 + pos.width / 2.0
            offset = (0.5 - ax_center) / pos.width
            ax.title.set_x(0.5 + offset)
        except Exception:
            pass
        
    
    def create_scrollable_tab(self, parent):
        outer_frame = tk.Frame(parent)

        canvas = tk.Canvas(outer_frame)
        v_scrollbar = tk.Scrollbar(outer_frame, orient="vertical", command=canvas.yview)
        h_scrollbar = tk.Scrollbar(outer_frame, orient="horizontal", command=canvas.xview)

        scrollable_frame = tk.Frame(canvas)

        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")

        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )

        canvas.configure(
            yscrollcommand=v_scrollbar.set,
            xscrollcommand=h_scrollbar.set
        )

        def _on_mousewheel(event):
            canvas.yview_scroll(int(-event.delta / 120), "units")

        def _bind_mousewheel(event):
            canvas.bind_all("<MouseWheel>", _on_mousewheel)

        def _unbind_mousewheel(event):
            canvas.unbind_all("<MouseWheel>")

        outer_frame.bind("<Enter>", _bind_mousewheel)
        outer_frame.bind("<Leave>", _unbind_mousewheel)

        canvas.grid(row=0, column=0, sticky="nsew")
        v_scrollbar.grid(row=0, column=1, sticky="ns")
        h_scrollbar.grid(row=1, column=0, sticky="ew")

        outer_frame.grid_rowconfigure(0, weight=1)
        outer_frame.grid_columnconfigure(0, weight=1)

        return outer_frame, scrollable_frame

    def setup_tab2(self): 
        
        
        # Column 0 holds the well plate + controls; column 1 holds the plot.
        # The controls column is kept to a modest fixed width so it never grows
        # to push the plot off-screen, and the plot column takes all remaining
        # width. This keeps the two from overlapping on small laptop screens.
        self.tab2.grid_columnconfigure(0, weight=0, minsize=300)
        self.tab2.grid_columnconfigure(1, weight=1)
        # Let the single content row stretch to the full height of the tab so
        # the plot and controls fill the window instead of leaving a gray band
        # of empty space at the bottom.
        self.tab2.grid_rowconfigure(0, weight=1)
        
        left_column_tab2 = tk.Frame(self.tab2)
        left_column_tab2.grid(column = 0, row = 0, sticky = "nsew")
        
        left_column_tab2.grid_rowconfigure(0, weight = 3)
        left_column_tab2.grid_rowconfigure(1, weight = 1)
        left_column_tab2.grid_rowconfigure(2, weight = 1)
        
        right_column_tab2 = tk.Frame(self.tab2)
        right_column_tab2.grid(column = 1, row = 0, sticky = "nsew")
        
        right_column_tab2.grid_columnconfigure(0, weight = 1)
        right_column_tab2.grid_rowconfigure(0, weight = 1)
        
        
        well_frame = tk.Frame(left_column_tab2)
        well_frame.grid(row=0, column=0, padx=10, pady=10, sticky="nsew")
        rows = 8
        cols = 12

        # Single, scale-aware definition for the 8x12 well plate.
        # Keep the plate compact: the well font is deliberately NOT scaled up on
        # high-DPI screens, because 12 columns of buttons must fit next to the
        # plot even on small laptop displays. A small fixed font keeps the
        # plate's minimum width modest.
        padding = 1
        well_font = ("Arial", 8)
        # Color used for a selected well, matched to the app's default
        # CTkButton color so the highlight is consistent with the rest of
        # the UI, and rendered via CustomTkinter so it displays correctly
        # on both Windows and macOS.
        self.well_selected_color = "#3B8ED0"

        # Let the plate distribute its space evenly so it grows with the window.
        for r in range(rows):
            well_frame.grid_rowconfigure(r, weight=1)
        for c in range(cols):
            well_frame.grid_columnconfigure(c, weight=1)
        
        
        
        
        self.well_buttons = {}
        self.well_states = {}
        self.plot_lines = {}
        self.replicate_bars = {}
        self.sheet_names_slope_rep = []
        self.sheet_names_max_growth_rep = []
        self.sheet_names_max_growth_means = []
        self.sheet_names_doubling_rep = []
        self.sheet_names_doubling_means = []
        self.sheet_names_slope_means = []
        self.sheet_names_auc_means = []
        
        self.sheet_names_score_rep = []
        self.sheet_names_score_means = []
        
        self.auc_calc = []
        
        
        self.auc_bars_rep_death = {}
        self.auc_bars_rep_stat = {}
        self.auc_bars_rep_log = {}
        self.auc_bars_rep_lag = {}
        
        self.replicate_bars_mean = {}
        self.auc_bars_mean_lag = {}
        self.auc_bars_mean_log = {}
        self.auc_bars_mean_stationary = {}
        self.auc_bars_mean_death = {}
        
        
        
        
        self.auc_index_dictionary = {}
        
        self.auc_dictionary = {}
        self.auc_dictionary_lag = {}
        self.auc_dictionary_log = {}
        self.auc_dictionary_stationary = {}
        self.auc_dictionary_death = {}
        
        
        self.onset_delays_index = {}
        self.exponential_times_index = {}
        
        self.onset_delays = {}
        self.exponential_times = {}
        self.full_exponential_time = {}
        

        for row in range(rows):
            for col in range(cols):
                # Create a button for each cell in the grid
                label = f'{chr(65 + row)}{col + 1}'  # Label like A1, B2, etc.
                self.well_states[label] = False
                self.plot_lines[label] = None
                # CTkButton is used instead of a plain tk.Button because
                # native tk background-color changes are not rendered by
                # macOS's Aqua theme (Windows renders them fine), which is
                # why the red highlight previously only showed on Windows.
                # CTkButton draws its own background, so the highlight is
                # consistent on both platforms.
                button = ctk.CTkButton(
                    well_frame,
                    text=label,
                    width=24,
                    height=20,
                    corner_radius=2,
                    border_width=1,
                    border_color="gray70",
                    fg_color="white",
                    text_color="black",
                    font=well_font,
                    command=partial(self.on_well_click, label)
                )
                button.grid(row=row, column=col, padx=padding, pady=padding, sticky="nsew")
                self.well_buttons[label] = button
                # Bind the button to a click event
                
       
        #Frame for the excel loading
        data_loading_frame = tk.LabelFrame(left_column_tab2, text="Data loading", padx=10, pady=10)
        data_loading_frame.grid(column = 0, row = 1, sticky = "nsew")
        
        data_loading_frame.grid_columnconfigure(0, weight = 1)
        data_loading_frame.grid_columnconfigure(1, weight = 1)
        
        data_loading_frame.grid_rowconfigure(0, weight = 1)
        data_loading_frame.grid_rowconfigure(1, weight = 1)
        
        #Button for the raw data loading
        browser_button = ctk.CTkButton(data_loading_frame, text = "Select Raw Data File", font=self.sfont(13), command = self.open_file_browser)
        browser_button.grid(column = 1, row = 0, sticky = "nsew", pady = 10, padx = 10)
        
        #Button for the metadata loading
        browser_button = ctk.CTkButton(data_loading_frame, text = "Select Metadata File", font=self.sfont(13), command = self.open_file_browser_for_metadata)
        browser_button.grid(column = 1, row = 1, sticky = "nsew", pady = 10, padx = 10)
                
        
        #Writing out the file that has been opened
        self.raw_file_variable = tk.StringVar(master=self, value="")
        self.entry_raw_data = tk.Entry(data_loading_frame, textvariable = self.raw_file_variable, state="readonly", readonlybackground="white",  width=20)
        self.entry_raw_data.grid(column = 0, row = 0, pady = 10, padx = 10, sticky = "w")
        
        #Writing out the metadata file that has been opened
        self.meta_file_variable = tk.StringVar(master=self, value="")
        self.entry_metadata = tk.Entry(data_loading_frame, textvariable = self.meta_file_variable, state="readonly",readonlybackground="white", width=20)
        self.entry_metadata.grid(column = 0, row = 1, pady = 10, padx = 10, sticky = "w")
        
        
        left_column_last_row = tk.Frame(left_column_tab2)
        left_column_last_row.grid(column = 0, row = 2, padx = 0, pady = 10, sticky = "nsew")
        
        left_column_last_row.grid_columnconfigure(0, weight = 1)
        left_column_last_row.grid_columnconfigure(1, weight = 1)
        
        # #Adding a logging window (width is in characters; Tk scaling handles px)
        info_width = 24

        self.info_text_box = ScrolledText(
            left_column_last_row,
            height=10,
            width=info_width,
            bg="#f0f0f0",
            state="disabled"
        )
        self.info_text_box.grid(column=1, row=0, sticky="nsew", padx=(2,0), pady=2)
        
        
        ##Adding a plot
        self.fig, self.ax = plt.subplots(constrained_layout=True, figsize=self.sfig(3.5, 3.0))

        self.ax.set_title("Bacterial growth curve")
        self.ax.set_xlabel("Time [min]")
        self.ax.set_ylabel("Optical Density")
        self.legend = None
        

        # Embed plot in GUI
        main_display_plot_frame = tk.Frame(right_column_tab2)
        main_display_plot_frame.grid(column = 0, row = 0, sticky = "nsew", pady = 2, padx = 2)
        
        main_display_plot_frame.grid_columnconfigure(0, weight = 1)
        main_display_plot_frame.grid_rowconfigure(0, weight = 1)
        
        
        self.canvas = FigureCanvasTkAgg(self.fig, master=main_display_plot_frame)
        self.canvas_widget = self.canvas.get_tk_widget()
        self.canvas_widget.grid(column = 0, row = 0, pady = 10, padx = 10, sticky = "nsew")
        
        # Right-click menu for the plot
        self.plot_menu = tk.Menu(self, tearoff=0)
        self.plot_menu.add_command(label="Hide Legend", command=self.toggle_legend)
        self.plot_menu.add_command(label="Clear plot", command=self.clear_plot)
        self.plot_menu.add_command(label = "Set Title", command = self.plot_title)
        self.plot_menu.add_command(label = "Set x axis label", command = self.plot_x_axis_label)
        self.plot_menu.add_command(label = "Set y axis label", command = self.plot_y_axis_label)
        self.plot_menu.add_command(label = "Save", command = self.save_view_plot)
        
        
        
        

        # Correct: get index of the last item by its label
        self.legend_menu_index = self.plot_menu.index("Hide Legend")
        
        self.canvas_widget.bind("<Button-3>", self.show_plot_menu)
        
        console_frame = tk.Frame(left_column_last_row, borderwidth=2, relief="ridge")
        console_frame.grid(column = 0, row = 0, padx = 10, pady = 10, sticky = "nsew")
        
        console_frame.grid_rowconfigure(0, weight = 1)
        console_frame.grid_rowconfigure(1, weight = 1)
        console_frame.grid_rowconfigure(2, weight = 1)
        
        console_frame.grid_columnconfigure(0, weight=1)
        
        self.checkbox_var_slope = ctk.BooleanVar(value = False)
        checkbox_filter = ctk.CTkCheckBox(console_frame, text = "Blank substraction", font=self.sfont(13), variable = self.checkbox_var_slope)
        checkbox_filter.grid(column = 0, row = 0, sticky = "n", padx = 2, pady = 2)
        
        self.metadata_loading_button = ctk.CTkButton(console_frame, text="Edit Metadata Table", font=self.sfont(13), command = self.load_metadata)
        self.metadata_loading_button.grid(column = 0, row = 1, sticky = "n", padx = 2, pady = 2)
        
        ##A button for loading the data
        self.loading_button = ctk.CTkButton(console_frame, text = "Build Analysis", font=self.sfont(13), width = 50, height = 30, command = self._load_safe)
        self.loading_button.grid(column = 0, row = 2, sticky = "n", padx = 2, pady = 2)
        
        

        
        
    ########     FUNCTIONS      ##########################################

    def open_file_browser(self):
        filepath = filedialog.askopenfilename(title="Select the raw data file", filetypes=[("Excel files", "*.xlsx *.xls"), ("All files", "*.*")])
        if not filepath:
            return
        excel_name = os.path.basename(filepath)

        try:
            self.df_raw_data = pd.read_excel(filepath, skiprows = 31)

            if self.df_raw_data["Cycle Nr."].astype(str).str.contains("ms").any():
                self.df_raw_data = pd.read_excel(filepath, skiprows = 31, header = None, index_col=0)
                cycle_df = self.df_raw_data.iloc[0].to_frame()
                time_df = self.df_raw_data.iloc[3].to_frame()/1000/60
                self.df_raw_data = self.df_raw_data.drop(["Time [ms]", "Cycle Nr.", "End Time:"])
                self.df_raw_data = pd.concat([cycle_df, time_df, self.df_raw_data.T], axis = 1)
                self.df_raw_data = self.df_raw_data.rename(columns={"Time [ms]": "Time [min]"})

            else:
                self.df_raw_data["Time [s]"] = self.df_raw_data["Time [s]"]/60
                self.df_raw_data = self.df_raw_data.rename(columns={"Time [s]": "Time [min]"})
                first_nan_index = self.df_raw_data[self.df_raw_data['A1'].isna()].index.min()
                self.df_raw_data = self.df_raw_data.drop(self.df_raw_data.index[first_nan_index:])
                
        except Exception as e:
            # Wrong format / unexpected columns: surface it in the window
            # instead of only the terminal, and leave previous data untouched.
            #self.log_message(f"Could not read raw data file '{excel_name}': {e}")
            #messagebox.showerror("Checking for template")
                    
            try:
                self.df_raw_data = pd.read_excel(filepath)
                self.df_raw_data["Time [s]"] = self.df_raw_data["Time [s]"]/60
                self.df_raw_data = self.df_raw_data.rename(columns={"Time [s]": "Time [min]"})
                first_nan_index = self.df_raw_data[self.df_raw_data['A1'].isna()].index.min()
                self.df_raw_data = self.df_raw_data.drop(self.df_raw_data.index[first_nan_index:])
                        
            except Exception as e:
                self.df_raw_data = None
                self.log_message(f"Could not read raw data file '{excel_name}': {e}")
                messagebox.showerror(
                            "Raw data error",
                            "The selected raw data file could not be read.\nIt may be in "
                            "the wrong format.\n\nDetails: " + str(e))
                return
            
            
            
        if not self.df_raw_data.empty:
            self.raw_file_variable.set(excel_name)
            self.info_text_box.config(state="normal")
            self.info_text_box.insert(tk.END, excel_name + " loaded successfully\n")
            self.info_text_box.see(tk.END)
            self.info_text_box.config(state="disabled")
                
            
        else:
            self.info_text_box.config(state="normal")
            self.info_text_box.insert(tk.END, "Data could not be loaded\n")
            self.info_text_box.see(tk.END)
            self.info_text_box.config(state="disabled")
            
            
        
        
    def open_file_browser_for_metadata(self):
        filepath = filedialog.askopenfilename(title="Select the metadata file", filetypes=[("Excel files", "*.xlsx *.xls"), ("All files", "*.*")])
        if not filepath:
            return
        self.meta_excel_name = os.path.basename(filepath)

        try:
            self.df_metadata = pd.read_excel(filepath)
            if self.df_metadata.empty:
                raise ValueError("the file contains no data")
            # Touch the columns we rely on so a wrong-format file fails here
            # with a clear message rather than deep inside load().
            blank_rows = self.df_metadata[self.df_metadata["Sample name"].str.contains("BLANK", case=False, na=False)]
            if blank_rows.empty:
                raise ValueError("no row with Sample name 'BLANK' was found")
            
            blank_dict = {}
            blank_names = []
            
            for i in np.arange(0, len(blank_rows), 1):
                temp_name = "BLANK(" + str(blank_rows.iloc[i]["Medium"]) + ")"
                blank_names.append("BLANK(" + str(blank_rows.iloc[i]["Medium"]) + ")")
                blank_wells_temp = blank_rows.iloc[i][1:-1]
                blank_wells_temp = [item for item in blank_wells_temp if item != "-"]
                blank_dict[temp_name] = blank_wells_temp
            self.blank_wells = blank_rows.values[0][1:]
        except Exception as e:
            self.df_metadata = None
            self.log_message(f"Could not read metadata file '{self.meta_excel_name}': {e}")
            messagebox.showerror(
                "Metadata error",
                "The selected metadata file could not be read.\nIt may be in "
                "the wrong format.\n\nDetails: " + str(e))
            return blank_dict
        


        blank_text = "\n".join(f"{key}:\n{', '.join(map(str, value)) if isinstance(value, list) else value}" for key, value in blank_dict.items())
        self.info_text_box.config(state="normal")
        self.info_text_box.insert(tk.END, "Metadata loaded successfully\n")
        self.info_text_box.insert(tk.END, f"The blank wells are: \n{blank_text}\n")
        self.info_text_box.see(tk.END)
        self.info_text_box.config(state="disabled")

        self.meta_file_variable.set(self.meta_excel_name)

        return
    

    def _load_safe(self):
        """Run load() and guarantee the button is usable again on any failure.

        Even if load() raises an unexpected error partway through, this catches
        it, reports it in the log and a dialog, and re-enables the Build
        Analysis button so the app never gets stuck with the button disabled.
        """
        try:
            self.load()
        except Exception as e:
            import traceback
            traceback.print_exc()
            try:
                self.log_message(f"Build Analysis failed: {e}")
            except Exception:
                pass
            try:
                messagebox.showerror(
                    "Build Analysis error",
                    "Build Analysis failed. The selected files may be in the "
                    "wrong format.\n\nDetails: " + str(e))
            except Exception:
                pass
        finally:
            # Whatever happened, make sure the user can try again.
            try:
                self.loading_button.configure(state="normal")
            except Exception:
                pass

    def load(self):
        self.loading_button.configure(state="disabled")
        self.log_message("Building analysis ...")

        # Make sure both files were actually loaded and have the expected
        # structure before doing any work. If not, tell the user, re-enable the
        # button, and stop, instead of crashing partway through and leaving the
        # button disabled (which used to make the app appear stuck).
        if not hasattr(self, "df_raw_data") or self.df_raw_data is None or self.df_raw_data.empty:
            self.log_message("No valid raw data loaded. Use 'Select Raw Data File' to select a correct file.")
            messagebox.showerror("Build Analysis error", "Build Analysis requires raw data.\nNo valid raw data is loaded.\nPlease use 'Select Raw Data File' to select a correct raw data file, then try again.")
            self.loading_button.configure(state="normal")
            return
        if not hasattr(self, "df_metadata") or self.df_metadata is None or self.df_metadata.empty:
            self.log_message("No valid metadata loaded. Use 'Select Metadata File' to select a correct file. Raw growth curves can still be viewed on this tab without metadata.")
            messagebox.showerror("Build Analysis error", "Build Analysis requires a metadata file to group replicates and identify blank wells.\nNo valid metadata is loaded.\nPlease use 'Select Metadata File' to select a correct metadata file, then try again.\n\nNote: raw growth curves can still be plotted on this tab without metadata; only Build Analysis requires it.")
            self.loading_button.configure(state="normal")
            return
        if "Sample name" not in self.df_metadata.columns or "Medium" not in self.df_metadata.columns:
            self.log_message("Metadata is missing required columns ('Sample name', 'Medium').")
            messagebox.showerror("Build Analysis error", "The metadata file does not have the expected columns\n('Sample name', 'Medium'). Please check the file.")
            self.loading_button.configure(state="normal")
            return

        try:
            for widget in self.scrollable_tab3_content.winfo_children():
                widget.destroy()
            for widget in self.scrollable_tab_slope.winfo_children():
                widget.destroy()    
            for widget in self.scrollable_tab_max_growth.winfo_children():
                widget.destroy()
            for widget in self.scrollable_tab_auc.winfo_children():
                widget.destroy()
            for widget in self.scrollable_doubling.winfo_children():
                widget.destroy()
            for widget in self.scrollable_score.winfo_children():
                widget.destroy()
            for widget in self.scrollable_tab_filter_content.winfo_children():
                widget.destroy()
        except Exception as e:
            self.log_message(f"Error while building analysis: {e}")
            messagebox.showerror("Build Analysis error", str(e))
            self.loading_button.configure(state="normal")
            return
        
        self.list_for_dataframes = []
        self.list_for_multisample_measurement = []
        

        self.transposed_raw_data = self.df_raw_data.T
        self.sample_names = list(self.df_metadata["Sample name"])
        self.medium_names = list(self.df_metadata["Medium"])
        
        self.sample_medium_dict = dict(zip(self.sample_names, self.medium_names))
        
        self.medium_sample_dict = {}
        
        for key, value in self.sample_medium_dict.items():
            self.medium_sample_dict.setdefault(value, []).append(key)
        

        ### Checking for replicate measurements
        for i in np.arange(0, len(self.sample_names), 1):
            list_temp = self.df_metadata.iloc[i][1:-1]
            cleaned_list = [item for item in list_temp if item != '-']   
            self.list_for_multisample_measurement.append(cleaned_list)
    
        ###Segmenting the dataframes according to the replicates
        for i in np.arange(0, len(self.list_for_multisample_measurement), 1):
            df_temp = self.transposed_raw_data.loc[self.list_for_multisample_measurement[i]]
            means = df_temp.mean(axis=0)
            df_means = means.to_frame().T
            df_means = df_means.rename(index={0: 'Mean ' + self.sample_names[i]})
            df_temp_with_timestamps = pd.concat([self.transposed_raw_data.loc["Time [min]"].to_frame().T, df_temp, df_means], axis=0, ignore_index=False)
            
            self.list_for_dataframes.append(df_temp_with_timestamps)
            
            
        
        self.frame_filter = tk.Frame(self.scrollable_tab_filter_content)
        self.frame_filter.pack(padx=8, pady=10, fill = "x", expand = True)
        
        self.frame_slope = tk.Frame(self.scrollable_tab_slope)
        self.frame_slope.pack(padx=8, pady=10, fill = "x", expand = True)
        
        self.frame_max_growth = tk.Frame(self.scrollable_tab_max_growth)
        self.frame_max_growth.pack(padx=8, pady=10, fill = "x", expand = True)
        
        self.frame_auc = tk.Frame(self.scrollable_tab_auc)
        self.frame_auc.pack(padx=8, pady=10, fill = "x", expand = True)
        
        self.frame_doubling = tk.Frame(self.scrollable_doubling)
        self.frame_doubling.pack(padx=8, pady=10, fill = "x", expand = True)
        
        self.frame_score = tk.Frame(self.scrollable_score)
        self.frame_score.pack(padx=8, pady=10, fill = "x", expand = True)
        
        ##### Rows in Filter frame ######################
        
        self.frame_filter.grid_rowconfigure(0, weight=1)
        # The filter row has three columns: sheet switches (0), the control
        # console (1), and the plots (2). Give the two control columns no extra
        # weight so they stay at their content width, and let the plot column
        # absorb all remaining space instead of the console panel being wide.
        self.frame_filter.grid_columnconfigure(0, weight=0)
        self.frame_filter.grid_columnconfigure(1, weight=0)
        # Plot column (2) shares the leftover width with an empty spacer column
        # (3). Weights 2:1 make the plots about two-thirds as wide as the full
        # remaining space, leaving the plots comfortably sized rather than
        # stretched across the whole window.
        self.frame_filter.grid_columnconfigure(2, weight=2)
        self.frame_filter.grid_columnconfigure(3, weight=1)
        
        self.frame_filter_row = tk.Frame(self.frame_filter)
        self.frame_filter_row.grid(row=0, column=0, pady=10, sticky = "nsew")
        
        self.frame_filter_row.grid_columnconfigure(0, weight=1)
        self.frame_filter_row.grid_columnconfigure(1, weight=1)
        self.frame_filter_row.grid_columnconfigure(2, weight=4)
        
        
        ##### Rows in Slope frame #######################
        
        
        self.frame_slope.grid_rowconfigure(0, weight=1)
        self.frame_slope.grid_rowconfigure(1, weight=1)
        
        self.slope_frame_top = tk.Frame(self.frame_slope)
        self.slope_frame_top.grid(row=0, column=0, pady=10, sticky = "nsew")
        
        # The two switch columns (0,1) size to their content; the two plot
        # columns (2,3) absorb the remaining width. A small extra row at the
        # top holds the Calculate button so it sits at the top-left.
        self.slope_frame_top.grid_columnconfigure(0, weight=0)
        self.slope_frame_top.grid_columnconfigure(1, weight=0)
        self.slope_frame_top.grid_columnconfigure(2, weight=1)
        self.slope_frame_top.grid_columnconfigure(3, weight=1)
        self.slope_frame_top.grid_rowconfigure(0, weight=0)  # button row
        self.slope_frame_top.grid_rowconfigure(1, weight=1)  # content row
        
        self.slope_frame_bottom = tk.Frame(self.frame_slope)
        self.slope_frame_bottom.grid(row=1, column=0, pady=10, sticky = "nsew")
        
        self.slope_frame_bottom.grid_columnconfigure(0, weight=1)
        self.slope_frame_bottom.grid_columnconfigure(1, weight=1)
        self.slope_frame_bottom.grid_rowconfigure(1, weight=1)
                
        
        
        ##### Rows in Maximum growth frame ####################
        
        self.frame_max_growth.grid_rowconfigure(0, weight=1)
        self.frame_max_growth.grid_rowconfigure(1, weight=1)
        
        self.max_growth_frame_top = tk.Frame(self.frame_max_growth)
        self.max_growth_frame_top.grid(row=0, column=0, pady=10, sticky = "nsew")
        
        self.max_growth_frame_top.grid_columnconfigure(0, weight=0)
        self.max_growth_frame_top.grid_columnconfigure(1, weight=0)
        self.max_growth_frame_top.grid_columnconfigure(2, weight=0)
        self.max_growth_frame_top.grid_columnconfigure(3, weight=1)
        
        
        
        self.max_growth_frame_bottom = tk.Frame(self.frame_max_growth)
        self.max_growth_frame_bottom.grid(row=1, column=0, pady=10, sticky = "nsew")
        
        self.max_growth_frame_bottom.grid_columnconfigure(0, weight = 1)
        self.max_growth_frame_bottom.grid_columnconfigure(1, weight = 1)
        
        
        ##### ROWS IN AUC FRAME ##########################
        
        self.frame_auc.grid_rowconfigure(0, weight=1)
        self.frame_auc.grid_rowconfigure(1, weight=1)
        self.frame_auc.grid_rowconfigure(2, weight=1)
        self.frame_auc.grid_rowconfigure(3, weight=1)
        self.frame_auc.grid_rowconfigure(4, weight=1)
        self.frame_auc.grid_rowconfigure(5, weight=1)
        
        self.auc_frame_first = tk.Frame(self.frame_auc)
        self.auc_frame_first.grid(row=0, column=0, pady=10, sticky = "nsew")
        
        self.auc_frame_first.grid_columnconfigure(0, weight=0)
        self.auc_frame_first.grid_columnconfigure(1, weight=0)
        self.auc_frame_first.grid_columnconfigure(2, weight=0)
        self.auc_frame_first.grid_columnconfigure(3, weight=1)
        self.auc_frame_first.grid_rowconfigure(0, weight=1)
        
        self.auc_frame_second = tk.Frame(self.frame_auc)
        self.auc_frame_second.grid(row=1, column=0, pady=10, sticky = "nsew")
        
        self.auc_frame_second.grid_columnconfigure(0, weight=1)
        self.auc_frame_second.grid_columnconfigure(1, weight=1)
        self.auc_frame_second.grid_rowconfigure(0, weight=1)
        
        self.auc_frame_third = tk.Frame(self.frame_auc)
        self.auc_frame_third.grid(row=2, column=0, pady=10, sticky = "nsew")
        
        self.auc_frame_third.grid_columnconfigure(0, weight=1)
        self.auc_frame_third.grid_columnconfigure(1, weight=1)
        self.auc_frame_third.grid_rowconfigure(0, weight=1)
        
        self.auc_frame_fourth = tk.Frame(self.frame_auc)
        self.auc_frame_fourth.grid(row=3, column=0, pady=10, sticky = "nsew")
        
        self.auc_frame_fourth.grid_columnconfigure(0, weight=1)
        self.auc_frame_fourth.grid_columnconfigure(1, weight=1)
        self.auc_frame_fourth.grid_rowconfigure(0, weight=1)
        
        self.auc_frame_fifth = tk.Frame(self.frame_auc)
        self.auc_frame_fifth.grid(row=4, column=0, pady=10, sticky = "nsew")
        
        self.auc_frame_fifth.grid_columnconfigure(0, weight=1)
        self.auc_frame_fifth.grid_columnconfigure(1, weight=1)
        self.auc_frame_fifth.grid_rowconfigure(0, weight=1)
        
        self.auc_frame_sixth = tk.Frame(self.frame_auc)
        self.auc_frame_sixth.grid(row=5, column=0, pady=10, sticky = "nsew")
        
        self.auc_frame_sixth.grid_columnconfigure(0, weight=1)
        self.auc_frame_sixth.grid_columnconfigure(1, weight=1)
        
        
        
        ############### ROWS IN DOUBLING TIME #############################
        
        self.frame_doubling.grid_rowconfigure(0, weight=1)
        self.frame_doubling.grid_rowconfigure(1, weight=1)
        self.frame_doubling.grid_columnconfigure(0, weight=1)
        
        self.doubling_frame_top = tk.Frame(self.frame_doubling)
        self.doubling_frame_top.grid(row=0, column=0, pady=10, sticky = "nsew")
        
        self.doubling_frame_top.grid_columnconfigure(0, weight=0)
        self.doubling_frame_top.grid_columnconfigure(1, weight=0)
        self.doubling_frame_top.grid_columnconfigure(2, weight=1)
        self.doubling_frame_top.grid_columnconfigure(3, weight=1)
        
        self.doubling_frame_top.grid_rowconfigure(0, weight=0)
        self.doubling_frame_top.grid_rowconfigure(1, weight=1)
        
        self.doubling_frame_bottom = tk.Frame(self.frame_doubling)
        self.doubling_frame_bottom.grid(row=1, column=0, pady=10, sticky = "nsew")
        
        self.doubling_frame_bottom.grid_columnconfigure(0, weight=1)
        self.doubling_frame_bottom.grid_columnconfigure(1, weight=1)
        self.doubling_frame_bottom.grid_columnconfigure(2, weight=4)
        self.doubling_frame_bottom.grid_columnconfigure(3, weight=4)
        self.doubling_frame_bottom.grid_rowconfigure(0, weight=1)
        
        ############ ROWS IN SCORE ##########################################
        self.frame_score.grid_rowconfigure(0, weight=1)
        self.frame_score.grid_rowconfigure(1, weight=1)
        self.frame_score.grid_columnconfigure(0, weight=1)
        
        
        self.score_frame_top = tk.Frame(self.frame_score)
        self.score_frame_top.grid(row=0, column=0, pady=10, sticky = "nsew")
        
        self.score_frame_top.grid_columnconfigure(0, weight=0)
        self.score_frame_top.grid_columnconfigure(1, weight=0)
        self.score_frame_top.grid_columnconfigure(2, weight=1)
        self.score_frame_top.grid_columnconfigure(3, weight=1)
        
        self.score_frame_top.grid_rowconfigure(0, weight=0)
        self.score_frame_top.grid_rowconfigure(1, weight=1)
        
        self.score_frame_bottom = tk.Frame(self.frame_score)
        self.score_frame_bottom.grid(row=1, column=0, pady=10, sticky = "nsew")
        
        self.score_frame_bottom.grid_columnconfigure(0, weight=1)
        self.score_frame_bottom.grid_columnconfigure(1, weight=1)
        self.score_frame_bottom.grid_columnconfigure(2, weight=4)
        self.score_frame_bottom.grid_columnconfigure(3, weight=4)
        self.score_frame_bottom.grid_rowconfigure(0, weight=1)
        
        ###################################################################
        
        
        self.score_button = ctk.CTkButton(self.score_frame_top, text = "Calculate Index", font=self.sfont(13), width = 40, height = 30)
        self.score_button.configure(command=lambda: self._run_calculation(self.score_button, self.calculate_score, "Calculate Index"))
        self.score_button.grid(row=0, column=0, padx=10, pady=(2,8), sticky="nw")
        
        
        self.doubling_button = ctk.CTkButton(self.doubling_frame_top, text = "Calculate\ndoubling time", font=self.sfont(13), width = 40, height = 30)
        self.doubling_button.configure(command=lambda: self._run_calculation(self.doubling_button, self.calculate_doubling_time, "Calculate doubling time"))
        self.doubling_button.grid(row=0, column=0, padx=10, pady=(2,8), sticky="nw")
        
        
        self.slope_button = ctk.CTkButton(self.slope_frame_top, text = "Calculate slopes", font=self.sfont(13), width = 40, height = 30)
        self.slope_button.configure(command=lambda: self._run_calculation(self.slope_button, self.calculate_slopes, "Calculate slopes"))
        self.slope_button.grid(row=0, column=0, padx=10, pady=(2, 8), sticky="nw")
        
        #### Frames for the Filter Switches ###########################################################
        
        frame_filter_console = tk.Frame(self.frame_filter, borderwidth=3, relief="ridge")
        frame_filter_console.grid(row=0, column=1, padx=10, pady=10, sticky="nsew")
        
        
        frame_filter_switch_one = tk.Frame(self.frame_filter, borderwidth=3, relief="ridge")
        frame_filter_switch_one.grid(row=0, column=0, padx=10, pady=10, sticky="nsew")
        
            
        ####The frames for the switches on the slope tab ##################################
        
        frame_slope_switch_one = tk.Frame(self.slope_frame_top, borderwidth=3, relief="ridge")
        frame_slope_switch_one.grid(row=1, column=0, padx=10, pady=10, sticky="nsew")
        
        frame_slope_switch_two = tk.Frame(self.slope_frame_top, borderwidth=3, relief="ridge")
        frame_slope_switch_two.grid(row=1, column=1, padx=10, pady=10, sticky="nsew")
        
        #### Frame for Max growth switches #############################################################
        self.frame_maxg_switch_one = tk.Frame(self.max_growth_frame_top, borderwidth=3, relief="ridge")
        self.frame_maxg_switch_one.grid(row=0, column=0, padx=10, pady=10, sticky="nsew")
        
        
        frame_maxg_switch_two = tk.Frame(self.max_growth_frame_top, borderwidth=3, relief="ridge")
        frame_maxg_switch_two.grid(row=0, column=1, padx=10, pady=10, sticky ="nsew")
        
        
        #### Frame for AUC switches #############################################################
        self.frame_auc_switch_one = tk.Frame(self.auc_frame_first, borderwidth=3, relief="ridge")
        self.frame_auc_switch_one.grid(row=0, column=0, padx=10, pady=10, sticky ="nsew")
        
        self.frame_auc_switch_two = tk.Frame(self.auc_frame_first, borderwidth=3, relief="ridge")
        self.frame_auc_switch_two.grid(row=0, column=1, padx=10, pady=10, sticky ="nsew")
        
        
        #### Frames for Doubling time switches ##########################################################x
        
        self.frame_doubling_switch_one = tk.Frame(self.doubling_frame_top, borderwidth=3, relief="ridge")
        self.frame_doubling_switch_one.grid(row=1, column=0, padx=10, pady=10, sticky="nsew")
        
        
        self.frame_doubling_switch_two = tk.Frame(self.doubling_frame_top, borderwidth=3, relief="ridge")
        self.frame_doubling_switch_two.grid(row=1, column=1, padx=10, pady=10, sticky="nsew")
        
        
        #### Frames for Score switches ###################################################################
        self.frame_score_switch_one = tk.Frame(self.score_frame_top, borderwidth=3, relief="ridge")
        self.frame_score_switch_one.grid(row=1, column=0, padx=10, pady=10, sticky="nsew")
        
        self.frame_score_switch_two = tk.Frame(self.score_frame_top, borderwidth=3, relief="ridge")
        self.frame_score_switch_two.grid(row=1, column=1, padx=10, pady=10, sticky="nsew")
            
        
        self.raw_data_dict = dict(zip(self.sample_names, self.list_for_dataframes))
        
        
        
        self.raw_data_filter_display_dict = {}
        self.filtered_data_display_dict = {}
        
        self.max_growth_display_dict = {}
        self.derivatives_display = {}
        self.auc_display_dict = {}
        
        
        self.filter_parameters = {}
        
        
        
        self.sheets = {}
        self.switch_vars_filter = {} 
        self.switch_vars = {}
        self.switch_vars_mean = {}
        self.switch_vars_max_growth = {}
        self.switch_vars_max_growth_means = {}
        self.switch_vars_auc = {}
        self.switch_vars_auc_means = {}
        
        self.switch_vars_doubling = {}
        self.switch_vars_doubling_means = {}
        
        self.switch_vars_score = {}
        self.switch_vars_score_means = {}
        
        
        if self.checkbox_var_slope.get():
            try:
                
                
                #### Extracting the blank values
                for value_list in self.medium_sample_dict.values():
                    value_list.sort(key=lambda item: "BLANK" in str(item).upper())
                    
                self.blank_dict_temp = {key: blank_values for key, values in self.medium_sample_dict.items() if (blank_values := [ item for item in values   if "BLANK" in str(item).upper() ] )}   
                
                for key in self.medium_sample_dict:
                    for values in self.medium_sample_dict[key]:
                        blank_name_temp = self.blank_dict_temp[key]
                        for i in np.arange(1, len(self.raw_data_dict[values]), 1):
                            self.raw_data_dict[values].iloc[i] = self.raw_data_dict[values].iloc[i] - self.raw_data_dict[blank_name_temp[0]].iloc[-1]
                
                
                
            except KeyError:
                self.info_text_box.config(state="normal")
                self.info_text_box.insert(tk.END, "BLANK measurement does not exist")
                self.info_text_box.see(tk.END)
                self.info_text_box.config(state="disabled")
                
        
        
        
        ###---------------------------------------------------------------------------------------------------
    
        ##### REMOVING THE NEGATIVE VALUES AFTER BLANK SUBSTRACTION######
        #IT REMOVES THE NEGATIVE VALUES EVEN IF THERE IS NO BLANK SUBSTRACTION, BUT THEN
        #IF NEGATIVES APPEAR IT IS VERY LIKELY MEASUREMENT ERROR AND REMEASUREMENT IS RECOMMENDED
            
            
        for key in self.raw_data_dict:
            highest_negative_index = -1
            highest_negative_index_temp = -1

            for i in np.arange(1, len(self.raw_data_dict[key]), 1):
                row = self.raw_data_dict[key].iloc[i]

                negative_positions = np.where(row.to_numpy() < 0)[0]

                if len(negative_positions) > 0:
                    highest_negative_index_temp = negative_positions[-1]

                if highest_negative_index_temp > highest_negative_index:
                    highest_negative_index = highest_negative_index_temp

            if highest_negative_index != -1:
                start_idx = highest_negative_index + 1

                if start_idx < self.raw_data_dict[key].shape[1]:
                        self.raw_data_dict[key] = self.raw_data_dict[key].iloc[:, start_idx:]
                    
                    
        ###---------------------------------------------------------------------------------------------------
                    
            
        for idx, (sheet_name, df) in enumerate(self.raw_data_dict.items()):
            # Create frame for each sheet
            frame = tk.Frame(self.scrollable_tab3_content)
            frame.pack(padx=8, pady=10)
            
            

            label = tk.Label(frame, text=sheet_name + " - " + self.sample_medium_dict[sheet_name], font=self.sfont(12, "bold"))
            label.pack(anchor="w")

            # Create tksheet
            sheet = tksheet.Sheet(frame, data=df.values.tolist(), headers=list(df.columns), row_index=df.index.tolist(), height = self.table_height, width = self.table_width)
            sheet.pack(padx=5, pady=10, fill="x", expand=True)
            

            sheet.enable_bindings((
                "single_select", "column_select", "edit_cell", "arrowkeys", "ctrl_z", "ctrl_y", "column_width_resize",
                    "double_click_column_resize",
                    "row_height_resize",
                    "double_click_row_resize", 
            ))

            self.sheets[sheet_name] = sheet

            # Recolor button
            btn_frame = tk.Frame(frame)
            btn_frame.pack(pady=5)
            
            
            btn_delete = ctk.CTkButton(btn_frame, text=f"Exclude Selected Columns in {sheet_name}",
                            command=lambda s=sheet: self.recolor_selected_columns(s))
            btn_delete.pack(side='left', padx=5)
            
            btn_reset = ctk.CTkButton(btn_frame, text=f"Reset",
                            command=lambda s=sheet: self.reset_original_data(s))
            btn_reset.pack(side='left', padx=5)
            
            btn_plot = ctk.CTkButton(btn_frame, text=f"Plot",
                            command=lambda s=sheet: self.plot_the_respective_triplicate(s))
            btn_plot.pack(side='left', padx=5)
            
            btn_plot.bind("<Button-3>", self.add_custom_colors)
            
            
            switch_var_filter = ctk.BooleanVar(value = False)
            self.switch_vars_filter[sheet_name] = switch_var_filter
            
            switch_var = ctk.BooleanVar(value = False)
            self.switch_vars[sheet_name] = switch_var
            
            switch_var_mean = ctk.BooleanVar(value = False)
            self.switch_vars_mean[sheet_name] = switch_var_mean
            
            switch_var_max_growth = ctk.BooleanVar(value = False)
            self.switch_vars_max_growth[sheet_name] = switch_var_max_growth
            
            switch_var_max_growth_means = ctk.BooleanVar(value = False)
            self.switch_vars_max_growth_means[sheet_name] = switch_var_max_growth_means
            
            switch_var_auc = ctk.BooleanVar(value = False)
            self.switch_vars_auc[sheet_name] = switch_var_auc
            
            switch_var_auc_means = ctk.BooleanVar(value = False)
            self.switch_vars_auc_means[sheet_name] = switch_var_auc_means
            
            switch_var_doubling = ctk.BooleanVar(value = False)
            self.switch_vars_doubling[sheet_name] = switch_var_doubling
            
            switch_var_doubling_means = ctk.BooleanVar(value = False)
            self.switch_vars_doubling_means[sheet_name] = switch_var_doubling_means
            
            switch_var_score = ctk.BooleanVar(value = False)
            self.switch_vars_score[sheet_name] = switch_var_score
            
            switch_var_score_means = ctk.BooleanVar(value = False)
            self.switch_vars_score_means[sheet_name] = switch_var_score_means
            
        
            
            ### Switches for the 
            switch_filter = ctk.CTkSwitch(frame_filter_switch_one, text=sheet_name, variable = switch_var_filter, command=lambda s=sheet, name=sheet_name: self.plot_raw_data_for_filtering(s, name))
            switch_filter.pack(pady=1, padx = 10, anchor = "w")
            
            ###Switches for the slope
            switch = ctk.CTkSwitch(frame_slope_switch_one, text=sheet_name, variable = switch_var, command=lambda s=sheet, name=sheet_name: self.plot_replicate_slopes(s, name))
            switch.pack(pady=1, padx = 10, anchor = "w")
            
            switch_mean = ctk.CTkSwitch(frame_slope_switch_two, text=sheet_name, variable = switch_var_mean, command=lambda s=sheet, name=sheet_name: self.plot_means(s, name))
            switch_mean.pack(pady=1, padx = 10, anchor = "w")
            
            
            ###Switches for the maximum growth calculation            
            switch_max_growth_display = ctk.CTkSwitch(self.frame_maxg_switch_one, text=sheet_name, variable = switch_var_max_growth, font=self.sfont(12), command=lambda s=sheet, name=sheet_name: self.plot_max_growth_curves(s, name))
            switch_max_growth_display.pack(pady=1, padx = 10, anchor = "w")
            
            switch_max_growth_means = ctk.CTkSwitch(frame_maxg_switch_two, text=sheet_name, variable = switch_var_max_growth_means, font=self.sfont(12), command=lambda s=sheet, name=sheet_name: self.plot_max_growth_means(s, name))
            switch_max_growth_means.pack(pady=1, padx = 10, anchor = "w")
            
            ###Switches for the AUC            
            switch_auc_display = ctk.CTkSwitch(self.frame_auc_switch_one, text=sheet_name, variable = switch_var_auc, command=lambda s=sheet, name=sheet_name: self.plot_auc_curves(s, name))
            switch_auc_display.pack(pady=1, padx = 10, anchor = "w")
            
            switch_auc_means = ctk.CTkSwitch(self.frame_auc_switch_two, text=sheet_name, variable = switch_var_auc_means, command=lambda s=sheet, name=sheet_name: self.plot_auc_means(s, name))
            switch_auc_means.pack(pady=1, padx = 10, anchor = "w")
            
            
            ###Switches for the Doubling time            
            switch_doubling_display = ctk.CTkSwitch(self.frame_doubling_switch_one, text=sheet_name, variable = switch_var_doubling, command=lambda s=sheet, name=sheet_name: self.plot_doubling_replicates(s, name))
            switch_doubling_display.pack(pady=1, padx = 10, anchor = "w")
            
            switch_doubling_means = ctk.CTkSwitch(self.frame_doubling_switch_two, text=sheet_name, variable = switch_var_doubling_means, command=lambda s=sheet, name=sheet_name: self.plot_doubling_means(s, name))
            switch_doubling_means.pack(pady=1, padx = 10, anchor = "w")
            
            ### Switches for the score
            switch_score_display = ctk.CTkSwitch(self.frame_score_switch_one, text=sheet_name, variable = switch_var_score, command=lambda s=sheet, name=sheet_name: self.plot_score_replicates(s, name))
            switch_score_display.pack(pady=1, padx = 10, anchor = "w")
            
            switch_score_means = ctk.CTkSwitch(self.frame_score_switch_two, text=sheet_name, variable = switch_var_score_means, command=lambda s=sheet, name=sheet_name: self.plot_score_means(s, name))
            switch_score_means.pack(pady=1, padx = 10, anchor = "w")
            
            
            
        self.original_raw_data_dict = copy.deepcopy(self.raw_data_dict) ## Copying the dict, so even if later there are points deleted they can be restored
        self.raw_data_for_filtering_dict = copy.deepcopy(self.raw_data_dict) 
        
        ################ Plots for the Filter frame ########################################################################
        
        # Container for both filter plots, spanning the full height of the
        # filter row so the two plots stack tightly one above the other instead
        # of being pushed apart by the tall switch column.
        plot_container_filter = tk.Frame(self.frame_filter)
        plot_container_filter.grid(column=2, row=0, rowspan=2, sticky="nsew", padx=5, pady=5)
        plot_container_filter.grid_columnconfigure(0, weight=1)
        plot_container_filter.grid_rowconfigure(0, weight=1)
        plot_container_filter.grid_rowconfigure(1, weight=1)

        self.plot_frame_filter_top = tk.Frame(plot_container_filter)
        self.plot_frame_filter_top.grid(column = 0, row = 0, sticky = "nsew", padx = 5, pady = 5)
        self.plot_frame_filter_top.grid_columnconfigure(0, weight=1)
        self.plot_frame_filter_top.grid_rowconfigure(0, weight=1)
        
        self.plot_frame_filter_bottom = tk.Frame(plot_container_filter)
        self.plot_frame_filter_bottom.grid(column = 0, row = 1, sticky = "nsew", padx = 5, pady = 5)
        self.plot_frame_filter_bottom.grid_columnconfigure(0, weight=1)
        self.plot_frame_filter_bottom.grid_rowconfigure(0, weight=1)

        # Filter figure size. Kept compact so the two stacked plots (raw +
        # filtered) fit in the window without forcing the scroll bar. Width is
        # generous for the legend; height is modest so both fit vertically.
        filter_figsize = self.sfig(4.0, 2.4)
        # Compact base sizes for the analysis plots. The canvases are made
        # responsive (they resize to fill their cell), so these are just a
        # modest starting/minimum size rather than the fixed final size.
        analysis_large_figsize = self.sfig(4.0, 2.6)
        analysis_small_figsize = self.sfig(3.2, 2.6)

        self.fig_raw_data_filter, self.ax_raw_data_filter = plt.subplots(
            figsize=filter_figsize
        )
        # Reserve a fixed right margin for the legend so the plot area never
        # shrinks as the legend grows. constrained_layout is intentionally off
        # here because it competes with an outside legend.
        self.fig_raw_data_filter.subplots_adjust(left=0.12, right=0.72, top=0.88, bottom=0.20)
        self.ax_raw_data_filter.set_title("Raw bacterial growth curve")
        self.ax_raw_data_filter.set_xlabel("Time [min]")
        self.ax_raw_data_filter.set_ylabel("Optical density [a.u.]")
        
        self.canvas_raw_data_filter = FigureCanvasTkAgg(self.fig_raw_data_filter, master=self.plot_frame_filter_top)
        self.canvas_widget_raw_data_filter = self.canvas_raw_data_filter.get_tk_widget()
        self.canvas_widget_raw_data_filter.grid(row=0, column=0, padx=10, pady=10, sticky="nsew")
        self._make_canvas_responsive(self.canvas_raw_data_filter, self.fig_raw_data_filter)
        
        
        self.fig_filtered_data, self.ax_filtered_data = plt.subplots(figsize=filter_figsize)
        self.fig_filtered_data.subplots_adjust(left=0.12, right=0.72, top=0.88, bottom=0.20)
        self.ax_filtered_data.set_title("Filtered growth curve")
        self.ax_filtered_data.set_xlabel("Time [min]")
        self.ax_filtered_data.set_ylabel("Optical density [a.u.]")
        
        self.canvas_filtered_data = FigureCanvasTkAgg(self.fig_filtered_data, master=self.plot_frame_filter_bottom)
        self.canvas_widget_filtered_data = self.canvas_filtered_data.get_tk_widget()
        self.canvas_widget_filtered_data.grid(row = 0, column = 0, padx=10, pady=10, sticky="nsew")
        self._make_canvas_responsive(self.canvas_filtered_data, self.fig_filtered_data)
        
        
        
        ################ PLOTS FOR THE SLOPES ##############################################################################
        
        #-------------- DERIVATIVE PLOT------------------------------------
        
        self.fig_slope_plot, self.ax_slope_plot = plt.subplots(constrained_layout=True, figsize=analysis_small_figsize)
        self.ax_slope_plot.set_title("First derivative of the growth curve")
        self.ax_slope_plot.set_xlabel("Time [min]")
        self.ax_slope_plot.set_ylabel("Speed of change of the Optical Density [1/min]")
        
        self.canvas_slope_plot = FigureCanvasTkAgg(self.fig_slope_plot, master=self.slope_frame_top)
        self.canvas_widget_slope_plot = self.canvas_slope_plot.get_tk_widget()
        self.canvas_widget_slope_plot.grid(row=1, column=2, padx=10, pady=10, sticky="nsew")
        self._make_canvas_responsive(self.canvas_slope_plot, self.fig_slope_plot, height_px=320, max_width_px=520)
        
        
        self.canvas_widget_slope_plot.bind("<Button-3>", self.show_menu_slope_plot)
        
        self.menu_slope_plot = tk.Menu(self.frame_slope, tearoff=0)
        self.menu_slope_plot.add_command(label="Save plot", command = self.save_slope_plot)
        self.menu_slope_plot.add_command(label="Set title", command = self.title_slope_plot)
        self.menu_slope_plot.add_command(label="Set x axis", command = self.xaxis_slope_plot)
        self.menu_slope_plot.add_command(label="Set y axis", command = self.yaxis_slope_plot)
        
        
        #-------------- Slope plot of replicas -----------------------------
        
        self.fig_slope_rep, self.ax_slope_rep = plt.subplots(constrained_layout=True, figsize=analysis_small_figsize)
        self.ax_slope_rep.set_title("Slope values per replica")
        
        self.canvas_slope_rep = FigureCanvasTkAgg(self.fig_slope_rep, master=self.slope_frame_bottom)
        self.canvas_widget_slope = self.canvas_slope_rep.get_tk_widget()
        self.canvas_widget_slope.grid(row=1, column=0, padx=10, pady=10, sticky="nsew")
        self._make_canvas_responsive(self.canvas_slope_rep, self.fig_slope_rep, height_px=300, max_width_px=460)
        
        self.canvas_widget_slope.bind("<Button-3>", self.show_menu_slope_rep)
        
        self.menu_slope_rep = tk.Menu(self.frame_slope, tearoff=0)
        self.menu_slope_rep.add_command(label="Change color", command = lambda: self.change_line_color())
        self.menu_slope_rep.add_command(label="Save plot", command = self.save_slope_reps)
        self.menu_slope_rep.add_command(label="Set title", command = self.title_slope_reps)
        self.menu_slope_rep.add_command(label="Set x axis", command = self.xaxis_slope_reps)
        self.menu_slope_rep.add_command(label="Set y axis", command = self.yaxis_slope_reps)
        
        
        
        
        #---------- 
        self.fig_slope_mean, self.ax_slope_mean = plt.subplots(constrained_layout=True, figsize=analysis_small_figsize)
        self.ax_slope_mean.set_title("Mean slope values")
        
        self.canvas_slope_mean = FigureCanvasTkAgg(self.fig_slope_mean, master=self.slope_frame_bottom)
        self.canvas_widget_slope_mean = self.canvas_slope_mean.get_tk_widget()
        self.canvas_widget_slope_mean.grid(row=1, column=1, padx=10, pady=10, sticky="nsew")
        self._make_canvas_responsive(self.canvas_slope_mean, self.fig_slope_mean, height_px=300, max_width_px=460)
        
        self.canvas_widget_slope_mean.bind("<Button-3>", self.show_menu_slope_mean)
        
        self.menu_slope_mean = tk.Menu(self.frame_slope, tearoff=0)
        self.menu_slope_mean.add_command(label="Save plot", command = self.save_slope_means)
        self.menu_slope_mean.add_command(label="Set title", command = self.title_slope_means)
        self.menu_slope_mean.add_command(label="Set x axis", command = self.xaxis_slope_means)
        self.menu_slope_mean.add_command(label="Set y axis", command = self.yaxis_slope_means)
        
        
        
        ################ Plots for the maximum growth ################################################################
        
        
        #---------- Plot for the Maximum growth selection -------------------------
        
        self.plot_frame_mg_top = tk.Frame(self.max_growth_frame_top)
        self.plot_frame_mg_top.grid(column = 3, row = 0, sticky = "nsew", padx = 5, pady = 5)
        self.plot_frame_mg_top.grid_columnconfigure(0, weight=1)
        self.plot_frame_mg_top.grid_rowconfigure(1, weight=1)
        
        self.fig_max_growth, self.ax_max_growth = plt.subplots(constrained_layout=True, figsize=analysis_small_figsize)
        self.ax_max_growth.set_title("Bacterial growth curve")
        self.ax_max_growth.set_ylabel("Optical Density [a.u.]")
        self.ax_max_growth.set_xlabel("Time [min]")
        
        
        self.canvas_max_growth = FigureCanvasTkAgg(self.fig_max_growth, master=self.plot_frame_mg_top)
        self.canvas_widget_max_growth = self.canvas_max_growth.get_tk_widget()
        self.canvas_widget_max_growth.grid(row=1, column=0, padx=10, pady=10, sticky="nsew")
        self._make_canvas_responsive(self.canvas_max_growth, self.fig_max_growth, height_px=320, max_width_px=520)
        
        # Toolbar sits directly above its own plot (row 0), not in the settings
        # column where it used to overlap the controls panel.
        self.toolbar_mg = NavigationToolbar2Tk(self.canvas_max_growth, self.plot_frame_mg_top, pack_toolbar=False)
        self.toolbar_mg.update()
        self.toolbar_mg.grid(row=0, column=0, sticky="nw")     
        
        
        ##----------------Selection plot for Maximum Growth --------------
        
        self.fig_max_selection, self.ax_max_selection = plt.subplots(constrained_layout=True, figsize=analysis_small_figsize)
        self.ax_max_selection.set_title("Mean maximum growth values")
        
        self.canvas_max_growth_selection = FigureCanvasTkAgg(self.fig_max_selection, master=self.max_growth_frame_bottom)
        self.canvas_widget_max_growth_selection = self.canvas_max_growth_selection.get_tk_widget()
        self.canvas_widget_max_growth_selection.grid(row=0, column=1, padx=10, pady=10, sticky="nsew")
        self._make_canvas_responsive(self.canvas_max_growth_selection, self.fig_max_selection)
        
        
        self.canvas_widget_max_growth_selection.bind("<Button-3>", self.show_menu_mg_mean)
        
        self.menu_mg_mean = tk.Menu(self.frame_slope, tearoff=0)
        self.menu_mg_mean.add_command(label="Save plot", command = self.save_mg_means)
        self.menu_mg_mean.add_command(label="Set title", command = self.title_mg_means)
        self.menu_mg_mean.add_command(label="Set x axis", command = self.xaxis_mg_means)
        self.menu_mg_mean.add_command(label="Set y axis", command = self.yaxis_mg_means)
        
        
        #-------- Plot for the maximum growth values display per replica -----------------
        
        
        self.fig_max_replica, self.ax_max_replica = plt.subplots(constrained_layout=True, figsize=analysis_small_figsize)
        self.ax_max_replica.set_title("Maximum growth values per replica")
        
        self.canvas_max_growth_replica = FigureCanvasTkAgg(self.fig_max_replica, master=self.max_growth_frame_bottom)
        self.canvas_widget_max_growth_replica = self.canvas_max_growth_replica.get_tk_widget()
        self.canvas_widget_max_growth_replica.grid(row=0, column=0, padx=10, pady=10, sticky="nsew")
        self._make_canvas_responsive(self.canvas_max_growth_replica, self.fig_max_replica)
        
        self.canvas_widget_max_growth_replica.bind("<Button-3>", self.show_menu_mg_rep)
        
        self.menu_mg_rep = tk.Menu(self.frame_slope, tearoff=0)
        self.menu_mg_rep.add_command(label="Save plot", command = self.save_mg_reps)
        self.menu_mg_rep.add_command(label="Set title", command = self.title_mg_reps)
        self.menu_mg_rep.add_command(label="Set x axis", command = self.xaxis_mg_reps)
        self.menu_mg_rep.add_command(label="Set y axis", command = self.yaxis_mg_reps)
        
        
        
        
        
        self.time_values = list(self.raw_data_dict.values())[0].iloc[0]
        self.time_indices = len(self.time_values)
        
        ##### Console for the Filter ###########################################
        # Laid out with grid so it adapts to font/DPI scaling instead of fixed
        # pixel coordinates.
        frame_filter_console.grid_columnconfigure(0, weight=0)
        frame_filter_console.grid_columnconfigure(1, weight=0)

        scale_window_label = tk.Label(frame_filter_console, text="Select window size:", font=self.sfont(12, "bold"))
        scale_window_label.grid(row=0, column=0, sticky="w", padx=5, pady=(5, 0))

        scale_window = tk.Scale(frame_filter_console, from_=1, to=100, orient="horizontal", length=160, resolution=1, command=self.scale_window)
        scale_window.grid(row=1, column=0, sticky="w", padx=5, pady=2)

        window_size_label = tk.Label(frame_filter_console, text="Window size:")
        window_size_label.grid(row=2, column=0, sticky="w", padx=5, pady=(2, 0))

        self.window_variable = tk.StringVar(value="2")
        self.window_value = tk.Entry(frame_filter_console, textvariable=self.window_variable, state="readonly", readonlybackground="white", width=10)
        self.window_value.grid(row=3, column=0, sticky="w", padx=5, pady=(0, 2))

        scale_polyorder_label = tk.Label(frame_filter_console, text="Select order of polynomial:", font=self.sfont(12, "bold"))
        scale_polyorder_label.grid(row=4, column=0, sticky="w", padx=5, pady=(10, 0))

        scale_polyorder = tk.Scale(frame_filter_console, from_=1, to=10, orient="horizontal", length=160, resolution=1, command=self.scale_polyorder_command)
        scale_polyorder.grid(row=5, column=0, sticky="w", padx=5, pady=2)

        order_of_polynomial_label = tk.Label(frame_filter_console, text="Order of polynomial:")
        order_of_polynomial_label.grid(row=6, column=0, sticky="w", padx=5, pady=(2, 0))

        self.polyorder_variable = tk.StringVar(value="1")
        self.polyorder_value = tk.Entry(frame_filter_console, textvariable=self.polyorder_variable, state="readonly", readonlybackground="white", width=10)
        self.polyorder_value.grid(row=7, column=0, sticky="w", padx=5, pady=(0, 2))

        scale_mode_label = tk.Label(frame_filter_console, text="Select mode:", font=self.sfont(12, "bold"))
        scale_mode_label.grid(row=8, column=0, sticky="w", padx=5, pady=(10, 0))

        mode_label = tk.Label(frame_filter_console, text="Mode:")
        mode_label.grid(row=9, column=0, sticky="w", padx=5, pady=(2, 0))

        filter_modes = ["interp", "mirror", "nearest", "constant", "wrap"]
        self.dropdown_filter_modes = ttk.Combobox(frame_filter_console, values=filter_modes, state="readonly", width=12)
        self.dropdown_filter_modes.grid(row=10, column=0, sticky="w", padx=5, pady=(0, 2))
        self.dropdown_filter_modes.set("interp")

        self.dropdown_filter_modes.bind("<<ComboboxSelected>>", self.select_filter_mode)

        save_filtered_data_button = ctk.CTkButton(frame_filter_console, text="Set filtered data", width=140, command=self.save_filtered_data)
        reset_raw_data_button = ctk.CTkButton(frame_filter_console, text="Reset raw data", width=140, command=self.reset_unfiltered_data)
        create_filter_tables_button = ctk.CTkButton(frame_filter_console, text="Create table", width=140, command=self.create_filter_table)

        save_filtered_data_button.grid(row=11, column=0, sticky="w", padx=5, pady=(12, 2))
        reset_raw_data_button.grid(row=12, column=0, sticky="w", padx=5, pady=2)
        create_filter_tables_button.grid(row=13, column=0, sticky="w", padx=5, pady=2)
        
        ##### Scales for the maximum growth ####################################
        
        frame_max_growth_scale = tk.Frame(self.max_growth_frame_top, borderwidth=3, relief="ridge")
        frame_max_growth_scale.grid(row=0, column=2, padx=10, pady=10, sticky = "nw")
        
        frame_max_growth_scale.grid_columnconfigure(0, weight=1)
        frame_max_growth_scale.grid_columnconfigure(1, weight=1)
        frame_max_growth_scale.grid_rowconfigure(0, weight=1)
        
        
        
        self.max_growth_button = ctk.CTkButton(frame_max_growth_scale, text = "Maximum growth\ncalculation", font=self.sfont(13))
        self.max_growth_button.configure(command=lambda: self._run_calculation(self.max_growth_button, self.calculate_max_growth, "Maximum growth calculation"))
        self.max_growth_button.grid(row = 0, column = 0, sticky = "nw", padx = 10, pady = 10)
        
        ttk.Separator(frame_max_growth_scale, orient= "horizontal").grid(row=1, column=0, columnspan=2, sticky="ew", pady=5)
        
        scale_start_label = tk.Label(frame_max_growth_scale, text="Select the beginning of the custom timeframe:", font=self.sfont(12, "bold"))
        scale_start_label.grid(row=2, column=0, pady=10, sticky="nw")
        
        scale_start = tk.Scale(frame_max_growth_scale, from_= 1, to = self.time_indices, orient="horizontal", length=300, resolution=1, command = self.on_scale_change_start)
        scale_start.grid(row=3, column=0, pady=10, sticky="n")
        
        start_time_label = tk.Label(frame_max_growth_scale, text="Start time:")
        start_time_label.grid(row=4, column=0, padx = 3, pady=10, sticky="nw")
        
        self.start_time_variable = tk.StringVar()
        self.entry_start_time = tk.Entry(frame_max_growth_scale, textvariable = self.start_time_variable, state="readonly", readonlybackground="white", width=15)
        self.entry_start_time.grid(row=4, column=0, padx = 3, pady=10, sticky="n")
        
        min_label_one = tk.Label(frame_max_growth_scale, text="min")
        min_label_one.grid(row=4, column=0, padx = 3, pady=10, sticky="ne")
        
        
        scale_end_label = tk.Label(frame_max_growth_scale, text="Select the end of the custom timeframe:", font=self.sfont(12, "bold"))
        scale_end_label.grid(row=6, column=0, pady=10, sticky="nw")
        
        
        scale_end = tk.Scale(frame_max_growth_scale, from_=1, to=self.time_indices, orient="horizontal", length=300, resolution=1, command = self.on_scale_change_end)
        scale_end.grid(row=7, column=0, pady=10, sticky="n")
        
        end_time_label = tk.Label(frame_max_growth_scale, text="End time:")
        end_time_label.grid(row=8, column=0, pady=10, sticky="nw")
        
        min_label_two = tk.Label(frame_max_growth_scale, text="min")
        min_label_two.grid(row=8, column=0, pady=10, sticky="ne")
        
        
        self.end_time_variable = tk.StringVar()
        self.entry_end_time = tk.Entry(frame_max_growth_scale, textvariable = self.end_time_variable, state="readonly", readonlybackground="white", width=15)
        self.entry_end_time.grid(row=8, column=0, pady=10, sticky="n")
        
        
        button_frame = tk.Frame(frame_max_growth_scale)
        button_frame.grid(row=9, column=0, columnspan=2, pady=10)

        local_max_growth_button = ctk.CTkButton(button_frame, text="Calculate local maximum", font=self.sfont(13), command=self.calculate_local_max_growth)
        local_max_growth_button.grid(row=0, column=0, padx=5)

        max_growth_table_button = ctk.CTkButton(button_frame, text="Create table of values", font=self.sfont(13),command=self.table_of_values_max_growth)
        max_growth_table_button.grid(row=0, column=1, padx=5)
        
        
        
        ################ Plots for the AUC ################################################################
        #-------- Curves ---------------
        
        self.fig_auc_curves, self.ax_auc_curves = plt.subplots(constrained_layout=True, figsize=analysis_small_figsize)
        self.ax_auc_curves.set_title("Bacterial growth curve")
        self.ax_auc_curves.set_ylabel("Optical density [a.u.]")
        self.ax_auc_curves.set_xlabel("Time [min]")
        
        # Wrap the AUC curve plot in a top-anchored container so it keeps a
        # sensible aspect ratio instead of being stretched into the tall, narrow
        # column cell (which clipped the title and left empty space below).
        self.plot_frame_auc_top = tk.Frame(self.auc_frame_first)
        self.plot_frame_auc_top.grid(row=0, column=3, sticky="new", padx=5, pady=5)
        self.plot_frame_auc_top.grid_columnconfigure(0, weight=1)
        self.plot_frame_auc_top.grid_rowconfigure(0, weight=1)

        self.canvas_auc_curves = FigureCanvasTkAgg(self.fig_auc_curves, master=self.plot_frame_auc_top)
        self.canvas_widget_auc_curves = self.canvas_auc_curves.get_tk_widget()
        self.canvas_widget_auc_curves.grid(row=0, column=0, padx=10, pady=10, sticky="nsew")
        self._make_canvas_responsive(self.canvas_auc_curves, self.fig_auc_curves, height_px=320, max_width_px=520)
        
        
        
        #----------- Lag replicas ----------
        
        
        self.fig_auc_replicas_lag, self.ax_auc_replicas_lag = plt.subplots(constrained_layout=True, figsize=analysis_small_figsize)
        self.ax_auc_replicas_lag.set_title("Lag phase AUC values")        
        
        self.canvas_auc_replicas_lag = FigureCanvasTkAgg(self.fig_auc_replicas_lag, master=self.auc_frame_second)
        self.canvas_widget_auc_replicas_lag = self.canvas_auc_replicas_lag.get_tk_widget()
        self.canvas_widget_auc_replicas_lag.grid(row=0, column=0, padx=10, pady=10, sticky="nsew")
        self._make_canvas_responsive(self.canvas_auc_replicas_lag, self.fig_auc_replicas_lag, height_px=300, max_width_px=440)
        
        
        self.canvas_widget_auc_replicas_lag.bind("<Button-3>", self.show_menu_auc_replicas_lag)
        
        self.menu_auc_replicas_lag = tk.Menu(self.frame_score, tearoff=0)
        self.menu_auc_replicas_lag.add_command(label="Save plot", command = self.save_auc_replicas_lag)
        self.menu_auc_replicas_lag.add_command(label="Set title", command = self.title_auc_replicas_lag)
        self.menu_auc_replicas_lag.add_command(label="Set x axis", command = self.xaxis_auc_replicas_lag)
        self.menu_auc_replicas_lag.add_command(label="Set y axis", command = self.yaxis_auc_replicas_lag)
        
        
        
        # ------------Lag means ---------------
        
        
        self.fig_auc_replicas_lag_mean, self.ax_auc_replicas_lag_mean = plt.subplots(constrained_layout=True, figsize=analysis_small_figsize)
        self.ax_auc_replicas_lag_mean.set_title("Mean lag phase AUC values")        
        
        self.canvas_auc_replicas_lag_mean = FigureCanvasTkAgg(self.fig_auc_replicas_lag_mean, master=self.auc_frame_second)
        self.canvas_widget_auc_replicas_lag_mean = self.canvas_auc_replicas_lag_mean.get_tk_widget()
        self.canvas_widget_auc_replicas_lag_mean.grid(row=0, column=1, padx=10, pady=10, sticky="nsew")
        self._make_canvas_responsive(self.canvas_auc_replicas_lag_mean, self.fig_auc_replicas_lag_mean, height_px=300, max_width_px=440)
        
        
        self.canvas_widget_auc_replicas_lag_mean.bind("<Button-3>", self.show_menu_auc_lag_mean)
        
        self.menu_auc_lag_mean = tk.Menu(self.frame_score, tearoff=0)
        self.menu_auc_lag_mean.add_command(label="Save plot", command = self.save_auc_lag_mean)
        self.menu_auc_lag_mean.add_command(label="Set title", command = self.title_auc_lag_mean)
        self.menu_auc_lag_mean.add_command(label="Set x axis", command = self.xaxis_auc_lag_mean)
        self.menu_auc_lag_mean.add_command(label="Set y axis", command = self.yaxis_auc_lag_mean)
        
        
        
        # ----------- Log replicas --------------
        
        self.fig_auc_replicas_log, self.ax_auc_replicas_log = plt.subplots(constrained_layout=True, figsize=analysis_small_figsize)
        self.ax_auc_replicas_log.set_title("Log phase AUC values")        
        
        self.canvas_auc_replicas_log = FigureCanvasTkAgg(self.fig_auc_replicas_log, master=self.auc_frame_third)
        self.canvas_widget_auc_replicas_log = self.canvas_auc_replicas_log.get_tk_widget()
        self.canvas_widget_auc_replicas_log.grid(row=0, column=0, padx=10, pady=10, sticky="nsew")
        self._make_canvas_responsive(self.canvas_auc_replicas_log, self.fig_auc_replicas_log, height_px=300, max_width_px=440)
        
        
        self.canvas_widget_auc_replicas_log.bind("<Button-3>", self.show_menu_auc_replicas_log)
        
        self.menu_auc_rep_log = tk.Menu(self.frame_score, tearoff=0)
        self.menu_auc_rep_log.add_command(label="Save plot", command = self.save_auc_rep_log)
        self.menu_auc_rep_log.add_command(label="Set title", command = self.title_auc_rep_log)
        self.menu_auc_rep_log.add_command(label="Set x axis", command = self.xaxis_auc_rep_log)
        self.menu_auc_rep_log.add_command(label="Set y axis", command = self.yaxis_auc_rep_log)
        
        # # ------- Log means ------------------
        
        self.fig_auc_replicas_log_mean, self.ax_auc_replicas_log_mean = plt.subplots(constrained_layout=True, figsize=analysis_small_figsize)
        self.ax_auc_replicas_log_mean.set_title("Mean log phase AUC values")        
        
        self.canvas_auc_replicas_log_mean = FigureCanvasTkAgg(self.fig_auc_replicas_log_mean, master=self.auc_frame_third)
        self.canvas_widget_auc_replicas_log_mean = self.canvas_auc_replicas_log_mean.get_tk_widget()
        self.canvas_widget_auc_replicas_log_mean.grid(row=0, column=1, padx=10, pady=10, sticky="nsew")
        self._make_canvas_responsive(self.canvas_auc_replicas_log_mean, self.fig_auc_replicas_log_mean, height_px=300, max_width_px=440)
        
        
        self.canvas_widget_auc_replicas_log_mean.bind("<Button-3>", self.show_menu_auc_mean_log)
        
        self.menu_auc_mean_log = tk.Menu(self.frame_score, tearoff=0)
        self.menu_auc_mean_log.add_command(label="Save plot", command = self.save_auc_mean_log)
        self.menu_auc_mean_log.add_command(label="Set title", command = self.title_auc_mean_log)
        self.menu_auc_mean_log.add_command(label="Set x axis", command = self.xaxis_auc_mean_log)
        self.menu_auc_mean_log.add_command(label="Set y axis", command = self.yaxis_auc_mean_log)
        
        # # ------ Stationary replicas -------------
        
        self.fig_auc_replicas_stat, self.ax_auc_replicas_stat = plt.subplots(constrained_layout=True, figsize=analysis_small_figsize)
        self.ax_auc_replicas_stat.set_title("Stationary phase AUC values")        
        
        self.canvas_auc_replicas_stat = FigureCanvasTkAgg(self.fig_auc_replicas_stat, master=self.auc_frame_fourth)
        self.canvas_widget_auc_replicas_stat = self.canvas_auc_replicas_stat.get_tk_widget()
        self.canvas_widget_auc_replicas_stat.grid(row=0, column=0, padx=10, pady=10, sticky="nsew")
        self._make_canvas_responsive(self.canvas_auc_replicas_stat, self.fig_auc_replicas_stat, height_px=300, max_width_px=440)
        
        self.canvas_widget_auc_replicas_stat.bind("<Button-3>", self.show_menu_auc_rep_stat)
        
        self.menu_auc_rep_stat = tk.Menu(self.frame_score, tearoff=0)
        self.menu_auc_rep_stat.add_command(label="Save plot", command = self.save_auc_rep_stat)
        self.menu_auc_rep_stat.add_command(label="Set title", command = self.title_auc_rep_stat)
        self.menu_auc_rep_stat.add_command(label="Set x axis", command = self.xaxis_auc_rep_stat)
        self.menu_auc_rep_stat.add_command(label="Set y axis", command = self.yaxis_auc_rep_stat)
        
        # # ------ Stationary means ---------------
        
        self.fig_auc_replicas_stat_mean, self.ax_auc_replicas_stat_mean = plt.subplots(constrained_layout=True, figsize=analysis_small_figsize)
        self.ax_auc_replicas_stat_mean.set_title("Stationary phase AUC values")        
        
        self.canvas_auc_replicas_stat_mean = FigureCanvasTkAgg(self.fig_auc_replicas_stat_mean, master=self.auc_frame_fourth)
        self.canvas_widget_auc_replicas_stat_mean = self.canvas_auc_replicas_stat_mean.get_tk_widget()
        self.canvas_widget_auc_replicas_stat_mean.grid(row=0, column=1, padx=10, pady=10, sticky="nsew")
        self._make_canvas_responsive(self.canvas_auc_replicas_stat_mean, self.fig_auc_replicas_stat_mean, height_px=300, max_width_px=440)
        
        self.canvas_widget_auc_replicas_stat_mean.bind("<Button-3>", self.show_menu_auc_mean_stat)
        
        self.menu_auc_mean_stat = tk.Menu(self.frame_score, tearoff=0)
        self.menu_auc_mean_stat.add_command(label="Save plot", command = self.save_auc_mean_stat)
        self.menu_auc_mean_stat.add_command(label="Set title", command = self.title_auc_mean_stat)
        self.menu_auc_mean_stat.add_command(label="Set x axis", command = self.xaxis_auc_mean_stat)
        self.menu_auc_mean_stat.add_command(label="Set y axis", command = self.yaxis_auc_mean_stat)
        
        # # ------ Death phase replicas -------------
        
        self.fig_auc_replicas_death, self.ax_auc_replicas_death = plt.subplots(constrained_layout=True, figsize=analysis_small_figsize)
        self.ax_auc_replicas_death.set_title("Death phase AUC values")        
        
        self.canvas_auc_replicas_death = FigureCanvasTkAgg(self.fig_auc_replicas_death, master=self.auc_frame_fifth)
        self.canvas_widget_auc_replicas_death = self.canvas_auc_replicas_death.get_tk_widget()
        self.canvas_widget_auc_replicas_death.grid(row=0, column=0, padx=10, pady=10, sticky="nsew")
        self._make_canvas_responsive(self.canvas_auc_replicas_death, self.fig_auc_replicas_death, height_px=300, max_width_px=440)
        
        
        self.canvas_widget_auc_replicas_death.bind("<Button-3>", self.show_menu_auc_rep_death)
        
        self.menu_auc_rep_death = tk.Menu(self.frame_score, tearoff=0)
        self.menu_auc_rep_death.add_command(label="Save plot", command = self.save_auc_rep_death)
        self.menu_auc_rep_death.add_command(label="Set title", command = self.title_auc_rep_death)
        self.menu_auc_rep_death.add_command(label="Set x axis", command = self.xaxis_auc_rep_death)
        self.menu_auc_rep_death.add_command(label="Set y axis", command = self.yaxis_auc_rep_death)
        
        # # ------ Death phase means ---------------
        
        self.fig_auc_replicas_death_mean, self.ax_auc_replicas_death_mean = plt.subplots(constrained_layout=True, figsize=analysis_small_figsize)
        self.ax_auc_replicas_death_mean.set_title("Death phase AUC values")        
        
        self.canvas_auc_replicas_death_mean = FigureCanvasTkAgg(self.fig_auc_replicas_death_mean, master=self.auc_frame_fifth)
        self.canvas_widget_auc_replicas_death_mean = self.canvas_auc_replicas_death_mean.get_tk_widget()
        self.canvas_widget_auc_replicas_death_mean.grid(row=0, column=1, padx=10, pady=10, sticky="nsew")
        self._make_canvas_responsive(self.canvas_auc_replicas_death_mean, self.fig_auc_replicas_death_mean, height_px=300, max_width_px=440)
        
        
        self.canvas_widget_auc_replicas_death_mean.bind("<Button-3>", self.show_menu_auc_mean_death)
        
        self.menu_auc_mean_death = tk.Menu(self.frame_score, tearoff=0)
        self.menu_auc_mean_death.add_command(label="Save plot", command = self.save_auc_mean_death)
        self.menu_auc_mean_death.add_command(label="Set title", command = self.title_auc_mean_death)
        self.menu_auc_mean_death.add_command(label="Set x axis", command = self.xaxis_auc_mean_death)
        self.menu_auc_mean_death.add_command(label="Set y axis", command = self.yaxis_auc_mean_death)
        
        # # -----Onset delay -------------
        
        self.fig_onset_delay, self.ax_onset_delay = plt.subplots(constrained_layout=True, figsize=analysis_small_figsize)
        self.ax_onset_delay.set_title("Onset delay values")        
        
        self.canvas_onset_delay = FigureCanvasTkAgg(self.fig_onset_delay, master=self.auc_frame_sixth)
        self.canvas_widget_onset_delay = self.canvas_onset_delay.get_tk_widget()
        self.canvas_widget_onset_delay.grid(row=0, column=0, padx=10, pady=10, sticky="nsew")
        self._make_canvas_responsive(self.canvas_onset_delay, self.fig_onset_delay)
        
        self.canvas_widget_onset_delay.bind("<Button-3>", self.show_menu_auc_onset_time)
        
        self.menu_auc_onset_time = tk.Menu(self.frame_score, tearoff=0)
        self.menu_auc_onset_time.add_command(label="Save plot", command = self.save_auc_onset_time)
        self.menu_auc_onset_time.add_command(label="Set title", command = self.title_auc_onset_time)
        self.menu_auc_onset_time.add_command(label="Set x axis", command = self.xaxis_auc_onset_time)
        self.menu_auc_onset_time.add_command(label="Set y axis", command = self.yaxis_auc_onset_time)
        
        # # ------ Exponential time ---------------
        
        self.fig_exp_time, self.ax_exp_time = plt.subplots(constrained_layout=True, figsize=analysis_small_figsize)
        self.ax_exp_time.set_title("Exponential time values")        
        
        self.canvas_exp_time = FigureCanvasTkAgg(self.fig_exp_time, master=self.auc_frame_sixth)
        self.canvas_widget_exp_time = self.canvas_exp_time.get_tk_widget()
        self.canvas_widget_exp_time.grid(row=0, column=1, padx=10, pady=10, sticky="nsew")
        self._make_canvas_responsive(self.canvas_exp_time, self.fig_exp_time)
        
        self.canvas_widget_exp_time.bind("<Button-3>", self.show_menu_auc_exp_time)
        
        self.menu_auc_exp_time = tk.Menu(self.frame_score, tearoff=0)
        self.menu_auc_exp_time.add_command(label="Save plot", command = self.save_auc_exp_time)
        self.menu_auc_exp_time.add_command(label="Set title", command = self.title_auc_exp_time)
        self.menu_auc_exp_time.add_command(label="Set x axis", command = self.xaxis_auc_exp_time)
        self.menu_auc_exp_time.add_command(label="Set y axis", command = self.yaxis_auc_exp_time)
        
        
        ############## PLOTS FOR DOUBLING TIME #############################################################
        
        #----------- Doubling Time Replicas Plot ---------------------------------------------------------------
        
        self.fig_doubling_replicas, self.ax_doubling_replicas = plt.subplots(constrained_layout=True, figsize=analysis_small_figsize)
        self.ax_doubling_replicas.set_title("Doubling time values")
        
        
        self.canvas_doubling_replicas = FigureCanvasTkAgg(self.fig_doubling_replicas, master=self.doubling_frame_top)
        self.canvas_widget_doubling_replicas = self.canvas_doubling_replicas.get_tk_widget()
        self.canvas_widget_doubling_replicas.grid(row=1, column=2, columnspan=2, padx=10, pady=10, sticky="nsew")
        self._make_canvas_responsive(self.canvas_doubling_replicas, self.fig_doubling_replicas, height_px=300, max_width_px=460)
        
        
        self.canvas_widget_doubling_replicas.bind("<Button-3>", self.show_menu_doubling_rep)
        
        self.menu_doubling_rep = tk.Menu(self.frame_score, tearoff=0)
        self.menu_doubling_rep.add_command(label="Save plot", command = self.save_doubling_reps)
        self.menu_doubling_rep.add_command(label="Set title", command = self.title_doubling_reps)
        self.menu_doubling_rep.add_command(label="Set x axis", command = self.xaxis_doubling_reps)
        self.menu_doubling_rep.add_command(label="Set y axis", command = self.yaxis_doubling_reps)
        
        
        #----------- Doubling Time Means Plot ---------------------------------------------------------------
        
        
        self.fig_doubling_means, self.ax_doubling_means = plt.subplots(constrained_layout=True, figsize=analysis_small_figsize)
        self.ax_doubling_means.set_title("Mean doubling time values")
        
        
        self.canvas_doubling_means = FigureCanvasTkAgg(self.fig_doubling_means, master=self.doubling_frame_bottom)
        self.canvas_widget_doubling_means = self.canvas_doubling_means.get_tk_widget()
        self.canvas_widget_doubling_means.grid(row=0, column=0, columnspan=4, padx=10, pady=10, sticky="nsew")
        self._make_canvas_responsive(self.canvas_doubling_means, self.fig_doubling_means, height_px=300, max_width_px=460)
        
        self.canvas_widget_doubling_means.bind("<Button-3>", self.show_menu_doubling_mean)
        
        self.menu_doubling_mean = tk.Menu(self.frame_score, tearoff=0)
        self.menu_doubling_mean.add_command(label="Save plot", command = self.save_doubling_means)
        self.menu_doubling_mean.add_command(label="Set title", command = self.title_doubling_means)
        self.menu_doubling_mean.add_command(label="Set x axis", command = self.xaxis_doubling_means)
        self.menu_doubling_mean.add_command(label="Set y axis", command = self.yaxis_doubling_means)
        
        
        
        ############ PLOTS FOR SCORE #####################################################################xx
        
        #------- Score Replicas Plot ---------------------------------------------------------------------------------
        
        self.fig_score_replicas, self.ax_score_replicas = plt.subplots(constrained_layout=True, figsize=analysis_small_figsize)
        self.ax_score_replicas.set_title("Index values per replica")
        
        
        self.canvas_score_replicas = FigureCanvasTkAgg(self.fig_score_replicas, master=self.score_frame_top)
        self.canvas_widget_score_replicas = self.canvas_score_replicas.get_tk_widget()
        self.canvas_widget_score_replicas.grid(row=1, column=2, columnspan=2, padx=10, pady=10, sticky="nsew")
        self._make_canvas_responsive(self.canvas_score_replicas, self.fig_score_replicas, height_px=300, max_width_px=460)
        
        self.canvas_widget_score_replicas.bind("<Button-3>", self.show_menu_score_rep)
        
        self.menu_score_rep = tk.Menu(self.frame_score, tearoff=0)
        self.menu_score_rep.add_command(label="Save plot", command = self.save_score_reps)
        self.menu_score_rep.add_command(label="Set title", command = self.title_score_reps)
        self.menu_score_rep.add_command(label="Set x axis", command = self.xaxis_score_reps)
        self.menu_score_rep.add_command(label="Set y axis", command = self.yaxis_score_reps)
        
        #------- Score Means Plot ---------------------------------------------------------------------------------
        
        self.fig_score_means, self.ax_score_means = plt.subplots(constrained_layout=True, figsize=analysis_small_figsize)
        self.ax_score_means.set_title("Mean Index Values")
        
        
        self.canvas_score_means = FigureCanvasTkAgg(self.fig_score_means, master=self.score_frame_bottom)
        self.canvas_widget_score_means = self.canvas_score_means.get_tk_widget()
        self.canvas_widget_score_means.grid(row=0, column=0, columnspan=4, padx=10, pady=10, sticky="nsew")
        self._make_canvas_responsive(self.canvas_score_means, self.fig_score_means, height_px=300, max_width_px=460)
        
        
        self.canvas_widget_score_means.bind("<Button-3>", self.show_menu_score_means)
        
        self.menu_score_means = tk.Menu(self.frame_score, tearoff=0)
        self.menu_score_means.add_command(label="Save plot", command = self.save_score_means)
        self.menu_score_means.add_command(label="Set title", command = self.title_score_means)
        self.menu_score_means.add_command(label="Set x axis", command = self.xaxis_score_means)
        self.menu_score_means.add_command(label="Set y axis", command = self.yaxis_score_means)
        
        
        #### Scales for the AUC ############################################################xx
        
        frame_auc_scale = tk.Frame(self.auc_frame_first, borderwidth=3, relief="ridge")
        frame_auc_scale.grid(row=0, column=2, padx=10, pady=10, sticky="nw")
        
        frame_auc_scale.grid_columnconfigure(0, weight=0)
        frame_auc_scale.grid_columnconfigure(1, weight=1)
        frame_auc_scale.grid_columnconfigure(2, weight=0)
        frame_auc_scale.grid_rowconfigure(0, weight=0)
        frame_auc_scale.grid_rowconfigure(1, weight=0)
        frame_auc_scale.grid_rowconfigure(2, weight=0)
        frame_auc_scale.grid_rowconfigure(3, weight=0)
        frame_auc_scale.grid_rowconfigure(4, weight=0)
        frame_auc_scale.grid_rowconfigure(5, weight=0)
        frame_auc_scale.grid_rowconfigure(6, weight=0)
        frame_auc_scale.grid_rowconfigure(7, weight=0)
        frame_auc_scale.grid_rowconfigure(8, weight=0)
        frame_auc_scale.grid_rowconfigure(9, weight=0)
        
        scale_first_label_auc = tk.Label(frame_auc_scale, text="Select the breakpoint between the Lag- and Log\nphase:", justify = "left", font=self.sfont(12, "bold"))
        scale_first_label_auc.grid(row=0, column=0, columnspan=3, pady=10, sticky="nw")
        
        scale_auc_one = tk.Scale(frame_auc_scale, from_=1, to=self.time_indices, orient="horizontal", length=300, resolution=1, command = self.on_scale_change_auc_one)
        scale_auc_one.grid(row=1, column=0, pady=10, sticky="nw")
        
        first_breakpoint_time_label = tk.Label(frame_auc_scale, text="1st breakpoint time:")
        first_breakpoint_time_label.grid(row=2, column=0, pady=10, sticky="nw")
        
        self.time_variable_auc_one = tk.StringVar()
        self.entry_auc_one = tk.Entry(frame_auc_scale, textvariable = self.time_variable_auc_one, state="readonly", readonlybackground="white", width=15)
        self.entry_auc_one.grid(row=2, column=1, pady=10, sticky="nw")
        
        min_label_one = tk.Label(frame_auc_scale, text="min")
        min_label_one.grid(row=2, column=2, pady=10, sticky="nw")        
        
        
        scale_second_label_auc = tk.Label(frame_auc_scale, text="Select the breakpoint between the Log- and \nStationary phase:", justify="left", font=self.sfont(12, "bold"))
        scale_second_label_auc.grid(row=3, column=0, columnspan = 3, pady=10, sticky="nw")   
        
        scale_auc_two = tk.Scale(frame_auc_scale, from_=1, to=self.time_indices, orient="horizontal", length=300, resolution=1, command = self.on_scale_change_auc_two)
        scale_auc_two.grid(row=4, column=0, pady=10, sticky="n")   
        
        second_breakpoint_time_label = tk.Label(frame_auc_scale, text="2nd breakpoint time:")
        second_breakpoint_time_label.grid(row=5, column=0, pady=10, sticky="nw")   
        
        self.time_variable_auc_two = tk.StringVar()
        self.entry_auc_two = tk.Entry(frame_auc_scale, textvariable = self.time_variable_auc_two, state="readonly", readonlybackground="white", width=15)
        self.entry_auc_two.grid(row=5, column=1, pady=10, sticky="s")
        
        min_label_two = tk.Label(frame_auc_scale, text="min")
        min_label_two.grid(row=5, column=2, pady=10, sticky="se")
        
        
        scale_third_label_auc = tk.Label(frame_auc_scale, text="Select the breakpoint between the Stationary- and\nDeath phase:", justify="left", font=self.sfont(12, "bold"))
        scale_third_label_auc.grid(row=6, column=0, columnspan = 3, pady=10, sticky="nw")
        
        scale_auc_three = tk.Scale(frame_auc_scale, from_=1, to=self.time_indices, orient="horizontal", length=300, resolution=1, command = self.on_scale_change_auc_three)
        scale_auc_three.grid(row=7, column=0, pady=10, sticky="n")
        
        # # # AUC String frame 3 -------------------------------------------------------------------
        
        
        third_breakpoint_time_label = tk.Label(frame_auc_scale, text="3rd breakpoint time:")
        third_breakpoint_time_label.grid(row=8, column=0, pady=10, sticky="nw")
        
        self.time_variable_auc_three = tk.StringVar()
        self.entry_auc_three = tk.Entry(frame_auc_scale, textvariable = self.time_variable_auc_three, state="readonly", readonlybackground="white", width=15)
        self.entry_auc_three.grid(row=8, column=1, pady=10, sticky="n")

        
        min_label_two = tk.Label(frame_auc_scale, text="min")
        min_label_two.grid(row=8, column=2, pady=10, sticky="n")
        
        # # #------------------------------------------------------------------------
        
        button_frame_auc = tk.Frame(frame_auc_scale)
        button_frame_auc.grid(row=9, column=0, columnspan=3, rowspan=2,  pady=10, padx = 10, sticky="nsew")
        
        button_frame_auc.grid_columnconfigure(0, weight = 1)
        button_frame_auc.grid_columnconfigure(1, weight = 1)
        
        
        self.calc_auc_button = ctk.CTkButton(button_frame_auc, text = "Calculate AUC", width = 40, height = 30, font=self.sfont(13))
        self.calc_auc_button.configure(command=lambda: self._run_calculation(self.calc_auc_button, self.calculate_auc, "Calculate AUC"))
        self.calc_auc_button.grid(row=0, column=0, pady=10, padx = 5, sticky="w")
        
        create_auc_table_button = ctk.CTkButton(button_frame_auc, text = "Create AUC table", width = 40, height = 30, font=self.sfont(13), command = self.create_auc_table)
        create_auc_table_button.grid(row=0, column=1, pady=10, padx = 5, sticky="w")
        
        self.toolbar_auc = NavigationToolbar2Tk(self.canvas_auc_curves, button_frame_auc, pack_toolbar=False)
        self.toolbar_auc.update()
        
        self.toolbar_auc.grid(row=1, column=0, columnspan = 3, padx= 5, sticky="ew")
        
        
        
        self.info_text_box.config(state="normal")
        self.info_text_box.insert(tk.END, "Raw data tables created successfully \n")
        self.loading_button.configure(state="normal")
        self.info_text_box.see(tk.END)
        self.info_text_box.config(state="disabled")
    
    
 
            
    def recolor_selected_columns(self, sheet):
        
        sheet_name = next((name for name, s in self.sheets.items() if s == sheet), None)
        sheet = self.sheets[sheet_name]
        df = self.raw_data_dict[sheet_name]
        selected = sheet.get_selected_columns()

        if selected:
            # Highlight the selected columns
            sheet.highlight_columns(columns=selected, bg="red", fg="black", redraw=True)

            # Use selected instead of selected_cols
            headers = sheet.headers()
            cols_to_delete = [headers[i] for i in selected]

            # Drop the selected columns from the DataFrame
            self.raw_data_dict[sheet_name] = df.drop(columns = cols_to_delete)

            # Recreate the sheet with the updated data
            sheet.refresh()
        
        
    def show_dataframe_with_column_selector(self, dataframe, parent_frame, x=10, y=10, table_width=800, table_height=200):
        self.df_full = dataframe.copy()
        self.column_vars = {}
        self.treeview_frame = parent_frame

        # Frame to hold checkboxes
        checkbox_frame = tk.Frame(parent_frame)
        checkbox_frame.place(x=x, y=y)

        # Checkboxes next to each column
        for i, col in enumerate(dataframe.columns):
            var = tk.BooleanVar(value=True)
            chk = tk.Checkbutton(checkbox_frame, text=col, variable=var, command=self.update_visible_columns)
            chk.grid(row=0, column=i, padx=2, pady=2, sticky="w")
            self.column_vars[col] = var

        # Add Treeview
        self.tree = ttk.Treeview(parent_frame, show="headings")
        self.tree.place(x=x, y=y + 40, width=table_width, height=table_height)

        # Add scrollbars
        y_scroll = tk.Scrollbar(parent_frame, orient="vertical", command=self.tree.yview)
        y_scroll.place(x=x + table_width, y=y + 40, height=table_height)

        x_scroll = tk.Scrollbar(parent_frame, orient="horizontal", command=self.tree.xview)
        x_scroll.place(x=x, y=y + 40 + table_height, width=table_width)

        self.tree.configure(yscrollcommand=y_scroll.set, xscrollcommand=x_scroll.set)

        self.update_visible_columns()
        
    def update_visible_columns(self):
        selected_cols = [col for col, var in self.column_vars.items() if var.get()]
        self.tree.delete(*self.tree.get_children())  # Clear old data

        self.tree["columns"] = selected_cols

        for col in selected_cols:
            self.tree.heading(col, text=col)
            self.tree.column(col, width=100, anchor="center")

        for _, row in self.df_full[selected_cols].iterrows():
            self.tree.insert("", "end", values=list(row))
            
            
    ################### COMMANDS FOR THE MAIN PLOT ########################################################################
    # %%
    
    def on_well_click(self, label):
    # Toggle state
        self.well_states[label] = not self.well_states[label]

        if self.well_states[label]:
            # Highlight and plot
            self.well_buttons[label].configure(fg_color=self.well_selected_color, text_color="white")

            if label in self.df_raw_data.columns:
                line, = self.ax.plot(self.df_raw_data["Time [min]"], self.df_raw_data[label], label=label)
                self.plot_lines[label] = line
            else:
                self.plot_lines[label] = None  # Nothing plotted

        else:
            # Remove highlight and plot
            self.well_buttons[label].configure(fg_color="white", text_color="black")

            line = self.plot_lines[label]
            if line:
                line.remove()
                self.plot_lines[label] = None
        
        #
        self.ax.relim()
        self.ax.autoscale_view()

        # Refresh plot
        self._legend(self.ax, where="right")
        self.canvas.draw()
    
    def show_plot_menu(self, event):
        try:
            self.plot_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.plot_menu.grab_release()
    
    def save_view_plot(self):
        
        file_path = filedialog.asksaveasfilename(defaultextension=".png", filetypes=[("PNG image", "*.png"), ("SVG image", "*.svg"), ("PDF file", "*.pdf"), ("All files", "*.*")])
        
        if file_path:
            self.fig.savefig(file_path, dpi = 500)
    
    def plot_title(self):
        self.custom_plot_title = tk.simpledialog.askstring("Plot Title", "Enter a title for the plot")
        self.ax.set_title(self.custom_plot_title)
        self.canvas.draw()
    
    def plot_x_axis_label(self):
        self.custom_x_axis = tk.simpledialog.askstring("Plot x axis", "Enter the name of the x axis")
        self.ax.set_xlabel(self.custom_x_axis)
        self.canvas.draw()
    
    def plot_y_axis_label(self):
        self.custom_y_axis = tk.simpledialog.askstring("Plot y axis", "Enter the name of the y axis")
        self.ax.set_ylabel(self.custom_y_axis)
        self.canvas.draw()
    
    
    def clear_plot(self):
        self.ax.clear()
        self.canvas.draw()
        
        # Reset based on the tracked selection state (self.well_states)
        # rather than reading the widget's current color back, since that
        # keeps the reset logic independent of how CTkButton stores/returns
        # color values internally.
        for label, is_selected in list(self.well_states.items()):
            if is_selected:
                self.well_buttons[label].configure(fg_color="white", text_color="black")
                self.plot_lines[label] = None
                self.well_states[label] = False
    
    def toggle_legend(self):
        if self.legend:
            self.legend.remove()
            self.legend = None
            self.plot_menu.entryconfig(self.legend_menu_index, label="Show Legend")
        else:
            self.legend = self._legend(self.ax, where="right")
            self.plot_menu.entryconfig(self.legend_menu_index, label="Hide Legend")
        self.canvas.draw()
    
    # %%
    ################### COMMANDS FOR THE RAW DATA TAB #################################################################
    
    def reset_original_data(self, sheet):
        
        columns = list(range(sheet.total_columns()))
        sheet_name = next((name for name, s in self.sheets.items() if s == sheet), None)
        self.raw_data_dict[sheet_name] = self.original_raw_data_dict[sheet_name]
        sheet.highlight_columns(columns=columns, bg = "white", fg="black", redraw=True)
        
        return
    
    def plot_the_respective_triplicate(self, sheet):
        
        sheet_name = next((name for name, s in self.sheets.items() if s == sheet), None)
        sheet = self.sheets[sheet_name]
        df = self.raw_data_dict[sheet_name]
        
        #Here comes a dictionary containing the colors of the plots
        
        
        
        number_of_replicates_temp = len(df)
        
        try:
            #self.int_list_rgb
            if len(self.int_list_rgb) < number_of_replicates_temp:
                for i in np.arange(1, number_of_replicates_temp, 1):
                    self.ax.plot(df.loc["Time [min]"], df.iloc[i], label = sheet_name + ", " + "Well:" + df.index[i], color = self.int_list_rgb[i-1])
        except:
            for i in np.arange(1, number_of_replicates_temp, 1):
                self.ax.plot(df.loc["Time [min]"], df.iloc[i], label = sheet_name + ", " + "Well:" + df.index[i])
        
        self.ax.relim()
        self.ax.autoscale_view()

        # Refresh plot
        self._legend(self.ax, where="right")
        self.canvas.draw()
    
    def add_custom_colors(self, event):
                    
        split_according_to_plot = []
        split_list_rgb = []
        self.int_list_rgb = []
        self.custom_color_rgb = tk.simpledialog.askstring("Input", "Enter the RGB values:")
        split_according_to_plot.append(self.custom_color_rgb.split("/"))
        for i in np.arange(0, len(split_according_to_plot[0]), 1):
            temp = split_according_to_plot[0][i]
            temp_list=temp.split(",")
            self.int_list_rgb.append([float(int(temp_list[j])/255) for j in range(3)])
    
    # %%
    ################### COMMANDS FOR THE FILTER TAB ####################################################################
    def scale_window(self, val):
        self.window_variable.set(int(val))      

        self.ax_filtered_data.clear()
        for sheet_name in self.filtered_data_display_dict:
            plots_list = []
            for i in np.arange(1, len(self.raw_data_for_filtering_dict[sheet_name]), 1):
                plots = self.ax_filtered_data.plot(
                    self.raw_data_for_filtering_dict[sheet_name].iloc[0],
                    self._apply_savgol(self.raw_data_for_filtering_dict[sheet_name].iloc[i]),
                    label = sheet_name + " Well: " + self.raw_data_for_filtering_dict[sheet_name].index[i].split(" ")[0])
                plots_list.extend(plots)
                self.filtered_data_display_dict[sheet_name] = plots_list
                
                
        self._legend(self.ax_filtered_data, where="right")
        self.ax_filtered_data.relim()
        self.ax_filtered_data.autoscale_view()
        self.canvas_filtered_data.draw()
        return
    
    def scale_polyorder_command(self, val):
        self.polyorder_variable.set(int(val))      

        self.ax_filtered_data.clear()
        for sheet_name in self.filtered_data_display_dict:
            plots_list = []
            for i in np.arange(1, len(self.raw_data_for_filtering_dict[sheet_name]), 1):
                plots = self.ax_filtered_data.plot(
                    self.raw_data_for_filtering_dict[sheet_name].iloc[0],
                    self._apply_savgol(self.raw_data_for_filtering_dict[sheet_name].iloc[i]),
                    label = sheet_name + " Well: " + self.raw_data_for_filtering_dict[sheet_name].index[i].split(" ")[0])
                plots_list.extend(plots)
            self.filtered_data_display_dict[sheet_name] = plots_list
                
            
        self.ax_filtered_data.set_title("Filtered growth curve")
        self.ax_filtered_data.set_ylabel("Optical density [a.u.]")
        self.ax_filtered_data.set_xlabel("Time [min]")
            
        self._legend(self.ax_filtered_data, where="right")
        self.ax_filtered_data.relim()
        self.ax_filtered_data.autoscale_view()
        self.canvas_filtered_data.draw()
        
        return
    
    def window_text(self):
        
        return
    
    def plot_raw_data_for_filtering(self, sheet, sheet_name):
        is_on = self.switch_vars_filter[sheet_name].get()
        # Clear previous bars for this sample if they exist
        if sheet_name in self.raw_data_filter_display_dict:
            for plots in self.raw_data_filter_display_dict[sheet_name]:
                plots.remove()
            del self.raw_data_filter_display_dict[sheet_name]
        # If switch is ON, plot and store the bars
        if is_on:
            plots_list = []
            for i in np.arange(1, len(self.raw_data_for_filtering_dict[sheet_name]), 1):
                plots = self.ax_raw_data_filter.plot(
                    self.raw_data_for_filtering_dict[sheet_name].iloc[0],
                    self.raw_data_for_filtering_dict[sheet_name].iloc[i],
                    label = sheet_name + " Well: " + self.raw_data_for_filtering_dict[sheet_name].index[i].split(" ")[0])
                plots_list.extend(plots)
            self.raw_data_filter_display_dict[sheet_name] = plots_list
            
            
        if sheet_name in self.filtered_data_display_dict:
            for plots in self.filtered_data_display_dict[sheet_name]:
                plots.remove()
            del self.filtered_data_display_dict[sheet_name]
        # If switch is ON, plot and store the bars
        if is_on:
            plots_list = []
            for i in np.arange(1, len(self.raw_data_for_filtering_dict[sheet_name]), 1):
                plots = self.ax_filtered_data.plot(
                    self.raw_data_for_filtering_dict[sheet_name].iloc[0],
                    self._apply_savgol(self.raw_data_for_filtering_dict[sheet_name].iloc[i]),
                    label = sheet_name + " Well: " + self.raw_data_for_filtering_dict[sheet_name].index[i].split(" ")[0])
                plots_list.extend(plots)
            self.filtered_data_display_dict[sheet_name] = plots_list
            
            
        
        self._legend(self.ax_raw_data_filter, where="right")
        self.ax_raw_data_filter.relim()
        self.ax_raw_data_filter.autoscale_view()
        self.canvas_raw_data_filter.draw()
        
        
        self.ax_filtered_data.set_title("Filtered growth curve")
        self.ax_filtered_data.set_ylabel("Optical density [a.u.]")
        self.ax_filtered_data.set_xlabel("Time [min]")
        
        self._legend(self.ax_filtered_data, where="right")
        self.ax_filtered_data.relim()
        self.ax_filtered_data.autoscale_view()
        self.canvas_filtered_data.draw()
        
        
        return
    
    def save_filtered_data(self):
        for sheet_name in self.filtered_data_display_dict:
            for i in np.arange(1, len(self.raw_data_dict[sheet_name]), 1):
                self.raw_data_dict[sheet_name].iloc[i] = self._apply_savgol(self.raw_data_for_filtering_dict[sheet_name].iloc[i])
            self.filter_parameters[sheet_name] = [self.window_variable.get(), self.polyorder_variable.get(), self.dropdown_filter_modes.get()]
        return
    
    def reset_unfiltered_data(self):
        for sheet_name in self.filtered_data_display_dict:
            for i in np.arange(1, len(self.raw_data_dict[sheet_name]), 1):
                self.raw_data_dict[sheet_name].iloc[i] = self.raw_data_for_filtering_dict[sheet_name].iloc[i]
        
        return
    
    def select_filter_mode(self, event):
        self.ax_filtered_data.clear()
        for sheet_name in self.filtered_data_display_dict:
            plots_list = []
            for i in np.arange(1, len(self.raw_data_for_filtering_dict[sheet_name]), 1):
                plots = self.ax_filtered_data.plot(
                    self.raw_data_for_filtering_dict[sheet_name].iloc[0],
                    self._apply_savgol(self.raw_data_for_filtering_dict[sheet_name].iloc[i]),
                    label = sheet_name + " Well: " + self.raw_data_for_filtering_dict[sheet_name].index[i].split(" ")[0])
                plots_list.extend(plots)
            self.filtered_data_display_dict[sheet_name] = plots_list
            
            
        
        self.ax_filtered_data.set_title("Filtered growth curve")
        self.ax_filtered_data.set_ylabel("Optical density [a.u.]")
        self.ax_filtered_data.set_xlabel("Time [min]")
        
                    
        self._legend(self.ax_filtered_data, where="right")
        self.ax_filtered_data.relim()
        self.ax_filtered_data.autoscale_view()
        self.canvas_filtered_data.draw()
        return
    
    def create_filter_table(self):
        for widget in self.scrollable_tab_filter_table.winfo_children():
            widget.destroy()
        
        self.frame_filter_tables = tk.Frame(self.scrollable_tab_filter_table)
        self.frame_filter_tables.pack(padx=8, pady=10, fill = "x", expand = True)
        
        left_column = tk.Frame(self.frame_filter_tables)
        left_column.pack(fill="x", pady=5, side = "left")
        
        right_column = tk.Frame(self.frame_filter_tables)
        right_column.pack(fill = "x", pady = 5, side = "top")
        
        for idx, (sheet_name, df) in enumerate(self.raw_data_dict.items()):
            frame = tk.Frame(left_column)
            frame.pack(padx=8, pady=10)
            

            label = tk.Label(frame, text=sheet_name + " - " + self.sample_medium_dict[sheet_name], font=self.sfont(12, "bold"))
            label.pack(anchor="w")

            # Create tksheet
            sheet = tksheet.Sheet(frame, data=df.values.tolist(), headers=list(df.columns), row_index=df.index.tolist(), height = self.table_height, width = self.table_width)
            sheet.pack(padx=5, pady=10, fill="x", expand=True)
            

            sheet.enable_bindings((
                "single_select", "column_select", "edit_cell", "arrowkeys", "ctrl_z", "ctrl_y", "column_width_resize",
                    "double_click_column_resize",
                    "row_height_resize",
                    "double_click_row_resize", 
            ))
            
            if sheet_name in self.filter_parameters:
                label_parameters = tk.Label(frame, text="Parameters: " + sheet_name + " - " + self.sample_medium_dict[sheet_name], font=self.sfont(12, "bold"))
                label_parameters.pack(anchor="w")
            
                sheet_parameters = tksheet.Sheet(frame, data=[self.filter_parameters[sheet_name]], headers = ["Window size", "Polynomoal order", "Mode"], height = 80, width = self.table_width)
                sheet_parameters.pack(padx=5, pady=10, fill="x", expand=True)
        
            
        save_button = ctk.CTkButton(right_column, text = "Save to .csv", width = 40, height = 30, command = self.filter_to_csv)
        save_button.pack(padx = 10, pady = 20, anchor = "nw")
        
        
        return
    
    def filter_to_csv(self):
        file_path = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV files", "*.csv"), ("All files", "*.*")], title="Save as")

        f = open(file_path, "a", newline="", encoding="utf-8")
        w = csv.writer(f)
        
        
        now = datetime.now()
        
        w.writerow([f"File creation: {now}"])
        
        w.writerow(["Bacteria names", "Well numbers", "Growth values"])
        
        for sheet_name in self.raw_data_dict:
            for i in np.arange(1, len(self.raw_data_dict[sheet_name]), 1):
                w.writerow([sheet_name, self.raw_data_dict[sheet_name].index.tolist()[i], self.raw_data_dict[sheet_name].iloc[i].tolist()])
                f.flush()
                
        w.writerow(["Bacteria names", "Filter window", "Order of polynomila", "Mode"])
        for sheet_name in self.filter_parameters:
            w.writerow([sheet_name, self.filter_parameters[sheet_name]])
        f.close()
        
        return
    
    
    # %%
    
    # %%
    ################### COMMANDS FOR THE REPLICATE SLOPE PLOT #############################################################
    #%%
    def show_menu_slope_plot(self, event):
        self.menu_slope_plot.post(event.x_root, event.y_root)
        
    def title_slope_plot(self):
        custom_slopes_plot_title = tk.simpledialog.askstring("Plot Title", "Enter a title:")
        self.ax_slope_plot.set_title(custom_slopes_plot_title)
        self.canvas_slope_plot.draw()
        
    def title_slope_plot(self):
        custom_slopes_rep_title = tk.simpledialog.askstring("Plot Title", "Enter a title:")
        self.ax_slope_plot.set_title(custom_slopes_rep_title)
        self.canvas_slope_plot.draw()
        
    def xaxis_slope_plot(self):
        custom_slopes_rep_xaxis = tk.simpledialog.askstring("Plot x axis", "Enter the name of the x axis:")
        self.ax_slope_plot.set_xlabel(custom_slopes_rep_xaxis)
        self.canvas_slope_plot.draw()
        return
    
    def yaxis_slope_plot(self):
        custom_slopes_rep_yaxis = tk.simpledialog.askstring("Plot x axis", "Enter the name of the y axis:")
        self.ax_slope_plot.set_ylabel(custom_slopes_rep_yaxis)
        self.canvas_slope_plot.draw()
        return
    
    def save_slope_plot(self):
        file_path = filedialog.asksaveasfilename(defaultextension=".png", filetypes=[("PNG image", "*.png"), ("SVG image", "*.svg"), ("PDF file", "*.pdf"), ("All files", "*.*")])
        
        if file_path:
            self.fig_slope_plot.savefig(file_path, dpi = 500)
        return  
    
    
    
    
    def show_menu_slope_rep(self, event):
        self.menu_slope_rep.post(event.x_root, event.y_root)
    
    def show_menu_slope_mean(self, event):
        self.menu_slope_mean.post(event.x_root, event.y_root)
        return
    
    def calculate_slopes(self):
        self.max_slope_values_dictionary = {}
        self.max_slope_index_dictionary = {}
        self.first_derivative_dictionary = {}
        
        
        
        for sheet_name, df in self.raw_data_dict.items():
            max_slopes = []
            first_derivatives_temp = []
            time_temp = df.iloc[0]
            
            for i in np.arange(1, len(df)-1, 1):
                df_slope = np.gradient(df.iloc[i], time_temp)
                first_derivatives_temp.append(df_slope)    
                max_slopes.append(max(df_slope))
            max_slopes.append(np.mean(max_slopes))
            self.max_slope_index_dictionary[sheet_name] = df.index[1:]
            self.max_slope_values_dictionary[sheet_name] = max_slopes
            self.first_derivative_dictionary[sheet_name] = first_derivatives_temp
            
        
        for widget in self.scrollable_slope_values.winfo_children():
            widget.destroy()
            
        self.frame_slope_tables = tk.Frame(self.scrollable_slope_values)
        self.frame_slope_tables.pack(padx=8, pady=10, fill = "x", expand = True)
        
        left_column = tk.Frame(self.frame_slope_tables)
        left_column.pack(fill="x", pady=5, side = "left")
        
        right_column = tk.Frame(self.frame_slope_tables)
        right_column.pack(fill = "x", pady = 5, side = "top")
        
        for sheet_name in self.max_slope_values_dictionary:
            frame = tk.Frame(left_column, width=400, height=80)
            frame.pack(padx=10, pady=5, anchor = "w")
            
            label = tk.Label(frame, text = sheet_name, font=self.sfont(12, "bold"))
            label.pack(padx = 5, pady = 5, anchor = "w")
            
            data = list(zip(self.max_slope_index_dictionary[sheet_name], self.max_slope_values_dictionary[sheet_name]))
            
            sheet = tksheet.Sheet(frame, data = data, headers = ["Well numbers", "Max Slope Values"], height = 150, width = 500)
            sheet.pack(padx=5, pady=5, expand=False)
        
            sheet.enable_bindings((
                     "single_select", "column_select", "edit_cell", "arrowkeys", "row_select", "ctrl_z", "ctrl_y"
                 ))
            
        save_button = ctk.CTkButton(right_column, text = "Save to .csv", width = 40, height = 30, command = self.slopes_to_csv)
        save_button.pack(padx = 5, pady = 10, anchor = "nw")
        
                    
        return
    
    def plot_replicate_slopes(self, sheet, sheet_name):
        if not self._require_calc("first_derivative_dictionary", "Calculate slopes",
                                  self.switch_vars.get(sheet_name)):
            return
        is_on = self.switch_vars[sheet_name].get()
        
        if sheet_name in self.derivatives_display:
            for plots in self.derivatives_display[sheet_name]:
                plots.remove()
            del self.derivatives_display[sheet_name]
        if is_on:
            plots_list = []
            for i in np.arange(0, len(self.first_derivative_dictionary[sheet_name]), 1):
                plots = self.ax_slope_plot.plot(
                    self.raw_data_dict[sheet_name].iloc[0],
                    self.first_derivative_dictionary[sheet_name][i],
                    label=sheet_name)
                plots_list.extend(plots)
            self.derivatives_display[sheet_name] = plots_list
        
        self.replicate_bars = {}

        # Clear previous bars for this sample if they exist
        if sheet_name in self.sheet_names_slope_rep:
            self.sheet_names_slope_rep.remove(sheet_name)
            self.ax_slope_rep.clear()
            temp_length = -1
            for sheet_name in self.sheet_names_slope_rep:
                length = len(self.max_slope_index_dictionary[sheet_name])
                temp_length = temp_length + length
                bars = self.ax_slope_rep.bar(self.max_slope_index_dictionary[sheet_name],
                self.max_slope_values_dictionary[sheet_name],
                label=sheet_name + ': CV='+ str(round(np.std(self.max_slope_values_dictionary[sheet_name][0:-1])/self.max_slope_values_dictionary[sheet_name][-1]*100, 2)) + "%", width = 0.5
            )
                temp_scatter = self.max_slope_values_dictionary[sheet_name][0:]
                self.ax_slope_rep.scatter([temp_length] * len(self.max_slope_index_dictionary[sheet_name]), temp_scatter, color = "black", s = 10, zorder = 3)
                self.replicate_bars[sheet_name] = bars
            
                
        else:
            self.sheet_names_slope_rep.append(sheet_name)
            
        
        # If switch is ON, plot and store the bars
        if is_on:
            self.ax_slope_rep.clear()
            temp_length = -1
            for sheet_name in self.sheet_names_slope_rep:
                length = len(self.max_slope_index_dictionary[sheet_name])
                temp_length = temp_length + length
                bars = self.ax_slope_rep.bar(self.max_slope_index_dictionary[sheet_name],
                self.max_slope_values_dictionary[sheet_name],
                label=sheet_name + ': CV='+ str(round(np.std(self.max_slope_values_dictionary[sheet_name][0:-1])/self.max_slope_values_dictionary[sheet_name][-1]*100, 2)) + "%", width = 0.5
            )
                temp_scatter = self.max_slope_values_dictionary[sheet_name][0:]
                self.ax_slope_rep.scatter([temp_length] * len(self.max_slope_index_dictionary[sheet_name]), temp_scatter, color = "black", s = 10, zorder = 3)
                self.replicate_bars[sheet_name] = bars
            
            
            
        self.ax_slope_rep.set_title("Maximum slope values")
        self.ax_slope_rep.set_ylabel("Maximum slope values [1/s]")
        self.ax_slope_rep.set_xlabel("Sample names")
        self.ax_slope_rep.tick_params(axis='x', rotation=90)
        self._legend(self.ax_slope_rep, where="right")


        self.ax_slope_rep.relim()
        self.ax_slope_rep.autoscale_view()
        self.canvas_slope_rep.draw()
        
        self.ax_slope_plot.relim()
        self.ax_slope_plot.autoscale_view()
        self.canvas_slope_plot.draw()
    
    def slopes_to_csv(self):
        file_path = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV files", "*.csv"), ("All files", "*.*")], title="Save as")

        f = open(file_path, "a", newline="", encoding="utf-8")
        w = csv.writer(f)
        
        
        now = datetime.now()
        
        w.writerow([f"File creation: {now}"])
        
        w.writerow(["Bacteria names", "Well numbers", "Maximum Slope Values"])
        for sheet_name in self.max_slope_values_dictionary:
            for i in np.arange(0, len(self.max_slope_values_dictionary[sheet_name]), 1):
                w.writerow([sheet_name, self.max_slope_index_dictionary[sheet_name][i], self.max_slope_values_dictionary[sheet_name][i]])
                f.flush()
        f.close()
        
        return
    
    def title_slope_reps(self):
        custom_slopes_rep_title = tk.simpledialog.askstring("Plot Title", "Enter a title:")
        self.ax_slope_rep.set_title(custom_slopes_rep_title)
        self.canvas_slope_rep.draw()
        
    def xaxis_slope_reps(self):
        custom_slopes_rep_xaxis = tk.simpledialog.askstring("Plot x axis", "Enter the name of the x axis:")
        self.ax_slope_rep.set_xlabel(custom_slopes_rep_xaxis)
        self.canvas_slope_rep.draw()
        return
    
    def yaxis_slope_reps(self):
        custom_slopes_rep_yaxis = tk.simpledialog.askstring("Plot x axis", "Enter the name of the y axis:")
        self.ax_slope_rep.set_ylabel(custom_slopes_rep_yaxis)
        self.canvas_slope_rep.draw()
        return
    
    def save_slope_reps(self):
        file_path = filedialog.asksaveasfilename(defaultextension=".png", filetypes=[("PNG image", "*.png"), ("SVG image", "*.svg"), ("PDF file", "*.pdf"), ("All files", "*.*")])
        
        if file_path:
            self.fig_slope_rep.savefig(file_path, dpi = 500)
        return  
    
    def change_line_color(self):
        
        iteration = 0
        
        split_according_to_plot = []
        #split_list_rgb = []
        self.int_list_rgb_slope_rep = []
        self.custom_color_slope_rep = tk.simpledialog.askstring("Input", "Enter the RGB values:")
        split_according_to_plot.extend(self.custom_color_slope_rep.split("/"))
        for i in np.arange(0, len(split_according_to_plot), 1):
            temp = split_according_to_plot[i]
            temp_list=temp.split(",")
            self.int_list_rgb_slope_rep.append([float(int(temp_list[j])/255) for j in range(3)])
        
        
        for keys, values in self.replicate_bars.items():
            for bars in values:
                bars.set_facecolor(self.int_list_rgb_slope_rep[iteration])
                self.canvas_slope_rep.draw()
                self.ax_slope_rep.legend([bars[0] for name, bars in self.replicate_bars.items()],
            [name for name in self.replicate_bars], loc="upper left", bbox_to_anchor=(1.02, 1.0), ncol=(1 if len(self.replicate_bars) <= 16 else 2), fontsize=max(5.0, self.plot_font_base*(0.9 if len(self.replicate_bars)>6 else 1.0)), borderaxespad=0.0, frameon=True)
            iteration = iteration + 1
    
    def title_slope_means(self):
        custom_slopes_mean_title = tk.simpledialog.askstring("Plot Title", "Enter a title:")
        self.ax_slope_mean.set_title(custom_slopes_mean_title)
        self.canvas_slope_mean.draw()
        
    def xaxis_slope_means(self):
        custom_slopes_mean_xaxis = tk.simpledialog.askstring("Plot x axis", "Enter the name of the x axis:")
        self.ax_slope_mean.set_xlabel(custom_slopes_mean_xaxis)
        self.canvas_slope_mean.draw()
        return
    
    def yaxis_slope_means(self):
        custom_slopes_mean_yaxis = tk.simpledialog.askstring("Plot x axis", "Enter the name of the y axis:")
        self.ax_slope_mean.set_ylabel(custom_slopes_mean_yaxis)
        self.canvas_slope_mean.draw()
        return
    
    def save_slope_means(self):
        file_path = filedialog.asksaveasfilename(defaultextension=".png", filetypes=[("PNG image", "*.png"), ("SVG image", "*.svg"), ("PDF file", "*.pdf"), ("All files", "*.*")])
        
        if file_path:
            self.fig_slope_mean.savefig(file_path, dpi = 500)
        return   
    
    
    # %%
    ##################### COMMANDS FOR PLOTTING THE SLOPE MEANS #######################################################
    # %%
    
    def plot_means(self, sheet, sheet_name):
        if not self._require_calc("first_derivative_dictionary", "Calculate slopes", self.switch_vars_mean.get(sheet_name)):
            return
        is_on = self.switch_vars_mean[sheet_name].get()
        
        self.replicate_slope_mean_bars = {}

        # Clear previous bars for this sample if they exist
        if sheet_name in self.sheet_names_slope_means:
            self.sheet_names_slope_means.remove(sheet_name)
            self.ax_slope_mean.clear()
            for sheet_name in self.sheet_names_slope_means:
                bars = self.ax_slope_mean.bar(
                    self.max_slope_index_dictionary[sheet_name][-1],
                    self.max_slope_values_dictionary[sheet_name][-1],
                    label=sheet_name, width = 0.5
                )
                self.replicate_bars_mean[sheet_name] = bars
        else:
            self.sheet_names_slope_means.append(sheet_name)
            

        # If switch is ON, plot and store the bars
        if is_on:
            self.ax_slope_mean.clear()
            for sheet_name in self.sheet_names_slope_means:
                bars = self.ax_slope_mean.bar(
                    self.max_slope_index_dictionary[sheet_name][-1],
                    self.max_slope_values_dictionary[sheet_name][-1],
                    label=sheet_name, width = 0.5
                )
                self.replicate_bars_mean[sheet_name] = bars
            self.replicate_bars_mean[sheet_name] = bars
            
            
        self.ax_slope_mean.set_title("Mean slope values")
        self.ax_slope_mean.set_ylabel("Mean slope values [1/s]")
        self.ax_slope_mean.set_xlabel("Sample names")
        self.ax_slope_mean.tick_params(axis='x', rotation=90)
        self._legend(self.ax_slope_mean, where="right")
        

        self.ax_slope_mean.relim()
        self.ax_slope_mean.autoscale_view()
        self.canvas_slope_mean.draw()
        return


    # %%
    #################### COMMANDS FOR PLOTTING THE AUC PLOTS ##########################################################
    # %%
    
    def plot_auc_curves(self, sheet, sheet_name):
        is_on = self.switch_vars_auc[sheet_name].get()
        # Clear previous bars for this sample if they exist
        
        
        if sheet_name in self.auc_display_dict:
            for plots in self.auc_display_dict[sheet_name]:
                plots.remove()
            del self.auc_display_dict[sheet_name]
        # If switch is ON, plot and store the bars
        if is_on:
            plots_list = []
            for i in np.arange(1, len(self.raw_data_dict[sheet_name]), 1):
                plots = self.ax_auc_curves.plot(
                    self.raw_data_dict[sheet_name].iloc[0],
                    self.raw_data_dict[sheet_name].iloc[i],
                    label=sheet_name)
                plots_list.extend(plots)
            self.auc_display_dict[sheet_name] = plots_list
          
        
        
        self.ax_auc_replicas_lag.clear()
        self.ax_auc_replicas_log.clear()
        self.ax_auc_replicas_stat.clear()
        self.ax_auc_replicas_death.clear()
        if sheet_name in self.auc_dictionary:
            temp_length = - 1
            for sheet_name in self.auc_display_dict:
                length = len(self.auc_index_dictionary[sheet_name])
                temp_length = temp_length + length
                bars = self.ax_auc_replicas_lag.bar(self.auc_index_dictionary[sheet_name],
                                                        self.auc_dictionary_lag[sheet_name],
                                                        label=sheet_name + ': CV='+ str(round(np.std(self.auc_dictionary_lag[sheet_name][0:-1])/self.auc_dictionary_lag[sheet_name][-1]*100, 2)) + "%", width = 0.5
                                                        )
                temp_scatter = self.auc_dictionary_lag[sheet_name][0:]
                self.ax_auc_replicas_lag.scatter([temp_length] * len(self.auc_index_dictionary[sheet_name]), temp_scatter, color = "black", s = 10, zorder = 3)
                
                ##### Plotting the Log AUCs -------------
                
                bars = self.ax_auc_replicas_log.bar(self.auc_index_dictionary[sheet_name],
                self.auc_dictionary_log[sheet_name],
                label=sheet_name + ': CV='+ str(round(np.std(self.auc_dictionary_log[sheet_name][0:-1])/self.auc_dictionary_log[sheet_name][-1]*100, 2)) + "%", width = 0.5
                )
                temp_scatter = self.auc_dictionary_log[sheet_name][0:]
                self.ax_auc_replicas_log.scatter([temp_length] * len(self.auc_index_dictionary[sheet_name]), temp_scatter, color = "black", s = 10, zorder = 3)
                
                #### Plotting the Stationary AUCs ------
                
                bars = self.ax_auc_replicas_stat.bar(self.auc_index_dictionary[sheet_name],
                self.auc_dictionary_stationary[sheet_name],
                label=sheet_name + ': CV='+ str(round(np.std(self.auc_dictionary_stationary[sheet_name][0:-1])/self.auc_dictionary_stationary[sheet_name][-1]*100, 2)) + "%", width = 0.5
                )
                temp_scatter = self.auc_dictionary_stationary[sheet_name][0:]
                self.ax_auc_replicas_stat.scatter([temp_length] * len(self.auc_index_dictionary[sheet_name]), temp_scatter, color = "black", s = 10, zorder = 3)
                
                #### Plotting the Death Phase AUCs ------
                
                bars = self.ax_auc_replicas_death.bar(self.auc_index_dictionary[sheet_name],
                self.auc_dictionary_death[sheet_name],
                label=sheet_name + ': CV='+ str(round(np.std(self.auc_dictionary_death[sheet_name][0:-1])/self.auc_dictionary_death[sheet_name][-1]*100, 2)) + "%", width = 0.5
                )
                temp_scatter = self.auc_dictionary_death[sheet_name][0:]
                self.ax_auc_replicas_death.scatter([temp_length] * len(self.auc_index_dictionary[sheet_name]), temp_scatter, color = "black", s = 10, zorder = 3)
            
               

        self.ax_auc_curves.relim()
        self.ax_auc_curves.autoscale_view()
        self.canvas_auc_curves.draw()
        
        
        
        self.ax_auc_replicas_lag.set_title("Lag phase AUC values")
        self.ax_auc_replicas_lag.set_ylabel("Lag Phase AUC values [min]")
        self.ax_auc_replicas_lag.set_xlabel("Sample names")
        self.ax_auc_replicas_lag.tick_params(axis='x', rotation=90)
        self._legend(self.ax_auc_replicas_lag, where="right")
        
        
        self.ax_auc_replicas_log.set_title("Log phase AUC values")
        self.ax_auc_replicas_log.set_ylabel("Log Phase AUC values [min]")
        self.ax_auc_replicas_log.set_xlabel("Sample names")
        self.ax_auc_replicas_log.tick_params(axis='x', rotation=90)
        self._legend(self.ax_auc_replicas_log, where="right")
        
        self.ax_auc_replicas_stat.set_title("Stationary phase AUC values")
        self.ax_auc_replicas_stat.set_ylabel("Stationary Phase AUC values [min]")
        self.ax_auc_replicas_stat.set_xlabel("Sample names")
        self.ax_auc_replicas_stat.tick_params(axis='x', rotation=90)
        self._legend(self.ax_auc_replicas_stat, where="right")
        
        self.ax_auc_replicas_death.set_title("Death phase AUC values")
        self.ax_auc_replicas_death.set_ylabel("Death Phase AUC values [min]")
        self.ax_auc_replicas_death.set_xlabel("Sample names")
        self.ax_auc_replicas_death.tick_params(axis='x', rotation=90)
        self._legend(self.ax_auc_replicas_death, where="right")
        
        
        self.ax_auc_replicas_lag.relim()
        self.ax_auc_replicas_lag.autoscale_view()
        self.canvas_auc_replicas_lag.draw()
        
        self.ax_auc_replicas_log.relim()
        self.ax_auc_replicas_log.autoscale_view()
        self.canvas_auc_replicas_log.draw()
        
        self.ax_auc_replicas_stat.relim()
        self.ax_auc_replicas_stat.autoscale_view()
        self.canvas_auc_replicas_stat.draw()
        
        self.ax_auc_replicas_death.relim()
        self.ax_auc_replicas_death.autoscale_view()
        self.canvas_auc_replicas_death.draw()
        
        
        
        
        return
    
    def on_scale_change_auc_one(self, val):
        self.time_variable_auc_one.set(self.time_values.tolist()[int(val)-1])      
        if self.max_vline_auc_one:
            self.max_vline_auc_one.remove()
        self.max_vline_auc_one = self.ax_auc_curves.axvline(x = self.time_values.tolist()[int(val)-1], color='green', linestyle='-', linewidth=1)
        self.canvas_auc_curves.draw()
    
    def on_scale_change_auc_two(self, val):
        self.time_variable_auc_two.set(self.time_values.tolist()[int(val)-1])      
        if self.max_vline_auc_two:
            self.max_vline_auc_two.remove()
        self.max_vline_auc_two = self.ax_auc_curves.axvline(x = self.time_values.tolist()[int(val)-1], color='blue', linestyle='-', linewidth=1)
        self.canvas_auc_curves.draw()
    
    def on_scale_change_auc_three(self, val):
        self.time_variable_auc_three.set(self.time_values.tolist()[int(val)-1])      
        if self.max_vline_auc_three:
            self.max_vline_auc_three.remove()
        self.max_vline_auc_three = self.ax_auc_curves.axvline(x = self.time_values.tolist()[int(val)-1], color='red', linestyle='-', linewidth=1)
        self.canvas_auc_curves.draw()
    
    def calculate_auc(self):
        # AUC works the other way round from the slope tabs: first select the
        # samples (switches) and set the three breakpoints, THEN calculate.
        if not self.auc_display_dict:
            self.log_message("Select at least one sample (left switches) before calculating AUC.")
            messagebox.showinfo("Select data first",
                "Please select at least one sample with the switches on the left, "
                "and set the three breakpoints, before calculating AUC.")
            return
        brkp_one = self.entry_auc_one.get()
        brkp_two = self.entry_auc_two.get()
        brkp_three = self.entry_auc_three.get()
        if not (brkp_one and brkp_two and brkp_three):
            self.log_message("Set all three breakpoints (sliders) before calculating AUC.")
            messagebox.showinfo("Set breakpoints",
                "Please set all three breakpoints with the sliders before calculating AUC.")
            return
        
        for key, val in self.auc_display_dict.items():
            auc_values = []
            auc_lag_temp = []
            auc_log_temp = []
            auc_stationary_temp = []
            auc_death_temp = []
            brkp_one_index = self.raw_data_dict[key].iloc[0].isin([float(brkp_one)]).tolist().index(True)
            brkp_two_index = self.raw_data_dict[key].iloc[0].isin([float(brkp_two)]).tolist().index(True)
            brkp_three_index = self.raw_data_dict[key].iloc[0].isin([float(brkp_three)]).tolist().index(True)
            
            for i in np.arange(1, len(self.raw_data_dict[key])-1, 1):
                auc_lag = np.trapezoid(y = self.raw_data_dict[key].iloc[i][0:brkp_one_index + 1], x = self.raw_data_dict[key].iloc[0][0:brkp_one_index + 1] )
                auc_lag_temp.append(auc_lag)
                auc_log = np.trapezoid(y = self.raw_data_dict[key].iloc[i][brkp_one_index:brkp_two_index + 1], x = self.raw_data_dict[key].iloc[0][brkp_one_index:brkp_two_index + 1] )
                auc_log_temp.append(auc_log)
                auc_stationary = np.trapezoid(y = self.raw_data_dict[key].iloc[i][brkp_two_index:brkp_three_index + 1], x = self.raw_data_dict[key].iloc[0][brkp_two_index:brkp_three_index + 1] )
                auc_stationary_temp.append(auc_stationary)
                auc_death = np.trapezoid(y = self.raw_data_dict[key].iloc[i][brkp_three_index:], x = self.raw_data_dict[key].iloc[0][brkp_three_index:] )
                auc_death_temp.append(auc_death)
                auc_values.append([auc_lag, auc_log, auc_stationary, auc_death])
            self.auc_index_dictionary[key] = self.raw_data_dict[key].index[1:]
            auc_values.append([np.mean(auc_lag_temp), np.mean(auc_log_temp), np.mean(auc_stationary_temp), np.mean(auc_death_temp)])
            auc_lag_temp.append(np.mean(auc_lag_temp))
            auc_log_temp.append(np.mean(auc_log_temp))
            auc_stationary_temp.append(np.mean(auc_stationary_temp))
            auc_death_temp.append(np.mean(auc_death_temp))
            
            
            
            
            self.auc_dictionary[key] = auc_values
            self.auc_dictionary_lag[key] = auc_lag_temp
            self.auc_dictionary_log[key] = auc_log_temp
            self.auc_dictionary_stationary[key] = auc_stationary_temp
            self.auc_dictionary_death[key] = auc_death_temp
            
            
            self.onset_delays_index[key] = brkp_one_index
            self.exponential_times_index[key] = brkp_two_index
            
            self.onset_delays[key] = float(brkp_one)
            self.exponential_times[key] = float(brkp_two) - float(brkp_one)
            self.full_exponential_time[key] = brkp_two_index
            self.auc_calc.append(key)
            
            
            
            
            
        self.ax_auc_replicas_lag.clear()
        self.ax_auc_replicas_log.clear()
        self.ax_auc_replicas_stat.clear()
        self.ax_auc_replicas_death.clear()
        temp_length = -1
        for sheet_name in self.auc_display_dict:
            length = len(self.auc_index_dictionary[sheet_name])
            temp_length = temp_length + length
            
            ### Plotting the Lag AUCs -----------
            
            bars = self.ax_auc_replicas_lag.bar(self.auc_index_dictionary[sheet_name],
            self.auc_dictionary_lag[sheet_name],
            label=sheet_name + ': CV='+ str(round(np.std(self.auc_dictionary_lag[sheet_name][0:-1])/self.auc_dictionary_lag[sheet_name][-1]*100, 2)) + "%", width = 0.5
            )
            temp_scatter = self.auc_dictionary_lag[sheet_name][0:]
            self.auc_bars_rep_lag[sheet_name] = bars
            self.ax_auc_replicas_lag.scatter([temp_length] * len(self.auc_index_dictionary[sheet_name]), temp_scatter, color = "black", s = 10, zorder = 3)
            
            #### Plotting the Log AUCs ----
            
            bars = self.ax_auc_replicas_log.bar(self.auc_index_dictionary[sheet_name],
            self.auc_dictionary_log[sheet_name],
            label=sheet_name + ': CV='+ str(round(np.std(self.auc_dictionary_log[sheet_name][0:-1])/self.auc_dictionary_log[sheet_name][-1]*100, 2)) + "%", width = 0.5
            )
            temp_scatter = self.auc_dictionary_log[sheet_name][0:]
            self.auc_bars_rep_log[sheet_name] = bars
            self.ax_auc_replicas_log.scatter([temp_length] * len(self.auc_index_dictionary[sheet_name]), temp_scatter, color = "black", s = 10, zorder = 3)
            
            #### Plotting the Stationary AUCs ------
            
            bars = self.ax_auc_replicas_stat.bar(self.auc_index_dictionary[sheet_name],
            self.auc_dictionary_stationary[sheet_name],
            label=sheet_name + ': CV='+ str(round(np.std(self.auc_dictionary_stationary[sheet_name][0:-1])/self.auc_dictionary_stationary[sheet_name][-1]*100, 2)) + "%", width = 0.5
            )
            temp_scatter = self.auc_dictionary_stationary[sheet_name][0:]
            self.auc_bars_rep_stat[sheet_name] = bars
            self.ax_auc_replicas_stat.scatter([temp_length] * len(self.auc_index_dictionary[sheet_name]), temp_scatter, color = "black", s = 10, zorder = 3)
            
            #### Plotting the Death Phase AUCs ------
            
            bars = self.ax_auc_replicas_death.bar(self.auc_index_dictionary[sheet_name],
            self.auc_dictionary_death[sheet_name],
            label=sheet_name + ': CV='+ str(round(np.std(self.auc_dictionary_death[sheet_name][0:-1])/self.auc_dictionary_death[sheet_name][-1]*100, 2)) + "%", width = 0.5
            )
            temp_scatter = self.auc_dictionary_death[sheet_name][0:]
            self.auc_bars_rep_death[sheet_name] = bars
            self.ax_auc_replicas_death.scatter([temp_length] * len(self.auc_index_dictionary[sheet_name]), temp_scatter, color = "black", s = 10, zorder = 3)
         
        self.ax_onset_delay.clear()
        self.ax_exp_time.clear()
        for sheet_name in self.auc_display_dict:
            bars = self.ax_onset_delay.bar(self.auc_index_dictionary[sheet_name],
            self.onset_delays[sheet_name],
            label = sheet_name, width = 0.5
            )
            
            bars = self.ax_exp_time.bar(self.auc_index_dictionary[sheet_name],
            self.exponential_times[sheet_name],
            label = sheet_name, width = 0.5
            )
            
            
            
        self.ax_auc_replicas_lag.set_title("Lag phase AUC values")
        self.ax_auc_replicas_lag.set_ylabel("Lag Phase AUC values [min]")
        self.ax_auc_replicas_lag.set_xlabel("Sample names")
        self.ax_auc_replicas_lag.tick_params(axis='x', rotation=90)
        self._legend(self.ax_auc_replicas_lag, where="right")
        
        self.ax_auc_replicas_log.set_title("Log phase AUC values")
        self.ax_auc_replicas_log.set_ylabel("Log Phase AUC values [min]")
        self.ax_auc_replicas_log.set_xlabel("Sample names")
        self.ax_auc_replicas_log.tick_params(axis='x', rotation=90)
        self._legend(self.ax_auc_replicas_log, where="right")
        
        self.ax_auc_replicas_stat.set_title("Stationary phase AUC values")
        self.ax_auc_replicas_stat.set_ylabel("Stationary Phase AUC values [min]")
        self.ax_auc_replicas_stat.set_xlabel("Sample names")
        self.ax_auc_replicas_stat.tick_params(axis='x', rotation=90)
        self._legend(self.ax_auc_replicas_stat, where="right")
        
        self.ax_auc_replicas_death.set_title("Death phase AUC values")
        self.ax_auc_replicas_death.set_ylabel("Death Phase AUC values [min]")
        self.ax_auc_replicas_death.set_xlabel("Sample names")
        self.ax_auc_replicas_death.tick_params(axis='x', rotation=90)
        self._legend(self.ax_auc_replicas_death, where="right")
        
        self.ax_onset_delay.set_title("Onset delay values")
        self.ax_onset_delay.set_ylabel("Onset Delay times [min]")
        self.ax_onset_delay.set_xlabel("Sample names")
        self.ax_onset_delay.tick_params(axis='x', rotation=90)
        self._legend(self.ax_onset_delay, where="right")
        
        self.ax_exp_time.set_title("Exponential time values")
        self.ax_exp_time.set_ylabel("Exponential times [min]")
        self.ax_exp_time.set_xlabel("Sample names")
        self.ax_exp_time.tick_params(axis='x', rotation=90)
        self._legend(self.ax_exp_time, where="right")
                
                
            
        
        self.ax_auc_replicas_lag.relim()
        self.ax_auc_replicas_lag.autoscale_view()
        self.canvas_auc_replicas_lag.draw()
        
        self.ax_auc_replicas_log.relim()
        self.ax_auc_replicas_log.autoscale_view()
        self.canvas_auc_replicas_log.draw()
        
        self.ax_auc_replicas_stat.relim()
        self.ax_auc_replicas_stat.autoscale_view()
        self.canvas_auc_replicas_stat.draw()
        
        self.ax_auc_replicas_death.relim()
        self.ax_auc_replicas_death.autoscale_view()
        self.canvas_auc_replicas_death.draw()
        
        self.ax_onset_delay.relim()
        self.ax_onset_delay.autoscale_view()
        self.canvas_onset_delay.draw()
        
        self.ax_exp_time.relim()
        self.ax_exp_time.autoscale_view()
        self.canvas_exp_time.draw()
        
        return
    
    def plot_auc_means(self, sheet, sheet_name):
        if not self._require_calc("auc_dictionary", "Calculate AUC", self.switch_vars_auc_means.get(sheet_name)):
            return
        is_on = self.switch_vars_auc_means[sheet_name].get()
        
        self.auc_mean_bars = {}

        # Clear previous bars for this sample if they exist
        if sheet_name in self.sheet_names_auc_means:
            self.sheet_names_auc_means.remove(sheet_name)
            self.ax_auc_replicas_lag_mean.clear()
            self.ax_auc_replicas_log_mean.clear()
            self.ax_auc_replicas_stat_mean.clear()
            self.ax_auc_replicas_death_mean.clear()
            for sheet_name in self.sheet_names_auc_means:
                bars = self.ax_auc_replicas_lag_mean.bar(
                    self.auc_index_dictionary[sheet_name][-1],
                    self.auc_dictionary_lag[sheet_name][-1],
                    label=sheet_name, width = 0.5
                )
                self.auc_bars_mean_lag[sheet_name] = bars
                
                bars = self.ax_auc_replicas_log_mean.bar(
                    self.auc_index_dictionary[sheet_name][-1],
                    self.auc_dictionary_log[sheet_name][-1],
                    label=sheet_name, width = 0.5
                )
                self.auc_bars_mean_log[sheet_name] = bars
                
                bars = self.ax_auc_replicas_stat_mean.bar(
                    self.auc_index_dictionary[sheet_name][-1],
                    self.auc_dictionary_stationary[sheet_name][-1],
                    label=sheet_name, width = 0.5
                )
                self.auc_bars_mean_stationary[sheet_name] = bars
                
                bars = self.ax_auc_replicas_death_mean.bar(
                    self.auc_index_dictionary[sheet_name][-1],
                    self.auc_dictionary_death[sheet_name][-1],
                    label=sheet_name, width = 0.5
                )
                self.auc_bars_mean_death[sheet_name] = bars
        else:
            self.sheet_names_auc_means.append(sheet_name)

        # If switch is ON, plot and store the bars
        if is_on:
            self.ax_auc_replicas_lag_mean.clear()
            self.ax_auc_replicas_log_mean.clear()
            self.ax_auc_replicas_stat_mean.clear()
            self.ax_auc_replicas_death_mean.clear()
            for sheet_name in self.sheet_names_auc_means:
                bars = self.ax_auc_replicas_lag_mean.bar(
                    self.auc_index_dictionary[sheet_name][-1],
                    self.auc_dictionary_lag[sheet_name][-1],
                    label=sheet_name, width = 0.5
                )
                self.auc_bars_mean_lag[sheet_name] = bars
                
                bars = self.ax_auc_replicas_log_mean.bar(
                    self.auc_index_dictionary[sheet_name][-1],
                    self.auc_dictionary_log[sheet_name][-1],
                    label=sheet_name, width = 0.5
                )
                self.auc_bars_mean_log[sheet_name] = bars
                
                bars = self.ax_auc_replicas_stat_mean.bar(
                    self.auc_index_dictionary[sheet_name][-1],
                    self.auc_dictionary_stationary[sheet_name][-1],
                    label=sheet_name, width = 0.5
                )
                self.auc_bars_mean_stationary[sheet_name] = bars
                
                bars = self.ax_auc_replicas_death_mean.bar(
                    self.auc_index_dictionary[sheet_name][-1],
                    self.auc_dictionary_death[sheet_name][-1],
                    label=sheet_name, width = 0.5
                )
                self.auc_bars_mean_death[sheet_name] = bars
            
            
        self.ax_auc_replicas_lag_mean.set_title("Mean lag phase AUC values")
        self.ax_auc_replicas_lag_mean.set_ylabel("Mean Lag AUC values [min]")
        self.ax_auc_replicas_lag_mean.set_xlabel("Sample names")
        self.ax_auc_replicas_lag_mean.tick_params(axis='x', rotation=90)
        self._legend(self.ax_auc_replicas_lag_mean, where="right")
        
        self.ax_auc_replicas_log_mean.set_title("Mean log phase AUC values")
        self.ax_auc_replicas_log_mean.set_ylabel("Mean Log AUC values [min]")
        self.ax_auc_replicas_log_mean.set_xlabel("Sample names")
        self.ax_auc_replicas_log_mean.tick_params(axis='x', rotation=90)
        self._legend(self.ax_auc_replicas_log_mean, where="right")
        
        self.ax_auc_replicas_stat_mean.set_title("Mean stationary phase AUC values")
        self.ax_auc_replicas_stat_mean.set_ylabel("Mean Stationary AUC values [min]")
        self.ax_auc_replicas_stat_mean.set_xlabel("Sample names")
        self.ax_auc_replicas_stat_mean.tick_params(axis='x', rotation=90)
        self._legend(self.ax_auc_replicas_stat_mean, where="right")
        
        self.ax_auc_replicas_death_mean.set_title("Mean death phase AUC values")
        self.ax_auc_replicas_death_mean.set_ylabel("Mean Death pahse AUC values [min]")
        self.ax_auc_replicas_death_mean.set_xlabel("Sample names")
        self.ax_auc_replicas_death_mean.tick_params(axis='x', rotation=90)
        self._legend(self.ax_auc_replicas_death_mean, where="right")

        self.ax_auc_replicas_lag_mean.relim()
        self.ax_auc_replicas_lag_mean.autoscale_view()
        self.canvas_auc_replicas_lag_mean.draw()
        
        self.ax_auc_replicas_log_mean.relim()
        self.ax_auc_replicas_log_mean.autoscale_view()
        self.canvas_auc_replicas_log_mean.draw()
        
        self.ax_auc_replicas_stat_mean.relim()
        self.ax_auc_replicas_stat_mean.autoscale_view()
        self.canvas_auc_replicas_stat_mean.draw()
        
        self.ax_auc_replicas_death_mean.relim()
        self.ax_auc_replicas_death_mean.autoscale_view()
        self.canvas_auc_replicas_death_mean.draw()
        
        
        return
    
    def create_auc_table(self):
        for widget in self.scrollable_auc_values_tables.winfo_children():
            widget.destroy()
        
        self.frame_auc_tables = tk.Frame(self.scrollable_auc_values_tables)
        self.frame_auc_tables.pack(padx=8, pady=10, fill = "x", expand = True)
        
        left_column = tk.Frame(self.frame_auc_tables)
        left_column.pack(fill="x", pady=5, side = "left")
        
        right_column = tk.Frame(self.frame_auc_tables)
        right_column.pack(fill = "x", pady = 5, side = "top")
        
        for sheet_name in self.auc_dictionary:
            frame = tk.Frame(left_column, width=150, height=80)
            frame.pack(padx=10, pady=5, anchor = "w")
            
            
            label = tk.Label(frame, text = sheet_name, font=self.sfont(12, "bold"))
            label.pack(padx = 5, pady = 5, anchor = "w")
            
            
            
            data = [[self.auc_index_dictionary[sheet_name][i]] + self.auc_dictionary[sheet_name][i] + [self.onset_delays[sheet_name]] + [self.exponential_times[sheet_name]] for i in range(len(self.auc_index_dictionary[sheet_name]))]
            
            sheet = tksheet.Sheet(frame, data = data, headers = ["Well numbers", "Lag AUC", "Log AUC", "Stationary AUC", "Death AUC", "Onset Delay [min]", "Exponential time [min]"], height = 150, width = 500)
            sheet.pack(padx=5, pady=5, expand=False)
        
            sheet.enable_bindings((
                     "single_select", "column_select", "edit_cell", "arrowkeys", "row_select", "ctrl_z", "ctrl_y"
                 ))
            
        save_button = ctk.CTkButton(right_column, text = "Save to .csv", width = 40, height = 30, command = self.auc_to_csv)
        save_button.pack(padx = 10, pady = 20, anchor = "nw")
        
        return
    
    def auc_to_csv(self):
        
        file_path = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV files", "*.csv"), ("All files", "*.*")], title="Save as")

        f = open(file_path, "a", newline="", encoding="utf-8")
        w = csv.writer(f)
        
        
        now = datetime.now()
        
        w.writerow([f"File creation: {now}"])
        
        w.writerow(["Bacteria names", "Well numbers", "Lag AUC", "Log AUC", "Stationary AUC", "Death AUC", "Onset Delay", "Exponential time"])
        for sheet_name in self.auc_dictionary:
            for i in np.arange(0, len(self.auc_dictionary[sheet_name]), 1):
                w.writerow([sheet_name, self.auc_index_dictionary[sheet_name][i], self.auc_dictionary_lag[sheet_name][i], self.auc_dictionary_log[sheet_name][i], self.auc_dictionary_stationary[sheet_name][i], self.auc_dictionary_death[sheet_name][i], self.onset_delays[sheet_name], self.exponential_times[sheet_name]])    
                f.flush()
        f.close()
        
        return
    
    def show_menu_auc_replicas_lag(self, event):
        self.menu_auc_replicas_lag.post(event.x_root, event.y_root)
    
    def title_auc_replicas_lag(self):
        custom_auc_rep_title = tk.simpledialog.askstring("Plot Title", "Enter a title:")
        self.ax_auc_replicas_lag.set_title(custom_auc_rep_title)
        self.canvas_auc_replicas_lag.draw()
        
    def xaxis_auc_replicas_lag(self):
        custom_auc_rep_xaxis = tk.simpledialog.askstring("Plot x axis", "Enter the name of the x axis:")
        self.ax_auc_replicas_lag.set_xlabel(custom_auc_rep_xaxis)
        self.canvas_auc_replicas_lag.draw()
        return
    
    def yaxis_auc_replicas_lag(self):
        custom_auc_rep_yaxis = tk.simpledialog.askstring("Plot x axis", "Enter the name of the y axis:")
        self.ax_auc_replicas_lag.set_ylabel(custom_auc_rep_yaxis)
        self.canvas_auc_replicas_lag.draw()
        return
    
    def save_auc_replicas_lag(self):
        file_path = filedialog.asksaveasfilename(defaultextension=".png", filetypes=[("PNG image", "*.png"), ("SVG image", "*.svg"), ("PDF file", "*.pdf"), ("All files", "*.*")])
        
        if file_path:
            self.fig_auc_replicas_lag.savefig(file_path, dpi = 500)
        return
    
    #-------------------------------------------
    
    def show_menu_auc_lag_mean(self, event):
        self.menu_auc_lag_mean.post(event.x_root, event.y_root)

    def title_auc_lag_mean(self):
        temp_title = tk.simpledialog.askstring("Plot Title", "Enter a title:")
        self.ax_auc_replicas_lag_mean.set_title(temp_title)
        self.canvas_auc_replicas_lag_mean.draw()
    
    def xaxis_auc_lag_mean(self):
        temp_xaxis = tk.simpledialog.askstring("Plot x axis", "Enter the name of the x axis:")
        self.ax_auc_replicas_lag_mean.set_xlabel(temp_xaxis)
        self.canvas_auc_replicas_lag_mean.draw()
        return

    def yaxis_auc_lag_mean(self):
        temp_yaxis = tk.simpledialog.askstring("Plot x axis", "Enter the name of the y axis:")
        self.ax_auc_replicas_lag_mean.set_ylabel(temp_yaxis)
        self.canvas_auc_replicas_lag_mean.draw()
        return

    def save_auc_lag_mean(self):
        file_path = filedialog.asksaveasfilename(defaultextension=".png", filetypes=[("PNG image", "*.png"), ("SVG image", "*.svg"), ("PDF file", "*.pdf"), ("All files", "*.*")])
    
        if file_path:
            self.fig_auc_replicas_lag_mean.savefig(file_path, dpi = 500)
        return
    
    
    #--------------------------------------------------------------------
    def show_menu_auc_replicas_log(self, event):
        self.menu_auc_rep_log.post(event.x_root, event.y_root)

    def title_auc_rep_log(self):
        temp_title = tk.simpledialog.askstring("Plot Title", "Enter a title:")
        self.ax_auc_replicas_log.set_title(temp_title)
        self.canvas_auc_replicas_log.draw()
    
    def xaxis_auc_rep_log(self):
        temp_xaxis = tk.simpledialog.askstring("Plot x axis", "Enter the name of the x axis:")
        self.ax_auc_replicas_log.set_xlabel(temp_xaxis)
        self.canvas_auc_replicas_log.draw()
        return

    def yaxis_auc_rep_log(self):
        temp_yaxis = tk.simpledialog.askstring("Plot x axis", "Enter the name of the y axis:")
        self.ax_auc_replicas_log.set_ylabel(temp_yaxis)
        self.canvas_auc_replicas_log.draw()
        return

    def save_auc_rep_log(self):
        file_path = filedialog.asksaveasfilename(defaultextension=".png", filetypes=[("PNG image", "*.png"), ("SVG image", "*.svg"), ("PDF file", "*.pdf"), ("All files", "*.*")])
    
        if file_path:
            self.fig_auc_replicas_log.savefig(file_path, dpi = 500)
        return  


    
    #---------------------------------------------
    
    def show_menu_auc_mean_log(self, event):
        self.menu_auc_mean_log.post(event.x_root, event.y_root)

    def title_auc_mean_log(self):
        temp_title = tk.simpledialog.askstring("Plot Title", "Enter a title:")
        self.ax_auc_replicas_log_mean.set_title(temp_title)
        self.canvas_auc_replicas_log_mean.draw()
    
    def xaxis_auc_mean_log(self):
        temp_xaxis = tk.simpledialog.askstring("Plot x axis", "Enter the name of the x axis:")
        self.ax_auc_replicas_log_mean.set_xlabel(temp_xaxis)
        self.canvas_auc_replicas_log_mean.draw()
        return

    def yaxis_auc_mean_log(self):
        temp_yaxis = tk.simpledialog.askstring("Plot x axis", "Enter the name of the y axis:")
        self.ax_auc_replicas_log_mean.set_ylabel(temp_yaxis)
        self.canvas_auc_replicas_log_mean.draw()
        return

    def save_auc_mean_log(self):
        file_path = filedialog.asksaveasfilename(defaultextension=".png", filetypes=[("PNG image", "*.png"), ("SVG image", "*.svg"), ("PDF file", "*.pdf"), ("All files", "*.*")])
    
        if file_path:
            self.fig_auc_replicas_log_mean.savefig(file_path, dpi = 500)
        return  

    
    
    #-------------------------------------------------------------
    def show_menu_auc_rep_stat(self, event):
        self.menu_auc_rep_stat.post(event.x_root, event.y_root)

    def title_auc_rep_stat(self):
        temp_title = tk.simpledialog.askstring("Plot Title", "Enter a title:")
        self.ax_auc_replicas_stat.set_title(temp_title)
        self.canvas_auc_replicas_stat.draw()
    
    def xaxis_auc_rep_stat(self):
        temp_xaxis = tk.simpledialog.askstring("Plot x axis", "Enter the name of the x axis:")
        self.ax_auc_replicas_stat.set_xlabel(temp_xaxis)
        self.canvas_auc_replicas_stat.draw()
        return

    def yaxis_auc_rep_stat(self):
        temp_yaxis = tk.simpledialog.askstring("Plot x axis", "Enter the name of the y axis:")
        self.ax_auc_replicas_stat.set_ylabel(temp_yaxis)
        self.canvas_auc_replicas_stat.draw()
        return

    def save_auc_rep_stat(self):
        file_path = filedialog.asksaveasfilename(defaultextension=".png", filetypes=[("PNG image", "*.png"), ("SVG image", "*.svg"), ("PDF file", "*.pdf"), ("All files", "*.*")])
    
        if file_path:
            self.fig_auc_replicas_stat.savefig(file_path, dpi = 500)
        return  

    
    #---------------------------------------------------------
    def show_menu_auc_mean_stat(self, event):
        self.menu_auc_mean_stat.post(event.x_root, event.y_root)

    def title_auc_mean_stat(self):
        temp_title = tk.simpledialog.askstring("Plot Title", "Enter a title:")
        self.ax_auc_replicas_stat_mean.set_title(temp_title)
        self.canvas_auc_replicas_stat_mean.draw()
    
    def xaxis_auc_mean_stat(self):
        temp_xaxis = tk.simpledialog.askstring("Plot x axis", "Enter the name of the x axis:")
        self.ax_auc_replicas_stat_mean.set_xlabel(temp_xaxis)
        self.canvas_auc_replicas_stat_mean.draw()
        return

    def yaxis_auc_mean_stat(self):
        temp_yaxis = tk.simpledialog.askstring("Plot x axis", "Enter the name of the y axis:")
        self.ax_auc_replicas_stat_mean.set_ylabel(temp_yaxis)
        self.canvas_auc_replicas_stat_mean.draw()
        return

    def save_auc_mean_stat(self):
        file_path = filedialog.asksaveasfilename(defaultextension=".png", filetypes=[("PNG image", "*.png"), ("SVG image", "*.svg"), ("PDF file", "*.pdf"), ("All files", "*.*")])
    
        if file_path:
            self.fig_auc_replicas_stat_mean.savefig(file_path, dpi = 500)
        return
    
    
    #-------------------------------------------------------------
    
    def show_menu_auc_rep_death(self, event):
        self.menu_auc_rep_death.post(event.x_root, event.y_root)

    def title_auc_rep_death(self):
        temp_title = tk.simpledialog.askstring("Plot Title", "Enter a title:")
        self.ax_auc_replicas_death.set_title(temp_title)
        self.canvas_auc_replicas_death.draw()
    
    def xaxis_auc_rep_death(self):
        temp_xaxis = tk.simpledialog.askstring("Plot x axis", "Enter the name of the x axis:")
        self.ax_auc_replicas_replicas_death.set_xlabel(temp_xaxis)
        self.canvas_auc_replicas_replicas_death.draw()
        return

    def yaxis_auc_rep_death(self):
        temp_yaxis = tk.simpledialog.askstring("Plot x axis", "Enter the name of the y axis:")
        self.ax_auc_replicas_death.set_ylabel(temp_yaxis)
        self.canvas_auc_replicas_death.draw()
        return

    def save_auc_rep_death(self):
        file_path = filedialog.asksaveasfilename(defaultextension=".png", filetypes=[("PNG image", "*.png"), ("SVG image", "*.svg"), ("PDF file", "*.pdf"), ("All files", "*.*")])
    
        if file_path:
            self.fig_auc_replicas_death.savefig(file_path, dpi = 500)
        return  

    
    #----------------------------------------------------------------------
    
    def show_menu_auc_mean_death(self, event):
        self.menu_auc_mean_death.post(event.x_root, event.y_root)

    def title_auc_mean_death(self):
        temp_title = tk.simpledialog.askstring("Plot Title", "Enter a title:")
        self.ax_auc_replicas_death_mean.set_title(temp_title)
        self.canvas_auc_replicas_death_mean.draw()
    
    def xaxis_auc_mean_death(self):
        temp_xaxis = tk.simpledialog.askstring("Plot x axis", "Enter the name of the x axis:")
        self.ax_auc_replicas_replicas_death_mean.set_xlabel(temp_xaxis)
        self.canvas_auc_replicas_replicas_death_mean.draw()
        return

    def yaxis_auc_mean_death(self):
        temp_yaxis = tk.simpledialog.askstring("Plot x axis", "Enter the name of the y axis:")
        self.ax_auc_replicas_death_mean.set_ylabel(temp_yaxis)
        self.canvas_auc_replicas_death_mean.draw()
        return

    def save_auc_mean_death(self):
        file_path = filedialog.asksaveasfilename(defaultextension=".png", filetypes=[("PNG image", "*.png"), ("SVG image", "*.svg"), ("PDF file", "*.pdf"), ("All files", "*.*")])
    
        if file_path:
            self.fig_auc_replicas_death_mean.savefig(file_path, dpi = 500)
        return  

    
    
    #-------------------------------------------------------------------------
    
    def show_menu_auc_onset_time(self, event):
        self.menu_auc_onset_time.post(event.x_root, event.y_root)

    def title_auc_onset_time(self):
        temp_title = tk.simpledialog.askstring("Plot Title", "Enter a title:")
        self.ax_onset_delay.set_title(temp_title)
        self.canvas_onset_delay.draw()
    
    def xaxis_auc_onset_time(self):
        temp_xaxis = tk.simpledialog.askstring("Plot x axis", "Enter the name of the x axis:")
        self.ax_onset_delay.set_xlabel(temp_xaxis)
        self.canvas_onset_delay.draw()
        return

    def yaxis_auc_onset_time(self):
        temp_yaxis = tk.simpledialog.askstring("Plot x axis", "Enter the name of the y axis:")
        self.ax_onset_delay.set_ylabel(temp_yaxis)
        self.canvas_onset_delay.draw()
        return

    def save_auc_onset_time(self):
        file_path = filedialog.asksaveasfilename(defaultextension=".png", filetypes=[("PNG image", "*.png"), ("SVG image", "*.svg"), ("PDF file", "*.pdf"), ("All files", "*.*")])
    
        if file_path:
            self.fig_onset_delay.savefig(file_path, dpi = 500)
        return  

    
    #-------------------------------------------------------------------------
    
    def show_menu_auc_exp_time(self, event):
        self.menu_auc_exp_time.post(event.x_root, event.y_root)

    def title_auc_exp_time(self):
        temp_title = tk.simpledialog.askstring("Plot Title", "Enter a title:")
        self.ax_exp_time.set_title(temp_title)
        self.canvas_exp_time.draw()
    
    def xaxis_auc_exp_time(self):
        temp_xaxis = tk.simpledialog.askstring("Plot x axis", "Enter the name of the x axis:")
        self.ax_exp_time.set_xlabel(temp_xaxis)
        self.canvas_exp_time.draw()
        return

    def yaxis_auc_exp_time(self):
        temp_yaxis = tk.simpledialog.askstring("Plot x axis", "Enter the name of the y axis:")
        self.ax_exp_time.set_ylabel(temp_yaxis)
        self.canvas_exp_time.draw()
        return

    def save_auc_exp_time(self):
        file_path = filedialog.asksaveasfilename(defaultextension=".png", filetypes=[("PNG image", "*.png"), ("SVG image", "*.svg"), ("PDF file", "*.pdf"), ("All files", "*.*")])
    
        if file_path:
            self.fig_exp_time.savefig(file_path, dpi = 500)
        return
    
    
    # %%
    ################### COMMANDS FOR THE MAXIMUM GROWTH PLOT #############################################################
    # %%
    
    def calculate_max_growth(self):
        self.max_growth_dictionary = {}
        self.initial_values_dictionary = {}
        
        self.max_growth_index_dictionary = {}
        
        for sheet_name, df in self.raw_data_dict.items():
            max_growths = []
            initial_values = []
            for i in np.arange(1, len(df)-1, 1):
                df_max = max(df.iloc[i])
                max_growths.append(df_max)
                
                df_start = df.iloc[i, 0]
                initial_values.append(df_start)
            
            temp_mean = np.mean(max_growths)
            temp_initial_mean = np.mean(initial_values)
            
            max_growths.append(temp_mean)
            initial_values.append(temp_initial_mean)
            
            
            self.max_growth_index_dictionary[sheet_name] = df.index[1:]
            self.max_growth_dictionary[sheet_name] = max_growths
            
            self.initial_values_dictionary[sheet_name] = initial_values
            
            

        # Draw the "Maximum growth values per replica" bar chart for whichever
        # samples are currently selected. Without this, the main calculation
        # filled the numbers but never populated this plot, so it stayed empty
        # unless the user happened to toggle a switch after calculating.
        self.sheet_names_max_growth_rep = [
            name for name, var in self.switch_vars_max_growth.items()
            if var.get() and name in self.max_growth_index_dictionary
        ]
        self.ax_max_replica.clear()
        temp_length = -1
        for sheet_name in self.sheet_names_max_growth_rep:
            length = len(self.max_growth_index_dictionary[sheet_name])
            temp_length = temp_length + length
            self.ax_max_replica.bar(
                self.max_growth_index_dictionary[sheet_name],
                self.max_growth_dictionary[sheet_name],
                label=sheet_name + ': CV=' + str(round(np.std(self.max_growth_dictionary[sheet_name][0:-1]) / self.max_growth_dictionary[sheet_name][-1] * 100, 2)) + "%",
                width=0.5)
            temp_scatter = self.max_growth_dictionary[sheet_name][0:]
            self.ax_max_replica.scatter([temp_length] * len(self.max_growth_index_dictionary[sheet_name]), temp_scatter, color="black", s=10, zorder=3)
        self.ax_max_replica.tick_params(axis='x', rotation=90)
        self.ax_max_replica.set_title("Maximum growth values per replica")
        self.ax_max_replica.set_ylabel("Maximum growth value [a.u.]")
        self.ax_max_replica.set_xlabel("Sample names")
        if self.sheet_names_max_growth_rep:
            self._legend(self.ax_max_replica, where="right")
            self.ax_max_replica.relim()
            self.ax_max_replica.autoscale_view()
        self.canvas_max_growth_replica.draw_idle()

        return
    
    def calculate_local_max_growth(self):
        
        start_time = self.entry_start_time.get()
        end_time = self.entry_end_time.get()
        
        for key, val in self.max_growth_display_dict.items():
            custom_max_growth_values = []
            start_time_index = self.raw_data_dict[key].iloc[0].isin([float(start_time)]).tolist().index(True)
            end_time_index = self.raw_data_dict[key].iloc[0].isin([float(end_time)]).tolist().index(True)
            for i in np.arange(1, len(self.raw_data_dict[key])-1, 1):
                custom_max_growth_values.append(max(self.raw_data_dict[key].iloc[i][start_time_index:end_time_index]))
            temp_mean = np.mean(custom_max_growth_values)
            custom_max_growth_values.append(temp_mean)
            self.max_growth_dictionary[key] = custom_max_growth_values
            
            
        # Build the replica list from whichever sample switches are currently
        # ON, then draw the replica bars below.
        self.sheet_names_max_growth_rep = [
            name for name, var in self.switch_vars_max_growth.items()
            if var.get() and name in self.max_growth_index_dictionary
        ]

        self.ax_max_replica.clear()
        temp_length = - 1
        for sheet_name in self.sheet_names_max_growth_rep:
            length = len(self.max_growth_index_dictionary[sheet_name])
            temp_length = temp_length + length
            self.ax_max_replica.bar(self.max_growth_index_dictionary[sheet_name],
            self.max_growth_dictionary[sheet_name],
            label = sheet_name + ': CV='+ str(round(np.std(self.max_growth_dictionary[sheet_name][0:-1])/self.max_growth_dictionary[sheet_name][-1]*100, 2)) + "%", width = 0.5
                )
            temp_scatter = self.max_growth_dictionary[sheet_name][0:]
            self.ax_max_replica.scatter([temp_length] * len(self.max_growth_index_dictionary[sheet_name]), temp_scatter, color = "black", s = 10, zorder = 3)
            
        self.ax_max_replica.tick_params(axis='x', rotation=90)
        self._legend(self.ax_max_replica, where="right")
        
        self.ax_max_replica.set_title("Maximum growth values per replica")
        self.ax_max_replica.set_ylabel("Maximum growth value [a.u.]")
        self.ax_max_replica.set_xlabel("Sample names")
        
        self.ax_max_replica.relim()
        self.ax_max_replica.autoscale_view()
        self.canvas_max_growth_replica.draw()
        
        return
        
    def plot_max_growth_curves(self, sheet, sheet_name):
        is_on = self.switch_vars_max_growth[sheet_name].get()

        # Clear previous plots for this sample if they exist
        if sheet_name in self.max_growth_display_dict:
            for plots in self.max_growth_display_dict[sheet_name]:
                plots.remove()
            del self.max_growth_display_dict[sheet_name]

        # If switch is ON, plot and store the raw growth curves. This works
        # before any calculation; selecting data first lets you inspect curves
        # and pick a timeframe, then calculate.
        if is_on:
            plots_list = []
            for i in np.arange(1, len(self.raw_data_dict[sheet_name]), 1):
                plots = self.ax_max_growth.plot(
                    self.raw_data_dict[sheet_name].iloc[0],
                    self.raw_data_dict[sheet_name].iloc[i],
                    label=sheet_name)
                plots_list.extend(plots)
            self.max_growth_display_dict[sheet_name] = plots_list
            cursor = mplcursors.cursor(plots, hover=True)

        # The bar charts below need the Maximum Growth calculation. If it has
        # not been run, label and refresh the curve canvas and stop here.
        self.ax_max_growth.set_title("Bacterial growth curves")
        self.ax_max_growth.set_ylabel("Optical density [a.u.]")
        self.ax_max_growth.set_xlabel("Time [min]")
        self._legend(self.ax_max_growth, where="right")
        self.ax_max_growth.relim()
        self.ax_max_growth.autoscale_view()
        self.canvas_max_growth.draw_idle()
        if "max_growth_index_dictionary" not in self.__dict__ or not self.max_growth_index_dictionary:
            return

        self.replicate_bars_max_growth = {}

        # Clear previous bars for this sample if they exist
        if sheet_name in self.sheet_names_max_growth_rep:
            self.sheet_names_max_growth_rep.remove(sheet_name)
            self.ax_max_replica.clear()
            temp_length = - 1
            for sheet_name in self.sheet_names_max_growth_rep:
                length = len(self.max_growth_index_dictionary[sheet_name])
                temp_length = temp_length + length
                bars = self.ax_max_replica.bar(self.max_growth_index_dictionary[sheet_name],
                self.max_growth_dictionary[sheet_name],
                label = sheet_name + ': CV='+ str(round(np.std(self.max_growth_dictionary[sheet_name][0:-1])/self.max_growth_dictionary[sheet_name][-1]*100, 2)) + "%", width = 0.5
            )
                temp_scatter = self.max_growth_dictionary[sheet_name][0:]
                self.ax_max_replica.scatter([temp_length] * len(self.max_growth_index_dictionary[sheet_name]), temp_scatter, color = "black", s = 10, zorder = 3)
                self.replicate_bars_max_growth[sheet_name] = bars
        else:
            self.sheet_names_max_growth_rep.append(sheet_name)
            
        
        # If switch is ON, plot and store the bars
        if is_on:
            self.ax_max_replica.clear()
            temp_length = - 1
            for sheet_name in self.sheet_names_max_growth_rep:
                length = len(self.max_growth_index_dictionary[sheet_name])
                temp_length = temp_length + length
                bars = self.ax_max_replica.bar(self.max_growth_index_dictionary[sheet_name],
                self.max_growth_dictionary[sheet_name],
                label = sheet_name + ': CV='+ str(round(np.std(self.max_growth_dictionary[sheet_name][0:-1])/self.max_growth_dictionary[sheet_name][-1]*100, 2)) + "%", width = 0.5
            )
                temp_scatter = self.max_growth_dictionary[sheet_name][0:]
                self.ax_max_replica.scatter([temp_length] * len(self.max_growth_index_dictionary[sheet_name]), temp_scatter, color = "black", s = 10, zorder = 3)
                self.replicate_bars_max_growth[sheet_name] = bars
            
        
        
        self.ax_max_growth.set_title("Bacterial growth curves")
        self.ax_max_growth.set_ylabel("Optical density [a.u.]")
        self.ax_max_growth.set_xlabel("Time [min]")
        self._legend(self.ax_max_growth, where="right")
        
        
        self.ax_max_replica.set_title("Maximum growth values per replica")
        self.ax_max_replica.set_ylabel("Maximum growth values [a.u.]")
        self.ax_max_replica.set_xlabel("Sample names")
        self.ax_max_replica.tick_params(axis='x', rotation=90)
        self._legend(self.ax_max_replica, where="right")

        self.ax_max_growth.relim()
        self.ax_max_growth.autoscale_view()
        self.canvas_max_growth.draw()
        
        self.ax_max_replica.relim()
        self.ax_max_replica.autoscale_view()
        self.canvas_max_growth_replica.draw()
        
        return
    
    def plot_max_growth_means(self, sheet, sheet_name):
        if not self._require_calc("max_growth_index_dictionary", "Maximum Growth Calculation", self.switch_vars_max_growth_means.get(sheet_name)):
            return
        is_on = self.switch_vars_max_growth_means[sheet_name].get()
        
        self.replicate_bars_max_growth_means = {}
        
        if sheet_name in self.sheet_names_max_growth_means:
            self.sheet_names_max_growth_means.remove(sheet_name)
            self.ax_max_selection.clear()
            for sheet_name in self.sheet_names_max_growth_means:
                bars = self.ax_max_selection.bar(self.max_growth_index_dictionary[sheet_name][-1],
                self.max_growth_dictionary[sheet_name][-1],
                label=sheet_name, width = 0.5
            )
                self.replicate_bars_max_growth_means[sheet_name] = bars
        else:
            self.sheet_names_max_growth_means.append(sheet_name)
            
        
        # If switch is ON, plot and store the bars
        if is_on:
            self.ax_max_selection.clear()
            for sheet_name in self.sheet_names_max_growth_means:
                bars = self.ax_max_selection.bar(self.max_growth_index_dictionary[sheet_name][-1],
                self.max_growth_dictionary[sheet_name][-1],
                label=sheet_name, width = 0.5
            )
                self.replicate_bars_max_growth_means[sheet_name] = bars
            

        
        self.ax_max_selection.set_title("Mean maximum growth values")
        self.ax_max_selection.set_ylabel("Mean maximum growth values [a.u.]")
        self.ax_max_selection.set_xlabel("Sample names")
        self.ax_max_selection.tick_params(axis='x', rotation=90)
        self._legend(self.ax_max_selection, where="right")

        self.ax_max_selection.relim()
        self.ax_max_selection.autoscale_view()
        self.canvas_max_growth_selection.draw()
        
        return
    
    def on_scale_change_start(self, val):
        self.start_time_variable.set(self.time_values.tolist()[int(val)-1])
        if self.max_vline_start:
            self.max_vline_start.remove()
        self.max_vline_start = self.ax_max_growth.axvline(x = self.time_values.tolist()[int(val)-1], color='green', linestyle='-', linewidth=1)
        self.canvas_max_growth.draw()
        
        return
    
    def on_scale_change_end(self, val):
        self.end_time_variable.set(self.time_values.tolist()[int(val)-1])
        if self.max_vline_end:
            self.max_vline_end.remove()
        self.max_vline_end = self.ax_max_growth.axvline(x = self.time_values.tolist()[int(val)-1], color='red', linestyle='-', linewidth=1)
        self.canvas_max_growth.draw()
        
        return
    
    def table_of_values_max_growth(self):
        for widget in self.scrollable_mg_values.winfo_children():
            widget.destroy()
        
        self.frame_mg_tables = tk.Frame(self.scrollable_mg_values)
        self.frame_mg_tables.pack(padx=8, pady=10, fill = "x", expand = True)
        
        left_column = tk.Frame(self.frame_mg_tables)
        left_column.pack(fill="x", pady=5, side = "left")
        
        right_column = tk.Frame(self.frame_mg_tables)
        right_column.pack(fill = "x", pady = 5, side = "top")
        
        for sheet_name in self.max_growth_dictionary:
            frame = tk.Frame(left_column, width=150, height=80)
            frame.pack(padx=10, pady=5, anchor = "w")
            
            
            label = tk.Label(frame, text = sheet_name, font=self.sfont(12, "bold"))
            label.pack(padx = 5, pady = 5, anchor = "w")
            
            data = list(zip(self.max_growth_index_dictionary[sheet_name], self.max_growth_dictionary[sheet_name]))
            
            sheet = tksheet.Sheet(frame, data = data, headers = ["Well numbers", "Max Growth Values"], height = 150, width = 500)
            sheet.pack(padx=5, pady=5, expand=False)
        
            sheet.enable_bindings((
                     "single_select", "column_select", "edit_cell", "arrowkeys", "row_select", "ctrl_z", "ctrl_y"
                 ))
            
        save_button = ctk.CTkButton(right_column, text = "Save to .csv", width = 40, height = 30, command = self.max_to_csv)
        save_button.pack(padx = 10, pady = 20, anchor = "nw")
        
        return

    def max_to_csv(self):
        
        file_path = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV files", "*.csv"), ("All files", "*.*")], title="Save as")

        f = open(file_path, "a", newline="", encoding="utf-8")
        w = csv.writer(f)
        
        
        now = datetime.now()
        
        w.writerow([f"File creation: {now}"])
        
        w.writerow(["Bacteria names", "Well numbers", "Maximum Growth Values"])
        for sheet_name in self.max_growth_dictionary:
            for i in np.arange(0, len(self.max_growth_dictionary[sheet_name]), 1):
                w.writerow([sheet_name, self.max_growth_index_dictionary[sheet_name][i], self.max_growth_dictionary[sheet_name][i]])
                f.flush()
        f.close()
        
        return
    
    def show_menu_mg_rep(self, event):
        self.menu_mg_rep.post(event.x_root, event.y_root)
    
    def title_mg_reps(self):
        custom_mg_rep_title = tk.simpledialog.askstring("Plot Title", "Enter a title:")
        self.ax_max_replica.set_title(custom_mg_rep_title)
        self.canvas_max_growth_replica.draw()
        
    def xaxis_mg_reps(self):
        custom_mg_rep_xaxis = tk.simpledialog.askstring("Plot x axis", "Enter the name of the x axis:")
        self.ax_max_replica.set_xlabel(custom_mg_rep_xaxis)
        self.canvas_max_growth_replica.draw()
        return
    
    def yaxis_mg_reps(self):
        custom_mg_rep_yaxis = tk.simpledialog.askstring("Plot x axis", "Enter the name of the y axis:")
        self.ax_max_replica.set_ylabel(custom_mg_rep_yaxis)
        self.canvas_max_growth_replica.draw()
        return
    
    def save_mg_reps(self):
        file_path = filedialog.asksaveasfilename(defaultextension=".png", filetypes=[("PNG image", "*.png"), ("SVG image", "*.svg"), ("PDF file", "*.pdf"), ("All files", "*.*")])
        
        if file_path:
            self.fig_max_replica.savefig(file_path, dpi = 500)
        return
    
    def show_menu_mg_mean(self, event):
        self.menu_mg_mean.post(event.x_root, event.y_root)
    
    def title_mg_means(self):
        custom_mg_mean_title = tk.simpledialog.askstring("Plot Title", "Enter a title:")
        self.ax_max_selection.set_title(custom_mg_mean_title)
        self.canvas_max_growth_selection.draw()
        
    def xaxis_mg_means(self):
        custom_mg_mean_xaxis = tk.simpledialog.askstring("Plot x axis", "Enter the name of the x axis:")
        self.ax_max_selection.set_xlabel(custom_mg_mean_xaxis)
        self.canvas_max_growth_selection.draw()
        return
    
    def yaxis_mg_means(self):
        custom_mg_mean_yaxis = tk.simpledialog.askstring("Plot x axis", "Enter the name of the y axis:")
        self.ax_max_selection.set_ylabel(custom_mg_mean_yaxis)
        self.canvas_max_growth_selection.draw()
        return
    
    def save_mg_means(self):
        file_path = filedialog.asksaveasfilename(defaultextension=".png", filetypes=[("PNG image", "*.png"), ("SVG image", "*.svg"), ("PDF file", "*.pdf"), ("All files", "*.*")])
        
        if file_path:
            self.fig_max_selection.savefig(file_path, dpi = 500)
        return
    
    # %%
    ################# COMMANDS FOR THE DOUBLING TIME PLOT ################################################################
    def calculate_doubling_time(self):
        self.doubling_times = {}
        self.doubling_times_index = {}
        all_doubling_times = []
        
        for key, values in self.raw_data_dict.items():
            doubling_times_temp = []
            for i in np.arange(1,len(self.raw_data_dict[key])-1,1):
                
                
                
                y_values = np.array(self.raw_data_dict[key].iloc[i][self.onset_delays_index[key]:self.exponential_times_index[key]], dtype=float)
                y_values_pos = []
                for i in y_values: 
                    if i<0.0:
                        i = 0.0001
                        y_values_pos.append(i)
                    else:
                        y_values_pos.append(i)
                
                x_values = np.array(self.raw_data_dict[key].iloc[0][self.onset_delays_index[key]:self.exponential_times_index[key]], dtype=float)
 

                
                max_ln_gradient = trim_mean(np.gradient(np.log(y_values_pos), x_values), 0.2)
                     
                
                doubling_time = np.log(2)/max_ln_gradient
                
                doubling_times_temp.append(doubling_time)
            #duobling_time_mean_temp = doubling_times_temp.append(np.mean(doubling_times_temp))
            doubling_times_temp.append(np.mean(doubling_times_temp))
            self.doubling_times[key] = doubling_times_temp
            self.doubling_times_index[key] = self.raw_data_dict[key].index[1:]
        
        
        for widget in self.scrollable_doubling_tables.winfo_children():
            widget.destroy()
        
        self.frame_doubling_tables = tk.Frame(self.scrollable_doubling_tables)
        self.frame_doubling_tables.pack(padx=8, pady=10, fill = "x", expand = True)
        
        left_column = tk.Frame(self.frame_doubling_tables)
        left_column.pack(fill="x", pady=5, side = "left")
        
        right_column = tk.Frame(self.frame_doubling_tables)
        right_column.pack(fill = "x", pady = 5, side = "top")
        
        for sheet_name in self.doubling_times:
            frame = tk.Frame(left_column, width=150, height=80)
            frame.pack(padx=10, pady=5, anchor = "w")
            
            
            label = tk.Label(frame, text = sheet_name, font=self.sfont(12, "bold"))
            label.pack(padx = 5, pady = 5, anchor = "w")
            
            data = list(zip(self.doubling_times_index[sheet_name], self.doubling_times[sheet_name]))
            
            sheet = tksheet.Sheet(frame, data = data, headers = ["Well numbers", "Doubling Time Values"], height = 150, width = 500)
            sheet.pack(padx=5, pady=5, expand=False)
        
            sheet.enable_bindings((
                     "single_select", "column_select", "edit_cell", "arrowkeys", "row_select", "ctrl_z", "ctrl_y"
                 ))
            
        save_button = ctk.CTkButton(right_column, text = "Save to .csv", width = 40, height = 30, command = self.doubling_to_csv)
        save_button.pack(padx = 10, pady = 20, anchor = "nw")
        
        
        return
    
    def doubling_to_csv(self):
        file_path = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV files", "*.csv"), ("All files", "*.*")], title="Save as")

        f = open(file_path, "a", newline="", encoding="utf-8")
        w = csv.writer(f)
        
        
        now = datetime.now()
        
        w.writerow([f"File creation: {now}"])
        
        w.writerow(["Bacteria names", "Well numbers", "Doubling Time Values"])
        for sheet_name in self.doubling_times:
            for i in np.arange(0, len(self.doubling_times[sheet_name]), 1):
                w.writerow([sheet_name, self.doubling_times_index[sheet_name][i], self.doubling_times[sheet_name][i]])
                f.flush()
        f.close()
        
        return
    
    def plot_doubling_replicates(self, sheet, sheet_name):
        if not self._require_calc("doubling_times_index", "Calculate Doubling time", self.switch_vars_doubling.get(sheet_name)):
            return
        is_on = self.switch_vars_doubling[sheet_name].get()
        
        self.replicate_bars_doubling = {}

        # Clear previous bars for this sample if they exist
        if sheet_name in self.sheet_names_doubling_rep:
            self.sheet_names_doubling_rep.remove(sheet_name)
            self.ax_doubling_replicas.clear()
            temp_length = - 1
            for sheet_name in self.sheet_names_doubling_rep:
                length = len(self.doubling_times_index[sheet_name])
                temp_length = temp_length + length
                bars = self.ax_doubling_replicas.bar(self.doubling_times_index[sheet_name],
                self.doubling_times[sheet_name],
                label = sheet_name + ': CV='+ str(round(np.std(self.doubling_times[sheet_name][0:-1])/self.doubling_times[sheet_name][-1]*100, 2)) + "%", width = 0.5
            )
                temp_scatter = self.doubling_times[sheet_name][0:]
                self.ax_doubling_replicas.scatter([temp_length] * len(self.doubling_times_index[sheet_name]), temp_scatter, color = "black", s = 10, zorder = 3)
                self.replicate_bars_doubling[sheet_name] = bars
        else:
            self.sheet_names_doubling_rep.append(sheet_name)
            
        
        # If switch is ON, plot and store the bars
        if is_on:
            self.ax_doubling_replicas.clear()
            temp_length = - 1
            for sheet_name in self.sheet_names_doubling_rep:
                length = len(self.doubling_times_index[sheet_name])
                temp_length = temp_length + length
                bars = self.ax_doubling_replicas.bar(self.doubling_times_index[sheet_name],
                self.doubling_times[sheet_name],
                label = sheet_name + ': CV='+ str(round(np.std(self.doubling_times[sheet_name][0:-1])/self.doubling_times[sheet_name][-1]*100, 2)) + "%", width = 0.5
            )
                temp_scatter = self.doubling_times[sheet_name][0:]
                self.ax_doubling_replicas.scatter([temp_length] * len(self.doubling_times_index[sheet_name]), temp_scatter, color = "black", s = 10, zorder = 3)
                self.replicate_bars_doubling[sheet_name] = bars
            
            
        self.ax_doubling_replicas.set_title("Doubling time values")
        self.ax_doubling_replicas.set_ylabel("Doibling time values [min]")
        self.ax_doubling_replicas.set_xlabel("Sample names")
        self.ax_doubling_replicas.tick_params(axis='x', rotation=90)
        self._legend(self.ax_doubling_replicas, where="right")
        

        self.ax_doubling_replicas.relim()
        self.ax_doubling_replicas.autoscale_view()
        self.canvas_doubling_replicas.draw()

        
        return
    
    def plot_doubling_means(self, sheet, sheet_name):
        
        
        if not self._require_calc("doubling_times_index", "Calculate Doubling time", self.switch_vars_doubling_means.get(sheet_name)):
            return
        is_on = self.switch_vars_doubling_means[sheet_name].get()

        self.replicate_bars_doubling_means = {}

        # Clear previous bars for this sample if they exist
        if sheet_name in self.sheet_names_doubling_means:
            self.sheet_names_doubling_means.remove(sheet_name)
            self.ax_doubling_means.clear()
            for sheet_name in self.sheet_names_doubling_means:
                bars = self.ax_doubling_means.bar(self.doubling_times_index[sheet_name][-1],
                self.doubling_times[sheet_name][-1],
                label=sheet_name, width = 0.5
            )
                self.replicate_bars_doubling_means[sheet_name] = bars
        else:
            self.sheet_names_doubling_means.append(sheet_name)
            
        
        # If switch is ON, plot and store the bars
        if is_on:
            self.ax_doubling_means.clear()
            for sheet_name in self.sheet_names_doubling_means:
                bars = self.ax_doubling_means.bar(self.doubling_times_index[sheet_name][-1],
                self.doubling_times[sheet_name][-1],
                label=sheet_name, width = 0.5
            )
                self.replicate_bars_doubling_means[sheet_name] = bars
            
            
        self.ax_doubling_means.set_title("Mean doubling time values")
        self.ax_doubling_means.set_ylabel("Mean doubling time values [min]")
        self.ax_doubling_means.set_xlabel("Sample names")
        self.ax_doubling_means.tick_params(axis='x', rotation=90)
        self._legend(self.ax_doubling_means, where="right")
        

        self.ax_doubling_means.relim()
        self.ax_doubling_means.autoscale_view()
        self.canvas_doubling_means.draw()

        
        return
    
    
    def show_menu_doubling_rep(self, event):
        self.menu_doubling_rep.post(event.x_root, event.y_root)
    
    def title_doubling_reps(self):
        custom_doubling_rep_title = tk.simpledialog.askstring("Plot Title", "Enter a title:")
        self.ax_doubling_replicas.set_title(custom_doubling_rep_title)
        self.canvas_doubling_replicas.draw()
        
    def xaxis_doubling_reps(self):
        custom_doubling_rep_xaxis = tk.simpledialog.askstring("Plot x axis", "Enter the name of the x axis:")
        self.ax_doubling_replicas.set_xlabel(custom_doubling_rep_xaxis)
        self.canvas_doubling_replicas.draw()
        return
    
    def yaxis_doubling_reps(self):
        custom_doubling_rep_yaxis = tk.simpledialog.askstring("Plot x axis", "Enter the name of the y axis:")
        self.ax_doubling_replicas.set_ylabel(custom_doubling_rep_yaxis)
        self.canvas_doubling_replicas.draw()
        return
    
    def save_doubling_reps(self):
        file_path = filedialog.asksaveasfilename(defaultextension=".png", filetypes=[("PNG image", "*.png"), ("SVG image", "*.svg"), ("PDF file", "*.pdf"), ("All files", "*.*")])
        
        if file_path:
            self.fig_doubling_replicas.savefig(file_path, dpi = 500)
        return
    
    def show_menu_doubling_mean(self, event):
        self.menu_doubling_mean.post(event.x_root, event.y_root)
    
    def title_doubling_means(self):
        custom_doubling_mean_title = tk.simpledialog.askstring("Plot Title", "Enter a title:")
        self.ax_doubling_means.set_title(custom_doubling_mean_title)
        self.canvas_doubling_means.draw()
        
    def xaxis_doubling_means(self):
        custom_doubling_mean_xaxis = tk.simpledialog.askstring("Plot x axis", "Enter the name of the x axis:")
        self.ax_doubling_means.set_xlabel(custom_doubling_mean_xaxis)
        self.canvas_doubling_means.draw()
        return
    
    def yaxis_doubling_means(self):
        custom_doubling_mean_yaxis = tk.simpledialog.askstring("Plot x axis", "Enter the name of the y axis:")
        self.ax_doubling_means.set_ylabel(custom_doubling_mean_yaxis)
        self.canvas_doubling_means.draw()
        return
    
    def save_doubling_means(self):
        file_path = filedialog.asksaveasfilename(defaultextension=".png", filetypes=[("PNG image", "*.png"), ("SVG image", "*.svg"), ("PDF file", "*.pdf"), ("All files", "*.*")])
        
        if file_path:
            self.fig_doubling_means.savefig(file_path, dpi = 500)
        return  

    
    # %%
    ################# COMMANDS FOR THE SCORE TAB ########################################################################
    
    def calculate_score(self):
        # The score combines results from three other calculations. If any of
        # them has not been run, the loop below would silently produce nothing,
        # so check the prerequisites first and tell the user exactly what to do.
        missing = []
        if not getattr(self, "auc_dictionary", None):
            missing.append("Calculate AUC (AUC and onset delay tab)")
        if not getattr(self, "doubling_times", None):
            missing.append("Calculate doubling time (Doubling time tab)")
        if not getattr(self, "max_growth_dictionary", None):
            missing.append("Maximum growth calculation (Maximum growth tab)")
        if missing:
            msg = ("The score needs these calculations first:\n  - "
                   + "\n  - ".join(missing))
            self.log_message("Score needs: " + "; ".join(missing))
            messagebox.showinfo("Calculate prerequisites first", msg)
            return

        self.edr_values = {}
        
        for sheet_name, val in self.auc_dictionary.items():
            edr_temp = []
            for i in np.arange(0, len(self.auc_index_dictionary[sheet_name]), 1):
                edr = ((self.exponential_times[sheet_name])/(self.exponential_times[sheet_name]+self.onset_delays[sheet_name]))*(1/self.doubling_times[sheet_name][i])
                N = np.log2(self.max_growth_dictionary[sheet_name][i]/self.initial_values_dictionary[sheet_name][0])
                edr_temp.append(edr*(self.auc_dictionary_log[sheet_name][i] + self.auc_dictionary_stationary[sheet_name][i]))
            self.edr_values[sheet_name] = edr_temp
             
        for widget in self.scrollable_score_tables.winfo_children():
            widget.destroy()
        
        self.frame_score_tables = tk.Frame(self.scrollable_score_tables)
        self.frame_score_tables.pack(padx=8, pady=10, fill = "x", expand = True)
        
        left_column = tk.Frame(self.frame_score_tables)
        left_column.pack(fill="x", pady=5, side = "left")
        
        right_column = tk.Frame(self.frame_score_tables)
        right_column.pack(fill = "x", pady = 5, side = "top")
        
        for sheet_name in self.edr_values:
            frame = tk.Frame(left_column, width=150, height=80)
            frame.pack(padx=10, pady=5, anchor = "w")
            
            
            label = tk.Label(frame, text = sheet_name, font=self.sfont(12, "bold"))
            label.pack(padx = 5, pady = 5, anchor = "w")
            
            data = list(zip(self.doubling_times_index[sheet_name], self.edr_values[sheet_name]))
            
            sheet = tksheet.Sheet(frame, data = data, headers = ["Well numbers", "Index Values"], height = 150, width = 500)
            sheet.pack(padx=5, pady=5, expand=False)
        
            sheet.enable_bindings((
                     "single_select", "column_select", "edit_cell", "arrowkeys", "row_select", "ctrl_z", "ctrl_y"
                 ))
            
        save_button = ctk.CTkButton(right_column, text = "Save to .csv", width = 40, height = 30, command = self.score_to_csv)
        save_button.pack(padx = 10, pady = 20, anchor = "nw")
        return
    
    def plot_score_replicates(self, sheet, sheet_name):
        if not self._require_calc("edr_values", "Calculate Index", self.switch_vars_score.get(sheet_name)):
            return
        is_on = self.switch_vars_score[sheet_name].get()
        
        self.replicate_bars_score = {}

        # Clear previous bars for this sample if they exist
        if sheet_name in self.sheet_names_score_rep:
            self.sheet_names_score_rep.remove(sheet_name)
            self.ax_score_replicas.clear()
            temp_length = - 1
            for sheet_name in self.sheet_names_score_rep:
                length = len(self.doubling_times_index[sheet_name])
                temp_length = temp_length + length
                bars = self.ax_score_replicas.bar(self.doubling_times_index[sheet_name],
                self.edr_values[sheet_name],
                label = sheet_name + ': CV='+ str(round(np.std(self.edr_values[sheet_name][0:-1])/self.edr_values[sheet_name][-1]*100, 2)) + "%", width = 0.5
            )
                temp_scatter = self.edr_values[sheet_name][0:]
                self.ax_score_replicas.scatter([temp_length] * len(self.doubling_times_index[sheet_name]), temp_scatter, color = "black", s = 10, zorder = 3)
                self.replicate_bars_score[sheet_name] = bars
        else:
            self.sheet_names_score_rep.append(sheet_name)
            
        
        # If switch is ON, plot and store the bars
        if is_on:
            self.ax_score_replicas.clear()
            temp_length = - 1
            for sheet_name in self.sheet_names_score_rep:
                length = len(self.doubling_times_index[sheet_name])
                temp_length = temp_length + length
                bars = self.ax_score_replicas.bar(self.doubling_times_index[sheet_name],
                self.edr_values[sheet_name],
                label = sheet_name + ': CV='+ str(round(np.std(self.edr_values[sheet_name][0:-1])/self.edr_values[sheet_name][-1]*100, 2)) + "%", width = 0.5
            )
                temp_scatter = self.edr_values[sheet_name][0:]
                self.ax_score_replicas.scatter([temp_length] * len(self.doubling_times_index[sheet_name]), temp_scatter, color = "black", s = 10, zorder = 3)
                self.replicate_bars_score[sheet_name] = bars
            
            
        self.ax_score_replicas.set_title("BGI values")
        self.ax_score_replicas.set_ylabel("BGI values [a.u.]")
        self.ax_score_replicas.set_xlabel("Sample names")
        self.ax_score_replicas.tick_params(axis='x', rotation=90)
        self._legend(self.ax_score_replicas, where="right")
        

        self.ax_score_replicas.relim()
        self.ax_score_replicas.autoscale_view()
        self.canvas_score_replicas.draw()
        return
    
    def plot_score_means(self, sheet, sheet_name):
        if not self._require_calc("edr_values", "Calculate Index", self.switch_vars_score_means.get(sheet_name)):
            return
        is_on = self.switch_vars_score_means[sheet_name].get()

        self.replicate_bars_score_means = {}

        # Clear previous bars for this sample if they exist
        if sheet_name in self.sheet_names_score_means:
            self.sheet_names_score_means.remove(sheet_name)
            self.ax_score_means.clear()
            for sheet_name in self.sheet_names_score_means:
                bars = self.ax_score_means.bar(self.doubling_times_index[sheet_name][-1],
                self.edr_values[sheet_name][-1],
                label=sheet_name, width = 0.5
            )
                self.replicate_bars_score_means[sheet_name] = bars
        else:
            self.sheet_names_score_means.append(sheet_name)
            
        
        # If switch is ON, plot and store the bars
        if is_on:
            self.ax_score_means.clear()
            for sheet_name in self.sheet_names_score_means:
                bars = self.ax_score_means.bar(self.doubling_times_index[sheet_name][-1],
                self.edr_values[sheet_name][-1],
                label=sheet_name, width = 0.5
            )
                self.replicate_bars_score_means[sheet_name] = bars
            
            
        self.ax_score_means.set_title("Mean BGI values")
        self.ax_score_means.set_ylabel("Mean BGI values [a.u.]")
        self.ax_score_means.set_xlabel("Sample names")
        self.ax_score_means.tick_params(axis='x', rotation=90)
        self._legend(self.ax_score_means, where="right")
        

        self.ax_score_means.relim()
        self.ax_score_means.autoscale_view()
        self.canvas_score_means.draw()
        
        
        return
    
    def score_to_csv(self):
        file_path = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV files", "*.csv"), ("All files", "*.*")], title="Save as")

        f = open(file_path, "a", newline="", encoding="utf-8")
        w = csv.writer(f)
        
        
        now = datetime.now()
        
        w.writerow([f"File creation: {now}"])
        
        w.writerow(["Bacteria names", "Well numbers", "BGI Values"])
        for sheet_name in self.edr_values:
            for i in np.arange(0, len(self.edr_values[sheet_name]), 1):
                w.writerow([sheet_name, self.doubling_times_index[sheet_name][i], self.edr_values[sheet_name][i]])
                f.flush()
        f.close()
        return
    
    def show_menu_score_rep(self, event):
        self.menu_score_rep.post(event.x_root, event.y_root)
    
    def title_score_reps(self):
        custom_score_rep_title = tk.simpledialog.askstring("Plot Title", "Enter a title:")
        self.ax_score_replicas.set_title(custom_score_rep_title)
        self.canvas_score_replicas.draw()
        
    def xaxis_score_reps(self):
        custom_score_rep_xaxis = tk.simpledialog.askstring("Plot x axis", "Enter the name of the x axis:")
        self.ax_score_replicas.set_xlabel(custom_score_rep_xaxis)
        self.canvas_score_replicas.draw()
        return
    
    def yaxis_score_reps(self):
        custom_score_rep_yaxis = tk.simpledialog.askstring("Plot x axis", "Enter the name of the y axis:")
        self.ax_score_replicas.set_ylabel(custom_score_rep_yaxis)
        self.canvas_score_replicas.draw()
        return
    
    def save_score_reps(self):
        file_path = filedialog.asksaveasfilename(defaultextension=".png", filetypes=[("PNG image", "*.png"), ("SVG image", "*.svg"), ("PDF file", "*.pdf"), ("All files", "*.*")])
        
        if file_path:
            self.fig_score_replicas.savefig(file_path, dpi = 500)
        return  

    
    def show_menu_score_means(self, event):
        self.menu_score_means.post(event.x_root, event.y_root)
    
    def title_score_means(self):
        custom_score_mean_title = tk.simpledialog.askstring("Plot Title", "Enter a title:")
        self.ax_score_means.set_title(custom_score_mean_title)
        self.canvas_score_means.draw()
        
    def xaxis_score_means(self):
        custom_score_mean_xaxis = tk.simpledialog.askstring("Plot x axis", "Enter the name of the x axis:")
        self.ax_score_means.set_xlabel(custom_score_mean_xaxis)
        self.canvas_score_means.draw()
        return
    
    def yaxis_score_means(self):
        custom_score_mean_yaxis = tk.simpledialog.askstring("Plot x axis", "Enter the name of the y axis:")
        self.ax_score_means.set_ylabel(custom_score_mean_yaxis)
        self.canvas_score_means.draw()
        return
    
    def save_score_means(self):
        file_path = filedialog.asksaveasfilename(defaultextension=".png", filetypes=[("PNG image", "*.png"), ("SVG image", "*.svg"), ("PDF file", "*.pdf"), ("All files", "*.*")])
        
        if file_path:
            self.fig_score_means.savefig(file_path, dpi = 500)
        return
    
    # %%
    # %%
    ################# COMMANDS FOR THE METADATA TAB #######################################################################
    # %%
    
    def load_metadata(self):

        frame = tk.Frame(self.tab5)
        frame.pack(fill="both", expand=True, padx=10, pady=10)

        label = tk.Label(frame, text="Metadata" + " - " + self.meta_excel_name, font=self.sfont(12, "bold"))
        label.pack(anchor="w", pady=(0, 6))

        # Create tksheet
        self.metadata_sheet = tksheet.Sheet(frame, data=self.df_metadata.values.tolist(), headers=list(self.df_metadata.columns))
        self.metadata_sheet.pack(fill="both", expand=True)

        self.metadata_sheet.enable_bindings((
                "single_select", "column_select", "edit_cell", "arrowkeys", "row_select", "ctrl_z", "ctrl_y"
            ))
        
        button_metadata_update = ctk.CTkButton(frame, text = "Update Metadata", width = 30, height = 30, command = self.update_metadata)
        button_metadata_update.pack(padx=10, pady=10, side = "bottom", fill=None, expand=False)
        
        button_save_metadata = ctk.CTkButton(frame, text = "Save Metadata", width = 30, height = 30, command = self.save_metadata_to_excel)
        button_save_metadata.pack(padx=10, pady=10, side = "bottom", fill=None, expand=False)
        
        return
    
    def update_metadata(self):
        data = self.metadata_sheet.get_sheet_data()
        headers = self.metadata_sheet.headers()
        self.df_metadata = pd.DataFrame(data, columns=headers)
        return    
    
    def save_metadata_to_excel(self):
        file_path = filedialog.asksaveasfilename(defaultextension=".xlsx", filetypes=[("Excel files", "*.xlsx")], title="Save as")
        if file_path:
            self.df_metadata.to_excel(file_path, index = False)
       
        
            
        return
        
    
    

    
app = App()