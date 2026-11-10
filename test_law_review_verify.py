"""법규 검토 결과 후처리(law_review_verify.py) 시험. `python test_law_review_verify.py`. 네트워크·AI 없이 가짜 원문과 가짜 판정기로 확인한다.

확인하는 것: 건축 법령 항목은 토목·조경에서 빠지되 이유와 함께 남는가 / 룰 엔진 필수 항목을 AI가 빠뜨리면 덧붙는가(이미 있으면 중복 없음) /
조문 번호가 없거나 삭제된 경우와 내용이 다른 경우를 표시하는가(지우지는 않음) / 한 단계가 실패해도 결과가 유지되는가.
"""
import unittest

import law_review_verify as lrv

LAWS = {
    (False, '도로법'): {'art': {(61, 0): ('도로의 점용 허가', '제61조(도로의 점용 허가) ① 도로관리청의 허가를 받아야 한다.'),
                               (27, 0): ('행위제한 등', '제27조(행위제한 등) 도로구역에서는 ...'),
                               (71, 0): ('', '제71조 삭제 <2006.1.1>')}},
    (False, '건설기술진흥법'): {'art': {(62, 0): ('건설공사의 안전관리', '제62조(건설공사의 안전관리) 안전관리계획을 수립'),
                                    (39, 2): ('시공단계의 건설사업관리계획 등', '제39조의2 ...')}},
    (True, '건설공사사업관리방식검토기준및업무수행지침'): {'art': {(99, 0): ('설계변경계약전 기성고 및 지급자재의 지급', '제99조 ...')}},
}


def fake_loader(key):
    if key == (False, '없는법'):
        return None
    return LAWS.get(key)


def judge_unsupported(*names):
    """claim에 names 중 하나가 들어 있으면 '다른 분야'로 판정하는 가짜 판정기."""
    def judge(chunk):
        return {i: ({'verdict': 'unsupported', 'reason': '주제가 다름'} if any(n in x['claim'] for n in names) else {'verdict': 'supported', 'reason': ''})
                for i, x in enumerate(chunk)}
    return judge


def sample():
    return {
        'permits': [
            {'name': '도로점용허가', 'law_name': '도로법', 'article': '제61조(도로의 점용 허가)', 'reason': '도로 점용'},
        ],
        'phases': {
            'planning': [],
            'design': [{'task': '교통성 검토', 'law_name': '도시교통정비 촉진법', 'article': '제15조', 'desc': '교통영향평가'}],
            'construction': [
                {'task': '착공신고', 'law_name': '건축법', 'article': '제21조(착공신고 등)', 'desc': '착공신고'},
                {'task': '안전관리계획서 제출', 'law_name': '건설기술 진흥법', 'article': '제62조', 'desc': '착공 전 안전관리계획서 제출'},
            ],
            'completion': [
                {'task': '시설물 인수인계 및 도로대장 등재', 'law_name': '도로법', 'article': '제27조(행위제한 등)', 'desc': '도로대장 등재'},
                {'task': '예비준공검사', 'law_name': '건설공사 사업관리방식 검토기준 및 업무수행지침', 'article': '제99조', 'desc': '예비준공검사 실시'},
                {'task': '옛 조문', 'law_name': '도로법', 'article': '제71조', 'desc': '삭제된 조문 인용'},
                {'task': '없는 법', 'law_name': '없는법', 'article': '제1조', 'desc': 'x'},
                {'task': '번호 없음', 'law_name': '도로법', 'article': '', 'desc': 'x'},
                {'task': '엉뚱한 번호', 'law_name': '도로법', 'article': '제999조', 'desc': 'x'},
            ],
            'maintenance': [],
        },
    }


def by_task(result):
    out = {}
    for _ph, it in lrv._items(result):
        out[lrv._title_of(it)] = it
    return out


class TradeFilterTests(unittest.TestCase):
    def test_architecture_laws_are_removed_from_civil_works_but_recorded(self):
        r = sample()
        ex = lrv.exclude_mismatched_trade(r, '토목공사')
        self.assertEqual([(e['name'], e['law']) for e in ex], [('착공신고', '건축법')])
        self.assertIn('건축 분야', ex[0]['reason'])
        self.assertNotIn('착공신고', by_task(r))

    def test_other_project_types_keep_everything(self):
        for t in ('건축공사', '복합공사'):
            r = sample()
            self.assertEqual(lrv.exclude_mismatched_trade(r, t), [])
            self.assertIn('착공신고', by_task(r))

    def test_landscape_also_filtered_and_spacing_variants(self):
        r = {'permits': [{'name': 'x', 'law_name': '건축서비스산업 진흥법', 'article': '제21조'}], 'phases': {'design': [{'task': 'y', 'law_name': '건축물관리법'}]}}
        self.assertEqual(len(lrv.exclude_mismatched_trade(r, '조경공사')), 2)


