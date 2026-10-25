"""home.py - what the Home screen shows, as plain data. No window code in here, so every state can be tested on its own.

`build(state, facts, ...)` turns the guided-setup state (guide.py) plus the real facts about this PC (the same dict the checklist uses) into a view:

  mode      find | choose | setup | ready | starting | waiting | playing | finished | problem
  layout    'wizard' (first-run screens: a step pill, a card, two buttons) or 'hero' (the ring, a headline, one button, the step strip and three small cards)
  ring      dict(kind, frac, icon, big, small)        kind = off | work | on | full | warn | ok
  headline, sub, primary = (action, label, icon) or None, secondary = [(action, label)], steps = (labels, current) or None
  cards     the three small cards of the hero layout;  kpis  the live numbers while playing;  alert  a plain-words card (title, text, actions) or None
  choices   the two ways to load textures (first run);  folder  the game-folder card (first run);  footer = (level, text);  links = [(action, label)]

Actions are names the window maps to its handlers (ACTIONS). Wording is plain on purpose: no hosts, proxy, mirror, CDN or chunk in the main texts.
"""
import os
from . import guide, i18n

STEP_LABELS = ('Game found', 'Turn on', 'Play', 'Done')
PACK_MIN_GIB = 54                                                   # the smallest offline copy (campaign only)
ACTIONS = ('turn_on', 'turn_off', 'find_folder', 'use_found', 'confirm_anyway', 'choose_quick', 'choose_offline', 'pick_quick', 'pick_offline', 'game_setup', 'help',
           'open_check', 'open_report', 'abtest', 'done', 'apply_hosts', 'activity', 'open_advanced', 'open_settings', 'switch_path', 'what_setup', 'notice_ok', 'toggle_motion',
           'open_download', 'back_home', 'pack_start', 'pack_pause', 'pack_verify', 'pack_offline', 'set_scope_sp', 'set_scope_all', 'set_level_standard', 'set_level_high', 'set_level_ultra', 'pick_language')
MAP = dict(start_session='turn_on', stop_session='turn_off', doctor='open_check', find_folder='find_folder', game_setup='game_setup', apply_hosts='apply_hosts',
           confirm_anyway='confirm_anyway', hosts_remove='turn_off')                               # guide.coach actions -> Home actions

HEADLINES = dict(hosts_denied='Windows blocked the change', uac_cancelled="Windows didn't get a yes", cdn_unreachable="Can't reach the game's servers", port_busy='Another program is in the way',
                 hosts_lost='The redirect went missing', no_traffic="The game isn't using it yet", disk_low='Disk space is low', wrong_folder="That doesn't look like the game",
                 not_ready="It didn't switch on")


def fmt_dur(s):
    s = int(max(0, s or 0)); return f'{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}' if s >= 3600 else f'{s // 60}:{s % 60:02d}'


def short_path(p, keep=2):
    """The last `keep` parts of a folder path, with the drive in front: D:\\...\\Games\\Modern Warfare 4."""
    p = os.path.normpath(p or ''); parts = [x for x in p.replace('/', '\\').split('\\') if x]
    if len(parts) <= keep + 1: return p
    return parts[0] + '\\...\\' + '\\'.join(parts[-keep:])


def _drive(p):
    d = os.path.splitdrive(os.path.normpath(p or ''))[0]; return d or 'this drive'


def _plain(actions):
    """guide.coach actions -> Home actions with their labels (an action Home has no handler for is dropped)."""
    out = []
    for a, lab in actions:
        m = MAP.get(a)
        if m: out.append((m, 'Check my PC' if m == 'open_check' else lab))
    return out


def _cards(st, f):
    free = f.get('free_gib'); root = f.get('folder_root', '')
    return [dict(icon='folder', title='Game folder', value=short_path(root), action='find_folder', action_label='Change', tone='ok'),
            dict(icon='wifi' if st['path'] != 'offline' else 'download', title='Textures load', value='While I play' if st['path'] != 'offline' else 'From my offline copy',
                 action='switch_path', action_label='Change', tone='info'),
            dict(icon='disk', title='Free space', value=(f'{free:,.0f} GiB on {_drive(root)}' if free is not None else '-'), action='', action_label='', tone='info')]


