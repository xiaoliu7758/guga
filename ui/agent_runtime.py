"""Application-owned tool registry; the same handlers serve typed and spoken commands."""
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QApplication


class AppRuntime:
    def __init__(self, pet, panel, store):
        self.pet, self.panel, self.store = pet, panel, store
        from core.authorized_apps import AuthorizedApps
        self.apps = AuthorizedApps()
        from core.bg_director import BattlegroundDirector
        from core.bg_shadow import ShadowManager
        self.shadow=ShadowManager()
        self.battleground = BattlegroundDirector(panel)
        self.battleground.event.connect(panel._battleground_event)
        from core.dsh_worker import DshManager
        self.dsh = DshManager(panel)
        self.dsh.tools_enabled=True
        self.dsh.archive.recover_once()
        self.dsh.event.connect(panel._dsh_event)
        from core.music_performance import MusicPerformance
        self.music=MusicPerformance(panel)
        self.music.performance_event.connect(panel._music_event)
        from core.media_workflow import MediaWorkflow
        self.media=MediaWorkflow(self.store.path.parent/'video-workflows')
        from core.workflow_catalog import WorkflowCatalog
        self.workflows=WorkflowCatalog(self.store.path.parent/'workflows.sqlite3')
        self._restore_upgrade_playback()

    def _restore_upgrade_playback(self):
        """Consume one short-lived local restart receipt; never start a voice call."""
        import json,time
        from pathlib import Path
        path=Path(__file__).resolve().parents[1]/'runtime/personal-harness/restart.json'
        if not path.is_file():return
        try:
            state=json.loads(path.read_text(encoding='utf-8'))
            path.unlink()
            music=state.get('music',{})
            if not 0<=time.time()-float(state.get('created',0))<120:return
            if music.get('playing') and isinstance(music.get('title'),str) and len(music['title'])<=80:
                def restore():
                    self.music.sing(music['title'])
                    QTimer.singleShot(1200,lambda:self.music.player.setPosition(max(0,int(music.get('position_ms',0)))))
                from PyQt5.QtCore import QTimer
                QTimer.singleShot(700,restore)
        except (OSError,ValueError,TypeError):pass

    def execute(self, name, args):
        if name=='battleground' and args.get('action') in ('shadow','shadow_stop'):
            if args.get('action')=='shadow_stop':return self.shadow.stop()
            return self.shadow.start(args.get('seconds',900),bool(args.get('train',True)))
        if name=='music_performance':
            action=args.get('action')
            if action=='status':return self.music.status()
            if action=='stop':return self.music.stop()
            if action=='pause':return self.music.pause()
            if action=='resume':return self.music.resume()
            if action=='sing':return self.music.sing(str(args.get('title','')).strip())
            raise ValueError('未知音乐操作')
        if name=='media_workflow':
            return self.media.execute(dict(args),self.panel.agent.cancel_event)
        if name == 'dsh_task':
            action=args.get('action')
            if action=='status':return self.dsh.status()
            if action=='stop':return self.dsh.stop()
            if action=='start':
                accepted=self.dsh.start(args.get('task',''),self.panel.active_id,args.get('cwd'),
                    args.get('seconds',900),args.get('session_id'),profile=dict(self.panel.active_profile),
                    memory_context='\n'.join(x['content'] for x in self.panel.memory.recall(self.panel.active_agent_id,args.get('task',''),limit=6)),
                    workflow=self.workflows.match(args.get('task','')))
                self.pet._multi_agent.work_state(self.panel.active_agent_id,'thinking','dsh:'+accepted['job_id'])
                return accepted
            raise ValueError('未知 DSH 操作')
        if name == 'battleground':
            action = args.get('action')
            if action == 'status':
                return dict(self.battleground.status(),shadow=self.shadow.status())
            if action == 'stop':
                return self.battleground.stop()
            if action == 'open':
                from core.bg_live_windows import HearthstoneWindow
                return dict(message=HearthstoneWindow().open())
            self.battleground.conversation_id = self.panel.active_id
            return self.battleground.start(action,
                args.get('max_actions',120 if action=='auto' else 12),
                args.get('seconds',1200 if action=='auto' else 240))
        if name == 'applications':
            if args.get('action')=='command':
                from core.fast_commands import match
                text=str(args.get('name',''))
                if not match(text).get('matched'):raise ValueError('仅支持已识别的本地快速命令；本操作不会转交大模型')
                self.panel.send(text)
                return dict(self.panel._last_fast_result or {},route='local_fast_command')
            if args.get('action') == 'list':
                entries=self.apps.available(args.get('query',''))
                from core.window_inventory import list_windows
                running=list_windows(args.get('query','')) if self.apps.access.enabled else []
                return {'authorized_apps': list(entries)[:200], 'total':len(entries), 'running_windows':running,
                    'access':self.apps.access.status(),
                    'note':'running_windows是已打开软件，authorized_apps是可启动软件；先复用已打开窗口。'}
            if args.get('action') == 'open':
                return self.apps.open(args['name'])
            raise ValueError('未知软件操作')
        if name == 'confirm_external':
            if self.apps.access.enabled:
                return {'approved':True,'source':'user_enabled_full_access'}
            from PyQt5.QtWidgets import QMessageBox
            from PyQt5.QtCore import QTimer
            import json
            box = QMessageBox(self.panel)
            box.setWindowTitle('咕嘎 · 确认软件操作')
            box.setText('此工具尚未被标记为可直接执行的常规操作，是否允许本次调用？')
            box.setInformativeText(args['server'] + ' / ' + args['tool'] + '\n' + json.dumps(args.get('arguments', {}), ensure_ascii=False)[:1500])
            box.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
            box.setDefaultButton(QMessageBox.No)
            QTimer.singleShot(30000, box.reject)
            cancel_timer = QTimer(box)
            cancel_timer.setInterval(100)
            cancel_timer.timeout.connect(lambda: box.reject() if self.panel.agent.cancel_event.is_set() else None)
            cancel_timer.start()
            approved = box.exec_() == QMessageBox.Yes
            cancel_timer.stop()
            return {'approved': approved}
        if name == 'app_state':
            import os
            from core.authorized_apps import ROOT
            from core.realtime_agent import ROUTER_VERSION
            from core.self_agent import HARNESS_VERSION
            return dict(runtime=dict(pid=os.getpid(),project_root=str(ROOT),voice_router_version=ROUTER_VERSION),
                        agent_harness_version=HARNESS_VERSION,
                        pet=dict(x=self.pet.x(), y=self.pet.y(), visible=self.pet.isVisible(),
                                opacity=self.pet.windowOpacity(), status=self.pet._status.snapshot(),
                                volume=self.pet._tts._player.volume()),
                        current_conversation_id=self.panel.active_id,
                        voice_active=self.panel.voice_active,
                        voice_path=dict(owner_only=bool(self.panel.voice._cfg.get('owner_only',False)) if self.panel.voice else False,
                            speaker_gate_active=bool(self.panel.voice and self.panel.voice._speaker_gate)),
                        workspace=self.store.snapshot(),
                        authorized_apps=list(self.apps.entries()),
                        battleground=self.battleground.status(),
                        dsh=self.dsh.status(),
                        media_workflow=self.media.status(),
                        personal_harness=dict(backend='auto:local-first',tickets=self.dsh.archive.recent(self.panel.active_agent_id,limit=5)),
                        music=self.music.status(),
                        stage=dict(sunglasses=self.pet._anim.sunglasses,dancing=self.pet._anim.dancing,
                                   pet_scale=getattr(self.pet,'_pet_scale',1.),
                                   floating_ui_version='2026-10-29.7',
                                   task_motion=self.pet._anim2d._task_motion.snapshot(),
                                   task_animation=self.pet._anim2d.task_animation_status(),
                                   gesture_version='2026-11-02.1',
                                   selection_trigger='uia_text_geometry_before_capture',
                                   selection_actions=['解释','截图分析'],
                                   menu_version='2026-11-02.3',
                                   selection_reading='cached_visual_region',
                                   selection_status=getattr(getattr(self.pet,'_screen_tools',None),'last_selection_status','unavailable'),
                                   chat_route=self.panel.route_combo.currentData(),
                                   answer_effort=self.panel.effort_combo.currentData(),
                                   short_voice_active=self.panel.short_voice.active,
                                   proactive=self.panel.proactive.status(),
                                   selection_toolbar_enabled=bool(getattr(getattr(self.pet,'_screen_tools',None),'selection_enabled',False)),
                                   selection_hook_active=bool(getattr(getattr(self.pet,'_screen_tools',None),'selection_hook_ok',False)),
                                   screen_hotkey_conflicts=list(getattr(getattr(self.pet,'_screen_tools',None),'hotkey_errors',[])),
                                   expression=self.pet._anim.expression,
                                   appearance='3d' if self.pet._anim is self.pet._anim3d else 'illustration',
                                   motion_version='2',demo_active=bool(getattr(self.pet,'_avatar_demo_running',False)),
                                   last_demo=getattr(self.pet,'_last_avatar_demo',None)),
                        multi_agent=getattr(getattr(self.pet,'_multi_agent',None),'status',lambda:{})(),
                        active_agent=dict(id=self.panel.active_agent_id,profile=self.panel.active_profile),
                        local_access=self.apps.access.status(),
                        task=self.panel.agent.task_status(),
                        capabilities=['pet_control', 'workspace', 'applications', 'self_ask', 'ecosystem','battleground','dsh_task','local_computer','computer','task_plan','media_workflow','workflow_catalog','wechat_send_self','wechat','browser','web_search','music_performance','learning_tutor','screen','study'],
                        scope='本机能力由完整访问开关控制；继承咕嘎进程实际Windows权限')
        if name == 'pet_control':
            return self._pet(args)
        if name == 'workspace':
            return self._workspace(args)
        if name == 'learning_tutor':
            return self._learning_tutor(args)
        if name == 'screen':
            return self._screen(args)
        if name == 'study':
            return self._study(args)
        raise ValueError('该工具未注册')

    def _pet(self, args):
        pet = self.pet
        action = args.get('action')
        if action == 'move':
            x, y = int(args['x']), int(args['y'])
            screens = QApplication.screens()
            screen = next((s for s in screens if s.availableGeometry().contains(x, y)), QApplication.primaryScreen())
            g = screen.availableGeometry()
            x = max(g.left(), min(x, g.right() - pet.width() + 1))
            y = max(g.top(), min(y, g.bottom() - pet.height() + 1))
            pet.move(x, y)
            pet._save_state()
            return dict(x=pet.x(), y=pet.y())
        if action == 'show':
            pet.show()
            pet._force_top()
        elif action == 'hide':
            pet.hide()
        elif action == 'reset_position':
            pet._reset_pos()
        elif action == 'animate':
            name = args.get('name', 'bounce')
            if name not in ('look_up_step','idle_doze','idle_heart','bounce', 'shake', 'point', 'peek', 'tsundere','head_shake','nod','tilt','wave','sunglasses','remove_sunglasses','dance','stop_dance','sneak_peek'):
                raise ValueError('未知动画')
            if str(getattr(self.panel,'active_agent_id','001'))!='001' and hasattr(pet,'_multi_agent'):
                pet._multi_agent.gesture(self.panel.active_agent_id,name)
            else:pet._perform_gesture(name)
        elif action == 'set_expression':
            name = args.get('name')
            allowed=('normal','happy','sleepy','surprised','sad','playful')
            if str(getattr(self.panel,'active_agent_id','001'))!='001':allowed+=('angry','eating')
            if name not in allowed:raise ValueError('未知表情')
            if str(getattr(self.panel,'active_agent_id','001'))!='001' and hasattr(pet,'_multi_agent'):
                pet._multi_agent.set_expression(self.panel.active_agent_id,name)
                companion=pet._multi_agent.companions.get(self.panel.active_agent_id)
                expression=companion.anim.expression if companion else name
                return dict(action=action,expression=expression,held=expression!='normal',applied=expression==name)
            pet._anim.set_expression(name)
            return dict(action=action,expression=pet._anim.expression,
                        held=pet._anim.expression!='normal',
                        applied=pet._anim.expression==name)
        elif action == 'interact':
            name = args.get('name', '')
            if name not in ('feed', 'play', 'pet', 'sleep', 'dance'):
                raise ValueError('未知互动')
            pet._act(name)
        elif action == 'set_opacity':
            value = float(args['value'])
            if not .3 <= value <= 1:
                raise ValueError('透明度需要在 0.3—1 之间')
            pet.setWindowOpacity(value)
            pet._config.opacity = value
        elif action == 'set_volume':
            value = int(args['value'])
            if not 0 <= value <= 100:
                raise ValueError('音量需要在 0—100 之间')
            pet._tts._player.setVolume(value)
            pet._config._s.setValue('agent/volume', value)
        elif action == 'set_topmost':
            enabled = bool(args['value'])
            pet.setWindowFlag(Qt.WindowStaysOnTopHint, enabled)
            pet.show()
            pet._config._s.setValue('agent/topmost', enabled)
        elif action == 'set_bongo':
            if args['value']:
                pet._show_bongo()
            else:
                pet._bongo.hide()
                pet._bongo_on = False
                pet.setFixedSize(pet._iw, pet._ih)
        elif action == 'open_chat':
            self.panel.show()
            self.panel.raise_()
        elif action == 'open_voice_settings':
            # Deferred to avoid blocking the queued tool callback in a modal dialog.
            from PyQt5.QtCore import QTimer
            QTimer.singleShot(0, pet._configure_realtime_voice)
            return {'opened': '语音设置', 'state': '已请求打开，等待用户设置'}
        elif action == 'open_battleground_lab':
            pet._open_bg_agent()
        elif action == 'open_battleground_live':
            pet._open_bg_live()
        else:
            raise ValueError('未注册的自身操作')
        return dict(action=action, visible=pet.isVisible(), x=pet.x(), y=pet.y())

    def _workspace(self, args):
        action = args.get('action')
        ident = args.get('id') or self.panel.active_id
        result = {}
        if action == 'create_project':
            result['project_id'] = self.store.create_project(args['name'])
        elif action == 'rename_project':
            if not args.get('id'):
                raise ValueError('更名项目需要明确的项目 ID')
            self.store.rename('project', ident, args['name'])
        elif action == 'new_conversation':
            result['conversation_id'] = self.store.create_conversation(args.get('name', '新对话'), args.get('project_id') or None)
            # Keep this running turn bound to its original conversation.
        elif action == 'rename_conversation':
            self.store.rename('conversation', ident, args['name'])
        elif action == 'move_conversation':
            self.store.move(ident, args.get('project_id') or None)
        elif action == 'archive_conversation':
            self.store.archive(ident)
        elif action == 'restore_conversation':
            self.store.archive(ident, False)
        elif action == 'list_archived':
            return self.store.snapshot(archived=True)
        else:
            raise ValueError('未注册的会话操作')
        self.panel.refresh_tree()
        return dict(result, workspace=self.store.snapshot())

    def _learning_tutor(self, args):
        from core import learning_tutor as lt
        action = args.get('action')
        if action == 'questions':
            return {'questions': lt.questions()}
        if action == 'record':
            return lt.record(args.get('qid', ''), args.get('option', ''),
                             args.get('confidence', '确定'))
        if action == 'assess':
            return lt.assess()
        if action == 'profile':
            return lt.get_profile() or {'error': '尚未完成测评，请先 questions→record→assess'}
        if action == 'plan':
            return lt.plan(str(args.get('goal', '')).strip() or '新知识')
        if action == 'stage':
            return lt.set_stage(args.get('stage', 'goal'))
        if action == 'model':
            return lt.update_model(args.get('concept', ''), args.get('mastery', 'known'),
                                   args.get('note', ''))
        if action == 'model_status':
            return lt.model_status()
        if action == 'due':
            return lt.due_reviews()
        if action == 'review':
            result = lt.review(args.get('concept', ''), args.get('rating', 'good'))
            # 复习完成后，通知提醒器移除已提醒标记，允许该概念后续再次触发提醒
            reminder = getattr(self.pet, '_review_reminder', None)
            if reminder is not None and isinstance(result, dict):
                reminder.on_reviewed([result.get('concept', '')])
            return result
        if action == 'dashboard':
            from core.learning_stats import dashboard
            return dashboard()
        if action == 'mistake_add':
            from core import mistake_book
            return mistake_book.add(args.get('question', ''),
                                    args.get('answer', ''), args.get('user_answer', ''),
                                    args.get('concept', ''), '', args.get('cause', '其他'))
        if action == 'mistakes':
            from core import mistake_book
            return {'items': mistake_book.list_mistakes()}
        if action == 'mistake_stats':
            from core import mistake_book
            return mistake_book.stats()
        if action == 'recommend':
            from core import mistake_book
            return {'recommendations': mistake_book.recommend()}
        if action == 'learn_plan':
            from core import tutor_extra
            plan = tutor_extra.learn_plan(args.get('goal', ''), args.get('duration', ''))
            return {'plan': plan} if plan else {'error': '学习计划生成失败，请稍后重试'}
        if action == 'diagnose':
            from core import tutor_extra
            q = tutor_extra.diagnose(args.get('question', ''))
            return {'question': q} if q else {'error': '诊断启动失败，请稍后重试'}
        if action == 'code_review':
            from core import tutor_extra
            review = tutor_extra.code_review(args.get('code', ''))
            return {'review': review} if review else {'error': '代码判分失败，请稍后重试'}
        if action == 'track_behavior':
            from core import behavior_tracker
            return behavior_tracker.record(args.get('signal', ''), args.get('note', ''))
        if action == 'update_style':
            from core.personalize import update_profile_from_behavior
            result = update_profile_from_behavior()
            if result.get('updated'):
                return {'updated': True, 'primary': result['primary'],
                        'label': result['profile']['style']['label'],
                        'signals': result.get('behavior_signals', {})}
            return {'updated': False, 'reason': result.get('reason', '')}
        if action == 'weekly_report':
            from core import weekly_report
            weeks = int(args.get('weeks', 1) or 1)
            report = weekly_report.generate(weeks=max(1, min(4, weeks)))
            return {'report': report}
        raise ValueError('未知学习操作')

    def _screen(self, args):
        import base64
        import io
        from PIL import ImageGrab
        try:
            img = ImageGrab.grab(all_screens=True)
        except Exception as exc:
            return {'ok': False, 'error': f'截图失败：{exc}'}
        buf = io.BytesIO()
        img.save(buf, 'PNG')
        b64 = base64.b64encode(buf.getvalue()).decode('ascii')
        result = {'ok': True, 'screenshot': True,
                  'image': 'data:image/png;base64,' + b64}
        if args.get('describe', 'true') != 'false':
            from core import vision
            result['description'] = vision._call_vision(
                'data:image/png;base64,' + b64,
                '用中文简短描述当前电脑屏幕/桌面上正在显示什么，有哪些窗口和内容。')
        return result

    def _study(self, args):
        """截图 / 网址 / 本地文件 → 学习产物（思维导图/拓展/自测/复习卡）。"""
        import base64
        import io
        from PIL import ImageGrab
        from core import study_tools as st
        action = args.get('action', 'package')
        if action not in ('mindmap', 'expand', 'quiz', 'cards', 'package', 'from_url', 'from_file'):
            raise ValueError('未知学习操作')
        title = str(args.get('title', '')).strip() or None

        # 外部资源路径：不截图，直接抓取网址/读文件
        if action == 'from_url':
            pkg = st.study_from_source(url=args.get('url', ''), title=title,
                                       want=('mindmap', 'cards'))
            return self._summarize_study(pkg, action)
        if action == 'from_file':
            pkg = st.study_from_source(file_path=args.get('file', ''), title=title,
                                       want=('mindmap', 'cards'))
            return self._summarize_study(pkg, action)

        try:
            img = ImageGrab.grab(all_screens=True)
        except Exception as exc:
            return {'ok': False, 'error': f'截图失败：{exc}'}
        buf = io.BytesIO()
        img.save(buf, 'PNG')
        b64 = 'data:image/png;base64,' + base64.b64encode(buf.getvalue()).decode('ascii')
        want_map = {
            'mindmap': ('mindmap',),
            'expand': ('mindmap', 'expand'),
            'quiz': ('quiz',),
            'cards': ('cards',),
            'package': ('mindmap', 'expand', 'quiz', 'cards'),
        }
        try:
            pkg = st.study_package(image_b64=b64, title=title, want=want_map[action])
        except Exception as exc:
            return {'ok': False, 'error': f'学习内容生成失败：{exc}'}
        return self._summarize_study(pkg, action)

    @staticmethod
    def _summarize_study(pkg, action):
        if not pkg.get('ok'):
            return {'ok': False, 'error': pkg.get('error', '未能生成学习内容')}
        # 精简返回：给出产物路径与要点，供智能体复述；不把整张大图回传给上下文。
        summary = {}
        if 'mindmap' in pkg:
            mm = pkg['mindmap']
            summary['mindmap'] = {'title': mm.get('title'),
                                  'html': mm.get('html'), 'outline': mm.get('outline')}
        if 'expand' in pkg:
            e = pkg['expand']
            summary['expand'] = {'focus': e.get('focus', {}).get('name'),
                                 'path': e.get('path')}
        if 'quiz' in pkg:
            summary['quiz'] = {'count': len(pkg['quiz']), 'questions': pkg['quiz']}
        if 'cards' in pkg:
            summary['cards'] = {'count': len(pkg['cards'].get('cards', [])),
                                'path': pkg['cards'].get('path'),
                                'imported_srs': pkg['cards'].get('imported_srs', 0)}
        return {'ok': True, 'action': action, 'summary': summary,
                'note': '产物已保存到 runtime/study/ 目录，可用浏览器打开 html 思维导图。'}
