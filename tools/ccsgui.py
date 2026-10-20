#!/usr/bin/env python3
"""ccsgui - control window for the MW4 texture streaming toolkit (hosts override, proxy, mirror, disk guard, logs, doctor, reports).

  python tools/ccsgui.py            (or tools/ccs-gui.bat)         --selftest builds the window headless-ish, polls once and exits

Runs UNELEVATED. Only hosts-file changes need admin; they go through tools/ccshosts.py with a UAC prompt.
Children (proxy, diskguard) are detached processes tracked by pid files, so closing/restarting the GUI does not lose them.
See docs/USAGE.md.
"""
import collections, ctypes, json, os, queue, re, subprocess, sys, threading, time
import tkinter as tk
from tkinter import ttk, messagebox

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ccslib import cachectl, config, doctor, gamefix, guide, hosts, launch, logtail, mirrorctl, pack, paths, procs, proxyctl, report, session, version

BG, PANEL, FG, DIM, ACC = '#16181d', '#1e2128', '#d7dae0', '#8b93a1', '#4c8dff'
OK, WARN, BAD, OFF = '#3ecf6e', '#e8b43a', '#ec5b5b', '#555b66'
REQ_RE = re.compile(r'\b(GET|HEAD) /pc/')
LOG_SOURCES = (('proxy', proxyctl.PROXY_LOG), ('guard', proxyctl.GUARD_LOG), ('mirror', proxyctl.MIRROR_LOG), ('netwatch', os.path.join(paths.WORK, 'netwatch.log')),
               ('gui', os.path.join(paths.WORK, 'ccsgui.log')))


HOSTS_HINT = ('Permission denied? The hosts file is protected on purpose. Things that block this tool even as admin: the read-only attribute (attrib -r on the hosts file), or security software with hosts-file protection (pause it for a moment or allow python.exe). The tool never turns off security software and never changes file permissions for you; a failed write leaves the file unchanged. See docs/USAGE.md, Troubleshooting.')


class Tip:
    """Small hover tooltip (one per widget)."""
    def __init__(self, widget, text, delay=500, wrap=360):
        self.w, self.text, self.delay, self.wrap, self.win, self.job = widget, text, delay, wrap, None, None
        widget.bind('<Enter>', self._enter, add='+'); widget.bind('<Leave>', self._hide, add='+'); widget.bind('<ButtonPress>', self._hide, add='+')

    def _enter(self, _e=None): self._hide(); self.job = self.w.after(self.delay, self._show)

    def _show(self):
        try:
            self.win = tk.Toplevel(self.w); self.win.wm_overrideredirect(True)
            self.win.wm_geometry(f'+{self.w.winfo_rootx() + 12}+{self.w.winfo_rooty() + self.w.winfo_height() + 6}')
            tk.Label(self.win, text=self.text, justify='left', wraplength=self.wrap, bg=PANEL, fg=FG, relief='solid', borderwidth=1, padx=8, pady=6, font=('Segoe UI', 9)).pack()
        except tk.TclError: self.win = None

    def _hide(self, _e=None):
        if self.job: self.w.after_cancel(self.job); self.job = None
        if self.win: self.win.destroy(); self.win = None


def fmt_dur(s):
    s = int(s); return f'{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}'


