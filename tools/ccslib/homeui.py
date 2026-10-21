"""homeui.py - the Home screen: draws a home.build() view with the widgets of ui.py. No decisions in here; it shows what the view says and reports clicks as action names.

  page = HomePage(parent, ticker, on_action)      on_action(name) gets one of home.ACTIONS
  page.render(view)                               cheap to call every second: the layout is rebuilt only when it changes, the numbers are updated in place
"""
import json, tkinter as tk
from . import home, ui
from .ui import BG, CARD, TEXT, DIM, FAINT, ACCENT, OK, WARN, BAD, LINE, S

CONTENT_W = 1012


def _click(widget, fn):
    """Make a widget and everything in it clickable."""
    widget.bind('<Button-1>', lambda e: fn(), add='+')
    for c in widget.winfo_children(): _click(c, fn)


class Link(tk.Label):
    """Clickable text; brighter on hover."""
    def __init__(self, parent, text, command, fg=DIM, hover=TEXT, bg=BG, px=13):
        super().__init__(parent, text=text, fg=fg, bg=bg, cursor='hand2', font=ui.font(parent, px)); self.fg, self.hov = fg, hover
        self.bind('<Button-1>', lambda e: command()); self.bind('<Enter>', lambda e: self.configure(fg=self.hov)); self.bind('<Leave>', lambda e: self.configure(fg=self.fg))