def _preflight_alert(st, f):
    """A plain card for what stops the session from starting now, or None."""
    path = st['path'] or 'quick'
    if f.get('blocked_by'):
        return dict(id='port_busy', title=f"Another program is using port {f.get('port', 80)}", text=f"HD textures need that port for themselves ({f['blocked_by']} has it now). Check my PC shows what is using it and can free it.", actions=[('open_check', 'Check my PC')])
    free = f.get('free_gib'); need = guide.MIN_FREE_GIB.get(path, 2.0)
    if free is not None and free < need:
        return dict(id='disk_low', title='Not much free space', text=f'Only {free:.0f} GiB is free on this drive and about {need:g} GiB is needed. Free some space and this clears by itself.', actions=[])
    if f.get('game_running') and not guide.live_session(f):
        return dict(id='game_open', title='The game is already running', text='Close it, turn on HD textures, then start the game again so it picks them up.', actions=[])
    return None


def _kpis(f):
    st = f.get('stat') or {}; err, retry = int(st.get('err', 0)), int(st.get('retry', 0)); mir = int(st.get('mirror', 0)); up = max(0, int(st.get('ok', 0)) - mir)
    src = 'Your offline copy' if mir and not up else 'Offline copy and internet' if mir else 'The internet'
    mib = f.get('mibps')
    return [dict(title='Speed', value=f'{mib:.1f}' if mib is not None else '-', unit='MB/s'), dict(title='Failed', value=str(err), unit=f'{retry} retried' if retry else ''), dict(title='Loaded from', value=src, unit='')]


