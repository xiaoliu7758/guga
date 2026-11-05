# -*- coding: utf-8 -*-
"""咕嘎学习功能集成测试 —— 覆盖近几轮新增的全部学习能力。

用法：
  .venv/Scripts/python.exe tools/test_learning_suite.py            # 只跑离线逻辑
  .venv/Scripts/python.exe tools/test_learning_suite.py --api      # 附带真实 API 抽样测试
"""
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# 测试会写入的运行时目录
LEARNING = ROOT / 'runtime' / 'learning'
STUDY = ROOT / 'runtime' / 'study'

PASS = []
FAIL = []


def check(name, cond, detail=''):
    if cond:
        PASS.append(name)
        print('  ✓', name)
    else:
        FAIL.append(name)
        print('  ✗', name, detail)


def _reset_all():
    """清空测试涉及的运行时数据，保证可重复。"""
    for f, default in [
        ('understanding_model.json', {'concepts': {}}),
        ('srs.json', {'cards': {}}),
        ('mistakes.json', {'items': []}),
        ('behavior.json', {'signals': []}),
        ('profile.json', {}),
        ('pending_answers.json', []),
    ]:
        p = LEARNING / f
        p.write_text(json.dumps(default, ensure_ascii=False, indent=2))
    # 清空 study 目录里测试生成的产物（保留非测试文件）
    for f in STUDY.glob('*测试*'):
        try:
            f.unlink()
        except Exception:
            pass


def section(title):
    print('\n== ' + title + ' ==')


# --------------------------------------------------------------------------
# 1. study_tools：知识点提取 / 思维导图 / 拓展 / 出题 / 卡片
# --------------------------------------------------------------------------
def test_study_tools(api=False):
    section('study_tools 学习工具箱')
    from core import study_tools as st

    # 1.1 知识点解析（纯逻辑，离线）
    raw = '{"title":"装饰器","topics":[{"name":"闭包","summary":"捕获外层变量","detail":"","tags":["python"]}]}'
    data = st._parse_knowledge_json(raw)
    check('知识点 JSON 解析', data and data['title'] == '装饰器')

    # 1.2 降级解析
    fb = st._parse_knowledge_json('不是json', '第一行\n第二行')
    check('知识点解析降级', bool(fb.get('topics')))

    # 1.3 知识点转大纲
    outline = st._outline_from_knowledge({'title': '异步', 'topics': [
        {'name': '协程', 'summary': 'async def', 'detail': '', 'tags': []}]})
    check('知识点转大纲', outline.startswith('# 异步') and '## 协程' in outline)

    # 1.4 思维导图（文本降级路径，离线可跑）
    mm = st.mindmap(text='第一行标题\n第二行要点')
    check('思维导图落盘', mm and Path(mm['html']).exists() and Path(mm['outline']).exists())
    if mm:
        try:
            Path(mm['html']).unlink(); Path(mm['outline']).unlink()
        except Exception:
            pass

    # 1.5 出题难度调整（离线）
    qs = [{'type': 'choice', 'question': 'q1', 'options': ['A', 'B', 'C', 'D']},
          {'type': 'choice', 'question': 'q2', 'options': ['A', 'B', 'C', 'D']},
          {'type': 'choice', 'question': 'q3', 'options': ['A', 'B', 'C', 'D']}]
    # 无错题记录 → normal，不删题
    adj = st._apply_difficulty(qs)
    check('出题难度调整(默认)', len(adj) == 3 and adj[0]['_difficulty'] == 'normal')

    # 1.6 文本内容读取（离线，本地文件）
    tmp = STUDY / '测试输入.txt'
    tmp.write_text('这是测试内容：Python 生成器。', encoding='utf-8')
    c = st.content_from_file(str(tmp))
    check('本地文本读取', c and '生成器' in c)
    tmp.unlink()

    # 1.7 无效 URL 校验
    try:
        st.content_from_url('not-a-url')
        check('URL 校验', False, '应抛异常')
    except ValueError:
        check('URL 校验', True)

    # 真实 API 抽样
    if api:
        text = 'Python 装饰器本质是接收函数并返回新函数的高阶函数，常用于日志、鉴权、缓存。'
        k = st.extract_knowledge(text=text)
        check('真实API 知识点提取', k and k.get('topics'))
        mm2 = st.mindmap(text=text, title='装饰器测试')
        check('真实API 思维导图', mm2 and Path(mm2['html']).exists())
        q = st.quiz(text=text)
        check('真实API 出题', q and len(q) >= 1)
        cards = st.flashcards(text=text)
        check('真实API 复习卡', cards and len(cards) >= 1)
        if mm2:
            try:
                Path(mm2['html']).unlink(); Path(mm2['outline']).unlink()
            except Exception:
                pass