class RuleMergeTests(unittest.TestCase):
    RULES = [
        {'name': '안전관리계획서 수립', 'law_link': '건설기술 진흥법 제62조', 'phase': 'construction', 'desc': 'd1'},
        {'name': '토지조서·물건조서 작성, 보상계획 공고·열람 및 보상 협의', 'law_link': '토지보상법 제14조', 'phase': 'design', 'desc': 'd2'},
        {'name': '토지조서·물건조서 작성, 보상계획 공고·열람 및 보상 협의', 'law_link': '중복', 'phase': 'design', 'desc': 'dup'},
        {'name': '계약심사', 'law_link': '지방계약법', 'phase': 'design, construction', 'desc': 'd3'},
    ]

    def test_missing_rules_are_added_once_and_present_ones_are_not(self):
        r = sample()
        added = lrv.merge_rule_items(r, self.RULES)
        names = [a['name'] for a in added]
        self.assertNotIn('안전관리계획서 수립', names)            # 이미 "안전관리계획서 제출"이 있다(이름 포함 관계)
        self.assertEqual(names.count('토지조서·물건조서 작성, 보상계획 공고·열람 및 보상 협의'), 1)   # 같은 이름 규칙은 한 번만
        self.assertIn('계약심사', names)
        item = by_task(r)['계약심사']
        self.assertEqual((item['verify']['status'], item['law_link']), ('rule', '지방계약법'))
        self.assertIn(item, r['phases']['design'])                # 'design, construction'은 설계 단계에 둔다

    def test_empty_rules_change_nothing(self):
        r = sample()
        self.assertEqual(lrv.merge_rule_items(r, []), [])
        self.assertEqual(len(lrv._items(r)), len(lrv._items(sample())))


class CitationTests(unittest.TestCase):
    def run_verify(self, judge):
        r = sample()
        counts = lrv.verify_citations(r, fake_loader, judge)
        return r, counts

    def test_statuses(self):
        r, counts = self.run_verify(judge_unsupported('도로대장'))
        t = by_task(r)
        self.assertEqual(t['도로점용허가']['verify']['status'], 'ok')
        self.assertEqual(t['도로점용허가']['verify']['title'], '도로의 점용 허가')
        self.assertEqual(t['안전관리계획서 제출']['verify']['status'], 'ok')
        self.assertEqual(t['시설물 인수인계 및 도로대장 등재']['verify']['status'], 'mismatch')      # 도로법 제27조(행위제한)는 도로대장과 다른 분야
        self.assertIn('행위제한 등', t['시설물 인수인계 및 도로대장 등재']['verify']['note'])
        self.assertEqual(t['옛 조문']['verify']['status'], 'deleted')
        self.assertEqual(t['엉뚱한 번호']['verify']['status'], 'missing')
        self.assertEqual(t['없는 법']['verify']['status'], 'unchecked')
        self.assertEqual(t['번호 없음']['verify']['status'], 'unchecked')
        self.assertEqual(t['교통성 검토']['verify']['status'], 'unchecked')      # 가짜 원문에 없는 법령
        self.assertEqual(counts['mismatch'], 1)
        self.assertEqual(counts['ok'], 3)

    def test_nothing_is_removed(self):
        r, _c = self.run_verify(judge_unsupported('도로대장'))
        self.assertEqual(len(lrv._items(r)), len(lrv._items(sample())))

    def test_admrul_names_use_the_admrul_loader_key(self):
        r, _c = self.run_verify(judge_unsupported())
        self.assertEqual(by_task(r)['예비준공검사']['verify']['status'], 'ok')

    def test_judge_failure_keeps_items_as_existing_not_flagged(self):
        def broken(_chunk):
            raise RuntimeError('boom')
        r, counts = self.run_verify(broken)
        self.assertEqual(counts['mismatch'], 0)
        self.assertEqual(by_task(r)['도로점용허가']['verify']['status'], 'ok')

    def test_loader_failure_means_unchecked(self):
        def boom(_k):
            raise RuntimeError('network')
        r = sample()
        lrv.verify_citations(r, boom, judge_unsupported())
        self.assertTrue(all(it['verify']['status'] == 'unchecked' for _ph, it in lrv._items(r)))

    def test_large_batches_are_chunked(self):
        r = {'phases': {'design': [{'task': f't{i}', 'law_name': '도로법', 'article': '제61조', 'desc': f'd{i}'} for i in range(20)]}}
        sizes = []

        def judge(chunk):
            sizes.append(len(chunk))
            return {}
        lrv.verify_citations(r, fake_loader, judge)
        self.assertEqual(sorted(sizes), [4, 8, 8])