class App(tk.Tk):
    SPOT_BASE = dict(btn_start='Accent.TButton', btn_stop='TButton', btn_doctor='TButton')          # the style a highlighted button goes back to

    def __init__(self, selftest=False):                                      # selftest: no first-run dialogs (nobody is there to answer them)
        super().__init__()
        paths.ensure_dirs()
        self._set_icon(); self.title(f'MW4 Texture Streaming Toolkit {version.__version__}'); self.geometry('1180x760'); self.minsize(980, 620); self.configure(bg=BG)
        self.cfg = config.load(); self.snap = {}; self.q = queue.Queue(); self.busy = False
        self.rate = collections.deque(maxlen=12); self.series = collections.deque(maxlen=180); self._game_prev = False; self._guide_game_seen = False; self._guide_last = None; self._gfc = None; self._guide_sig = None; self._guide_lbl = {}; self._guide_peak = None; self._spot_key = None; self.game_start = None; self.tails = {n: logtail.Tail(p, 150) for n, p in LOG_SOURCES}
        self.log_lines = collections.deque(maxlen=6000); self.gui_log_path = dict(LOG_SOURCES)['gui']
        self._style(); self._build()
        self.protocol('WM_DELETE_WINDOW', self.on_close)
        self.stop_poll = threading.Event(); threading.Thread(target=self._poller, daemon=True).start()
        self.after(300, self._drain); self.after(700, self._refresh); self.after(500, self._tail_logs); self.after(250, self._guide_tick_safe)
        if not selftest: self.after(1200, self._first_run_notice)
        self.say('CCS Control started' + ('  (running as admin)' if procs.is_admin() else '  (unelevated; hosts changes use UAC)'))

    def _set_icon(self):
        p = launch.resource('app.ico')
        if p:
            try: self.iconbitmap(default=p)
            except tk.TclError: pass

    def _first_run_notice(self):
        """Show the research / responsibility notice once per version."""
        if self.cfg.get('notice_ack') != version.__version__:
            messagebox.showinfo('Before you start', version.NOTICE, parent=self); self.cfg['notice_ack'] = version.__version__; config.save(self.cfg)
        self._offer_guide()

    # ---------------------------------------------------------------- theme / widgets
    def _style(self):
        s = ttk.Style(self); s.theme_use('clam')
        s.configure('.', background=BG, foreground=FG, fieldbackground=PANEL, bordercolor='#2a2e37', lightcolor=PANEL, darkcolor=PANEL, troughcolor=PANEL, font=('Segoe UI', 10))
        s.configure('TNotebook', background=BG, borderwidth=0); s.configure('TNotebook.Tab', background=PANEL, foreground=DIM, padding=(14, 6))
        s.map('TNotebook.Tab', background=[('selected', BG)], foreground=[('selected', FG)])
        s.configure('TButton', background='#2b3039', foreground=FG, padding=(12, 6), borderwidth=0); s.map('TButton', background=[('active', '#363c48'), ('disabled', PANEL)], foreground=[('disabled', OFF)])
        s.configure('Accent.TButton', background=ACC, foreground='white'); s.map('Accent.TButton', background=[('active', '#6aa0ff'), ('disabled', PANEL)])
        s.configure('Spot.TButton', background=WARN, foreground=BG); s.map('Spot.TButton', background=[('active', '#f0c75e'), ('disabled', PANEL)], foreground=[('disabled', OFF)])
        s.configure('Danger.TButton', background='#7a2e32', foreground='white'); s.map('Danger.TButton', background=[('active', '#963a3f'), ('disabled', PANEL)])
        s.configure('TLabel', background=BG, foreground=FG); s.configure('Dim.TLabel', foreground=DIM); s.configure('H.TLabel', font=('Segoe UI Semibold', 11))
        s.configure('TFrame', background=BG); s.configure('Card.TFrame', background=PANEL); s.configure('TLabelframe', background=BG, bordercolor='#2a2e37'); s.configure('TLabelframe.Label', background=BG, foreground=DIM)
        s.configure('TCheckbutton', background=BG, foreground=FG); s.configure('Treeview', background=PANEL, fieldbackground=PANEL, foreground=FG, rowheight=22, borderwidth=0)
        s.configure('Treeview.Heading', background='#2b3039', foreground=FG); s.map('Treeview', background=[('selected', '#31507f')])
        s.configure('TEntry', insertcolor=FG, fieldbackground=PANEL, foreground=FG)
        s.configure('TCombobox', arrowcolor=FG, background='#2b3039', foreground=FG, fieldbackground=PANEL)
        s.map('TCombobox', fieldbackground=[('readonly', PANEL)], foreground=[('readonly', FG)], selectbackground=[('readonly', PANEL)], selectforeground=[('readonly', FG)], background=[('readonly', '#2b3039')])
        s.configure('Horizontal.TProgressbar', background=ACC, troughcolor=PANEL, bordercolor=PANEL, lightcolor=ACC, darkcolor=ACC)
        s.configure('TScrollbar', background='#2b3039', troughcolor=PANEL, arrowcolor=FG, bordercolor=PANEL); s.map('TScrollbar', background=[('active', '#363c48')])
        self.option_add('*TCombobox*Listbox.background', PANEL); self.option_add('*TCombobox*Listbox.foreground', FG); self.option_add('*TCombobox*Listbox.selectBackground', '#31507f')

    def _text(self, parent, h=10, **kw):
        t = tk.Text(parent, bg=PANEL, fg=FG, insertbackground=FG, relief='flat', height=h, font=('Consolas', 9), wrap='none', **kw)
        t.tag_config('ERR', foreground=BAD); t.tag_config('WARN', foreground=WARN); t.tag_config('OK', foreground=OK); t.tag_config('DIM', foreground=DIM); t.tag_config('ACC', foreground=ACC)
        return t

    def _scrolled(self, parent, h=10):
        f = ttk.Frame(parent); t = self._text(f, h); sy = ttk.Scrollbar(f, command=t.yview); t.configure(yscrollcommand=sy.set, state='disabled')
        t.pack(side='left', fill='both', expand=True); sy.pack(side='right', fill='y'); return f, t

    def _put(self, t, text, tag=None, scroll=True):
        t.configure(state='normal'); t.insert('end', text + '\n', tag or ());
        if int(t.index('end-1c').split('.')[0]) > 4000: t.delete('1.0', '500.0')
        t.configure(state='disabled')
        if scroll: t.see('end')

    def _build(self):
        top = ttk.Frame(self); top.pack(fill='x', padx=12, pady=(10, 4))
        self.lights = {}
        for key, label in (('hosts', 'Hosts'), ('resolve', 'Resolver'), ('proxy', 'Proxy'), ('port', 'Port'), ('mirror', 'Mirror'), ('guard', 'Guard'), ('game', 'Game'), ('disk', 'Disk')):
            f = ttk.Frame(top, style='Card.TFrame'); f.pack(side='left', padx=3, ipadx=6, ipady=3)
            dot = tk.Label(f, text='●', fg=OFF, bg=PANEL, font=('Segoe UI', 13)); dot.pack(side='left', padx=(6, 2))
            nm = tk.Label(f, text=label, fg=DIM, bg=PANEL, font=('Segoe UI', 8)); nm.pack(side='top', anchor='w', padx=(0, 6))
            val = tk.Label(f, text='-', fg=FG, bg=PANEL, font=('Segoe UI', 9)); val.pack(side='top', anchor='w', padx=(0, 6)); self.lights[key] = (dot, val)
            for w in (f, dot, nm, val): Tip(w, guide.LIGHT_HELP[key])                                      # what each light means, on hover
        self.nb = ttk.Notebook(self); self.nb.pack(fill='both', expand=True, padx=12, pady=(4, 12))
        self.tabs = {}
        for name, fn in (('Dashboard', self._tab_dash), ('Proxy', self._tab_proxy), ('Texture pack', self._tab_pack), ('Mirror', self._tab_mirror), ('Cache', self._tab_cache), ('Game', self._tab_game), ('Doctor', self._tab_doctor), ('Report', self._tab_report), ('Hosts / DNS', self._tab_hosts),
                         ('Logs', self._tab_logs), ('Settings', self._tab_settings)):
            f = ttk.Frame(self.nb); self.nb.add(f, text=name); self.tabs[name] = f; fn(f)
        self._apply_view(); self._sync_caps(); self.after(900, self.pack_refresh)

    def light(self, key, level, text):
        dot, val = self.lights[key]; dot.configure(fg={'ok': OK, 'warn': WARN, 'fail': BAD, 'off': OFF}[level]); val.configure(text=text)

    # ---------------------------------------------------------------- tabs
    def _tab_dash(self, f):
        slot_banner = ttk.Frame(f); slot_banner.pack(fill='x'); slot_guide = ttk.Frame(f); slot_guide.pack(fill='x')          # fixed places, so either can come and go without moving the other
        self.setup_banner = tk.Label(slot_banner, text='', fg='white', bg='#7a2e32', anchor='w', padx=10, font=('Segoe UI', 10, 'bold'))      # packed only while something needs setting up
        gh = ttk.Frame(slot_guide); ttk.Label(gh, text='Guided setup (optional)').pack(side='left', padx=(0, 14))
        for text, cmd, tip in (('Start over', lambda: self.guide_do('restart'), 'Run the checklist again from the session step.'),
                               ('Simple view', lambda: self.guide_do('view'), 'Hide the advanced tabs and the detailed counters. Press again for the full view.'),
                               ('Words', lambda: self.guide_do('glossary'), 'What the words used in this window mean.'),
                               ('Before/after test', lambda: self.guide_do('abtest'), 'A short guided test to compare the game with and without the tool on your PC.'),
                               ('Hide', lambda: self.guide_toggle(False), 'Close this checklist. The Guide button brings it back.')):
            b = ttk.Button(gh, text=text, command=cmd); b.pack(side='left', padx=2); Tip(b, tip)
            if text == 'Simple view': self.btn_view = b
        self.guide_frame = ttk.LabelFrame(slot_guide, labelwidget=gh); self.guide_body = ttk.Frame(self.guide_frame); self.guide_body.pack(fill='x', padx=10, pady=(4, 6)); self.guide_body.bind('<Configure>', self._guide_wrap)
        gs = guide.clean_state(self.cfg.get('guide')); self.sv_guide = tk.BooleanVar(value=gs['enabled']); self.sv_simple = tk.BooleanVar(value=gs['simple'])
        if self.sv_guide.get(): self.guide_frame.pack(fill='x', pady=(8, 0))
        row = self.dash_row = ttk.Frame(f); row.pack(fill='x', pady=10)
        self.prof_box = pf = ttk.Frame(row); pf.pack(side='left')
        ttk.Label(pf, text='Profile').pack(side='left'); self.profile = tk.StringVar(value=self.cfg['profile'])
        self.prof_cb = ttk.Combobox(pf, textvariable=self.profile, values=list(config.all_profiles(self.cfg)), state='readonly', width=16); self.prof_cb.pack(side='left', padx=(6, 2)); self.prof_cb.bind('<<ComboboxSelected>>', self._profile_changed)
        ttk.Button(pf, text='Save as...', command=self.profile_save_as).pack(side='left', padx=2); ttk.Button(pf, text='Delete', command=self.profile_delete).pack(side='left', padx=(2, 14))
        self.btn_start = ttk.Button(row, text='Start session', style='Accent.TButton', command=self.do_start); self.btn_start.pack(side='left', padx=4)
        self.btn_stop = ttk.Button(row, text='Stop session', command=self.do_stop); self.btn_stop.pack(side='left', padx=4)
        ttk.Button(row, text='Restore hosts (remove override)', style='Danger.TButton', command=self.do_hosts_remove).pack(side='left', padx=4)
        self.btn_doctor = ttk.Button(row, text='Doctor', command=self.do_doctor); self.btn_doctor.pack(side='left', padx=4)
        ttk.Button(row, text='Guide', command=self.guide_toggle).pack(side='left', padx=4)
        self.prof_desc = ttk.Label(f, text='', style='Dim.TLabel'); self.prof_desc.pack(anchor='w'); self._profile_changed()
        self.simple_note = ttk.Label(f, text='Simple view is on: the advanced tabs are hidden. Settings -> Help (or the Full view button in the guide) brings them back.', style='Dim.TLabel')
        self.cnt_box = g = ttk.LabelFrame(f, text='Live (proxy)'); g.pack(fill='x', pady=10); self.cnt = {}; self.cnt_cells = {}; self.cnt_lbl = {}; self.cnt_names = {}; self.cnt_order = []
        for k, lab in (('req', 'Requests'), ('mirror', 'From mirror'), ('upok', 'Upstream OK'), ('err', 'Errors'), ('retry', 'Retries'), ('cliabort', 'Client aborts'),
                       ('skip', 'Tier-skipped'), ('miss', 'Misses/404'), ('mgib', 'Mirror GiB'), ('ugib', 'Upstream GiB'), ('rps', 'Req/s (12s)'), ('sess', 'Session time')):
            c = ttk.Frame(g); name = ttk.Label(c, text=lab, style='Dim.TLabel'); name.pack(anchor='w')
            l = ttk.Label(c, text='-', style='H.TLabel'); l.pack(anchor='w'); self.cnt[k] = l; self.cnt_cells[k] = c; self.cnt_lbl[k] = name; self.cnt_names[k] = lab; self.cnt_order.append(k)
            for w in (c, name, l): Tip(w, guide.COUNTER_HELP[k])
        self.spark_box = sp = ttk.LabelFrame(f, text='Throughput, last 3 min  (blue = requests/s, green = MiB/s served)'); sp.pack(fill='x', pady=(0, 8))
        self.spark = tk.Canvas(sp, height=84, bg=PANEL, highlightthickness=0); self.spark.pack(fill='x', padx=8, pady=6)
        ttk.Label(f, text='Activity', style='H.TLabel').pack(anchor='w'); fr, self.act = self._scrolled(f, 10); fr.pack(fill='both', expand=True, pady=(4, 0))

    def _tab_proxy(self, f):
        form = ttk.LabelFrame(f, text='Proxy options (apply with restart)'); form.pack(fill='x', pady=10); self.pv = {}
        self.pe = {}
        def field(r, c, key, label, w=9):
            ttk.Label(form, text=label).grid(row=r, column=c * 2, sticky='e', padx=(12, 4), pady=6); v = tk.StringVar(value=str(self.cfg['proxy'][key]))
            e = ttk.Entry(form, textvariable=v, width=w); e.grid(row=r, column=c * 2 + 1, sticky='w'); self.pv[key] = v; self.pe[key] = e
        field(0, 0, 'max_raw_mib', 'Tier cap (MiB raw; set by Texture pack)'); field(0, 1, 'budget_gib', 'Upstream budget (GiB)'); field(0, 2, 'retries', 'Retries'); field(0, 3, 'port', 'Port')
        field(1, 0, 'upstream_ip', 'Upstream IP (blank=auto)', 16)
        self.pv_origin = tk.BooleanVar(value=self.cfg['proxy']['origin']); self.pv_off = tk.BooleanVar(value=self.cfg['proxy']['offline'])
        ttk.Checkbutton(form, text='Serve from mirror first', variable=self.pv_origin).grid(row=1, column=2, columnspan=2, sticky='w', padx=12)
        ttk.Checkbutton(form, text='Offline (mirror misses -> 404)', variable=self.pv_off).grid(row=1, column=4, columnspan=3, sticky='w')
        b = ttk.Frame(form); b.grid(row=2, column=0, columnspan=8, sticky='w', padx=10, pady=8)
        ttk.Button(b, text='Save + restart proxy', style='Accent.TButton', command=self.do_proxy_restart).pack(side='left', padx=4)
        ttk.Button(b, text='Start proxy only', command=lambda: self.bg('proxy start', self._proxy_only, True)).pack(side='left', padx=4)
        ttk.Button(b, text='Stop proxy only', command=lambda: self.bg('proxy stop', self._proxy_only, False)).pack(side='left', padx=4)
        ttk.Label(form, text='Profile overrides mirror/offline at run time (Dashboard). Saved values here are the base.', style='Dim.TLabel').grid(row=3, column=0, columnspan=8, sticky='w', padx=12, pady=(0, 8))
        mid = ttk.Frame(f); mid.pack(fill='both', expand=True)
        left = ttk.LabelFrame(mid, text='Requested chunk size tier (decoded size)'); left.pack(side='left', fill='y', padx=(0, 10))
        self.hist = tk.Canvas(left, width=360, height=250, bg=PANEL, highlightthickness=0); self.hist.pack(padx=8, pady=8)
        ttk.Label(left, text='The 8M / 16M bars are the largest pieces, the ones a 4K-class texture setting asks for.', style='Dim.TLabel', wraplength=340).pack(padx=8, pady=(0, 8))
        right = ttk.LabelFrame(mid, text='Recent requests'); right.pack(side='left', fill='both', expand=True)
        cols = ('time', 'id', 'raw', 'tier', 'src', 'status', 'bytes'); self.recent = ttk.Treeview(right, columns=cols, show='headings', height=12)
        for c, w in zip(cols, (70, 150, 80, 60, 90, 60, 80)): self.recent.heading(c, text=c); self.recent.column(c, width=w, anchor='w')
        self.recent.pack(fill='both', expand=True, padx=6, pady=6)

    # ---------------------------------------------------------------- Texture pack tab
    def _tab_pack(self, f):
        pk = self.cfg['pack']; self.pk_scope = tk.StringVar(value=pk['scope']); self.pk_level = tk.StringVar(value=config.effective(self.cfg)['pack']['level']); self._pack_plan = None
        self.pk_pkgs = {k: tk.BooleanVar(value=k in (pk.get('packages') or ())) for k in pack.ORDER}; self.pk_num = {}
        ttk.Label(f, text='Download the texture chunks to the local mirror once (resumable, any speed), then play offline from it. Chunk lists come from your own game install; '
                          'the data goes only to this PC and is never shared.', style='Dim.TLabel', wraplength=1120).pack(anchor='w', pady=(8, 4))
        row = ttk.Frame(f); row.pack(fill='x')
        a = ttk.LabelFrame(row, text='1. What to download (pack scope)'); a.pack(side='left', fill='both', expand=True, padx=(0, 8))
        for val, lab in (('sp', 'SP campaign (default)'), ('all', 'Whole pack (all packages)'), ('custom', 'Custom packages')):
            ttk.Radiobutton(a, text=lab, value=val, variable=self.pk_scope, command=self._pack_scope_changed).pack(anchor='w', padx=10, pady=1)
        pf = ttk.Frame(a); pf.pack(anchor='w', padx=28, pady=(0, 4)); self.pk_cb = {}
        for k in pack.ORDER:
            c = ttk.Checkbutton(pf, text=pack.PACKAGES[k][1], variable=self.pk_pkgs[k], command=self._pack_scope_changed); c.pack(anchor='w'); self.pk_cb[k] = c
        b = ttk.LabelFrame(row, text='2. Detail level (texture size cut-off, not a render resolution)'); b.pack(side='left', fill='both', expand=True)
        self.pk_rb = {}
        for lv in pack.LEVELS:
            r = ttk.Radiobutton(b, text=pack.LEVEL_LABELS[lv], value=lv, variable=self.pk_level, command=self._pack_level_changed); r.pack(anchor='w', padx=10, pady=1); self.pk_rb[lv] = r
        self.pk_lvnote = ttk.Label(b, text='', style='Dim.TLabel', wraplength=520); self.pk_lvnote.pack(anchor='w', padx=10, pady=(4, 2))
        ttk.Label(b, text='Standard = 2048-class textures and below (about the "1440p class"). Chunks above the level are neither downloaded nor served: the engine keeps the smaller mip it already has. '
                          'Pick it before downloading to save disk and time; raise it later and press Download to fetch only the missing chunks.', style='Dim.TLabel', wraplength=520).pack(anchor='w', padx=10, pady=(0, 6))
        row2 = ttk.Frame(f); row2.pack(fill='x', pady=8)
        c = ttk.LabelFrame(row2, text='3. Estimate'); c.pack(side='left', fill='both', expand=True, padx=(0, 8))
        self.pk_est = ttk.Label(c, text='calculating...', wraplength=520, justify='left'); self.pk_est.pack(anchor='w', padx=10, pady=6)
        d = ttk.LabelFrame(row2, text='4. Slow or metered connection (optional)'); d.pack(side='left', fill='both', expand=True)
        def num(r, key, label, hint):
            ttk.Label(d, text=label).grid(row=r, column=0, sticky='e', padx=(10, 4), pady=3); v = tk.StringVar(value=str(self.cfg['pack'].get(key, 0))); ttk.Entry(d, textvariable=v, width=7).grid(row=r, column=1, sticky='w'); self.pk_num[key] = v
            ttk.Label(d, text=hint, style='Dim.TLabel').grid(row=r, column=2, sticky='w', padx=6)
        num(0, 'line_mbps', 'My line speed (Mbps)', 'only for the ETA'); num(1, 'limit_mbps', 'Download cap (Mbps)', '0 = unlimited; shared by all connections'); num(2, 'daily_gib', 'Daily limit (GiB)', '0 = none; pauses until local midnight')
        num(3, 'workers', 'Connections', '0 = automatic (4); 8 helps on long-distance links'); num(4, 'link_wait_s', 'Give up after no link (s)', '0 = wait forever, chunks stay pending')
        bt = ttk.Frame(f); bt.pack(fill='x', pady=4)
        ttk.Button(bt, text='Download / resume', style='Accent.TButton', command=self.do_pack_start).pack(side='left', padx=4)
        ttk.Button(bt, text='Pause (finish in-flight)', command=self.do_mirror_pause).pack(side='left', padx=4)
        ttk.Button(bt, text='Refresh estimate', command=self.pack_refresh).pack(side='left', padx=4)
        ttk.Button(bt, text='Verify all', command=lambda: self.do_pack_verify(False)).pack(side='left', padx=(16, 4))
        ttk.Button(bt, text='Verify + repair', command=lambda: self.do_pack_verify(True)).pack(side='left', padx=4)
        ttk.Button(bt, text='Reclaim space above this level...', command=self.do_pack_prune).pack(side='left', padx=4)
        ttk.Button(bt, text='Play offline (profile)', command=self.do_pack_offline).pack(side='left', padx=(16, 4))
        pr = ttk.LabelFrame(f, text='Progress'); pr.pack(fill='x', pady=4); self.p_bar = ttk.Progressbar(pr, maximum=1000); self.p_bar.pack(fill='x', padx=10, pady=(8, 2))
        self.p_lbl = ttk.Label(pr, text='no run in progress', wraplength=1100); self.p_lbl.pack(anchor='w', padx=10, pady=(0, 8))
        t = ttk.LabelFrame(f, text='By package for the chosen level (an id in several lists is counted once, under the first)'); t.pack(fill='both', expand=True)
        cols = ('package', 'chunks', 'GiB', 'stored', 'to download GiB'); self.pk_tree = ttk.Treeview(t, columns=cols, show='headings', height=6)
        for cn, w in zip(cols, (240, 90, 90, 90, 120)): self.pk_tree.heading(cn, text=cn); self.pk_tree.column(cn, width=w, anchor='w' if cn == 'package' else 'e')
        self.pk_tree.pack(fill='both', expand=True, padx=6, pady=6); self._pack_scope_changed(refresh=False)

    def _pack_scope_changed(self, refresh=True):
        for k, c in self.pk_cb.items(): c.configure(state='normal' if self.pk_scope.get() == 'custom' else 'disabled')
        if refresh: self._pack_collect(soft=True); self.pack_refresh()

    def _pack_collect(self, soft=False):
        """Widgets -> cfg['pack'] (saved). soft = ignore bad numbers instead of raising."""
        pk = self.cfg['pack']; pk['scope'] = self.pk_scope.get(); pk['packages'] = [k for k, v in self.pk_pkgs.items() if v.get()]
        if pk['scope'] == 'custom' and not pk['packages'] and not soft: raise ValueError('tick at least one package')
        for key, v in self.pk_num.items():
            try: pk[key] = float(v.get() or 0) if key in ('line_mbps', 'limit_mbps', 'daily_gib') else int(float(v.get() or 0))
            except ValueError:
                if not soft: raise ValueError(f'{key}: not a number')
        config.save(self.cfg)

    def _pack_level_changed(self):
        lv = self.pk_level.get(); self.cfg['pack']['level'] = lv
        prof = config.all_profiles(self.cfg).get(self.cfg.get('profile'), {})
        if 'level' in prof.get('pack', {}) and prof['pack']['level'] != lv:
            self.say(f"profile '{self.cfg['profile']}' set another detail level - switching to the Default profile", 'WARN'); self.profile.set('Default'); self.cfg['profile'] = 'Default'
        config.save(self.cfg); self._sync_caps(); self.pack_refresh()
        if procs.status('proxy')['alive']: self.say('detail level changed: restart the proxy (Proxy tab -> Save + restart, or Stop/Start session) to apply it to the running game session', 'WARN')

    def _sync_caps(self):
        """Show the effective caps in the Proxy / Mirror tabs; they are read-only while the Texture pack level drives them (pack.link_caps)."""
        e = config.effective(self.cfg); linked = bool(e['pack'].get('link_caps', True)); mib = e['proxy']['max_raw_mib']
        for vars_, ents, key, val in ((getattr(self, 'pv', {}), getattr(self, 'pe', {}), 'max_raw_mib', mib), (getattr(self, 'mv', {}), getattr(self, 'me', {}), 'tier', e['mirror']['tier'])):
            if key in vars_ and linked: vars_[key].set(f'{val:g}')
            if key in ents: ents[key].configure(state='disabled' if linked else 'normal')

    def pack_refresh(self):
        if not hasattr(self, 'pk_est'): return
        try: self._pack_collect(soft=True)
        except Exception: pass
        e = config.effective(self.cfg)['pack']; scope, pkgs, level, line = e['scope'], e.get('packages'), e['level'], float(e.get('line_mbps') or 0)
        def go():
            try: pl = pack.plan(scope, pkgs, level, line_mbps=line)
            except Exception as ex: pl = dict(error=str(ex))
            self.q.put(('ask', lambda: self._show_pack(pl)))
        threading.Thread(target=go, daemon=True).start()

    def _show_pack(self, pl):
        if 'error' in pl: self.pk_est.configure(text='cannot compute: ' + pl['error']); return
        self._pack_plan = pl; self.pk_est.configure(text=pack.describe(pl), foreground=(BAD if not pl['fits'] else FG))
        for lv, rb in self.pk_rb.items():
            b = pl['levels'][lv]; rb.configure(text=f"{pack.LEVEL_LABELS[lv]}  -  {b['gib']:.1f} GiB total, {b['pending_gib']:.1f} GiB to download")
        prof = config.all_profiles(self.cfg).get(self.cfg.get('profile'), {}); self.pk_lvnote.configure(text=f"profile '{self.cfg['profile']}' sets the level to {prof['pack']['level']}" if 'level' in prof.get('pack', {}) else '')
        for i in self.pk_tree.get_children(): self.pk_tree.delete(i)
        for k, b in pl['by_pkg'].items():
            lab = pack.PACKAGES[k][1] + ('  (no chunk list on this install)' if k in pl['missing'] else '')
            self.pk_tree.insert('', 'end', values=(lab, f"{b['chunks']:,}", f"{b['gib']:.2f}", f"{b['stored']:,}", f"{b['pending_gib']:.2f}"))

    def _bulk_ack(self):
        """Ask once per version for the bulk-download notice; True if accepted."""
        if self.cfg.get('bulk_ack') == version.__version__: return True
        if not messagebox.askyesno('Bulk download - please read', version.BULK_NOTICE + '\n\nDo you accept and want to continue?', parent=self): return False
        self.cfg['bulk_ack'] = version.__version__; config.save(self.cfg); version.record_bulk_ack(); return True

    def do_pack_start(self):
        try: self._pack_collect()
        except ValueError as ex: messagebox.showerror('Texture pack', str(ex), parent=self); return
        if not paths.CONFIGURED: messagebox.showerror('Texture pack', 'Set the game folder in the Game tab first.', parent=self); return
        if procs.status('mirror')['alive']: self.say('a mirror run is already active', 'WARN'); return
        if not self._bulk_ack(): return
        e = config.effective(self.cfg)['pack']
        try: pl = pack.plan(e['scope'], e.get('packages'), e['level'], line_mbps=float(e.get('line_mbps') or 0))
        except Exception as ex: messagebox.showerror('Texture pack', f'cannot compute the estimate: {ex}', parent=self); return
        t = pl['total']
        if not t['pending']: self.say('Texture pack: nothing to download for this scope and level', 'OK'); self._show_pack(pl); return
        if not pl['fits']: messagebox.showerror('Texture pack', f"Not enough space on the mirror drive: need about {pl['need_gib']:.0f} GiB, {pl['free_gib']:.0f} GiB free.\nChoose a lower detail level, a smaller scope or another mirror folder (Game tab).", parent=self); return
        lim = float(e.get('limit_mbps') or 0); dq = float(e.get('daily_gib') or 0)
        if not messagebox.askyesno('Download texture pack', f"Download {t['pending']:,} chunks ({t['pending_gib']:.1f} GiB) from the public texture CDN into\n{paths.MIRROR}\n\n"
                                   f"scope: {pl['scope']}   level: {pl['level']}\nfree space: {pl['free_gib']:.0f} GiB" + (f"\ncap: {lim:g} Mbps" if lim else '') + (f"\ndaily limit: {dq:g} GiB" if dq else '') + '\n\nThese files belong to the game publisher: keep them on this PC, for use with your own copy of the game, and do not share them.\nIt can be paused and resumed at any time. Start?', parent=self): return
        st = mirrorctl.start(**mirrorctl.pack_kwargs(self.cfg)); self.say(f"texture pack run started (pid {st['pid']}): scope={pl['scope']} level={pl['level']} {t['pending']:,} chunks / {t['pending_gib']:.1f} GiB", 'OK')

    def do_pack_verify(self, repair):
        if procs.status('mirror')['alive']: self.say('pause the download first', 'WARN'); return
        self._m_oneshot(['verify', '--all', '--progress-json', mirrorctl.VERIFY_PROGRESS] + (['--fix'] if repair else []))

    def do_pack_prune(self):
        mib = config.effective(self.cfg)['proxy']['max_raw_mib']
        if mib >= 4096: messagebox.showinfo('Texture pack', 'Ultra has no size cap - nothing is above the level.', parent=self); return
        if procs.status('mirror')['alive']: self.say('pause the download first', 'WARN'); return
        def go():
            r = subprocess.run(launch.argv_for('ccsmirror', 'prune', '--above-tier', str(mib), '--json'), capture_output=True, text=True, timeout=300, creationflags=procs.CREATE_NO_WINDOW)
            try: d = json.loads(r.stdout.strip().splitlines()[-1])
            except Exception: self.say('prune check failed: ' + (r.stderr or r.stdout)[-200:], 'ERR'); return
            if not d['chunks']: self.say(f'nothing stored above {mib:g} MiB', 'OK'); return
            if self.ask_main(lambda: messagebox.askyesno('Reclaim space', f"Delete {d['chunks']:,} stored chunks above {mib:g} MiB raw ({d['gib']:.1f} GiB) from the mirror?\n\nThey are only mirror copies: choosing a higher level and pressing Download fetches them again.", parent=self)):
                mirrorctl.oneshot(['prune', '--above-tier', str(mib), '--yes']); self.say(f"prune started: removing {d['chunks']:,} chunks ({d['gib']:.1f} GiB)", 'OK')
        threading.Thread(target=go, daemon=True).start()

    def do_pack_offline(self):
        self.profile.set('Slow link - offline mirror'); self._profile_changed()
        self.say('profile "Slow link - offline mirror" selected: restart the session (Stop, then Start) - the game is then served only from the mirror', 'OK')

    # ---------------------------------------------------------------- Mirror tab
    def _tab_mirror(self, f):
        top = ttk.LabelFrame(f, text='Mirror of the SP streaming chunks (public CDN -> mirror/objects)'); top.pack(fill='x', pady=10); self.mv = {}
        self.me = {}
        def field(r, c, key, label):
            ttk.Label(top, text=label).grid(row=r, column=c * 2, sticky='e', padx=(12, 4), pady=5); v = tk.StringVar(value=str(self.cfg['mirror'][key])); e = ttk.Entry(top, textvariable=v, width=8); e.grid(row=r, column=c * 2 + 1, sticky='w'); self.mv[key] = v; self.me[key] = e
        field(0, 0, 'workers', 'Workers'); field(0, 1, 'tier', 'Tier cap (MiB; set by Texture pack)'); field(0, 2, 'budget_gib', 'Budget (GiB; 0 = auto)'); field(1, 0, 'max_rps', 'Max req/s'); field(1, 1, 'min_free_gib', 'Stop below free GiB'); field(1, 2, 'retries', 'Retries')
        b = ttk.Frame(top); b.grid(row=2, column=0, columnspan=8, sticky='w', padx=10, pady=8)
        self.m_start = ttk.Button(b, text='Start / resume run', style='Accent.TButton', command=self.do_mirror_start); self.m_start.pack(side='left', padx=4)
        ttk.Button(b, text='Pause (finish in-flight)', command=self.do_mirror_pause).pack(side='left', padx=4)
        ttk.Button(b, text='Kill now', style='Danger.TButton', command=lambda: self.say('mirror run killed' if mirrorctl.kill() else 'mirror run is not running')).pack(side='left', padx=4)
        ttk.Button(b, text='Verify 500 random', command=lambda: self._m_oneshot(['verify', '--n', '500'])).pack(side='left', padx=(16, 4))
        ttk.Button(b, text='Retry failed', command=lambda: self._m_oneshot(['retry-failed'])).pack(side='left', padx=4)
        ttk.Button(b, text='Re-init lists', command=lambda: self._m_oneshot(['init'])).pack(side='left', padx=4)
        pr = ttk.LabelFrame(f, text='Progress'); pr.pack(fill='x'); self.m_bar = ttk.Progressbar(pr, maximum=1000); self.m_bar.pack(fill='x', padx=10, pady=(8, 2))
        self.m_lbl = ttk.Label(pr, text='no run in progress'); self.m_lbl.pack(anchor='w', padx=10, pady=(0, 8))
        mid = ttk.Frame(f); mid.pack(fill='both', expand=True, pady=8)
        l = ttk.LabelFrame(mid, text='Chunks by priority (0 = game-requested, 1 = <=4 MiB, 2 = 4K class)'); l.pack(side='left', fill='both', expand=True, padx=(0, 8))
        cols = ('prio', 'status', 'chunks', 'wire GiB', 'raw GiB'); self.m_tree = ttk.Treeview(l, columns=cols, show='headings', height=9)
        for c, w in zip(cols, (60, 90, 90, 90, 90)): self.m_tree.heading(c, text=c); self.m_tree.column(c, width=w, anchor='e' if c not in ('status',) else 'w')
        self.m_tree.pack(fill='both', expand=True, padx=6, pady=6); self.m_sum = ttk.Label(l, text='', style='Dim.TLabel'); self.m_sum.pack(anchor='w', padx=8)
        ttk.Button(l, text='Refresh status', command=self.refresh_mirror).pack(anchor='w', padx=8, pady=6)
        r = ttk.LabelFrame(mid, text='Mirror log / tool output'); r.pack(side='left', fill='both', expand=True); fr, self.m_log = self._scrolled(r, 12); fr.pack(fill='both', expand=True, padx=6, pady=6)
        self._m_tails = [logtail.Tail(proxyctl.MIRROR_LOG, 40), logtail.Tail(mirrorctl.OUTFILE, 0)]
        self.after(1200, self.refresh_mirror)

    def _m_save(self):
        m = self.cfg['mirror']
        for k, v in self.mv.items(): m[k] = float(v.get()) if k in ('tier', 'budget_gib', 'min_free_gib', 'max_rps') else int(float(v.get()))
        config.save(self.cfg)

    def do_mirror_start(self):
        try: self._m_save()
        except ValueError as e: messagebox.showerror('Mirror', f'invalid number: {e}', parent=self); return
        if not self._bulk_ack(): return
        if not os.path.exists(os.path.join(paths.MIRROR, 'index.sqlite')): self.say('mirror not initialised - running init first', 'WARN'); self._m_oneshot(['init']); return
        kw = dict(self.cfg['mirror']); kw['tier'] = config.effective(self.cfg)['mirror']['tier']          # the Texture pack detail level sets the cap unless it is unlinked
        st = mirrorctl.start(**kw); self.say(f"mirror run started (pid {st['pid']}): workers={kw['workers']} tier<={kw['tier']:g}MiB budget={kw['budget_gib']}GiB (index rows, no scope filter)", 'OK')

    def do_mirror_pause(self): self.say('mirror: pause requested (in-flight objects finish)' if mirrorctl.pause() else 'mirror run is not running', 'OK')

    def _m_oneshot(self, args):
        if procs.status('mirror-' + args[0])['alive']: self.say(f'mirror {args[0]} is still running', 'WARN'); return
        mirrorctl.oneshot(args); self.say(f"mirror {' '.join(args)} started (output in the log box)", 'OK')

    def refresh_mirror(self):
        def go():
            st = mirrorctl.status(); self.q.put(('ask', lambda: self._show_mirror(st)))
        threading.Thread(target=go, daemon=True).start()

    def _show_mirror(self, st):
        for i in self.m_tree.get_children(): self.m_tree.delete(i)
        if not st: self.m_sum.configure(text='mirror not initialised (Re-init lists)'); return
        for r in st['rows']: self.m_tree.insert('', 'end', values=(r['prio'], r['status'], f"{r['chunks']:,}", f"{r['wire'] / 2**30:.2f}", f"{r['raw'] / 2**30:.2f}"))
        self.m_sum.configure(text=f"stored {st['stored']:,} chunks, {st['stored_gib']:.2f} GiB wire; {st['cod_key']:,} with an x-amz-meta-cod-key")

    @staticmethod
    def _prog_view(p, alive, vp=None, valive=False):
        """Mirror run / verify progress -> (bar 0..1000, text). Used by the Mirror and Texture pack tabs."""
        if valive and vp:
            return 1000 * vp['done'] / max(1, vp['total']), f"verifying stored objects: {vp['done']:,}/{vp['total']:,}, {vp['bad']} bad so far"
        if p and alive:
            done = p['ok'] + p['fail']; bar = 1000 * done / max(1, p['queued']); el = max(1, p['now'] - p['started']); rate = p['ok'] / el
            eta = fmt_dur(p['left'] / rate) if rate > 0 and p['left'] else '-'; st = p['state']
            head = {'quota-wait': f"DAILY QUOTA REACHED ({(p.get('used_today_gib') or 0):.1f} GiB today) - resumes {time.strftime('%H:%M', time.localtime(p['resume_at'])) if p.get('resume_at') else 'at midnight'}; Pause to stop",
                    'offline-wait': 'NO CONNECTION to the CDN - waiting, chunks stay pending (Pause to stop)'}.get(st, st)
            lim = f"  cap {p['limit_mbps']:g} Mbps" if p.get('limit_mbps') else ''
            sp = p.get('mibps_now', p['mibps'])                                          # rolling 30 s when the run reports it; MiB/s x 8.39 = Mbit/s
            via = f"  via {p['edge']}" if p.get('edge') else ''
            warn = f"  [{p['edge_note']}]" if p.get('edge_note') else ''
            return bar, f"{head}: {done:,}/{p['queued']:,} ({p['ok']:,} ok, {p['fail']} failed, {p['retry']} retries)  {p['bytes'] / 2**30:.2f}/{p['budget_gib']:.1f} GiB  {sp:.1f} MiB/s ({sp * 8.388608:.0f} Mbps){lim}{via}{warn}  ETA {eta}  free {p['free_gib']:.0f} GiB"
        if p:
            return (1000 * (p['ok'] + p['fail']) / max(1, p['queued']) if p['queued'] else 0), f"last run {p['state']}: {p['ok']:,} ok, {p['fail']} failed, {p['bytes'] / 2**30:.2f} GiB downloaded"
        return 0, 'no run in progress'

    def _refresh_mirror_live(self, s):
        p = s.get('mprog'); alive = s.get('mproc', {}).get('alive'); vp = s.get('vprog'); valive = s.get('vproc', {}).get('alive')
        bar, text = self._prog_view(p, alive, vp, valive)
        self.m_bar['value'] = bar; self.m_lbl.configure(text=text); self.p_bar['value'] = bar; self.p_lbl.configure(text=text)
        prev = getattr(self, '_m_was_alive', False)
        if prev and not alive: self.refresh_mirror(); self.pack_refresh()
        self._m_was_alive = bool(alive)
        pv = getattr(self, '_v_was_alive', False)
        if pv and not valive: self.refresh_mirror(); self.pack_refresh()
        self._v_was_alive = bool(valive)

    def _tail_mirror(self):
        for t in self._m_tails:
            for ln in t.read_new(): self._put(self.m_log, ln, self._log_tag(ln))

    # ---------------------------------------------------------------- Cache tab
    def _tab_cache(self, f):
        self.c_warn = ttk.Label(f, text='', foreground=WARN); self.c_warn.pack(anchor='w', pady=(8, 0))
        sm = ttk.LabelFrame(f, text='Engine cache (xpak_cache)'); sm.pack(fill='x', pady=6); self.c_sum = {}
        for i, (k, lab) in enumerate((('size', 'On disk'), ('active', 'Active shards'), ('records', 'Records'), ('unique', 'Unique ids'), ('dup', 'Dup ratio'), ('setting', 'Settings word (GB)'))):
            c = ttk.Frame(sm); c.grid(row=0, column=i, padx=14, pady=6, sticky='w'); ttk.Label(c, text=lab, style='Dim.TLabel').pack(anchor='w'); l = ttk.Label(c, text='-', style='H.TLabel'); l.pack(anchor='w'); self.c_sum[k] = l
        ttk.Button(sm, text='Refresh', command=self.refresh_cache).grid(row=0, column=7, padx=14)
        mid = ttk.Frame(f); mid.pack(fill='both', expand=True)
        l = ttk.LabelFrame(mid, text='Shards'); l.pack(side='left', fill='both', expand=True, padx=(0, 8))
        cols = ('shard', 'counter', 'records', 'unique', 'data GiB', 'key'); self.c_tree = ttk.Treeview(l, columns=cols, show='headings', height=10)
        for c, w in zip(cols, (110, 60, 70, 70, 70, 130)): self.c_tree.heading(c, text=c); self.c_tree.column(c, width=w, anchor='w')
        self.c_tree.pack(fill='both', expand=True, padx=6, pady=6)
        r = ttk.LabelFrame(mid, text='Backups / aside copies (xpak_cache.*)'); r.pack(side='left', fill='both', expand=True)
        cols = ('name', 'GiB', 'date'); self.cb_tree = ttk.Treeview(r, columns=cols, show='headings', height=6)
        for c, w in zip(cols, (240, 60, 130)): self.cb_tree.heading(c, text=c); self.cb_tree.column(c, width=w, anchor='w')
        self.cb_tree.pack(fill='both', expand=True, padx=6, pady=6)
        bb = ttk.Frame(r); bb.pack(pady=(0, 8))
        ttk.Button(bb, text='Backup now', style='Accent.TButton', command=lambda: self.bg('cache backup', self._cache_backup)).pack(side='left', padx=3)
        ttk.Button(bb, text='Restore selected', command=self.do_cache_restore).pack(side='left', padx=3)
        ttk.Button(bb, text='Delete selected', style='Danger.TButton', command=self.do_cache_delete).pack(side='left', padx=3)
        ttk.Button(bb, text='Open folder', command=lambda: os.startfile(paths.ROOT)).pack(side='left', padx=3)
        self.after(1500, self.refresh_cache)

    def refresh_cache(self):
        def go():
            try: s = cachectl.summary(); b = cachectl.backups()
            except Exception as e: self.say(f'cache scan failed: {e}', 'ERR'); return
            self.q.put(('ask', lambda: self._show_cache(s, b)))
        threading.Thread(target=go, daemon=True).start()

    def _show_cache(self, s, b):
        for i in self.c_tree.get_children(): self.c_tree.delete(i)
        for r in s['shards']:
            self.c_tree.insert('', 'end', values=(r['name'], r.get('counter', '?'), r.get('records', r.get('error', '?')), r.get('unique', ''), f"{r.get('data_size', 0) / 2**30:.2f}", r.get('key', '')))
        c = self.c_sum; c['size'].configure(text=f"{s['total_bytes'] / 2**30:.2f} GiB"); c['active'].configure(text=f"{s['active']}/{len(s['shards'])}"); c['records'].configure(text=f"{s['records']:,}")
        c['unique'].configure(text=f"{s['unique']:,}"); c['dup'].configure(text=f"{s['dup_ratio']}x"); c['setting'].configure(text=str(s['setting_gb']))
        for i in self.cb_tree.get_children(): self.cb_tree.delete(i)
        for n, p, sz, mt in b: self.cb_tree.insert('', 'end', iid=n, values=(n, f'{sz / 2**30:.2f}', time.strftime('%Y-%m-%d %H:%M', time.localtime(mt))))

    def _cache_backup(self):
        self.say('cache backup: copying xpak_cache ...'); d = cachectl.backup(); self.say(f'cache backup done: {d}', 'OK'); self.refresh_cache()

    def _sel_backup(self):
        s = self.cb_tree.selection(); return s[0] if s else None

    def do_cache_restore(self):
        n = self._sel_backup()
        if not n: return
        if not messagebox.askyesno('Restore cache', f'Make xpak_cache equal to\n{n}\n\nThe current xpak_cache is renamed aside (xpak_cache.replaced_<time>), not deleted. The game must be closed.', parent=self): return
        def go():
            aside = cachectl.restore(n); self.say(f'cache restored from {n}; previous cache kept as {os.path.basename(aside)}', 'OK'); self.refresh_cache()
        self.bg('cache restore', go)

    def do_cache_delete(self):
        n = self._sel_backup()
        if not n: return
        if not messagebox.askyesno('Delete backup', f'PERMANENTLY delete directory\n{n}?\n\nThis cannot be undone.', parent=self): return
        def go(): cachectl.delete_backup(n); self.say(f'deleted {n}', 'OK'); self.refresh_cache()
        self.bg('cache delete', go)

    # ---------------------------------------------------------------- Game tab (locations, game status, player config)
    EXPECT = {'TextureQuality': ('0', '0 = highest texture quality'), 'WorldStreamingQuality': ('High', 'on-demand world streaming'),
              'ResolutionMultiplier': (None, '100 = native render scale'), 'DLSSPerfModeMP': (None, 'Native Resolution = DLAA'), 'GraphicsQuality': (None, 'preset')}

    def _tab_game(self, f):
        loc = ttk.LabelFrame(f, text='Locations - nothing is assumed; set these once (stored in tools/work/gui_settings.json, used by every CCS tool)'); loc.pack(fill='x', pady=10)
        self.pv_loc = {}; self.pv_eff = {}
        rows = (('game_root', 'Game folder', 'dir', 'folder that contains cod26/, sp26/ and the game files'), ('cache_dir', 'Engine cache folder', 'dir', 'blank = <game folder>\\xpak_cache'),
                ('mirror_dir', 'Mirror folder', 'dir', 'blank = <game folder>\\mirror  (large - ~82 GiB; may be on another drive)'),
                ('player_cfg', 'Player config file', 'file', 'blank = auto (%LOCALAPPDATA%\\Activision\\Call of Duty\\players\\s.1.0.cod26.txt)'),
                ('game_exes', 'Game process names', 'text', 'comma separated; "game running" is detected by these'), ('kill_exes', 'Disk guard may terminate', 'text', 'comma separated; blank = sp26-cod.exe'))
        for i, (key, lab, kind, hint) in enumerate(rows):
            ttk.Label(loc, text=lab).grid(row=i * 2, column=0, sticky='e', padx=(12, 6), pady=(6, 0))
            v = tk.StringVar(value=self.cfg['paths'].get(key, '')); ttk.Entry(loc, textvariable=v, width=70).grid(row=i * 2, column=1, sticky='we', pady=(6, 0)); self.pv_loc[key] = v
            if kind != 'text': ttk.Button(loc, text='Browse...', command=lambda k=key, kd=kind: self._browse(k, kd)).grid(row=i * 2, column=2, padx=6, pady=(6, 0))
            e = ttk.Label(loc, text=hint, style='Dim.TLabel'); e.grid(row=i * 2 + 1, column=1, sticky='w'); self.pv_eff[key] = e
        loc.columnconfigure(1, weight=1)
        b = ttk.Frame(loc); b.grid(row=len(rows) * 2, column=0, columnspan=3, sticky='w', padx=10, pady=8)
        ttk.Button(b, text='Save locations', style='Accent.TButton', command=self.save_locations).pack(side='left', padx=4)
        ttk.Button(b, text='Detect game folder', command=self.detect_root).pack(side='left', padx=4)
        ttk.Button(b, text='Re-check', command=self.show_validation).pack(side='left', padx=4)
        ttk.Button(b, text='Open game folder', command=lambda: self._open(paths.GAME_ROOT)).pack(side='left', padx=(18, 4)); ttk.Button(b, text='Open player-config folder', command=lambda: self._open(os.path.dirname(paths.PLAYER_CFG))).pack(side='left', padx=4)
        mid = ttk.Frame(f); mid.pack(fill='both', expand=True)
        l = ttk.LabelFrame(mid, text='Checks'); l.pack(side='left', fill='both', expand=True, padx=(0, 8)); self.val_frame = ttk.Frame(l); self.val_frame.pack(fill='both', expand=True, padx=6, pady=6)
        r = ttk.LabelFrame(mid, text='Player config (read-only: texture / streaming / render keys)'); r.pack(side='left', fill='both', expand=True)
        cols = ('key', 'value', 'note'); self.pc_tree = ttk.Treeview(r, columns=cols, show='headings', height=10)
        for c, w in zip(cols, (200, 150, 200)): self.pc_tree.heading(c, text=c); self.pc_tree.column(c, width=w, anchor='w')
        self.pc_tree.tag_configure('good', foreground=OK); self.pc_tree.tag_configure('off', foreground=WARN); self.pc_tree.pack(fill='both', expand=True, padx=6, pady=6)
        ttk.Button(r, text='Reload', command=self.show_player_cfg).pack(anchor='w', padx=6, pady=(0, 6))
        self.after(800, lambda: (self.show_validation(), self.show_player_cfg()))

    def _open(self, p):
        try: os.startfile(p)
        except OSError as e: self.say(f'cannot open {p}: {e}', 'WARN')

    def _browse(self, key, kind):
        from tkinter import filedialog
        cur = self.pv_loc[key].get() or (paths.GAME_ROOT if key != 'player_cfg' else os.path.dirname(paths.PLAYER_CFG))
        p = filedialog.askdirectory(initialdir=cur, parent=self, title='Select folder') if kind == 'dir' else filedialog.askopenfilename(initialdir=os.path.dirname(cur) if cur else None, parent=self, title='Select file')
        if p: self.pv_loc[key].set(os.path.normpath(p))

    def detect_root(self):
        g = paths.detect_game_root()
        if not g: messagebox.showinfo('Detect', 'The folder the tools live in does not look like a game folder. Use Browse...', parent=self); return
        if messagebox.askyesno('Detect', f'Use this as the game folder?\n\n{g}', parent=self): self.pv_loc['game_root'].set(g)

    def save_locations(self):
        new = {k: v.get().strip() for k, v in self.pv_loc.items()}
        if new['game_root'] and not os.path.isdir(new['game_root']): messagebox.showerror('Locations', 'The game folder does not exist.', parent=self); return
        self.cfg['paths'] = new; config.save(self.cfg); self.say(f"locations saved: game={paths.GAME_ROOT} cache={paths.XPAK_CACHE} mirror={paths.MIRROR}", 'OK')
        self.show_validation(); self.show_player_cfg(); self.refresh_cache(); self.refresh_mirror(); self._refresh_runs()

    def show_validation(self):
        paths.reload()
        for k, lab in self.pv_eff.items():
            src = paths.SOURCES.get(k); eff = {'game_root': paths.GAME_ROOT, 'cache_dir': paths.XPAK_CACHE, 'mirror_dir': paths.MIRROR, 'player_cfg': paths.PLAYER_CFG}.get(k)
            if eff: lab.configure(text=f'in use: {eff}   [{ {"settings": "from settings", "derived": "derived", "fallback": "NOT CONFIGURED - fallback to tools folder", "env": "env override"}.get(src, src) }]')
        for w in self.val_frame.winfo_children(): w.destroy()
        col = dict(ok=OK, warn=WARN, fail=BAD, info=DIM)
        for i, r in enumerate(paths.validate()):
            tk.Label(self.val_frame, text='●', fg=col[r['level']], bg=BG, font=('Segoe UI', 11)).grid(row=i, column=0, sticky='n', padx=(2, 4))
            ttk.Label(self.val_frame, text=r['name'], width=18).grid(row=i, column=1, sticky='nw'); ttk.Label(self.val_frame, text=r['detail'], wraplength=420, justify='left').grid(row=i, column=2, sticky='nw', pady=2)
        self._update_setup_banner()

    def show_player_cfg(self):
        for i in self.pc_tree.get_children(): self.pc_tree.delete(i)
        cfg = report.player_config()
        if not cfg: self.pc_tree.insert('', 'end', values=('(player config not found / no matching keys)', '', paths.PLAYER_CFG)); return
        for k, v in sorted(cfg.items()):
            base = k.split('@')[0]; exp, note = self.EXPECT.get(base, (None, ''))
            tag = ('good',) if exp is not None and v == exp else (('off',) if exp is not None else ())
            self.pc_tree.insert('', 'end', values=(k, v, note + (f'  (expected {exp})' if exp is not None and v != exp else '')), tags=tag)

    def _update_setup_banner(self):
        bad = [r for r in paths.validate() if r['level'] == 'fail']
        self.setup_banner.configure(text=('SETUP NEEDED: ' + '; '.join(r['name'] for r in bad) + ' - open the Game tab and set the game folder.') if bad else '')
        if bad: self.setup_banner.pack(fill='x', pady=(8, 0))
        else: self.setup_banner.pack_forget()

    def _tab_doctor(self, f):
        row = ttk.Frame(f); row.pack(fill='x', pady=10)
        ttk.Button(row, text='Run Doctor', style='Accent.TButton', command=self.do_doctor).pack(side='left', padx=4)
        ttk.Button(row, text='Export support bundle (zip)', command=self.do_bundle).pack(side='left', padx=4)
        ttk.Label(row, text='Each failing check with a safe remedy has a Fix button. Nothing is changed without your click.', style='Dim.TLabel').pack(side='left', padx=12)
        self.doc_frame = ttk.Frame(f); self.doc_frame.pack(fill='both', expand=True)
        ttk.Label(self.doc_frame, text='Press "Run Doctor".', style='Dim.TLabel').pack(anchor='w', padx=8)

    def _tab_report(self, f):
        row = ttk.Frame(f); row.pack(fill='x', pady=10); self.run_var = tk.StringVar()
        ttk.Label(row, text='Proxy run').pack(side='left'); self.run_cb = ttk.Combobox(row, textvariable=self.run_var, state='readonly', width=44); self.run_cb.pack(side='left', padx=6)
        ttk.Button(row, text='Refresh', command=self._refresh_runs).pack(side='left', padx=2)
        ttk.Button(row, text='Generate report', style='Accent.TButton', command=lambda: self.bg('report', self._make_report, *self._sel_run())).pack(side='left', padx=6)
        ttk.Label(row, text='Saved').pack(side='left', padx=(14, 4)); self.saved_var = tk.StringVar(); self.saved_cb = ttk.Combobox(row, textvariable=self.saved_var, state='readonly', width=26); self.saved_cb.pack(side='left')
        self.saved_cb.bind('<<ComboboxSelected>>', self._view_saved); ttk.Button(row, text='Open folder', command=lambda: os.startfile(paths.SESSIONS)).pack(side='left', padx=8)
        ttk.Label(f, text='Auto-generated when the game exits during a session. The cache baseline is taken at Start session (game closed).', style='Dim.TLabel').pack(anchor='w')
        fr, self.rep_txt = self._scrolled(f, 30); fr.pack(fill='both', expand=True, pady=6); self._refresh_runs()

    def _tab_hosts(self, f):
        self.hosts_lbl = ttk.Label(f, text='', style='H.TLabel'); self.hosts_lbl.pack(anchor='w', pady=(10, 2))
        ttk.Label(f, text=f'File: {paths.hosts_path()}   Only the marked CCS block is ever modified; a backup is written before each change.', style='Dim.TLabel').pack(anchor='w')
        row = ttk.Frame(f); row.pack(fill='x', pady=8)
        b = ttk.Button(row, text='Apply override (UAC)', style='Accent.TButton', command=self.do_hosts_apply); b.pack(side='left', padx=4); Tip(b, HOSTS_HINT)
        b = ttk.Button(row, text='Remove override (UAC)', style='Danger.TButton', command=self.do_hosts_remove); b.pack(side='left', padx=4); Tip(b, HOSTS_HINT)
        ttk.Button(row, text='Test resolution', command=self.do_resolve).pack(side='left', padx=4)
        ttk.Button(row, text='Flush DNS (UAC)', command=lambda: self.bg('flush dns', self._hosts_simple, 'flush')).pack(side='left', padx=4)
        ttk.Button(row, text='Open hosts folder', command=lambda: os.startfile(os.path.dirname(paths.hosts_path()))).pack(side='left', padx=4)
        pan = ttk.Frame(f); pan.pack(fill='both', expand=True)
        l = ttk.LabelFrame(pan, text='CDN-host lines currently in the hosts file'); l.pack(side='left', fill='both', expand=True, padx=(0, 8))
        fr, self.hosts_txt = self._scrolled(l, 12); fr.pack(fill='both', expand=True, padx=6, pady=6)
        r = ttk.LabelFrame(pan, text='Backups (newest first)'); r.pack(side='left', fill='both', expand=True)
        self.bk_list = tk.Listbox(r, bg=PANEL, fg=FG, relief='flat', selectbackground='#31507f', font=('Consolas', 9), height=12); self.bk_list.pack(fill='both', expand=True, padx=6, pady=6)
        ttk.Button(r, text='Restore selected backup (UAC)', command=self.do_restore_backup).pack(pady=(0, 8))
        self._refresh_hosts_tab()

    def _tab_logs(self, f):
        bar = ttk.Frame(f); bar.pack(fill='x', pady=8); self.lv = {}
        ttk.Label(bar, text='Sources').pack(side='left')
        for n, _ in LOG_SOURCES:
            v = tk.BooleanVar(value=n in ('proxy', 'guard', 'gui')); self.lv[n] = v; ttk.Checkbutton(bar, text=n, variable=v, command=self._rerender_logs).pack(side='left', padx=4)
        self.hide_req = tk.BooleanVar(value=True); ttk.Checkbutton(bar, text='hide per-request lines', variable=self.hide_req, command=self._rerender_logs).pack(side='left', padx=12)
        self.paused = tk.BooleanVar(value=False); ttk.Checkbutton(bar, text='pause', variable=self.paused).pack(side='left', padx=4)
        ttk.Label(bar, text='filter (regex)').pack(side='left', padx=(12, 4)); self.flt = tk.StringVar(); e = ttk.Entry(bar, textvariable=self.flt, width=22); e.pack(side='left'); e.bind('<KeyRelease>', lambda _e: self._rerender_logs())
        ttk.Button(bar, text='Clear', command=self._clear_logs).pack(side='left', padx=8); ttk.Button(bar, text='Open folder', command=lambda: os.startfile(paths.WORK)).pack(side='left'); ttk.Button(bar, text='Support bundle', command=self.do_bundle).pack(side='left', padx=8)
        fr, self.logt = self._scrolled(f, 30); fr.pack(fill='both', expand=True)

    def _tab_settings(self, f):
        g = ttk.LabelFrame(f, text='Session'); g.pack(fill='x', pady=10); self.sv = {}
        def row(r, label, key, sub, w=10):
            ttk.Label(g, text=label).grid(row=r, column=0, sticky='e', padx=12, pady=6); v = tk.StringVar(value=str(self.cfg[sub][key])); ttk.Entry(g, textvariable=v, width=w).grid(row=r, column=1, sticky='w'); self.sv[(sub, key)] = v
        row(0, 'Disk guard: xpak_cache limit (GiB)', 'limit_gib', 'guard'); row(1, 'Disk guard poll interval (s)', 'interval', 'guard')
        ttk.Label(g, text='When limit is hit').grid(row=2, column=0, sticky='e', padx=12, pady=6); self.sv_action = tk.StringVar(value=self.cfg['guard']['action'])
        ttk.Combobox(g, textvariable=self.sv_action, values=('kill', 'warn'), state='readonly', width=8).grid(row=2, column=1, sticky='w'); ttk.Label(g, text='kill = terminate sp26-cod.exe (cache is disposable); warn = log only', style='Dim.TLabel').grid(row=2, column=2, sticky='w')
        self.sv_guard = tk.BooleanVar(value=self.cfg['guard']['enabled']); ttk.Checkbutton(g, text='Start disk guard with the session', variable=self.sv_guard).grid(row=3, column=1, sticky='w', pady=4)
        self.sv_nw = tk.BooleanVar(value=self.cfg['watchers']['netwatch']); ttk.Checkbutton(g, text='Start netwatch (DNS/TCP log of the game) with the session', variable=self.sv_nw).grid(row=4, column=1, sticky='w', pady=4)
        ttk.Label(g, text='Hosts override when session stops / GUI closes').grid(row=5, column=0, sticky='e', padx=12, pady=6); self.sv_exit = tk.StringVar(value=self.cfg['hosts']['on_exit'])
        ttk.Combobox(g, textvariable=self.sv_exit, values=('ask', 'keep', 'remove'), state='readonly', width=8).grid(row=5, column=1, sticky='w')
        self.sv_keep = tk.BooleanVar(value=self.cfg['keep_running_on_close']); ttk.Checkbutton(g, text='Keep proxy/guard running when the GUI closes (no prompt)', variable=self.sv_keep).grid(row=6, column=1, sticky='w', pady=4)
        ttk.Label(g, text='Rotate logs larger than (MB, 0 = never)').grid(row=7, column=0, sticky='e', padx=12, pady=6); self.sv_log = tk.StringVar(value=str(self.cfg['log_max_mb'])); ttk.Entry(g, textvariable=self.sv_log, width=8).grid(row=7, column=1, sticky='w')
        ttk.Label(g, text='checked at session start; 3 older copies are kept (.1 .2 .3)', style='Dim.TLabel').grid(row=7, column=2, sticky='w')
        bt = ttk.Frame(g); bt.grid(row=8, column=1, columnspan=2, sticky='w', pady=10)
        ttk.Button(bt, text='Save settings', style='Accent.TButton', command=self.save_settings).pack(side='left'); ttk.Button(bt, text='Create desktop shortcut', command=self.make_shortcut).pack(side='left', padx=10)
        h = ttk.LabelFrame(f, text='Help'); h.pack(fill='x', pady=6)
        ttk.Checkbutton(h, text='Show the guided setup on the Dashboard', variable=self.sv_guide, command=lambda: self.guide_toggle(self.sv_guide.get())).pack(anchor='w', padx=12, pady=(6, 2))
        ttk.Checkbutton(h, text='Simple view (hide the advanced tabs and the detailed counters)', variable=self.sv_simple, command=lambda: self.set_simple(self.sv_simple.get())).pack(anchor='w', padx=12, pady=2)
        hb = ttk.Frame(h); hb.pack(anchor='w', padx=12, pady=(2, 6))
        ttk.Button(hb, text='What do these words mean?', command=self.show_glossary).pack(side='left'); ttk.Button(hb, text='Before/after test', command=self.show_abtest).pack(side='left', padx=8)
        i = ttk.LabelFrame(f, text='Where things are (game/cache/mirror/player-config locations: Game tab)'); i.pack(fill='x', pady=6)
        for k, v in (('Tools / scripts', paths.TOOLS), ('Work dir (logs, reports, settings)', paths.WORK), ('Hosts file', paths.hosts_path()), ('Runtime', 'built in, no Python needed' if paths.FROZEN else 'Python: ' + paths.PY)):
            r = ttk.Frame(i); r.pack(fill='x', padx=10, pady=2); ttk.Label(r, text=k, width=32, style='Dim.TLabel').pack(side='left'); ttk.Label(r, text=v).pack(side='left')

    # ---------------------------------------------------------------- guided setup (optional; logic in ccslib/guide.py)
    def _guide_state(self): return guide.clean_state(self.cfg.get('guide'))

    def _guide_save(self, st):
        self.cfg['guide'] = st; config.save(self.cfg); self._guide_sig = None

    def _guide_facts(self):
        """The real state of the PC as the checklist needs it (from the poller's snapshot; nothing is probed here beyond a cheap folder check every few seconds)."""
        s = self.snap or {}; ps = s.get('pstat'); pp = s.get('pproc') or {}; own = s.get('owners') or []; port = config.effective_proxy(self.cfg)['port']
        blocked = ''
        if own and not (pp.get('alive') and all(o['pid'] == pp['pid'] for o in own)): blocked = own[0].get('name') if own[0].get('name') not in (None, '', '?') else 'another program'
        now = time.time(); root = paths.GAME_ROOT; fc = self._gfc
        if not fc or fc[1] != root or now - fc[0] > 5:
            ex = os.path.isdir(root); fc = (now, root, ex, guide.score_folder(root) if ex else 0, gamefix.state(root) if ex else 'na'); self._gfc = fc
        tot = (getattr(self, '_pack_plan', None) or {}).get('total') or {}; rs = s.get('resolve') or {}
        if ps and ps.get('stat'):                                                    # what the proxy has done so far; kept after it stops, for the "what happened" text
            c = ps['stat']; g = lambda k: c.get(k) or 0; self._guide_peak = dict(req=g('req'), mirror=g('mirror'), upok=g('ok') - g('mirror'), err=g('err'), skip=g('skip'), miss=g('miss'), secs=(ps.get('now') or 0) - (ps.get('started') or 0))
        return dict(configured=paths.CONFIGURED, folder_root=root, folder_exists=fc[2], folder_score=fc[3], game_setup=fc[4], blocked_by=blocked, port=port, free_gib=s.get('free'),
                    game_running=bool(s.get('game')), proxy_ready=bool(ps), proxy_alive=bool(pp.get('alive')), hosts_ok=s.get('hosts') in ('OK', 'FOREIGN', 'MIXED'),
                    resolve_ok=bool(rs.get('ok')), hosts_state=s.get('hosts', '?'), requests=int(ps['stat']['req']) if ps and ps.get('stat') else 0,
                    pack_total=tot.get('chunks'), pack_stored=tot.get('stored'), mirror_alive=bool((s.get('mproc') or {}).get('alive')),
                    pack_run_done=((s.get('mprog') or {}).get('ok', 0) + (s.get('mprog') or {}).get('fail', 0)), pack_run_total=(s.get('mprog') or {}).get('queued'),
                    last_stat=self._guide_peak, game_secs=(now - self.game_start) if s.get('game') and self.game_start else 0)

    def _guide_note(self):
        last = self._guide_last
        return last[1] if last and time.time() - last[0] < 600 else ''

    def _guide_tick_safe(self):
        """The checklist must never break the refresh loop; a given problem is logged once."""
        try: self._guide_tick()
        except Exception as e:
            if str(e) != getattr(self, '_guide_err', None): self._guide_err = str(e); self.say(f'guide: {e}', 'WARN')

    def _guide_tick(self):
        """Once a second from _refresh: advance the milestones the facts prove and redraw the panel when something changed."""
        st0 = self._guide_state()
        if not st0['enabled']: return
        f = self._guide_facts()
        if f['game_running'] and f['proxy_ready']: self._guide_game_seen = True
        if not f['proxy_alive']: self._guide_game_seen = False
        f['game_seen'] = self._guide_game_seen
        st = guide.advance(st0, f)
        if st != st0: self._guide_save(st)
        rows = guide.evaluate(st, f); self._spot(guide.spot(rows, f))
        self._guide_render(st, rows, guide.coach(st, f, self._guide_note()), guide.explain(st['summary']) if 'after' in st['ms'] and not guide.live_session(f) else [])

    def _guide_visibility(self):
        on = self._guide_state()['enabled']
        if on: self.guide_frame.pack(fill='x', pady=(8, 0))
        else: self.guide_frame.pack_forget(); self._spot(None)
        self.sv_guide.set(on); self._guide_sig = None

    def guide_toggle(self, on=None):
        st = self._guide_state(); st['enabled'] = (not st['enabled']) if on is None else bool(on); st['offered'] = st['offered'] or version.__version__
        self._guide_save(st); self._guide_visibility(); self._guide_tick()

    def _guide_render(self, st, rows, cards=(), lines=()):
        """Compact checklist: every step is one line; only the step you are on (and a running one) spells out what to do. Below it: help for what is going wrong, and what happened last time."""
        shown = lambda r: '' if r['status'] == 'todo' else r['detail']
        wl = self._guide_wraplength(); note = self._guide_note()
        sig = (json.dumps([[r['id'], r['n'], r['status'], r['actions'], r['skippable']] for r in rows]) + st['path'] + str(guide.all_passed(rows)) + note
               + json.dumps([[c['id'], c['actions']] for c in cards]) + '\n'.join(lines))
        if sig == self._guide_sig:                                                    # same layout: only refresh the texts (the request counter changes every second)
            for r in rows:
                lab = self._guide_lbl.get(r['id'])
                if lab is not None and lab.cget('text') != shown(r): lab.configure(text=shown(r))
            return
        self._guide_sig = sig; self._guide_lbl = {}
        for w in self.guide_body.winfo_children(): w.destroy()
        col = dict(done=OK, running=WARN, skipped=DIM, current=ACC, todo=OFF); mark = dict(done='\u2713', running='\u2026', skipped='-', current='\u25cf', todo='\u25cb')
        for r in rows:
            fr = ttk.Frame(self.guide_body); fr.pack(fill='x', pady=1); cur = r['status'] == 'current'
            tk.Label(fr, text=mark[r['status']], fg=col[r['status']], bg=BG, width=2, font=('Segoe UI', 11, 'bold')).pack(side='left', anchor='n')
            tf = tk.Frame(fr, width=230, height=22, bg=BG); tf.pack(side='left', anchor='n'); tf.pack_propagate(False)                       # fixed cell: the texts line up whatever the font
            ttk.Label(tf, text=f"{r['n']}. {r['title']}", style='H.TLabel' if cur else 'TLabel').pack(side='left', anchor='w')
            bt = ttk.Frame(fr); bt.pack(side='right', anchor='n', padx=(8, 0))
            dl = ttk.Label(fr, text=shown(r), wraplength=wl, justify='left', style='TLabel' if r['status'] in ('current', 'running') else 'Dim.TLabel'); dl.pack(side='left', fill='x', expand=True, anchor='n'); self._guide_lbl[r['id']] = dl
            if r['status'] != 'todo':
                for k, (act, lab) in enumerate(r['actions']):
                    b = ttk.Button(bt, text=lab, style='Accent.TButton' if cur and k == 0 else 'TButton', command=lambda a=act: self.guide_do(a)); b.pack(side='left', padx=2)
                    if act in ('choose_quick', 'choose_offline'): Tip(b, guide.PATH_TEXT[act.split('_', 1)[1]])                    # what each choice means, on hover
                if r['skippable'] and r['status'] in ('current', 'running'): ttk.Button(bt, text='Skip', command=lambda i=r['id']: self.guide_do('skip:' + i)).pack(side='left', padx=2)
        if rows and guide.all_passed(rows):
            ttk.Label(self.guide_body, text='All set. Next time: Start session, play, Stop session. "Start over" runs this checklist again.', style='H.TLabel').pack(anchor='w', pady=(4, 0))
        if lines:                                                                      # what happened in the session that just ended
            box = tk.Frame(self.guide_body, bg=PANEL); box.pack(fill='x', pady=(6, 0))
            tk.Label(box, text='What happened', fg=ACC, bg=PANEL, font=('Segoe UI', 10, 'bold'), anchor='w').pack(fill='x', padx=8, pady=(6, 0))
            tk.Label(box, text='\n'.join(lines), fg=FG, bg=PANEL, anchor='w', justify='left', wraplength=wl + 330).pack(fill='x', padx=8, pady=2)
            bb = tk.Frame(box, bg=PANEL); bb.pack(anchor='w', padx=8, pady=(2, 6)); ttk.Button(bb, text='Before/after test', command=lambda: self.guide_do('abtest')).pack(side='left')
        for c in cards:                                                                # plain-language help for what is going wrong now
            box = tk.Frame(self.guide_body, bg=PANEL); box.pack(fill='x', pady=(6, 0))
            tk.Label(box, text=c['title'], fg=WARN, bg=PANEL, font=('Segoe UI', 10, 'bold'), anchor='w').pack(fill='x', padx=8, pady=(6, 0))
            tk.Label(box, text=c['text'], fg=FG, bg=PANEL, anchor='w', justify='left', wraplength=wl + 330).pack(fill='x', padx=8, pady=2)
            if c['actions']:
                bb = tk.Frame(box, bg=PANEL); bb.pack(anchor='w', padx=8, pady=(2, 6))
                for k, (act, lab) in enumerate(c['actions']): ttk.Button(bb, text=lab, style='Accent.TButton' if k == 0 else 'TButton', command=lambda a=act: self.guide_do(a)).pack(side='left', padx=(0, 6))
            else: tk.Frame(box, bg=PANEL, height=4).pack()
        if note: tk.Label(self.guide_body, text='Last problem: ' + note + '   (details: Activity log below, or the Doctor)', fg=BAD, bg=BG, anchor='w', justify='left', wraplength=self._guide_wraplength() + 330).pack(fill='x', pady=(4, 0))

    def _guide_wraplength(self):
        w = self.guide_body.winfo_width()
        return max(260, w - 560) if w > 200 else 620                       # the room left of the title column and the buttons

    def _guide_wrap(self, e=None):
        wl = self._guide_wraplength()
        for l in self._guide_lbl.values(): l.configure(wraplength=wl)

    def guide_do(self, a):
        try:
            st = self._guide_state()
            if a in ('choose_quick', 'choose_offline'): st['path'] = a.split('_', 1)[1]; self._guide_save(st)
            elif a == 'find_folder': self.guide_find_folder()
            elif a == 'confirm_anyway': st['confirmed_root'] = paths.GAME_ROOT; self._guide_save(st)
            elif a.startswith('skip:'): self._guide_save(guide.skip(st, a[5:]))
            elif a == 'restart': self._guide_game_seen = False; self._guide_save(guide.restart(st))
            elif a == 'view': self.set_simple()
            elif a == 'glossary': self.show_glossary()
            elif a == 'abtest': self.show_abtest()
            elif a == 'goto_pack': self._goto('Texture pack')
            elif a == 'goto_report': self._goto('Report')
            elif a == 'doctor': self._goto('Doctor'); self.do_doctor()
            elif a == 'game_setup': self.do_game_setup()
            elif a == 'start_session': self.do_start()
            elif a == 'stop_session': self.do_stop()
            elif a == 'apply_hosts': self.do_hosts_apply()
            elif a == 'hosts_remove': self.do_hosts_remove()
            elif a == 'open_shots': os.makedirs(guide.ab_dir(), exist_ok=True); os.startfile(guide.ab_dir())
        except Exception as e: self.say(f'guide: {e}', 'WARN')
        self._guide_tick_safe()

    def guide_find_folder(self):
        self.say('guide: looking for the game folder in the usual places...')
        def work():
            try: found = guide.find_game_folders()
            except Exception as e: found = []; self.say(f'guide: folder search failed: {e}', 'WARN')
            self.q.put(('ask', lambda: self._guide_choose_folder(found)))
        threading.Thread(target=work, daemon=True).start()

    def _guide_choose_folder(self, found):
        """Show what was found (or nothing); the user picks one, browses to another, or cancels. Nothing is set without a click."""
        dlg = tk.Toplevel(self); dlg.title('Find my game folder'); dlg.configure(bg=BG); dlg.transient(self); dlg.geometry('760x330')
        ttk.Label(dlg, text=('I found these. Pick yours, or browse to another folder.' if found else 'I could not find it in the usual places. Browse to the folder that contains the game files.'), wraplength=720).pack(anchor='w', padx=12, pady=(12, 6))
        lb = tk.Listbox(dlg, bg=PANEL, fg=FG, selectbackground='#31507f', activestyle='none', height=9, font=('Segoe UI', 9)); lb.pack(fill='both', expand=True, padx=12)
        for c in found: lb.insert('end', guide.describe_candidate(c))
        if found: lb.selection_set(0)
        def use():
            sel = lb.curselection()
            if sel: dlg.destroy(); self._apply_game_folder(found[sel[0]]['path'])
        def browse():
            from tkinter import filedialog
            p = filedialog.askdirectory(parent=dlg, title='Select the game folder', initialdir=paths.GAME_ROOT if os.path.isdir(paths.GAME_ROOT) else None)
            if p: dlg.destroy(); self._apply_game_folder(p)
        bt = ttk.Frame(dlg); bt.pack(fill='x', padx=12, pady=10)
        b = ttk.Button(bt, text='Use selected', style='Accent.TButton', command=use); b.pack(side='left'); b.state(['!disabled'] if found else ['disabled'])
        ttk.Button(bt, text='Browse...', command=browse).pack(side='left', padx=6); ttk.Button(bt, text='Cancel', command=dlg.destroy).pack(side='right')
        lb.bind('<Double-Button-1>', lambda e: use())

    def _apply_game_folder(self, path):
        """Set the game folder (the same setting as Game tab -> Locations). A folder that does not look like the game is accepted only after an explicit yes."""
        path = os.path.normpath(path)
        if not os.path.isdir(path): messagebox.showerror('Game folder', 'That folder does not exist.', parent=self); return False
        sc = guide.score_folder(path)
        if sc == 0 and not messagebox.askyesno('Game folder', f'This folder does not look like the game folder (no cod26 or sp26 inside, no known game program):\n\n{path}\n\nUse it anyway?', parent=self): return False
        self.cfg['paths']['game_root'] = path; st = self._guide_state()
        if sc == 0: st['confirmed_root'] = path
        self.cfg['guide'] = st; self.pv_loc['game_root'].set(path); config.save(self.cfg); self._gfc = None; self._guide_sig = None
        self.say(f'game folder set to {path}', 'OK'); self.show_validation(); self.show_player_cfg(); self.refresh_cache(); self.refresh_mirror(); self._refresh_runs(); self.pack_refresh()
        return True

    def _offer_guide(self):
        """First start with no game folder configured: offer the guide once (never again, and never to someone who has already set things up)."""
        st = self._guide_state()
        if st['offered'] or paths.CONFIGURED: return
        yes = messagebox.askyesno('Guided setup', 'New here? The guided setup is a short checklist on the Dashboard that walks you through the first run and ticks each step off by itself.\n\n'
                                                  'It never changes anything without a click. While it is on, the advanced tabs are tucked away (Simple view); the "Full view" button or Settings -> Help brings them back.\n\nShow it?', parent=self)
        st['offered'] = version.__version__; st['enabled'] = bool(yes); st['simple'] = bool(yes); self._guide_save(st); self._guide_visibility(); self._apply_view(); self._guide_tick_safe()

    # ---------------------------------------------------------------- simple view, tabs, spotlight, words, before/after test
    def _apply_view(self):
        """Simple view hides the advanced tabs, the profile picker, the graph and most counters (and uses plainer counter names); Full view shows everything."""
        simple = self._guide_state()['simple']
        try: was = next((n for n, fr in self.tabs.items() if str(fr) == str(self.nb.select())), None)
        except tk.TclError: was = None
        for name, fr in self.tabs.items():
            try: self.nb.tab(fr, state='hidden' if simple and name not in guide.SIMPLE_TABS else 'normal')
            except tk.TclError: pass
        if simple and was and was not in guide.SIMPLE_TABS:                          # the tab that was open is gone: go to the Dashboard (not to whichever tab Tk picks)
            try: self.nb.select(self.tabs['Dashboard'])
            except tk.TclError: pass
        if simple: self.prof_box.pack_forget(); self.prof_desc.pack_forget(); self.spark_box.pack_forget(); self.simple_note.pack(anchor='w', after=self.dash_row)
        else: self.prof_box.pack(side='left', before=self.btn_start); self.simple_note.pack_forget(); self.prof_desc.pack(anchor='w', after=self.dash_row); self.spark_box.pack(fill='x', pady=(0, 8), after=self.cnt_box)
        for c in self.cnt_cells.values(): c.grid_remove()
        for n, k in enumerate([k for k in self.cnt_order if not simple or k in guide.SIMPLE_COUNTERS]):
            self.cnt_cells[k].grid(row=n // 6, column=n % 6, padx=14, pady=8, sticky='w'); self.cnt_lbl[k].configure(text=guide.SIMPLE_COUNTER_LABELS[k] if simple else self.cnt_names[k])
        self.btn_view.configure(text='Full view' if simple else 'Simple view'); self.sv_simple.set(simple)

    def set_simple(self, on=None):
        st = self._guide_state(); st['simple'] = (not st['simple']) if on is None else bool(on); self._guide_save(st); self._apply_view()

    def _goto(self, name):
        """Open a tab (a hidden one is brought back first: the user asked for it)."""
        fr = self.tabs[name]
        try:
            if self.nb.tab(fr, 'state') == 'hidden': self.nb.tab(fr, state='normal')
        except tk.TclError: pass
        self.nb.select(fr)

    def _spot(self, key):
        """Highlight the control the current step points at, and clear the previous one (a button turns amber, a tab gets an arrow)."""
        if key == self._spot_key: return
        old, self._spot_key = self._spot_key, key
        for k, on in ((old, False), (key, True)):
            if not k: continue
            try:
                if k.startswith('tab:'): self.nb.tab(self.tabs[k[4:]], text=('\u25b6 ' if on else '') + k[4:])
                else: getattr(self, k).configure(style='Spot.TButton' if on else self.SPOT_BASE.get(k, 'TButton'))
            except (tk.TclError, KeyError, AttributeError): pass

    def show_glossary(self):
        old = getattr(self, '_glossary', None)
        if old is not None and old.winfo_exists(): old.lift(); return old
        dlg = self._glossary = tk.Toplevel(self); dlg.title('What the words mean'); dlg.configure(bg=BG); dlg.transient(self); dlg.geometry('720x520')
        fr, t = self._scrolled(dlg, 20); fr.pack(fill='both', expand=True, padx=12, pady=(12, 6)); t.configure(state='normal', wrap='word')
        for term, text in guide.GLOSSARY: t.insert('end', term + '\n', 'ACC'); t.insert('end', text + '\n\n')
        t.configure(state='disabled'); ttk.Button(dlg, text='Close', command=dlg.destroy).pack(pady=(0, 10)); return dlg

    def show_abtest(self):
        """A short guided before/after comparison. It only points at the usual buttons; the steps are saved so it can be left and resumed."""
        old = getattr(self, '_ab', None)
        if old is not None and old.winfo_exists(): old.lift(); return old
        dlg = self._ab = tk.Toplevel(self); dlg.title('Before / after test'); dlg.configure(bg=BG); dlg.transient(self); dlg.geometry('660x330')
        head = ttk.Label(dlg, style='H.TLabel'); head.pack(anchor='w', padx=14, pady=(14, 4)); body = ttk.Label(dlg, wraplength=620, justify='left'); body.pack(anchor='w', padx=14)
        bt = ttk.Frame(dlg); bt.pack(side='bottom', fill='x', padx=14, pady=14); box = {}
        act = ttk.Button(bt, style='Accent.TButton'); back = ttk.Button(bt, text='Back'); nxt = ttk.Button(bt, text='Next'); ttk.Button(bt, text='Close', command=dlg.destroy).pack(side='right')
        nxt.pack(side='right', padx=6); back.pack(side='right')
        def show(i=None):
            st = self._guide_state()
            if i is not None: st['ab'] = i; self._guide_save(st)
            v = guide.ab_view(st['ab'], st['summary']); box['v'] = v
            head.configure(text=f"Step {v['n']} of {v['total']}: {v['title']}"); body.configure(text=v['text'])
            if v['action']: act.configure(text=v['action'][1], command=lambda a=v['action'][0]: self.guide_do(a)); act.pack(side='left')
            else: act.pack_forget()
            back.state(['disabled'] if v['first'] else ['!disabled']); nxt.configure(text='Done' if v['last'] else 'Next')
        def step(d):
            v = box['v']
            if d > 0 and v['last']: dlg.destroy(); return
            show(v['n'] - 1 + d)
        back.configure(command=lambda: step(-1)); nxt.configure(command=lambda: step(1)); dlg.show = show; show()
        return dlg

    # ---------------------------------------------------------------- thread plumbing
    def say(self, msg, tag=None):
        line = f"{time.strftime('%H:%M:%S')} {msg}"
        try:
            with open(self.gui_log_path, 'a', encoding='utf-8') as fh: fh.write(line + '\n')
        except OSError: pass
        self.q.put(('say', line, tag))
        if tag in ('ERR', 'WARN'): self._guide_last = (time.time(), ' '.join(str(msg).split())[:400])
        elif tag == 'OK': self._guide_last = None

    def bg(self, label, fn, *args):
        if self.busy: self.say(f'busy - wait for the current action to finish', 'WARN'); return
        self.busy = True; self._busy_ui(True)
        def run():
            try: fn(*args)
            except Exception as e: self.say(f'{label} failed: {e}', 'ERR')
            finally: self.q.put(('idle',))
        threading.Thread(target=run, daemon=True).start()

    def _busy_ui(self, b):
        st = 'disabled' if b else 'normal'
        for w in (self.btn_start, self.btn_stop): w.configure(state=st)

    def _drain(self):
        try:
            while True:
                m = self.q.get_nowait()
                if m[0] == 'say':
                    t = m[2] or ('ERR' if re.search(r'\bFAIL|failed|ERROR', m[1]) else 'WARN' if re.search(r'\bWARN', m[1]) else 'OK' if re.search(r'\bOK\b|READY|started|stopped', m[1]) else None)
                    for ln in m[1].split('\n'): self._put(self.act, ln, t)
                elif m[0] == 'idle': self.busy = False; self._busy_ui(False)
                elif m[0] == 'ask': m[1]()
        except queue.Empty: pass
        self.after(200, self._drain)

    def ask_main(self, fn):
        """Run fn() on the UI thread and return its result (for dialogs from worker threads)."""
        ev = threading.Event(); box = []
        self.q.put(('ask', lambda: (box.append(fn()), ev.set()))); ev.wait(); return box[0]

    # ---------------------------------------------------------------- poller (worker thread)
    def _poller(self):
        n = 0; slow = {}
        while not self.stop_poll.is_set():
            try:
                s = {}; cfg = self.cfg; port = config.effective_proxy(cfg)['port']
                st = hosts.status(); s['hosts'] = st['state']
                if n % 4 == 0: slow['resolve'] = hosts.resolve_check()
                if n % 3 == 0:
                    slow['game'] = procs.image_running(*paths.GAME_EXES); slow['owners'] = procs.port_owner(port)
                if n % 10 == 0:
                    free = __import__('shutil').disk_usage(paths.ROOT).free / 2**30; slow['free'] = free
                s.update(slow)
                s['pstat'] = proxyctl.fetch_stats(port); s['pproc'] = procs.status('proxy'); s['gproc'] = procs.status('guard')
                s['gstat'] = proxyctl.read_json(proxyctl.GUARD_STATS) if s['gproc']['alive'] else None
                s['mproc'] = procs.status('mirror'); s['mprog'] = mirrorctl.progress(); s['vproc'] = procs.status('mirror-verify'); s['vprog'] = mirrorctl.verify_progress() if s['vproc']['alive'] else None
                s['session'] = session.session_info(); s['t'] = time.time()
                self.snap = s
            except Exception as e:
                self.snap = dict(self.snap, poll_error=str(e))
            n += 1; time.sleep(1.0)

    # ---------------------------------------------------------------- UI refresh (main thread)
    def _refresh(self):
        s = self.snap
        if s and 't' in s:
            h = s.get('hosts', '?'); self.light('hosts', {'OK': 'ok', 'FOREIGN': 'warn', 'MIXED': 'warn'}.get(h, 'fail'), h)
            r = s.get('resolve') or {}; self.light('resolve', 'ok' if r.get('ok') else 'fail', 'loopback' if r.get('ok') else 'not ours')
            ps = s.get('pstat'); pp = s.get('pproc', {})
            if ps: self.light('proxy', 'ok', f"pid {ps['pid']}")
            elif pp.get('alive'): self.light('proxy', 'fail', 'not answering')
            else: self.light('proxy', 'off', 'stopped')
            own = s.get('owners') or []; port = config.effective_proxy(self.cfg)['port']
            if not own: self.light('port', 'off', f'{port} free')
            elif pp.get('alive') and all(o['pid'] == pp['pid'] for o in own): self.light('port', 'ok', f'{port} ours')
            else: self.light('port', 'fail', f"{port}: {own[0]['name']}")
            mi = ps.get('mirror_ids') if ps else None
            self.light('mirror', 'ok' if mi else 'off', f'{mi:,} ids' if mi else ('off' if ps else '-'))
            gs = s.get('gstat'); gp = s.get('gproc', {})
            if gs: self.light('guard', 'fail' if gs.get('hit') else 'ok', f"{gs['cache_gib']:.1f}/{gs['limit_gib']:.0f} GiB")
            else: self.light('guard', 'ok' if gp.get('alive') else 'off', 'running' if gp.get('alive') else 'stopped')
            g = s.get('game') or []; self.light('game', 'warn' if g else 'off', 'RUNNING' if g else 'closed')
            if g and not self._game_prev: self.game_start = time.time() - 5; self.say(f"game detected: {', '.join(g)}")            # launch detected (poll granularity ~3 s)
            if self._game_prev and not g:
                win = self._game_ended()
                # no live proxy needed: the report reads the proxy log, so it also works when the session was stopped while the game was still shutting down
                self.say('game exited - generating the session report' + (' for this launch' if win else '')); self.bg('report', self._make_report, -1, win, True)
            self._game_prev = bool(g)
            fr = s.get('free');
            if fr is not None: self.light('disk', 'fail' if fr < 20 else 'warn' if fr < 60 else 'ok', f'{fr:.0f} GiB free')
            self._refresh_counters(ps, s); self._refresh_hosts_tab(h); self._refresh_mirror_live(s)
            self._guide_tick_safe()
            self.c_warn.configure(text='Game is running: the cache may be mid-write (read-only view; backup/restore/install are blocked).' if g else '')
        self.after(1000, self._refresh)

    def _refresh_counters(self, ps, s):
        if not ps:
            for l in self.cnt.values(): l.configure(text='-')
            self.rate.clear(); self.series.clear(); self._draw_hist({}); self._draw_spark(); return
        st = ps['stat']; self.rate.append((ps['now'], st['req']))
        tot = st['bytes'] + st.get('mbytes', 0)
        if self.series and ps['now'] > self.series[-1][0]:
            t0, r0, b0 = self.series[-1][:3]; dt = ps['now'] - t0; self.series.append((ps['now'], st['req'], tot, (st['req'] - r0) / dt, (tot - b0) / dt / 2**20))
        elif not self.series: self.series.append((ps['now'], st['req'], tot, 0.0, 0.0))
        self._draw_spark()
        rps = (self.rate[-1][1] - self.rate[0][1]) / max(0.001, self.rate[-1][0] - self.rate[0][0]) if len(self.rate) > 1 else 0
        c = self.cnt; c['req'].configure(text=f"{st['req']:,}"); c['mirror'].configure(text=f"{st['mirror']:,}"); c['upok'].configure(text=f"{st['ok'] - st['mirror']:,}")
        c['err'].configure(text=str(st['err'])); c['retry'].configure(text=str(st['retry'])); c['cliabort'].configure(text=str(st['cliabort'])); c['skip'].configure(text=str(st['skip'])); c['miss'].configure(text=str(st['miss']))
        c['mgib'].configure(text=f"{st.get('mbytes', 0) / 2**30:.2f}"); c['ugib'].configure(text=f"{st['bytes'] / 2**30:.2f}"); c['rps'].configure(text=f'{rps:.1f}')
        c['sess'].configure(text=fmt_dur(ps['now'] - ps['started'])); self._draw_hist(ps['hist'])
        for iid in self.recent.get_children(): self.recent.delete(iid)
        for r in reversed(ps['recent'][-30:]):
            raw = r['raw']; self.recent.insert('', 'end', values=(time.strftime('%H:%M:%S', time.localtime(r['t'])), r['id'] or '-', f'{raw / 2**20:.2f}M' if raw else '?', r['tier'], r['src'], r['status'], r['bytes']))

    def _draw_spark(self):
        cv = self.spark; cv.delete('all'); w = max(cv.winfo_width(), 300); h = int(cv['height']); pts = list(self.series)[-180:]
        if len(pts) < 2: cv.create_text(10, h // 2, text='no data (proxy not running)', fill=DIM, anchor='w'); return
        for k, (idx, colr, unit) in enumerate(((3, ACC, 'req/s'), (4, OK, 'MiB/s'))):
            vals = [p[idx] for p in pts]; mx = max(max(vals), 1e-9); top = 4; ht = h - 8
            xy = []
            for i, v in enumerate(vals): xy += [8 + (w - 16) * i / 179 + (w - 16) * (180 - len(vals)) / 179, top + ht - ht * v / mx]
            cv.create_line(*xy, fill=colr, width=1.6)
            cv.create_text(w - 10, 8 + k * 14, text=f'{unit}: now {vals[-1]:.1f}  peak {mx:.1f}', fill=colr, anchor='e', font=('Consolas', 9))

    def _draw_hist(self, hist):
        cv = self.hist; cv.delete('all'); labels = ['<=64K', '<=256K', '<=1M', '<=4M', '<=8M', '<=16M', '>16M']
        mx = max([hist.get(k, 0) for k in labels] + [1])
        for i, k in enumerate(labels):
            v = hist.get(k, 0); y = 12 + i * 33; w = int(250 * v / mx)
            cv.create_text(6, y + 10, text=k, fill=DIM, anchor='w', font=('Consolas', 9)); cv.create_rectangle(70, y, 70 + max(w, 1 if v else 0), y + 20, fill=BAD if k in ('<=8M', '<=16M', '>16M') else ACC, width=0)
            cv.create_text(76 + w, y + 10, text=str(v), fill=FG, anchor='w', font=('Consolas', 9))

    def _refresh_hosts_tab(self, h=None):
        try: st = hosts.status()
        except Exception as e: self.hosts_lbl.configure(text=f'cannot read hosts: {e}'); return
        txt = {'OK': 'Override ACTIVE (managed block)', 'FOREIGN': 'Override present as hand-added lines (not managed)', 'MIXED': 'Managed block + duplicate hand-added lines', 'PARTIAL': 'PARTIAL block (one family missing)', 'ABSENT': 'No override (normal DNS)'}[st['state']]
        self.hosts_lbl.configure(text=txt)
        body = '\n'.join((st['block'] or []) + [l for _, _, l in st['foreign']]) or '(none)'
        if body != getattr(self, '_hosts_body', None):
            self._hosts_body = body; self.hosts_txt.configure(state='normal'); self.hosts_txt.delete('1.0', 'end'); self.hosts_txt.insert('end', body); self.hosts_txt.configure(state='disabled')
        bk = [os.path.basename(b) for b in hosts.list_backups()]
        if bk != getattr(self, '_bk', None):
            self._bk = bk; self.bk_list.delete(0, 'end'); [self.bk_list.insert('end', b) for b in bk]

    # ---------------------------------------------------------------- logs
    def _tail_logs(self):
        self._tail_mirror()
        new = []
        for n, _ in LOG_SOURCES:
            for ln in self.tails[n].read_new(): new.append((n, ln))
        if new:
            self.log_lines.extend(new)
            if not self.paused.get():
                for n, ln in new:
                    if self._log_visible(n, ln): self._put(self.logt, f'[{n:7s}] {ln}', self._log_tag(ln))
        self.after(600, self._tail_logs)

    def _log_visible(self, n, ln):
        if not self.lv[n].get(): return False
        if self.hide_req.get() and REQ_RE.search(ln): return False
        f = self.flt.get().strip()
        if f:
            try: return re.search(f, ln, re.I) is not None
            except re.error: return True
        return True

    @staticmethod
    def _log_tag(ln):
        if re.search(r'ERR|FAIL|BIND-FAIL|LIMIT HIT|Traceback', ln): return 'ERR'
        if re.search(r'RETRY|CLIENT-ABORT|SKIP-TIER|MISS|BUDGET|WARN', ln): return 'WARN'
        if re.search(r'READY|listening', ln): return 'OK'
        return None

    def _rerender_logs(self):
        self.logt.configure(state='normal'); self.logt.delete('1.0', 'end'); self.logt.configure(state='disabled')
        for n, ln in list(self.log_lines)[-2500:]:
            if self._log_visible(n, ln): self._put(self.logt, f'[{n:7s}] {ln}', self._log_tag(ln), scroll=False)
        self.logt.see('end')

    def _clear_logs(self):
        self.log_lines.clear(); self._rerender_logs()

    # ---------------------------------------------------------------- actions
    def _profile_changed(self, *_):
        p = self.profile.get(); self.cfg['profile'] = p; config.save(self.cfg)
        d = {'Default': 'Mirror first, upstream CDN only for chunks missing from the mirror.', 'Offline test': 'Mirror only - any miss is a 404 (finds mirror gaps; no network use).', 'Capture': 'No mirror - every chunk comes from the CDN (new-content runs).',
             'Standard HD (1440p class)': 'Detail level Standard: chunks above 4 MiB raw are withheld (404), the engine keeps the smaller mip. Mirror first.', 'Ultra (4K class)': 'Detail level Ultra: no size cap. Mirror first.',
             'Slow link - offline mirror': 'Play only from the local mirror (offline): nothing is fetched from the internet; a mirror gap is a 404.'}
        prof = config.all_profiles(self.cfg).get(p, {}); extra = ', '.join(f'{s}.{k}={v}' for s in config.SECTIONS for k, v in prof.get(s, {}).items()) if p not in config.BUILTIN_PROFILES else ''
        self.prof_desc.configure(text=d.get(p) or ('Saved profile: ' + extra))
        if hasattr(self, 'pk_level'): self._sync_caps(); self.pk_level.set(config.effective(self.cfg)['pack']['level']); self.pack_refresh()

    def profile_save_as(self):
        from tkinter import simpledialog
        try: self._read_proxy_form()
        except Exception: pass
        name = simpledialog.askstring('Save profile', 'Name for the current proxy / disk-guard / watcher settings:', parent=self)
        if not name or not name.strip(): return
        name = name.strip()
        if name in config.BUILTIN_PROFILES: messagebox.showerror('Profile', 'That name is a built-in profile.', parent=self); return
        self.cfg.setdefault('profiles', {})[name] = config.snapshot_profile(self.cfg); self.cfg['profile'] = name; config.save(self.cfg)
        self.prof_cb.configure(values=list(config.all_profiles(self.cfg))); self.profile.set(name); self._profile_changed(); self.say(f'profile "{name}" saved', 'OK')

    def profile_delete(self):
        n = self.profile.get()
        if n in config.BUILTIN_PROFILES: messagebox.showinfo('Profile', 'Built-in profiles cannot be deleted.', parent=self); return
        if not messagebox.askyesno('Delete profile', f'Delete profile "{n}"?', parent=self): return
        self.cfg['profiles'].pop(n, None); self.cfg['profile'] = 'Default'; config.save(self.cfg)
        self.prof_cb.configure(values=list(config.all_profiles(self.cfg))); self.profile.set('Default'); self._profile_changed()

    def do_start(self):
        def go():
            self.say('--- Start session ---', 'ACC'); ok, msg = session.start(self.cfg, self.say); self.say(('Session READY: ' if ok else 'Session NOT ready: ') + msg, 'OK' if ok else 'ERR')
            if ok: self.say('You can launch the game now.', 'OK')
        self.bg('start', go)

    def do_stop(self):
        def go():
            self.say('--- Stop session ---', 'ACC')
            try:                                      # traffic since the last report and the game is closed: write the report now (a running game gets its report when it exits)
                if procs.image_running(*paths.GAME_EXES): self.say('game is still running: its session report is written when it exits', 'WARN')
                else: self._make_report(-1, None, True)
            except Exception as e: self.say(f'report on stop failed: {e}', 'WARN')
            r = session.stop(self.cfg, self.say)
            if r['hosts_active']: self._hosts_policy('Session stopped.')
        self.bg('stop', go)

    def _hosts_policy(self, why):
        pol = self.cfg['hosts']['on_exit']
        if pol == 'ask': pol = 'remove' if self.ask_main(lambda: messagebox.askyesno('Hosts override', f'{why}\n\nThe hosts override for the CDN host is still active, but nothing is listening any more (the game cannot stream until the proxy runs again).\n\nRemove the override now? (UAC prompt)', parent=self)) else 'keep'
        if pol == 'remove': self._hosts_do('remove')
        else: self.say('hosts override left in place', 'WARN')

    def _hosts_do(self, cmd, extra=()):
        ok, res = session.hosts_cmd(cmd, self.say, extra)
        self.say(f"hosts {cmd}: {'ok' if ok else 'FAILED'} -> state {res.get('state', '?')}" + (f" backup {res.get('backup')}" if res.get('backup') else '') + ('' if ok else f" ({res.get('error')})"), 'OK' if ok else 'ERR')
        return ok

    def _hosts_simple(self, cmd): self._hosts_do(cmd)

    def do_hosts_apply(self):
        try: t, _ = hosts.read(); d = hosts.diff(t, hosts.compute(t, 'apply'))
        except Exception as e: messagebox.showerror('Hosts', str(e), parent=self); return
        if not d: messagebox.showinfo('Hosts', 'Override already in place - nothing to change.', parent=self); return
        if self._confirm_diff('Apply hosts override', d): self.bg('hosts apply', self._hosts_do, 'apply')

    def do_hosts_remove(self):
        try: t, _ = hosts.read(); d = hosts.diff(t, hosts.compute(t, 'remove'))
        except Exception as e: messagebox.showerror('Hosts', str(e), parent=self); return
        if not d: messagebox.showinfo('Hosts', 'No override present - nothing to remove.', parent=self); return
        if self._confirm_diff('Remove hosts override (restore normal DNS)', d): self.bg('hosts remove', self._hosts_do, 'remove')

    def _confirm_diff(self, title, diff_text):
        w = tk.Toplevel(self); w.title(title); w.configure(bg=BG); w.geometry('640x340'); w.transient(self); w.grab_set(); res = []
        ttk.Label(w, text='Changes to the hosts file (a backup is written first):', style='H.TLabel').pack(anchor='w', padx=12, pady=(10, 4))
        t = self._text(w, 12); t.pack(fill='both', expand=True, padx=12)
        for ln in diff_text.splitlines(): t.insert('end', ln + '\n', 'OK' if ln.startswith('+') and not ln.startswith('+++') else 'ERR' if ln.startswith('-') and not ln.startswith('---') else 'DIM')
        t.configure(state='disabled'); b = ttk.Frame(w); b.pack(pady=10)
        ttk.Button(b, text='Continue (UAC)', style='Accent.TButton', command=lambda: (res.append(1), w.destroy())).pack(side='left', padx=6); ttk.Button(b, text='Cancel', command=w.destroy).pack(side='left', padx=6)
        self.wait_window(w); return bool(res)

    def do_restore_backup(self):
        sel = self.bk_list.curselection()
        if not sel: return
        name = self.bk_list.get(sel[0])
        if messagebox.askyesno('Restore backup', f'Replace the whole hosts file with backup\n{name}?\n\n(The current file is backed up first.) Prefer "Remove override" unless you really want an old copy.', parent=self):
            self.bg('restore backup', self._hosts_do, 'restore-backup', (name,))

    def do_resolve(self):
        def go(): r = hosts.resolve_check(); self.say(f"resolver: v4={r['v4']} v6={r['v6']}  -> {'OK (loopback)' if r['ok'] else 'NOT loopback (override inactive or DNS cache stale)'}", 'OK' if r['ok'] else 'WARN')
        self.bg('resolve', go)

    def do_doctor(self, switch=True):
        def go():
            self.say('--- Doctor ---', 'ACC'); res = doctor.run_all(self.cfg); self.say(doctor.format_results(res))
            self.q.put(('ask', lambda: self._show_doctor(res)))
        if switch: self.nb.select(self.tabs['Doctor'])
        self.bg('doctor', go)

    def _show_doctor(self, res):
        for w in self.doc_frame.winfo_children(): w.destroy()
        col = dict(ok=OK, warn=WARN, fail=BAD, info=DIM)
        for i, r in enumerate(res):
            tk.Label(self.doc_frame, text='●', fg=col[r['level']], bg=BG, font=('Segoe UI', 12)).grid(row=i, column=0, padx=(8, 4), pady=3, sticky='n')
            ttk.Label(self.doc_frame, text=r['name'], style='H.TLabel', width=20).grid(row=i, column=1, sticky='nw', pady=3)
            ttk.Label(self.doc_frame, text=r['detail'], wraplength=640, justify='left').grid(row=i, column=2, sticky='nw', pady=3, padx=6)
            if r.get('fix'): ttk.Button(self.doc_frame, text='Fix: ' + {'hosts_apply': 'apply hosts (UAC)', 'flush_dns': 'flush DNS (UAC)', 'start_proxy': 'start proxy', 'restart_proxy': 'restart proxy', 'kill_port_owner': 'stop port owner', 'game_fix': 'set up the game', 'game_undo': 'undo the game setup'}[r['fix'][0]],
                                           command=lambda fx=r['fix'], n=r['name']: self.do_fix(fx, n)).grid(row=i, column=3, padx=8, pady=2, sticky='ne')
        self.doc_frame.columnconfigure(2, weight=1)

    def do_fix(self, fix, name):
        if fix[0] == 'game_fix': return self.do_game_setup()
        if fix[0] == 'game_undo': return self.do_game_undo()
        if fix[0] == 'kill_port_owner':
            who = ', '.join(f'{n} (pid {p})' for p, n in fix[1])
            if not messagebox.askyesno('Stop port owner', f'Terminate {who}?\n\nOnly do this if it is a stale proxy or something you do not need.', parent=self): return
        def go():
            ok, msg = session.run_fix(self.cfg, fix, self.say); self.say(f"fix {name}: {'ok' if ok else 'FAILED'} - {msg}", 'OK' if ok else 'ERR')
            res = doctor.run_all(self.cfg); self.q.put(('ask', lambda: self._show_doctor(res)))
        self.bg('fix', go)

    def do_game_setup(self):
        """Ask first (it changes two things in the game folder), then apply; the Doctor and the checklist show the result."""
        s = gamefix.status()
        if not s['applicable']: messagebox.showinfo('Game setup', gamefix.describe(s), parent=self); return
        if s['ok']: messagebox.showinfo('Game setup', 'Already set up.', parent=self); return
        if s['game_running']: messagebox.showinfo('Game setup', 'The game is running. Close it, then try again.', parent=self); return
        if not messagebox.askyesno('Set up the game',
                                   'This makes two small changes in your game folder so the game uses the textures that are streamed to it:\n\n'
                                   "1. In sp26\\steam_settings\\configs.main.ini: offline=0 and disable_lan_only=1 (the game's Steam emulator stops reporting offline mode). "
                                   'A copy of the original is kept next to it.\n'
                                   "2. sp26\\xpak_cache becomes a link to the game's xpak_cache folder. A real folder in the way is renamed, not deleted.\n\n"
                                   'Windows may ask for permission if the game is in Program Files.\n\nContinue?', parent=self): return
        def go():
            ok, msg = session.run_fix(self.cfg, ('game_fix', None), self.say); self.say(f"game setup: {'ok' if ok else 'FAILED'} - {msg}", 'OK' if ok else 'ERR')
            self._gfc = None
            if ok: self.q.put(('ask', lambda: messagebox.showinfo('Game setup', 'Done: ' + msg + '\n\nStart (or restart) the game from its launcher now.', parent=self)))
            else: self.q.put(('ask', lambda: messagebox.showerror('Game setup', 'The setup could not be finished (the Doctor shows what is still missing):\n\n' + msg, parent=self)))
        self.bg('game setup', go)

    def do_game_undo(self):
        """Put the game folder back as it was before the setup (after a confirmation); the Doctor is refreshed afterwards."""
        s = gamefix.status()
        if s['game_running']: messagebox.showinfo('Undo game setup', 'The game is running. Close it, then try again.', parent=self); return
        if not messagebox.askyesno('Undo game setup',
                                   'This puts the two settings in configs.main.ini back to what they were before (your other edits to that file stay) and removes the sp26\\xpak_cache link. '
                                   "The game's real cache is not touched.\n\nWindows may ask for permission if the game is in Program Files.\n\nContinue?", parent=self): return
        def go():
            ok, msg = session.run_fix(self.cfg, ('game_undo', None), self.say); self.say(f"undo game setup: {'ok' if ok else 'FAILED'} - {msg}", 'OK' if ok else 'ERR')
            self._gfc = None
            self.q.put(('ask', lambda: (messagebox.showinfo if ok else messagebox.showerror)('Undo game setup', msg, parent=self))); self.do_doctor(switch=False)
        self.bg('undo game setup', go)

    def do_bundle(self):
        def go():
            from ccslib import bundle
            p = bundle.make(self.cfg); self.say(f'support bundle: {p}', 'OK'); self.q.put(('ask', lambda: os.startfile(os.path.dirname(p))))
        self.bg('bundle', go)

    # ---- report
    # game launches inside a proxy run (one proxy run can span several launches): recorded by the poller, listed in the Report tab
    def _runs_file(self): return os.path.join(paths.WORK, 'game_runs.json')

    def _load_game_runs(self):
        try: return json.load(open(self._runs_file(), encoding='utf-8'))
        except Exception: return []

    def _game_ended(self):
        start, end = self.game_start, time.time(); self.game_start = None
        if start is None: return None
        runs = self._load_game_runs(); runs.append(dict(start=start, end=end))
        try: json.dump(runs[-200:], open(self._runs_file(), 'w', encoding='utf-8'))
        except OSError: pass
        return (start, end)

    def _refresh_runs(self):
        segs = report.segments(); self._segs = segs; runs = self._load_game_runs(); self._run_opts = collections.OrderedDict()
        starts = [report.seg_start_epoch(s) for s in segs]
        for i, s in enumerate(segs):
            self._run_opts[f"#{s['idx']}  {s.get('date') or '(no date)'} {s['first']}-{s['last']}  reqs={s['nreq']}  [whole proxy run]"] = (s['idx'], None)
            e0 = starts[i]; e1 = next((x for x in starts[i + 1:] if x), float('inf'))
            if e0:
                for k, r in enumerate([r for r in runs if e0 - 60 <= r['start'] < e1], 1):
                    lab = f"#{s['idx']}  launch {k}: {time.strftime('%H:%M:%S', time.localtime(r['start']))}-{time.strftime('%H:%M:%S', time.localtime(r['end']))}"
                    self._run_opts[lab] = (s['idx'], (r['start'], r['end']))
        vals = list(self._run_opts); self.run_cb.configure(values=vals)
        if vals and self.run_var.get() not in vals: self.run_var.set(vals[-1])
        saved = [os.path.basename(x)[:-5] for x in reversed(report.list_reports())]; self.saved_cb.configure(values=saved)

    def _sel_run(self):
        """-> (segment index, window or None) for the Report tab selection."""
        return getattr(self, '_run_opts', {}).get(self.run_var.get(), (-1, None))

    def _show_report(self, md):
        self.rep_txt.configure(state='normal'); self.rep_txt.delete('1.0', 'end')
        for ln in md.splitlines(): self.rep_txt.insert('end', ln + '\n', 'ACC' if ln.startswith('#') else 'ERR' if re.search(r'missing from the mirror: \*\*[1-9]|FAIL', ln) else None)
        self.rep_txt.configure(state='disabled')

    def _view_saved(self, *_):
        p = os.path.join(paths.SESSIONS, self.saved_var.get() + '.md')
        try: self._show_report(open(p, encoding='utf-8').read())
        except OSError as e: self.say(f'cannot open report: {e}', 'ERR')

    @staticmethod
    def _saved_report_covers(seg, window):
        """True when the newest saved report already holds all of this proxy run's requests (same run, same request count, whole run or the single game launch): a stop-time report must not duplicate it."""
        try:
            ls = report.list_reports()
            if not ls or window: return False
            j = json.load(open(max(ls, key=os.path.getmtime), encoding='utf-8'))
            return j.get('segment') == seg['idx'] and j['requests']['total'] == seg['nreq'] and j.get('date') == seg.get('date')      # a report for the game-launch window that holds all of the run's requests counts too
        except Exception: return False

    def _make_report(self, idx, window=None, auto=False):
        segs = report.segments()
        if not segs: self.say('no proxy runs in the log yet', 'WARN'); return
        seg = segs[idx]; key = (seg['idx'], seg['nreq'], tuple(window) if window else None)
        if auto and (seg['nreq'] == 0 or key == getattr(self, '_report_key', None) or self._saved_report_covers(seg, window)): self.say('report: nothing new in the proxy log since the last report - skipped'); return
        self.say(f"report: analysing run #{seg['idx']} ({seg['nreq']} requests){' [auto, game exited]' if auto else ''}...")
        base = report.baseline_for(seg, t0=window[0]) if window else report.baseline_for(seg); post = report.snapshot_cache()
        if base is None: self.say('report: no cache baseline for this run (re-request rate unavailable)', 'WARN')
        rep = report.build(seg, mirror_ids=report.load_mirror_ids(), baseline=base, post=post, window=window); prev = report.previous_report(rep); md = report.to_markdown(rep, prev); m, j = report.save(rep, prev)
        if post and not procs.image_running(*paths.GAME_EXES):          # game closed: this "after" state is the "before" state of the next launch
            try: report.save_snapshot(post, os.path.join(paths.SESSIONS, time.strftime('baseline-%Y%m%d-%H%M%S.json')))
            except OSError: pass
        self._report_key = key; r = rep['requests']; c = rep.get('cache', {}); g = rep.get('mirror_gaps', {})
        self.say(f"report saved: {m}\n  requests={r['total']} unique={r['unique_ids']} >4MiB ids={rep['over_4mib']['ids']} mirror-gaps={g.get('missing_count', '?')} already-in-cache={c.get('requested_pct_already_in_cache', '?')}%", 'OK')
        self.q.put(('ask', lambda: (self._show_report(md), self._refresh_runs(), self.nb.select(self.tabs['Report']) if not auto else None)))

    def _read_proxy_form(self):
        p = self.cfg['proxy']
        for k, v in self.pv.items():
            raw = v.get().strip()
            if k == 'upstream_ip': p[k] = raw
            elif k in ('max_raw_mib', 'budget_gib'): p[k] = float(raw) if raw else p[k]
            else: p[k] = int(raw)
        p['origin'] = self.pv_origin.get(); p['offline'] = self.pv_off.get(); config.save(self.cfg)

    def do_proxy_restart(self):
        try: self._read_proxy_form()
        except ValueError as e: messagebox.showerror('Proxy options', f'invalid number: {e}', parent=self); return
        self.bg('proxy restart', self._proxy_only, True, True)

    def _proxy_only(self, start, restart=False):
        port = config.effective_proxy(self.cfg)['port']
        if start:
            if restart and procs.stop('proxy'): self.say('proxy: stopped for restart')
            if procs.status('proxy')['alive']: self.say('proxy already running'); return
            owners = procs.port_owner(port)
            if owners: self.say(f"port {port} in use by {owners[0]['name']} pid {owners[0]['pid']}", 'ERR'); return
            proxyctl.start_proxy(self.cfg); ok, msg = session._wait_proxy_ready(port, self.say); self.say(f'proxy: {msg}', 'OK' if ok else 'ERR')
        else:
            self.say('proxy: stopped' if procs.stop('proxy') else 'proxy was not running')

    def make_shortcut(self):
        from ccslib import shortcut
        try: p = shortcut.create(); self.say(f'desktop shortcut created: {p}', 'OK')
        except Exception as e: self.say(f'shortcut failed: {e}', 'ERR')

    def save_settings(self):
        try: self.cfg['log_max_mb'] = max(0, float(self.sv_log.get()))
        except ValueError: messagebox.showerror('Settings', 'invalid log size', parent=self); return
        try:
            for (sub, key), v in self.sv.items(): self.cfg[sub][key] = float(v.get()) if key == 'limit_gib' else int(float(v.get()))
        except ValueError as e: messagebox.showerror('Settings', f'invalid number: {e}', parent=self); return
        self.cfg['guard']['action'] = self.sv_action.get(); self.cfg['guard']['enabled'] = self.sv_guard.get(); self.cfg['watchers']['netwatch'] = self.sv_nw.get()
        self.cfg['hosts']['on_exit'] = self.sv_exit.get(); self.cfg['keep_running_on_close'] = self.sv_keep.get(); config.save(self.cfg); self.say('settings saved (apply on next session start)')

    def on_close(self):
        pr = procs.status('proxy')['alive'] or procs.status('guard')['alive']; ha = self.snap.get('hosts', 'ABSENT') != 'ABSENT'
        if (pr or ha) and not self.cfg['keep_running_on_close']:
            a = messagebox.askyesnocancel('Close CCS Control', ('Proxy / guard are running.\n' if pr else '') + ('The hosts override is active.\n' if ha else '') +
                                          '\nYes = stop everything' + (' and apply the hosts policy' if ha else '') + '\nNo = close the window, leave everything running\nCancel = stay', parent=self)
            if a is None: return
            if a:
                self.say('closing: stopping session'); r = session.stop(self.cfg, self.say)
                if r['hosts_active']:
                    pol = self.cfg['hosts']['on_exit']
                    if pol == 'remove' or (pol == 'ask' and messagebox.askyesno('Hosts override', 'Remove the hosts override too? (UAC prompt)', parent=self)): self._hosts_do('remove')
        self.stop_poll.set(); self.destroy()


def single_instance():
    lock = os.path.join(paths.RUN, 'gui.lock'); paths.ensure_dirs()
    try:
        d = json.load(open(lock));
        if procs.ctime(d['pid']) == d.get('ctime') and d['pid'] != os.getpid(): return False
    except Exception: pass
    json.dump(dict(pid=os.getpid(), ctime=procs.ctime(os.getpid())), open(lock, 'w')); return True


MUTEX_NAME = 'MW4TextureStreamingToolkit-Running'      # the installer looks for this to know the window is open (AppMutex)
_mutex = None


def hold_mutex():
    global _mutex
    try: _mutex = ctypes.windll.kernel32.CreateMutexW(None, False, MUTEX_NAME)
    except Exception: _mutex = None


def main(argv=None):
    argv = sys.argv[1:] if argv is None else list(argv)
    if '--selftest' in argv:
        app = App(selftest=True)
        def done():
            if sys.stdout is not None: print(json.dumps({k: v for k, v in app.snap.items() if k in ('hosts', 'resolve', 'pstat', 'game', 'free')}, default=str))
            app.destroy()
        app.after(2500, done); app.mainloop(); return 0
    if not single_instance():
        import tkinter.messagebox as mb; r = tk.Tk(); r.withdraw(); mb.showinfo('CCS Control', 'CCS Control is already running.'); return 0
    hold_mutex(); app = App()
    if '--tab' in argv: app.after(300, lambda: app.nb.select(app.tabs[argv[argv.index('--tab') + 1]]))
    if '--doctor' in argv: app.after(1500, app.do_doctor)
    app.mainloop(); return 0


if __name__ == '__main__':
    sys.exit(main())