# --------------------------------------------------------------------------
# 2. mistake_book：错题本 + 薄弱点推荐
# --------------------------------------------------------------------------
def test_mistake_book():
    section('mistake_book 错题本')
    from core import mistake_book as mb
    mb._reset_for_test()
    mb.record_answer('装饰器本质', 'C', 'A', '装饰器', correct=False, cause='概念不清')
    mb.record_answer('装饰器本质', 'C', 'B', '装饰器', correct=False, cause='概念不清')
    mb.record_answer('闭包是什么', '捕获外层变量', '忘了', '闭包', correct=False, cause='记不牢')
    st = mb.stats()
    check('错题统计', st['total'] == 2 and st['unsolved'] == 2)
    check('错题累加', [i for i in mb.list_mistakes() if '装饰器' in i['question']][0]['wrong_count'] == 2)
    rec = mb.recommend()
    check('薄弱点推荐', rec and rec[0]['concept'] == '装饰器' and rec[0]['wrong_count'] == 2)
    mb.record_answer('装饰器本质', 'C', 'C', '装饰器', correct=True)
    st2 = mb.stats()
    check('答对攻克', st2['solved'] == 1 and st2['unsolved'] == 1)
    check('攻克后推荐变化', mb.recommend()[0]['concept'] == '闭包')
    mb._reset_for_test()


# --------------------------------------------------------------------------
# 3. personalize：风格注入 + 自适应难度 + 画像动态更新
# --------------------------------------------------------------------------
def test_personalize():
    section('personalize 个性化')
    from core.learning_tutor import _save, PROFILE_PATH, TYPES
    from core import personalize as ps
    from core import behavior_tracker as bt

    # 未测评 → 空指令
    _save(PROFILE_PATH, {})
    check('未测评风格指令为空', ps.style_instruction() == '')

    # 测评后 → 有指令
    _save(PROFILE_PATH, {
        'types': TYPES, 'scores': {'results_first': 2.0, 'thorough': 0.5, 'help_seeking': 0.5},
        'primary': 'results_first', 'secondary': 'thorough', 'mixed': False,
        'concentration': 0.67, 'style': TYPES['results_first']})
    si = ps.style_instruction()
    check('风格指令生成', '快进结果型' in si)

    # 混合型 → 追加次型
    _save(PROFILE_PATH, {
        'types': TYPES, 'scores': {'results_first': 1.0, 'thorough': 0.8, 'help_seeking': 0.5},
        'primary': 'results_first', 'secondary': 'thorough', 'mixed': True,
        'concentration': 0.5, 'style': TYPES['results_first']})
    check('混合型追加次型', '细嚼稳扎型' in ps.style_instruction() or '次型' in ps.style_instruction())

    # 自适应难度
    mb = __import__('core.mistake_book', fromlist=['mistake_book'])
    mb._reset_for_test()
    check('无记录默认难度', ps.adaptive_difficulty()['level'] == 'normal')
    for i in range(5):
        mb.add('题%d' % i, 'A', 'B', '概念', cause='概念不清')
    check('低答对率→简单', ps.adaptive_difficulty()['level'] == 'easy')
    mb._reset_for_test()
    for i in range(5):
        it = mb.add('题%d' % i, 'A', 'B', '概念', cause='概念不清')
        mb.mark_solved(it['id'])
    check('高答对率→困难', ps.adaptive_difficulty()['level'] == 'hard')
    mb._reset_for_test()

    # 画像动态更新
    _save(PROFILE_PATH, {
        'types': TYPES, 'scores': {'results_first': 0.5, 'thorough': 1.5, 'help_seeking': 0.5},
        'primary': 'thorough', 'secondary': 'results_first', 'mixed': True,
        'concentration': 0.6, 'style': TYPES['thorough']})
    bt._reset_for_test()
    for _ in range(6):
        bt.record('skip')
        bt.record('rush')
    r = ps.update_profile_from_behavior(min_signals=5)
    check('画像动态更新', r.get('updated') and r['primary'] == 'results_first')
    bt._reset_for_test()