class RefinementTests(unittest.TestCase):
    def test_multi_article_citation_is_flagged_only_if_every_article_is_off_topic(self):
        laws = {(False, '계약법'): {'art': {(17, 0): ('검사', '제17조(검사) ...'), (18, 0): ('대가의 지급', '제18조(대가의 지급) ...')}}}

        def judge(chunk):                       # 제17조(검사)는 대금 청구와 다른 분야, 제18조(대가의 지급)는 같은 분야
            return {i: {'verdict': 'supported' if x['no'] == '18' else 'unsupported', 'reason': 'r'} for i, x in enumerate(chunk)}
        r = {'phases': {'construction': [{'task': '공사 대금 청구 및 지급', 'law_name': '계약법', 'article': '제17조, 제18조', 'desc': '대금 청구'}]}}
        lrv.verify_citations(r, lambda k: laws.get(k), judge)
        self.assertEqual(r['phases']['construction'][0]['verify']['status'], 'ok')
        both_off = lambda chunk: {i: {'verdict': 'unsupported', 'reason': 'r'} for i, _x in enumerate(chunk)}
        r = {'phases': {'construction': [{'task': '공사 대금 청구 및 지급', 'law_name': '계약법', 'article': '제17조, 제18조', 'desc': '대금 청구'}]}}
        lrv.verify_citations(r, lambda k: laws.get(k), both_off)
        self.assertEqual(r['phases']['construction'][0]['verify']['status'], 'mismatch')

    def test_byeolpyo_citations_explain_why_they_are_unchecked(self):
        r = {'phases': {'design': [{'task': 'x', 'law_name': '환경영향평가법 시행령', 'article': '별표 4', 'desc': 'd'}]}}
        lrv.verify_citations(r, fake_loader, judge_unsupported())
        v = r['phases']['design'][0]['verify']
        self.assertEqual(v['status'], 'unchecked')
        self.assertIn('별표', v['note'])

    def test_building_rules_are_not_added_to_civil_works(self):
        rules = [{'name': '건축공사 감리', 'law_link': '건축법 제25조, 시행령 제19조', 'phase': 'construction', 'desc': 'd'},
                 {'name': '공공건축심의', 'law_link': '건축서비스산업 진흥법 제22조의3', 'phase': 'design', 'desc': 'd'},
                 {'name': '품질관리계획 수립', 'law_link': '건설기술진흥법 제55조', 'phase': 'construction', 'desc': 'd', 'condition': 'total_area >= 5000'}]
        keep, skipped = lrv.split_rules_by_trade(rules, '조경공사')
        self.assertEqual([r['name'] for r in keep], ['품질관리계획 수립'])
        self.assertEqual({s['name'] for s in skipped}, {'건축공사 감리', '공공건축심의'})
        keep, skipped = lrv.split_rules_by_trade(rules, '건축공사')
        self.assertEqual((len(keep), skipped), (3, []))
        r = {'phases': {}}
        lrv.merge_rule_items(r, keep[2:])
        note = r['phases']['construction'][0]['verify']['note']
        self.assertIn('total_area >= 5000', note)             # 어떤 조건에 해당했는지 보여 준다

    def test_postprocess_reports_skipped_rules_as_excluded(self):
        r = {'phases': {}}
        lrv.postprocess(r, '토목공사', [{'name': '건축공사 감리', 'law_link': '건축법 제25조', 'phase': 'construction', 'desc': 'd'}],
                        loader=fake_loader, judge=judge_unsupported())
        self.assertEqual([e['name'] for e in r['verification']['excluded']], ['건축공사 감리'])
        self.assertEqual(r['verification']['added'], [])


class PostprocessTests(unittest.TestCase):
    def test_full_pipeline_attaches_verification_summary(self):
        r = sample()
        rules = RuleMergeTests.RULES[:2]
        lrv.postprocess(r, '토목공사', rules, loader=fake_loader, judge=judge_unsupported('도로대장'), warnings=['필지 A: 지역지구 오류'])
        v = r['verification']
        self.assertEqual([e['name'] for e in v['excluded']], ['착공신고'])
        self.assertEqual([a['name'] for a in v['added']], ['토지조서·물건조서 작성, 보상계획 공고·열람 및 보상 협의'])
        self.assertEqual(v['counts']['mismatch'], 1)
        self.assertEqual(v['counts']['rule'], 1)
        self.assertEqual(v['warnings'], ['필지 A: 지역지구 오류'])
        self.assertEqual(v['steps_failed'], [])

    def test_a_failing_step_does_not_lose_the_result(self):
        r = sample()

        def bad_loader(_k):
            raise RuntimeError('x')
        lrv.postprocess(r, '토목공사', [{'name': 5}], loader=bad_loader, judge=judge_unsupported())     # 잘못된 규칙이 있어도
        self.assertIn('verification', r)
        self.assertTrue(len(lrv._items(r)) >= 8)

    def test_every_status_has_a_label(self):
        for s in ('ok', 'mismatch', 'missing', 'deleted', 'unchecked', 'rule'):
            self.assertIn(s, lrv.STATUS_LABEL)


if __name__ == '__main__':
    unittest.main(verbosity=2)