class HomePage(tk.Frame):
    def __init__(self, parent, ticker, on_action, version='', tip=None):
        super().__init__(parent, bg=BG); ui.init(self)
        self.ticker, self.act, self.version, self.tip_factory = ticker, on_action, version, tip; self.tips = {}; self.page = 'home'; self._dsig = None; self.dview = None
        self.view = None; self._sig = None; self._pick_cb = None; self._dots = 0; self._compact = False
        self._build_header(); self._build_footer()
        self.stage = tk.Frame(self, bg=BG); self.stage.pack(fill='both', expand=True)
        self.col = tk.Frame(self.stage, bg=BG); self.col.place(relx=.5, rely=.5, anchor='center')
        self.stage.bind('<Configure>', self._resize)
        self.ring = ui.Ring(self.col, d=190, thick=9, ticker=ticker)
        self.h1 = tk.Label(self.col, text='', bg=BG, fg=TEXT, font=ui.font(self, 30, 'head', True)); self.sub = tk.Label(self.col, text='', bg=BG, fg=DIM, font=ui.font(self, 15), justify='center', wraplength=S(560))
        self.row = tk.Frame(self.col, bg=BG); self.pill_box = None
        self.stepper = ui.Stepper(self.col); self.cards_row = tk.Frame(self.col, bg=BG); self.kpi_row = tk.Frame(self.col, bg=BG); self.alert_box = tk.Frame(self.col, bg=BG)
        self.body_box = tk.Frame(self.col, bg=BG)                     # the first-run cards
        self.card_labels = []; self.kpi_labels = {}; self.spark = None; self.step_pill = None
        self.dl_col = tk.Frame(self.stage, bg=BG); self.drawer = Drawer(self, ticker, self._row_action)
        self.stage.bind('<Button-1>', lambda e: self.drawer.hide(), add='+'); self.col.bind('<Button-1>', lambda e: self.drawer.hide(), add='+')
        self.winfo_toplevel().bind('<Escape>', lambda e: self.drawer.hide(), add='+')
        self._tip('ring', self.ring, ''); self._tip('stepper', self.stepper, ''); self._tip('footer', self.foot_txt, '')

    # ------------------------------------------------------------------------ tips, settings drawer, pages
    def _tip(self, key, widget, text):
        """Hover help: one tip per key; the text is changed later by set_tip (a widget that was rebuilt gets a new tip)."""
        if not self.tip_factory: return
        t = self.tips.get(key)
        if t is None or t.w is not widget: self.tips[key] = t = self.tip_factory(widget, text)
        t.text = text

    def reset_motion(self):
        """After the motion setting changed: draw the rings again so their animations start or stop."""
        for r in (self.ring, getattr(self, 'dl_ring', None)):
            if r is not None:
                try: r.cfg = None; r._pulse_on = r._spin_on = False
                except tk.TclError: pass
        self._sig = None; self._dsig = None
        if self.view: self.render(self.view)

    def toggle_drawer(self):
        if self.drawer.is_open: self.drawer.hide()
        elif self.view: self.drawer.show(self.view['settings'])

    def _row_action(self, action):
        if action not in ('toggle_motion', 'switch_path', 'game_setup'): self.drawer.hide()
        self.act(action)

    def show_page(self, name):
        """'home' or 'download' (the offline-copy page)."""
        if name == self.page: return
        self.page = name; self.drawer.hide()
        if name == 'download': self.col.place_forget(); self.dl_col.place(relx=.5, rely=.5, anchor='center', width=min(S(CONTENT_W), max(100, self.stage.winfo_width() - S(88))))
        else: self.dl_col.place_forget(); self.col.place(relx=.5, rely=.5, anchor='center', width=min(S(CONTENT_W), max(100, self.stage.winfo_width() - S(88))))
        self._sig = None; self._dsig = None; self._links_sig = None

    # ------------------------------------------------------------------------ header and footer
    def _build_header(self):
        top = tk.Frame(self, bg=BG, height=S(68)); top.pack(fill='x', padx=S(44)); top.pack_propagate(False)
        mark = tk.Canvas(top, width=S(32), height=S(32), bg=BG, highlightthickness=0); mark.pack(side='left', pady=S(18))
        mark.create_image(0, 0, anchor='nw', image=ui.photo(self, ('logo', S(32)), lambda: ui.pill_rgba(S(32), S(32), ACCENT, ui.ACCENT2, None, 1, 0.12, S(9)))); mark.create_image(S(16), S(16), image=ui.icon(self, 'bolt', 18, ui.ON_ACCENT, 2.2))
        tk.Label(top, text='HD Textures', bg=BG, fg=TEXT, font=ui.font(self, 18, 'head', True)).pack(side='left', padx=(S(12), S(8)), pady=S(18))
        tk.Label(top, text=self.version, bg=BG, fg=FAINT, font=ui.font(self, 12)).pack(side='left', pady=S(18))
        self.btn_settings = ui.Button(top, 'Settings', self.toggle_drawer, kind='ghost', icon_name='sliders', height=36, px=14, pad=14); self.btn_settings.pack(side='right', pady=S(16))
        self.btn_help = ui.Button(top, 'Help', lambda: self.act('help'), kind='ghost', icon_name='help', height=36, px=14, pad=14); self.btn_help.pack(side='right', pady=S(16))

    def _build_footer(self):
        line = tk.Frame(self, bg='#131a27', height=1); line.pack(side='bottom', fill='x', padx=S(44))
        foot = tk.Frame(self, bg=BG, height=S(46)); foot.pack(side='bottom', fill='x', padx=S(44)); foot.pack_propagate(False)
        self.dot = tk.Canvas(foot, width=S(12), height=S(12), bg=BG, highlightthickness=0); self.dot.pack(side='left'); self.foot_txt = tk.Label(foot, text='', bg=BG, fg=DIM, font=ui.font(self, 13)); self.foot_txt.pack(side='left', padx=(S(6), 0))
        self.links = tk.Frame(foot, bg=BG); self.links.pack(side='right'); self._dot_color = None; self._links_sig = None

    def _set_dot(self, color):
        if color == self._dot_color: return
        self._dot_color = color; self.dot.delete('all'); ui.round_box(self.dot, 0, 0, S(12), S(12), S(6), ui.mix(color, BG, .55)); ui.round_box(self.dot, S(2), S(2), S(10), S(10), S(4), color)

    def _resize(self, e=None):
        w, h = self.stage.winfo_width(), self.stage.winfo_height()
        if w < 50: return
        (self.dl_col if self.page == 'download' else self.col).place_configure(width=min(S(CONTENT_W), w - S(88)))                      # only the page that is showing (place_configure would bring the other back)
        compact = h < S(590)
        if compact != self._compact: self._compact = compact; self._sig = None; self.render(self.view) if self.view else None

    # ------------------------------------------------------------------------ render
    def set_view(self, v):
        """Remember the latest view (the Settings drawer shows its rows, also while the offline-copy page is up)."""
        self.view = v; self.drawer.update(v['settings'])

    def render(self, v):
        if v is None: return
        self.set_view(v)
        sig = json.dumps([v['mode'], v['layout'], v['primary'], v['secondary'], v['alert'] and [v['alert']['id'], v['alert']['actions']], [(c['id'], c['selected']) for c in v['choices']], v['folder'] and v['folder'].get('path'),
                          v['steps'], [c['value'] for c in v['cards']], v['busy'], self._compact, v['waiting'], v['notice']], default=str)
        if sig != self._sig: self._sig = sig; self._rebuild(v)
        self._update(v)

    def _clear(self):
        if self.pill_box is not None: self.ticker.remove('home-dots')
        for w in (self.ring, self.h1, self.sub, self.row, self.stepper, self.cards_row, self.kpi_row, self.alert_box, self.body_box): w.pack_forget()
        for fr in (self.row, self.cards_row, self.kpi_row, self.alert_box, self.body_box):
            for c in fr.winfo_children(): c.destroy()
        if self.step_pill is not None: self.step_pill.destroy()
        self.pill_box = None; self.card_labels = []; self.kpi_labels = {}; self.spark = None; self.step_pill = None

    def _rebuild(self, v):
        self._clear()
        if v['layout'] == 'wizard': self._build_wizard(v)
        else: self._build_hero(v)

    def _buttons(self, parent, v, big=True):
        if v['primary']:
            act, label, icn = v['primary']; b = ui.Button(parent, label, lambda a=act: self.act(a), kind='primary', icon_name=icn, height=52 if big else 46, px=16, pad=34, minwidth=190); b.pack(side='left', padx=6)
            if v['busy'] or (v['mode'] in ('find',) and v['sub'].endswith('...')): b.enable(False)
            self.btn_primary = b
        else: self.btn_primary = None
        for act, label in v['secondary']:
            ui.Button(parent, label, lambda a=act: self.act(a), kind='secondary', height=40, px=14, pad=22).pack(side='left', padx=6, pady=S(8))

    def _build_hero(self, v):
        self.ring.pack(); self.h1.pack(pady=(S(2), 0)); self.sub.pack(pady=(S(8), 0))
        self.row.pack(pady=(S(14), 0)); self._buttons(self.row, v)
        if v['waiting']:
            self.pill_box = ui.Panel(self.row, fill=CARD, r=18, padx=16, pady=8, shrink=True); self.pill_lbl = tk.Label(self.pill_box.body, text='Waiting for the game', bg=CARD, fg=DIM, font=ui.font(self, 13)); self.pill_lbl.pack()
            self.pill_box.pack(side='left', padx=8, pady=S(8)); self.ticker.add('home-dots', self._tick_dots)
        if v['alert']: self._build_alert(v['alert'])
        if v['steps'] and not (self._compact and v['kpis']): self.stepper.pack(pady=(S(16), 0))                      # on a small window the numbers matter more than the step strip
        if v['kpis']: self.kpi_row.pack(pady=(S(18), 0)); self._build_kpis(v)
        if v['cards'] and not self._compact and v['mode'] in ('ready', 'waiting', 'starting'): self.cards_row.pack(fill='x', pady=(S(22), 0)); self._build_cards(v)

    def _tick_dots(self, t):
        if self.pill_box is None: return
        self.pill_lbl.configure(text='Waiting for the game' + '.' * (int(t * 1.6) % 4))

    def _build_cards(self, v):
        for i in range(3): self.cards_row.grid_columnconfigure(i, weight=1, uniform='c')
        for i, c in enumerate(v['cards']):
            p = ui.Panel(self.cards_row, fill=CARD, r=16, padx=16, pady=14); p.grid(row=0, column=i, sticky='ew', padx=(0 if i == 0 else S(7), 0 if i == 2 else S(7)))
            ic = tk.Label(p.body, image=ui.icon(self, c['icon'], 20, OK if c['tone'] == 'ok' else ACCENT), bg=CARD); ic.pack(side='left', padx=(0, S(12)))
            tx = tk.Frame(p.body, bg=CARD); tx.pack(side='left', fill='x', expand=True)
            tk.Label(tx, text=c['title'].upper(), bg=CARD, fg=FAINT, font=ui.font(self, 11), anchor='w').pack(fill='x')
            val = tk.Label(tx, text=c['value'], bg=CARD, fg=TEXT, font=ui.font(self, 14), anchor='w'); val.pack(fill='x'); self.card_labels.append(val)
            if c['action']: Link(p.body, c['action_label'], lambda a=c['action']: self.act(a), fg=ACCENT, hover=ui.lighten(ACCENT, .25), bg=CARD).pack(side='right')

    def _build_kpis(self, v):
        for i, k in enumerate(v['kpis']):
            p = ui.Panel(self.kpi_row, fill=CARD, r=14, padx=18, pady=12, shrink=True); p.pack(side='left', padx=S(7))
            tk.Label(p.body, text=k['title'].upper(), bg=CARD, fg=FAINT, font=ui.font(self, 11), anchor='w').pack(fill='x', ipadx=S(30))
            line = tk.Frame(p.body, bg=CARD); line.pack(fill='x'); val = tk.Label(line, text=k['value'], bg=CARD, fg=TEXT, font=ui.font(self, 19, 'head', True)); val.pack(side='left')
            unit = tk.Label(line, text=' ' + k['unit'], bg=CARD, fg=DIM, font=ui.font(self, 12)); unit.pack(side='left', pady=(S(5), 0)); self.kpi_labels[k['title']] = (val, unit)
        p = ui.Panel(self.kpi_row, fill=CARD, r=14, padx=14, pady=10, shrink=True); p.pack(side='left', padx=S(7))
        tk.Label(p.body, text='LAST 3 MINUTES', bg=CARD, fg=FAINT, font=ui.font(self, 11), anchor='w').pack(fill='x')
        self.spark = tk.Canvas(p.body, width=S(200), height=S(40), bg=CARD, highlightthickness=0); self.spark.pack()

    def _build_alert(self, a, box=None):
        box = box or self.alert_box; warm = ui.mix(WARN, BG, .88); p = ui.Panel(box, fill=warm, border=ui.mix(WARN, BG, .62), r=18, padx=22, pady=18, shrink=True); p.pack(pady=(S(16), 0))
        tk.Label(p.body, image=ui.icon(self, 'shield', 24, WARN), bg=warm).pack(side='left', anchor='n', padx=(0, S(16)))
        tx = tk.Frame(p.body, bg=warm); tx.pack(side='left', fill='x', expand=True)
        tk.Label(tx, text=a['title'], bg=warm, fg=TEXT, font=ui.font(self, 17, 'head', True), anchor='w', justify='left', wraplength=S(520)).pack(fill='x')
        tk.Label(tx, text=a['text'], bg=warm, fg='#cdbf9f', font=ui.font(self, 14), anchor='w', justify='left', wraplength=S(520)).pack(fill='x', pady=(S(6), 0))
        if a['actions']:
            br = tk.Frame(tx, bg=warm); br.pack(fill='x', pady=(S(14), 0))
            for i, (act, lab) in enumerate(a['actions']): ui.Button(br, lab, lambda x=act: self.act(x), kind='warn' if i == 0 else 'secondary', height=38, px=14, pad=20, bg=warm).pack(side='left', padx=(0, 8))
        box.pack(fill='x'); self.alert_pack = p

    # ------------------------------------------------------------------------ the first-run cards
    def _build_wizard(self, v):
        if v['wizard']:
            n, total = v['wizard']; self.step_pill = ui.Panel(self.col, fill=CARD, r=16, padx=14, pady=5, shrink=True); tk.Label(self.step_pill.body, text=f'Step {n} of {total}', bg=CARD, fg=DIM, font=ui.font(self, 13)).pack()
            self.step_pill.pack(pady=(0, S(18)))
        self.h1.pack(); self.sub.pack(pady=(S(8), 0)); self.body_box.pack(pady=(S(24), 0))
        if v['notice']: self._build_notice(v['notice'])
        if v['choices']: self._build_choices(v)
        if v['folder']: self._build_folder(v['folder'])
        self.row.pack(pady=(S(26), 0)); self._buttons(self.row, v)

    def _build_notice(self, text):
        p = ui.Panel(self.body_box, fill=CARD, r=18, padx=28, pady=22, shrink=True); p.pack()
        tk.Label(p.body, text=text, bg=CARD, fg=DIM, font=ui.font(self, 14), justify='left', anchor='w', wraplength=S(640)).pack()

    def _build_choices(self, v):
        for i, c in enumerate(v['choices']):
            sel = c['selected']; fill = '#141d33' if sel else CARD; p = ui.Panel(self.body_box, fill=fill, border=ACCENT if sel else LINE, r=18, padx=24, pady=22, shrink=True); p.pack(side='left', padx=S(10), anchor='n')
            top = tk.Frame(p.body, bg=fill); top.pack(fill='x'); box = tk.Canvas(top, width=S(46), height=S(46), bg=fill, highlightthickness=0); box.pack(side='left')
            ui.round_box(box, 0, 0, S(46), S(46), S(14), ui.mix(ACCENT if c['id'] == 'quick' else ui.ACCENT2, fill, .82)); box.create_image(S(23), S(23), image=ui.icon(self, c['icon'], 22, ACCENT if c['id'] == 'quick' else ui.ACCENT2, 2.0))
            if c['tag']:
                tp = ui.Panel(top, bg=fill, fill=ui.mix(OK, fill, .86), border=ui.mix(OK, fill, .86), r=11, padx=10, pady=3, shrink=True); tp.pack(side='right', anchor='n')
                tk.Label(tp.body, text=c['tag'], bg=ui.mix(OK, fill, .86), fg=OK, font=ui.font(self, 12)).pack()
            tk.Label(p.body, text=c['title'], bg=fill, fg=TEXT, font=ui.font(self, 18, 'head', True), anchor='w').pack(fill='x', pady=(S(14), 0))
            tk.Label(p.body, text=c['text'], bg=fill, fg=DIM, font=ui.font(self, 14), anchor='w', justify='left', wraplength=S(360)).pack(fill='x', pady=(S(6), S(8)))
            for text, tone in c['bullets']:
                r = tk.Frame(p.body, bg=fill); r.pack(fill='x', pady=S(3)); col = {'ok': OK, 'warn': WARN, 'bad': BAD}[tone]
                tk.Label(r, image=ui.icon(self, 'check' if tone == 'ok' else 'alert', 15, col, 2.2), bg=fill).pack(side='left'); tk.Label(r, text=text, bg=fill, fg=DIM, font=ui.font(self, 13)).pack(side='left', padx=(S(8), 0))
            _click(p, lambda cid=c['id']: self.act('pick_' + cid))

    def _build_folder(self, f):
        p = ui.Panel(self.body_box, fill='#141d33' if f.get('found') else CARD, border=ACCENT if f.get('found') else LINE, r=18, padx=22, pady=20, shrink=True); p.pack(); fill = '#141d33' if f.get('found') else CARD
        box = tk.Canvas(p.body, width=S(46), height=S(46), bg=fill, highlightthickness=0); box.pack(side='left', padx=(0, S(16)))
        ui.round_box(box, 0, 0, S(46), S(46), S(14), ui.mix(ACCENT, fill, .82)); box.create_image(S(23), S(23), image=ui.icon(self, 'folder', 22, ACCENT, 2.0))
        tx = tk.Frame(p.body, bg=fill); tx.pack(side='left')
        tk.Label(tx, text=f['title'], bg=fill, fg=TEXT, font=ui.font(self, 17, 'head', True), anchor='w').pack(fill='x')
        tk.Label(tx, text=f['path'], bg=fill, fg=DIM, font=ui.font(self, 13), anchor='w', wraplength=S(480), justify='left').pack(fill='x', pady=(S(3), 0))
        if f.get('note'): tk.Label(tx, text=f['note'], bg=fill, fg=OK if f.get('ok') else WARN, font=ui.font(self, 13), anchor='w').pack(fill='x', pady=(S(6), 0))
        self.folder_panel = p

    # ------------------------------------------------------------------------ the parts that change every second
    def _update(self, v):
        if v['headline'] != self.h1.cget('text'): self.h1.configure(text=v['headline'])
        if v['sub'] != self.sub.cget('text'): self.sub.configure(text=v['sub'])
        if v['layout'] == 'hero':
            r = v['ring']; self.ring.set(r['kind'], r['frac'], r['icon'], r['big'], r['small'])
            if v['steps']: self.stepper.set(*v['steps'])
            for lab, c in zip(self.card_labels, v['cards']):
                if lab.cget('text') != c['value']: lab.configure(text=c['value'])
            for k in v['kpis']:
                pair = self.kpi_labels.get(k['title'])
                if pair:
                    if pair[0].cget('text') != k['value']: pair[0].configure(text=k['value'])
                    if pair[1].cget('text') != ' ' + k['unit']: pair[1].configure(text=' ' + k['unit'])
            if self.spark is not None: self._draw_spark(v['spark'])
        h = home.help_for(v); self._tip('ring', self.ring, h['ring']); self._tip('stepper', self.stepper, h['steps']); self._tip('footer', self.foot_txt, h['footer'])
        for i, (lab, t) in enumerate(zip(self.card_labels, h['cards'])): self._tip(f'card{i}', lab, t)
        for title, (val, unit) in self.kpi_labels.items(): self._tip('kpi-' + title, val, h['kpis'].get(title, ''))
        if v['layout'] == 'hero' and getattr(self, 'btn_primary', None) is not None and v['primary']: self._tip('primary', self.btn_primary, h['buttons'].get(v['primary'][0], ''))
        self._footer(v)

    def _footer(self, v):
        self._set_dot({'ok': OK, 'warn': WARN, 'off': FAINT}[v['footer'][0]]); self.foot_txt.configure(text=v['footer'][1])
        sig = tuple(v['links'])
        if sig != self._links_sig:
            self._links_sig = sig
            for c in self.links.winfo_children(): c.destroy()
            for act, label in reversed(v['links']): Link(self.links, label, lambda a=act: self.act(a), fg=FAINT, hover=TEXT).pack(side='right', padx=(S(22), 0))

    def _draw_spark(self, vals):
        cv = self.spark; cv.delete('all'); w, h = int(cv['width']), int(cv['height'])
        if len(vals) < 2: cv.create_text(w / 2, h / 2, text='no data yet', fill=FAINT, font=ui.font(self, 11)); return
        mx = max(vals) or 1.0; n = len(vals); xy = [(w * i / (n - 1), h - 4 - (h - 10) * x / mx) for i, x in enumerate(vals)]
        poly = [0, h] + [c for p in xy for c in p] + [w, h]; cv.create_polygon(*poly, fill=ui.mix(ACCENT, CARD, .82), outline='')
        cv.create_line(*[c for p in xy for c in p], fill=ACCENT, width=2, smooth=True)

    # ------------------------------------------------------------------------ the offline-copy page
    def render_download(self, v):
        if v is None: return
        self.dview = v
        sig = json.dumps([v['mode'], v['primary'], v['secondary'], v['alert'] and v['alert']['id'], v['editable'], v['scope']['value'], v['level']['value'], v['bar'] is not None], default=str)
        if sig != self._dsig: self._dsig = sig; self._build_download(v)
        self._update_download(v)

    def _build_download(self, v):
        col = self.dl_col
        for c in col.winfo_children(): c.destroy()
        ui.Button(col, 'Home', lambda: self.act('back_home'), kind='ghost', icon_name='back', height=34, px=13, pad=12).pack(anchor='w')
        top = tk.Frame(col, bg=BG); top.pack(fill='x', pady=(S(10), 0)); self.dl_ring = ui.Ring(top, d=170, thick=9, ticker=self.ticker); self.dl_ring.pack(side='left', padx=(0, S(30)))
        right = tk.Frame(top, bg=BG); right.pack(side='left', fill='x', expand=True)
        tag = ui.Panel(right, fill=CARD, r=14, padx=12, pady=3, shrink=True); tag.pack(anchor='w'); tk.Label(tag.body, text='Offline copy', bg=CARD, fg=DIM, font=ui.font(self, 12)).pack()
        self.dl_h1 = tk.Label(right, bg=BG, fg=TEXT, font=ui.font(self, 28, 'head', True), anchor='w', justify='left'); self.dl_h1.pack(fill='x', pady=(S(10), 0))
        self.dl_sub = tk.Label(right, bg=BG, fg=DIM, font=ui.font(self, 14), anchor='w', justify='left', wraplength=S(560)); self.dl_sub.pack(fill='x', pady=(S(8), 0))
        self.dl_bar = None
        if v['bar'] is not None:
            self.dl_bar = ui.ProgressBar(right); self.dl_bar.pack(fill='x', pady=(S(18), 0)); row = tk.Frame(right, bg=BG); row.pack(fill='x', pady=(S(8), 0))
            self.dl_bar_l = tk.Label(row, bg=BG, fg=DIM, font=ui.font(self, 13)); self.dl_bar_l.pack(side='left'); self.dl_bar_r = tk.Label(row, bg=BG, fg=DIM, font=ui.font(self, 13)); self.dl_bar_r.pack(side='right')
        br = tk.Frame(right, bg=BG); br.pack(anchor='w', pady=(S(14), 0))
        if v['primary']:
            act, label, icn = v['primary']; ui.Button(br, label, lambda a=act: self.act(a), kind='warn' if act == 'pack_pause' else 'primary', icon_name=icn, height=44, px=15, pad=26).pack(side='left', padx=(0, 8))
        for act, label in v['secondary']: ui.Button(br, label, lambda a=act: self.act(a), kind='secondary', height=40, px=14, pad=22).pack(side='left', padx=(0, 8))
        if v['alert']: ab = tk.Frame(col, bg=BG); ab.pack(fill='x'); self._build_alert(v['alert'], ab)
        row = tk.Frame(col, bg=BG); row.pack(fill='x', pady=(S(26), 0)); row.grid_columnconfigure(0, weight=1, uniform='d'); row.grid_columnconfigure(1, weight=1, uniform='d')
        for i, (title, key) in enumerate((('How much', 'scope'), ('Detail level', 'level'))):
            seg = v[key]; p = ui.Panel(row, fill=CARD, r=16, padx=18, pady=14); p.grid(row=0, column=i, sticky='nsew', padx=(0 if i == 0 else S(7), 0 if i == 1 else S(7)))
            tk.Label(p.body, text=title.upper(), bg=CARD, fg=FAINT, font=ui.font(self, 11), anchor='w').pack(fill='x')
            s = ui.Segmented(p.body, seg['options'], seg['value'], lambda val, k=key: self.act(f'set_{k}_{val}'), bg=CARD); s.pack(anchor='w', pady=(S(8), S(6))); s.enable(v['editable'])
            note = 'Custom selection: change it in Advanced mode.' if key == 'scope' and seg.get('custom') else (
                'Campaign only is the single-player game. Everything adds every other texture list found on your install.' if key == 'scope' else seg.get('note', ''))
            tk.Label(p.body, text=note, bg=CARD, fg=DIM, font=ui.font(self, 12), anchor='w', justify='left', wraplength=S(400)).pack(fill='x')

    def _update_download(self, v):
        r = v['ring']; self.dl_ring.set(r['kind'], r['frac'], r['icon'], r['big'], r['small'])
        if v['headline'] != self.dl_h1.cget('text'): self.dl_h1.configure(text=v['headline'])
        if v['sub'] != self.dl_sub.cget('text'): self.dl_sub.configure(text=v['sub'])
        if self.dl_bar is not None and v['bar'] is not None:
            self.dl_bar.set(v['bar']['frac']); self.dl_bar_l.configure(text=v['bar']['left']); self.dl_bar_r.configure(text=v['bar']['right'])
        self._tip('dl-ring', self.dl_ring, 'How much of the texture pack is on this PC.'); self._footer(v)