# --------------------------------------------------------------------------
# 4. behavior_tracker：行为信号
# --------------------------------------------------------------------------
def test_behavior_tracker():
    section('behavior_tracker 行为追踪')
    from core import behavior_tracker as bt
    bt._reset_for_test()
    bt.record('skip', '想跳过')
    bt.record('ask_hint', '要提示')
    bt.record('confirm', '再确认')
    t = bt.tally()
    check('行为信号统计', t['total'] == 3 and t['counts']['results_first'] == 1)
    try:
        bt.record('bad_signal')
        check('非法信号校验', False, '应抛异常')
    except ValueError:
        check('非法信号校验', True)
    bt._reset_for_test()


# --------------------------------------------------------------------------
# 5. learning_stats：看板数据 + 雷达图
# --------------------------------------------------------------------------
def test_learning_stats():
    section('learning_stats 看板与雷达图')
    from core import learning_stats as ls
    from core.learning_tutor import update_model, review

    update_model('闭包', 'mastered')
    update_model('装饰器', 'known')
    update_model('生成器', 'unknown')
    review('闭包', 'good')

    d = ls.dashboard()
    check('看板掌握度', d['mastery']['total'] == 3 and d['mastery']['mastered'] == 1)
    check('看板复习卡', d['srs']['total'] >= 1)
    r = d['radar']
    check('雷达图五维', len(r) == 5 and all('axis' in x and 'value' in x for x in r))
    check('雷达图数值范围', all(0 <= x['value'] <= 100 for x in r))
    axes = [x['axis'] for x in r]
    check('雷达图维度正确', axes == ['掌握度', '复习进度', '错题掌握', '学习广度', '学习活跃度'])


# --------------------------------------------------------------------------
# 6. weekly_report：周报数据采集
# --------------------------------------------------------------------------
def test_weekly_report(api=False):
    section('weekly_report 周报')
    from core import weekly_report as wr
    data = wr.collect(weeks=1)
    check('周报数据采集', 'concepts_total' in data and 'mastery' in data and 'cards_due' in data)
    if api:
        report = wr.generate(weeks=1)
        check('周报生成', report and ('学习周报' in report or '本鹅' in report))


# --------------------------------------------------------------------------
# 7. tutor_extra：学习计划/诊断/代码判分
# --------------------------------------------------------------------------
def test_tutor_extra(api=False):
    section('tutor_extra 助教增强')
    from core import tutor_extra as te
    try:
        te.learn_plan('')
        check('计划空目标校验', False, '应抛异常')
    except ValueError:
        check('计划空目标校验', True)
    if api:
        p = te.learn_plan('三个月学爬虫', '3个月')
        check('学习计划生成', p and '阶段' in p)
        d = te.diagnose('装饰器怎么工作')
        check('诊断生成', d and len(d) > 10)
        c = te.code_review('def f(x):\n    return x + 1\nprint(f(1,2))')
        check('代码判分', c and '结论' in c)


# --------------------------------------------------------------------------
# 8. tts 分段朗读
# --------------------------------------------------------------------------
def test_tts_segmentation():
    section('tts 分段朗读')
    from ui.tts_engine import TTSEngine, strip_punct
    text = '这是第%d句话，用来测试分段。' 
    long_text = '。'.join([text % i for i in range(40)]) + '。'
    segs = TTSEngine._split_segments(strip_punct(long_text), max_len=280)
    check('长文本分段', len(segs) >= 2)
    check('每段不超限', all(len(s) <= 280 for s in segs))
    check('拼接还原', ''.join(segs).replace(' ', '') == strip_punct(long_text).replace(' ', ''))


# --------------------------------------------------------------------------
def main():
    api = '--api' in sys.argv
    _reset_all()
    print('咕嘎学习功能集成测试' + ('（含真实 API 抽样）' if api else '（仅离线逻辑）'))
    test_study_tools(api)
    test_mistake_book()
    test_personalize()
    test_behavior_tracker()
    test_learning_stats()
    test_weekly_report(api)
    test_tutor_extra(api)
    test_tts_segmentation()

    print('\n==============================')
    print('通过 %d 项，失败 %d 项' % (len(PASS), len(FAIL)))
    if FAIL:
        print('失败项：')
        for f in FAIL:
            print('  -', f)
        sys.exit(1)
    print('全部通过 ✅')
    _reset_all()  # 测试后清理
    sys.exit(0)


if __name__ == '__main__':
    main()