def summary_text(s):
    """The one-sentence version of guide.explain for the finished screen."""
    s = guide.numbers(s); req = int(s.get('req', 0))
    if not s: return 'The session is over.'
    if req == 0: return "Nothing reached HD textures this time, so the game wasn't served by it. Check my PC can tell you why (most often the game was already running)."
    err, mins = int(s.get('err', 0)), int(s.get('secs', 0) // 60)
    n, e = f'{req:,}', f'{err:,}'                                         # whole sentences, so a language can order the parts its own way
    if mins >= 1: return i18n.t('The game asked for {0} textures in about {1} min and every one was delivered.', n, mins) if not err else i18n.t('The game asked for {0} textures in about {1} min. {2} requests failed; the game asks again, a few are normal.', n, mins, e)
    return i18n.t('The game asked for {0} textures and every one was delivered.', n) if not err else i18n.t('The game asked for {0} textures. {1} requests failed; the game asks again, a few are normal.', n, e)


def settings_rows(st, f, extra=None):
    """The Settings drawer: sections of rows (icon, label, value, action). extra = dict(motion=bool, pack=text for the offline copy)."""
    extra = extra or {}; path = st['path'] or 'quick'; gs = f.get('game_setup'); setup = {'needed': 'Needs a change', 'ok': 'Done', 'limited': 'Not possible on this drive'}.get(gs, 'Not needed')
    return [dict(title='Textures', rows=[dict(icon='wifi' if path != 'offline' else 'download', label='How textures load', value='While I play' if path != 'offline' else 'From my offline copy', action='switch_path', tone=''),
                                         dict(icon='download', label='Offline copy', value=extra.get('pack', 'Not downloaded'), action='open_download', tone='')]),
            dict(title='Game', rows=[dict(icon='folder', label='Game folder', value=short_path(f.get('folder_root', ''), 1), action='find_folder', tone=''),
                                     dict(icon='bolt', label='One-time game setup', value=setup, action='game_setup' if gs == 'needed' else '', tone='warn' if gs in ('needed', 'limited') else 'ok' if gs == 'ok' else '')]),
            dict(title='Help', rows=[dict(icon='shield', label='Check my PC', value='', action='open_check', tone=''), dict(icon='help', label='What do the words mean?', value='', action='help', tone=''),
                                     dict(icon='chart', label='Reports and logs', value='', action='open_report', tone=''), dict(icon='gamepad', label='Before / after test', value='', action='abtest', tone='')]),
            dict(title='Look and feel', rows=[dict(icon='globe', label='Language', value=extra.get('language', 'English'), action='pick_language', tone=''), dict(icon='refresh', label='Reduce motion', value='On (Windows setting)' if extra.get('system_motion') else 'On' if extra.get('motion') else 'Off',
                                                    action='' if extra.get('system_motion') else 'toggle_motion', tone='')]),
            dict(title='Advanced', rows=[dict(icon='sliders', label='Advanced mode', value='Every setting', action='open_advanced', tone='')])]


HELP = dict(
    ring=dict(off='Off. Press the button to turn HD textures on.', work='Turning on...', on='On. The game gets its HD textures as soon as it starts.', full='Textures are being delivered to your game right now.',
              warn='Something needs your attention. Read the card below.', ok='The last session ended normally.'),
    cards=dict(folder='The folder your game is installed in. Press Change to pick another one.',
               textures='While I play: the game gets its textures from the internet as it asks for them. From my offline copy: they come from a copy saved on this PC.',
               space='Free space on the drive your game is on.'),
    kpis={'Speed': 'How fast textures are arriving right now.', 'Failed': 'Requests that still failed after retries. A few are normal: the game simply asks again.', 'Loaded from': 'Where the textures come from: the internet, or the offline copy on this PC.'},
    footer='A quick summary of the checks the tool runs by itself. Check my PC (in Settings) shows every one of them.',
    steps='Where you are: find the game, turn HD textures on, play, done.',
    turn_on='Switches HD textures on. One small change is made to a Windows network file and it is undone when you turn this off.',
    turn_off='Switches HD textures off and puts the Windows network file back as it was.')


def help_for(v):
    """Hover texts for the parts of a view: dict(ring, cards=[...], kpis={title: text}, footer, steps, buttons={action: text})."""
    r = HELP['ring']; kind = v['ring']['kind']
    return dict(ring=r.get(kind, ''), cards=[HELP['cards'].get(c['icon'] == 'folder' and 'folder' or c['icon'] == 'disk' and 'space' or 'textures', '') for c in v['cards']], kpis=HELP['kpis'], footer=HELP['footer'], steps=HELP['steps'],
                buttons={'turn_on': HELP['turn_on'], 'turn_off': HELP['turn_off']})


def _gb(gib): return f'{gib:,.0f}' if gib >= 10 else f'{gib:.1f}'


def pack_text(plan, prog=None, alive=False):
    """One short phrase for the Settings row: Not downloaded | 41% downloaded | Complete."""
    if not plan or 'total' not in plan: return 'Not downloaded'
    t = plan['total']; T, S_ = t.get('chunks', 0), t.get('stored', 0)
    if T and not t.get('pending'): return 'Complete'
    if alive and prog and prog.get('queued'): return f"{min(100, int(100 * (T - prog['queued'] + prog['ok']) / max(1, T)))}% downloaded"
    return f'{int(100 * S_ / T)}% downloaded' if T and S_ else 'Not downloaded'


def download_view(plan, prog=None, alive=False, vprog=None, valive=False, scope='sp', level='ultra', busy=False, now=None):
    """The offline-copy page: how much of the texture pack is on this PC, a run in progress, and the two choices (how much, how detailed).
    plan = pack.plan(...) or None (still being worked out), prog = the mirror run's progress, vprog = a file check's progress."""
    import time as _t
    now = now or _t.time(); v = dict(mode='loading', ring=dict(kind='prog', frac=0.0, icon=None, big='', small=''), headline='Working out the size...', sub='', bar=None, primary=None, secondary=[], alert=None,
                                     scope=dict(value=scope if scope in ('sp', 'all') else '', options=[('sp', 'Campaign only'), ('all', 'Everything')], custom=scope == 'custom'),
                                     level=dict(value=level, options=[('standard', 'Standard'), ('high', 'High'), ('ultra', 'Ultra')], note=''), editable=True, footer=('off', 'Offline copy'),
                                     links=[('back_home', 'Back to Home')])
    v['level']['note'] = {'standard': 'Standard leaves out the biggest textures (about the 1440p class): a smaller download.', 'high': 'High leaves out only the very biggest textures.',
                          'ultra': 'Ultra downloads everything: the biggest copy, best for 4K.'}.get(level, '')
    if valive and vprog:
        d, tot = vprog.get('done', 0), max(1, vprog.get('total', 1))
        v.update(mode='checking', ring=dict(kind='prog', frac=d / tot, icon=None, big=f'{int(100 * d / tot)}%', small='checked'), headline='Checking your files', editable=False, footer=('ok', 'Checking the offline copy'),
                 sub=f"{d:,} of {tot:,} pieces checked. Problems so far: {vprog.get('bad', 0)}.", bar=dict(frac=d / tot, left=f'{d:,} of {tot:,} pieces', right=''))
        return v
    if not plan: return v
    if 'error' in plan:
        v.update(mode='error', headline="Can't work out the size", sub='', alert=dict(id='plan', title="Couldn't read the game's file lists", text=str(plan['error']), actions=[('open_check', 'Check my PC')]), footer=('warn', 'Needs your attention'))
        return v
    t = plan['total']; T, pend = t.get('chunks', 0), t.get('pending', 0); tg = float(t.get('gib', 0.0)); stored = t.get('stored', 0)
    if not T:
        v.update(mode='error', headline='No file lists found', sub='The tool reads the list of textures from your game folder, and found none for this choice.', footer=('warn', 'Needs your attention'),
                 alert=dict(id='nolists', title='Nothing to download here', text='Pick the right game folder (Settings), or try the other choices below.', actions=[('find_folder', 'Choose the game folder')]))
        return v
    fits = plan.get('fits', True); free = plan.get('free_gib')
    if alive and prog and prog.get('queued'):
        q, ok, el = prog['queued'], prog.get('ok', 0), max(1, prog.get('now', now) - prog.get('started', now)); frac = max(0.0, min(1.0, (T - q + ok) / T)); rate = ok / el if ok else 0
        got = tg * frac; sp = prog.get('mibps_now', prog.get('mibps', 0.0)) or 0.0; eta = (prog.get('left', 0) / rate) if rate > 0 else None
        left = (i18n.t('About {0} left at {1} MB/s', _eta_text(eta), f'{sp:.1f}') if sp else i18n.t('About {0} left', _eta_text(eta))) if eta else (i18n.t('Working...') if not sp else i18n.t('{0} MB/s', f'{sp:.1f}'))
        st = prog.get('state', 'running'); head, sub, kind = 'Downloading your texture pack', 'You can keep using the PC. Pause whenever you like, it picks up where it stopped.', 'running'
        if st == 'quota-wait': head, sub, kind = "Paused for today's limit", 'The daily limit you set was reached. It carries on by itself when the new day starts.', 'waiting'; left = ''
        elif st == 'offline-wait': head, sub, kind = 'Waiting for the internet', 'There is no connection right now. It carries on by itself when it is back.', 'waiting'; left = ''
        v.update(mode=kind, ring=dict(kind='prog', frac=frac, icon=None, big=f'{int(frac * 100)}%', small=f'{_gb(got)} of {_gb(tg)} GB'), headline=head, sub=sub, editable=False, footer=('ok' if kind == 'running' else 'warn', 'Downloading'),
                 bar=dict(frac=frac, left=f'{T - q + ok:,} of {T:,} pieces', right=left), primary=('pack_pause', 'Pause', 'pause'))
        return v
    frac = stored / T if T else 0.0; got = tg * frac
    if not pend:
        v.update(mode='done', ring=dict(kind='ok', frac=1.0, icon='check', big='', small=''), headline='All textures are on this PC', sub=f'{T:,} pieces ({_gb(tg)} GB). Play with this copy and the game needs little or no internet.',
                 bar=None, primary=('pack_offline', 'Use only this copy', 'wifi'), secondary=[('pack_verify', 'Check the files')], footer=('ok', 'Offline copy is complete'), editable=True)
        return v
    v['ring'] = dict(kind='prog', frac=frac, icon=None if stored else 'download', big=f'{int(frac * 100)}%' if stored else '', small=f'{_gb(got)} of {_gb(tg)} GB' if stored else f'{_gb(plan["total"].get("pending_gib", tg))} GB'); v['bar'] = dict(frac=frac, left=f'{stored:,} of {T:,} pieces', right='') if stored else None
    pg = float(t.get('pending_gib', 0.0)); line = f'About {_gb(pg)} GB to download' + (f', {free:,.0f} GB free on this drive' if free is not None else '') + '.'
    if stored: v.update(mode='paused', headline='Your download is paused', sub=line + ' It picks up where it stopped.', primary=('pack_start', 'Resume', 'play'), secondary=[('pack_verify', 'Check the files')], footer=('off', 'Offline copy  -  paused'))
    else: v.update(mode='idle', headline='Download the texture pack', sub=line + ' Pause and resume whenever you like. The pack is for use with your own copy of the game.', primary=('pack_start', 'Start the download', 'download'), footer=('off', 'Offline copy'))
    if not fits:
        v['alert'] = dict(id='nospace', title='Not enough free space', text=f"This choice needs about {plan.get('need_gib', 0):.0f} GB and {free or 0:.0f} GB is free. Pick a smaller download below, or another drive in Advanced mode.", actions=[])
        v['primary'] = None if not stored else v['primary']; v['footer'] = ('warn', 'Needs your attention')
    return v


def _eta_text(secs):
    secs = int(secs or 0)
    if secs < 90: return i18n.t('a minute')
    if secs < 3600: return i18n.t('{0} min', secs // 60)
    h, m = secs // 3600, secs % 3600 // 60
    return i18n.t('{0} h {1} min', h, m) if h < 48 else i18n.t('{0} days', h // 24)


NOTICE_BUTTON = 'I understand, continue'


def build(state, f, note='', busy=False, starting=False, found=None, pick=None, searching=False, notice='', extra=None):
    """The Home view. state = guide state, f = facts (guide facts plus optional stat / mibps / spark / secs), note = the last problem text, busy = an action is running,
    starting = the user just pressed Turn on, found = game folders the finder offered (None until it ran), pick = the first-run choice the user has marked."""
    st = guide.clean_state(state); live = guide.live_session(f); ms = set(st['ms']); coach = guide.coach(st, f, note)
    v = dict(mode='', layout='hero', ring=dict(kind='off', frac=0.0, icon='power', big='', small=''), headline='', sub='', primary=None, secondary=[], steps=None, cards=[], kpis=[], spark=[],
             alert=None, waiting=False, notice='', settings=[], choices=[], folder=None, wizard=None, footer=('ok', 'Everything checks out'), links=[('activity', 'Activity'), ('open_advanced', 'Advanced mode')], busy=bool(busy))
    v['settings'] = settings_rows(st, f, extra); ok_folder = guide.folder_ok(st, f)
    if notice:                                                    # the research / responsibility notice, once per version, before anything else
        v.update(mode='notice', layout='wizard', wizard=None, headline='Before you start', sub='', notice=notice, footer=('off', 'Please read this once per version'), links=[],
                 primary=('notice_ok', NOTICE_BUTTON, 'check'))
        return v
    # ---- first run: the game folder, how textures load, the one-time game setup
    if not live and not f.get('proxy_alive') and not ok_folder:
        v.update(mode='find', layout='wizard', wizard=(1, 3), footer=('off', 'First-time setup  -  about a minute'), links=[('open_advanced', 'Advanced mode')])
        if f.get('configured') and f.get('folder_exists'):          # a folder is set but it does not look like the game
            v.update(headline="That folder doesn't look right", sub='There is no cod26 or sp26 folder in it. Pick another one, or use it anyway if you know it is the game.',
                     folder=dict(title='Chosen folder', path=f.get('folder_root', ''), note="Doesn't look like the game", ok=False), primary=('find_folder', 'Choose another folder', 'folder'), secondary=[('confirm_anyway', 'Use it anyway')])
        elif f.get('configured'):
            v.update(headline="That folder isn't there", sub='It may have been moved or deleted. Pick the folder again.', folder=dict(title='Chosen folder', path=f.get('folder_root', ''), note='Folder not found', ok=False),
                     primary=('find_folder', 'Choose the folder', 'folder'))
        elif searching or found is None:
            v.update(headline="Let's find your game", sub="I'm looking in the usual places...", primary=('find_folder', 'Choose a folder myself', 'folder'))
        elif found:
            c = found[0]; how = {3: 'Looks complete', 2: 'Looks like the game', 1: 'Might be the game'}.get(c['score'], '')
            v.update(headline="Let's find your game", sub='I looked in the usual places. Is this the right one?', folder=dict(title='Modern Warfare 4' if c['score'] >= 2 else 'Possible game folder', path=c['path'], note=how, ok=c['score'] >= 3, found=True),
                     primary=('use_found', 'Yes, use this one', 'arrow'), secondary=[('find_folder', 'Choose another folder')])
        else:
            v.update(headline="I couldn't find your game", sub='It is not in the usual places. Point me to the folder that has the game files.', primary=('find_folder', 'Choose the folder', 'folder'))
        return v
    if not live and not f.get('proxy_alive') and not st['path']:
        sel = pick if pick in guide.PATHS else 'quick'; free = f.get('free_gib')
        low = free is not None and free < PACK_MIN_GIB
        v.update(mode='choose', layout='wizard', wizard=(2, 3), headline='How should textures load?', sub='You can change this any time.', footer=('off', 'First-time setup'), links=[('open_advanced', 'Advanced mode')],
                 choices=[dict(id='quick', icon='wifi', title='While I play', text='No big download. The game gets its textures from the internet as you play.', tag='Recommended', selected=sel == 'quick',
                               bullets=[('Ready in a minute', 'ok'), ('Needs about 2 GB free', 'ok'), ('Needs a steady connection', 'ok')]),
                          dict(id='offline', icon='download', title='Download them once', text='Save the texture pack on this PC, then play from disk. Best for slow or limited internet.', tag='', selected=sel == 'offline',
                               bullets=[('Works with little or no internet', 'ok'), ('About 54 to 82 GB of disk', 'warn' if low else 'ok'), ('Download can be paused any time', 'ok')] + ([('Not enough free space on this drive', 'bad')] if low else []))],
                 primary=('choose_' + sel, 'Continue', 'arrow'))
        return v
    gs = f.get('game_setup'); fs = f.get('game_fs')              # fs: set when the game's drive cannot hold folder links (exFAT, FAT32): the cache link, which HD textures need, cannot be made there
    if not live and not f.get('proxy_alive') and gs in ('needed', 'limited'):          # required, so there is no way past this step except doing it (or, for experts, Advanced mode)
        if gs == 'limited':
            v.update(mode='setup', layout='wizard', wizard=(3, 3), headline='HD textures cannot work on this drive', footer=('off', 'First-time setup'), links=[('open_advanced', 'Advanced mode')],
                     sub=i18n.t('The online-mode change is made. HD textures also need the game folder on an NTFS drive, because the game setup links its cache folder and this drive ({0}) cannot hold folder links. Move the game to an NTFS drive, then choose its new folder.', fs or '?'),
                     primary=('find_folder', 'Choose another folder', 'folder'), secondary=[('help', 'What does this do?')])
            return v
        sub = (i18n.t('So the game uses the textures this tool sends it, the game goes into online mode. HD textures also need the game folder on an NTFS drive: this drive ({0}) cannot hold the folder link of the game setup, so only the online-mode change can be made here. Move the game to an NTFS drive, then choose its new folder.', fs) if fs else
               'So the game uses the textures this tool sends it, two settings change: the game goes into online mode and its cache folder gets a link. A backup is made first and you can undo it any time.')
        v.update(mode='setup', layout='wizard', wizard=(3, 3), headline='One small change in your game folder', footer=('off', 'First-time setup'), links=[('open_advanced', 'Advanced mode')], sub=sub,
                 primary=('game_setup', 'Make the change', 'check'), secondary=([('find_folder', 'Choose another folder')] if fs else []) + [('help', 'What does this do?')])
        return v
    # ---- the hero layout
    v['cards'] = _cards(st, f); gone = []
    for c in coach: gone.append(dict(id=c['id'], title=c['title'], text=c['text'], actions=_plain(c['actions'])))
    alert = gone[0] if gone else None
    if live:
        req = int(f.get('requests', 0)); running = bool(f.get('game_running'))
        if req > 0:
            closed = not running
            v.update(mode='playing', steps=(STEP_LABELS, 2), ring=dict(kind='full', frac=1.0, icon=None, big=f'{req:,}', small='textures delivered'),
                     headline='Game closed' if closed else 'Playing with HD textures', kpis=_kpis(f), spark=list(f.get('spark') or []),
                     sub=(i18n.t('{0} so far. ', fmt_dur(f.get('secs'))) if f.get('secs') else '') + i18n.t('The session is still on. Turn it off when you are done.' if closed else (
                         'Everything the game asked for was delivered.' if not int((f.get('stat') or {}).get('err', 0)) else 'A few requests failed; the game asks again, that is normal.')),
                     secondary=[('turn_off', 'Turn off' if closed else 'Turn off when you are done')], footer=('ok', 'Game running  -  no problems'))
        else:
            v.update(mode='waiting', steps=(STEP_LABELS, 2), ring=dict(kind='on', frac=1.0, icon='power', big='', small='ON'), headline='HD textures are on',
                     sub=('The game is starting. Textures show up here as soon as it asks for them.' if running else 'Now start your game as you normally do. Keep this window open while you play.'), secondary=[('turn_off', 'Turn off')], waiting=True, footer=('ok', 'HD textures are on  -  everything checks out'))
        if alert: v['alert'] = alert; v['footer'] = ('warn', 'Needs your attention')
        return v
    pre = _preflight_alert(st, f); has_note = bool(note and alert and alert['id'] in HEADLINES); lost = bool(alert and alert['id'] == 'hosts_lost')
    if (f.get('proxy_alive') and busy and not (has_note or lost)) or starting:           # only while something is really starting: a proxy that runs without a finished session offers Turn on again
        v.update(mode='starting', steps=(STEP_LABELS, 1), ring=dict(kind='work', frac=0.28, icon='power', big='', small=''), headline='Turning on...', sub='This takes a few seconds.',
                 primary=('turn_on', 'Turning on...', 'power'), busy=True)
        return v
    if 'after' in ms and st['summary'] and not lost:
        v.update(mode='finished', steps=(STEP_LABELS, 4), ring=dict(kind='ok', frac=1.0, icon='check', big='', small=''), headline='All done. Nice session.', sub=summary_text(st['summary']),
                 primary=('done', 'Done', 'check'), secondary=[('open_report', 'See the full report'), ('abtest', 'Compare before / after')], footer=('ok', 'Session finished'), cards=[])
        return v
    a = alert if (has_note or lost) else pre
    if a:
        v.update(mode='problem', ring=dict(kind='warn', frac=0.0, icon='alert', big='', small=''), headline=HEADLINES.get(a['id'], a['title']), alert=a, steps=None, cards=[],
                 footer=('warn', 'Needs your attention  -  nothing was changed'))
        return v
    v.update(mode='ready', steps=(STEP_LABELS, 1), ring=dict(kind='off', frac=0.0, icon='power', big='', small=''), headline='Ready when you are',
             sub='Turn on HD textures, then start your game as usual. You can turn it off any time.', primary=('turn_on', 'Turn on HD textures', 'power'))
    if busy: v['primary'] = ('turn_on', 'Turn on HD textures', 'power'); v['busy'] = True
    return v


def strings(v):
    """Every piece of text in a view (for the wording tests)."""
    out = [v['headline'], v['sub'], v['footer'][1]] + [x[1] for x in v['links']] + [x[1] for x in v['secondary']] + ([v['primary'][1]] if v['primary'] else [])
    out += [v['ring'].get('big', ''), v['ring'].get('small', '')] + [c['title'] + ' ' + c['value'] for c in v['cards']] + [k['title'] + ' ' + k['value'] + ' ' + k['unit'] for k in v['kpis']]
    out += [c['title'] + ' ' + c['text'] + ' ' + ' '.join(b[0] for b in c['bullets']) for c in v['choices']]
    out += [r['label'] + ' ' + r['value'] for s in v.get('settings', []) for r in s['rows']] + [s['title'] for s in v.get('settings', [])]
    if v['alert']: out += [v['alert']['title'], v['alert']['text']] + [a[1] for a in v['alert']['actions']]
    if v['folder']: out += [v['folder']['title'], v['folder']['note']]
    return [x for x in out if x]