class Drawer(tk.Frame):
    """The Settings panel that slides in from the right. show(sections) / hide(); on_row(action) is called for a row that has an action."""
    W = 360

    def __init__(self, page, ticker, on_row):
        super().__init__(page, bg=ui.BG2); self.page, self.ticker, self.on_row = page, ticker, on_row; self.is_open = False; self._sig = None
        tk.Frame(self, bg=LINE, width=1).pack(side='left', fill='y'); self.inner = tk.Frame(self, bg=ui.BG2); self.inner.pack(side='left', fill='both', expand=True, padx=S(22), pady=S(20))

    def show(self, sections):
        self.build(sections)
        if self.is_open: return
        self.is_open = True; self.lift(); self._slide(True)

    def hide(self):
        if not self.is_open: return
        self.is_open = False; self._slide(False)

    def update(self, sections):
        if self.is_open: self.build(sections)

    def _slide(self, opening):
        w = S(self.W); self.place(relx=1.0, rely=0.0, relheight=1.0, width=w, anchor='ne', x=w if opening and self.ticker.enabled else 0)
        if not self.ticker.enabled:
            if not opening: self.place_forget()
            return
        import time
        t0 = time.time(); key = 'drawer'
        def tick(_t):
            p = min(1.0, (time.time() - t0) / 0.18); e = 1 - (1 - p) ** 3; off = int(w * (1 - e)) if opening else int(w * e)
            self.place_configure(x=off)
            if p >= 1.0:
                self.ticker.remove(key)
                if not opening: self.place_forget()
        self.ticker.add(key, tick)

    def build(self, sections):
        sig = json.dumps(sections, default=str)
        if sig == self._sig: return
        self._sig = sig
        for c in self.inner.winfo_children(): c.destroy()
        bg = ui.BG2; head = tk.Frame(self.inner, bg=bg); head.pack(fill='x')
        tk.Label(head, text='Settings', bg=bg, fg=TEXT, font=ui.font(self, 20, 'head', True)).pack(side='left')
        ui.Button(head, '', self.hide, kind='ghost', icon_name='x', height=32, px=14, pad=8, bg=bg).pack(side='right')
        for sec in sections:
            tk.Label(self.inner, text=sec['title'].upper(), bg=bg, fg=FAINT, font=ui.font(self, 11), anchor='w').pack(fill='x', pady=(S(18), S(4)))
            for r in sec['rows']: self._row(r, bg)

    def _row(self, r, bg):
        act = r['action']; fr = tk.Frame(self.inner, bg=bg, cursor='hand2' if act else 'arrow'); fr.pack(fill='x')
        icn = tk.Label(fr, image=ui.icon(self, r['icon'], 18, DIM), bg=bg); icn.pack(side='left', padx=(S(10), S(12)), pady=S(10))
        lab = tk.Label(fr, text=r['label'], bg=bg, fg=TEXT, font=ui.font(self, 14), anchor='w'); lab.pack(side='left')
        tone = {'ok': OK, 'warn': WARN}.get(r.get('tone', ''), FAINT); val = tk.Label(fr, text=r['value'], bg=bg, fg=tone, font=ui.font(self, 13)); val.pack(side='right', padx=(0, S(10)))
        kids = (fr, icn, lab, val)
        def paint(on):
            for w in kids: w.configure(bg=CARD if on else bg)
        if act:
            for w in kids: w.bind('<Enter>', lambda e: paint(True)); w.bind('<Leave>', lambda e: paint(False)); w.bind('<Button-1>', lambda e, a=act: self.on_row(a))
