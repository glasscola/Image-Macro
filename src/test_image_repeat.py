import unittest
from unittest.mock import Mock, patch

from PIL import Image, ImageDraw, ImageFont

import core


class ImageRepeatTests(unittest.TestCase):
    def setUp(self):
        image=Image.new('RGB',(12,12),'blue')
        self.project=core.project()
        self.project['images']['target']=dict(name='target',data=core.encode_image(image))
        self.first=dict(core.step('image'),image='target',image_action='actions',
                        children=[dict(core.step('text'),text='A'),dict(core.step('text'),text='B')])
        self.project['steps']=[self.first,dict(core.step('text'),text='C')]
        self.output=Mock()
        self.emit=Mock()
        self.frame=image

    def runner(self):
        runner=core.Runner(self.project,self.emit,capture=lambda _:self.frame,output=self.output)
        runner.wait_image=Mock(return_value=dict(found=True,point=(1,1)))
        runner.probe=Mock(side_effect=[dict(found=True,point=(20,20)),dict(found=False,status='not_found'),dict(found=False,status='not_found')])
        return runner

    def test_repeat_ends_on_disappearance_and_next_step_runs(self):
        self.first['repeat_while_visible']=True
        runner=self.runner()
        runner.run()
        self.assertEqual([c.args for c in self.output.call_args_list],
                         [('text','A'),('text','B'),('text','A'),('text','B'),('text','C')])
        self.assertEqual([c.args[1][1] for c in self.emit.call_args_list if c.args[0]=='image_iteration'],[1,2])
        self.assertEqual(runner.wait_image.call_count,1)

    def test_disabled_repeat_runs_once(self):
        runner=self.runner()
        runner.run()
        runner.probe.assert_not_called()
        self.assertEqual([c.args[1] for c in self.output.call_args_list],['A','B','C'])

    def test_group_waits_through_uncertainty_and_advances_after_confirmed_absence(self):
        self.first['repeat_while_visible']=True
        runner=self.runner()
        runner.sleep=Mock()
        uncertain=dict(found=False,status='ambiguous',reason='후보가 여러 곳입니다.')
        absent=dict(found=False,status='not_found')
        runner.probe=Mock(side_effect=[uncertain]*25+[absent,absent])
        runner.run()
        self.assertEqual([c.args[1] for c in self.output.call_args_list],['A','B','C'])
        self.assertIn(('state','완료'),[c.args for c in self.emit.call_args_list])

    def test_one_missed_frame_does_not_exit_repeat(self):
        self.first['repeat_while_visible']=True
        runner=self.runner()
        miss=dict(found=False,status='not_found')
        runner.probe.side_effect=[miss,dict(found=True,point=(20,20)),miss,miss]
        runner.run()
        self.assertEqual([c.args[1] for c in self.output.call_args_list],['A','B','A','B','C'])

    def test_native_disappearance_confirmation_waits_past_a_short_redraw(self):
        runner=self.runner()
        runner.native_capture=True
        runner.sleep=Mock()
        absent=dict(found=False,status='not_found')
        visible=dict(found=True,point=(10,10))
        runner.probe=Mock(side_effect=[absent,visible])
        self.assertIs(runner.verify_disappearance(self.first,{}),visible)
        self.assertIn(.10,[call.args[0] for call in runner.sleep.call_args_list])

    def test_native_group_retries_multiple_misses_before_target_returns(self):
        runner=self.runner()
        runner.native_capture=True
        image=dict(self.first,repeat_while_visible=True)
        absent=dict(found=False,status='not_found')
        visible=dict(found=True,point=(10,10))
        runner.probe=Mock(side_effect=[absent]*9+[visible])
        elapsed=0.

        def sleep(seconds):
            nonlocal elapsed
            elapsed+=seconds

        runner.sleep=sleep
        with patch('core.time.monotonic',side_effect=lambda:elapsed):
            self.assertIs(runner.verify_disappearance(image,{}),visible)
        self.assertGreater(elapsed,.40)

    def test_native_group_samples_at_cutoff_after_initial_detection_delay(self):
        runner=self.runner()
        runner.native_capture=True
        image=dict(self.first,repeat_while_visible=True)
        elapsed=.11

        def sleep(seconds):
            nonlocal elapsed
            elapsed+=seconds

        runner.sleep=sleep
        runner.probe=lambda *_,**__:dict(found=elapsed>=.90,status='not_found')
        with patch('core.time.monotonic',side_effect=lambda:elapsed):
            self.assertIsNone(runner.verify_disappearance(image,{}))
        self.assertLess(elapsed,.90)

    def test_native_group_requires_uninterrupted_absence_after_capture_error(self):
        runner=self.runner()
        runner.native_capture=True
        image=dict(self.first,repeat_while_visible=True)
        absent=dict(found=False,status='not_found')
        elapsed=0.
        misses=[]

        def sleep(seconds):
            nonlocal elapsed
            elapsed+=seconds

        def probe(*_,**__):
            misses.append(elapsed)
            if len(misses)==5:
                raise core.CaptureError('transient failure')
            return absent

        runner.probe=probe
        runner.sleep=sleep
        with patch('core.time.monotonic',side_effect=lambda:elapsed):
            self.assertIsNone(runner.verify_disappearance(image,{}))
        self.assertGreaterEqual(elapsed-misses[5],.75)

    def test_native_group_checks_with_larger_budget_before_leaving(self):
        runner = self.runner()
        runner.native_capture = True
        image = dict(self.first,repeat_while_visible=True)
        visible = dict(found=True,status='found',point=(10,10))
        absent = dict(found=False,status='not_found')
        elapsed = 0.

        def sleep(seconds):
            nonlocal elapsed
            elapsed += seconds

        runner.sleep = sleep
        runner.probe = Mock(side_effect=lambda _,budget=1:visible if budget>=2 else absent)
        with patch('core.time.monotonic',side_effect=lambda:elapsed):
            self.assertIs(runner.verify_disappearance(image,{}),visible)
        self.assertGreaterEqual(elapsed,.75)

    def test_workflow_repeats_all_steps(self):
        self.project['workflow_repeats']=3
        runner=self.runner()
        runner.run()
        self.assertEqual([c.args[1] for c in self.output.call_args_list],['A','B','C']*3)
        self.assertEqual(runner.wait_image.call_count,3)

    def test_single_image_rearms_only_after_two_misses_when_requested(self):
        self.project['repeat_on_reappear']=True
        self.project['workflow_repeats']=2
        self.project['steps']=[self.first]
        runner=self.runner()
        miss=dict(found=False,status='not_found')
        runner.probe.side_effect=[dict(found=True,point=(1,1)),miss,miss]
        runner.run()
        self.assertEqual(runner.probe.call_count,3)
        self.assertEqual([c.args[1] for c in self.output.call_args_list],['A','B','A','B'])

    def test_next_image_takes_priority_while_first_is_still_visible(self):
        self.first.update(repeat_while_visible=True,advance_on_next=True)
        other=dict(core.step('image'),image='target',image_action='actions',
                   children=[self.project['steps'][1]])
        self.project['steps'][1:]=[dict(core.step('text'),enabled=False),other]
        runner=self.runner()
        real_wait=runner.wait_image
        def wait(step):
            if step is other:
                self.assertEqual(runner.carried[0],other['id'])
            return real_wait(step)
        runner.wait_image=wait
        runner.run()
        self.assertEqual([c.args[1] for c in self.output.call_args_list],['A','B','C'])

    def test_continuous_single_card_repeats_while_still_visible(self):
        self.project['steps']=[self.first]
        self.project['workflow_repeats']=0
        runner=self.runner()
        runner.sleep=Mock()
        def run_action(*_):
            if self.output.call_count==1000:
                runner.cancel.set()
        self.output.side_effect=run_action
        runner.run()
        self.assertEqual(self.output.call_count,1000)
        self.assertEqual(runner.wait_image.call_count,500)
        runner.probe.assert_not_called()
        self.assertIn(('state','정지됨'),[c.args for c in self.emit.call_args_list])

    def test_next_image_confirmation_finishes_before_repeating_visible_group(self):
        runner=self.runner()
        runner.sleep=Mock()
        following=dict(core.step('image'),stable=2)
        detected=dict(found=True,point=(20,20))
        runner.wait_image_candidate=Mock(return_value=detected)
        runner.presence=Mock(return_value=detected)
        self.assertIsNone(runner.verify_disappearance(self.first,{},following))
        self.assertEqual(runner.wait_image_candidate.call_count,2)
        self.assertEqual(runner.carried,(following['id'],detected))

    def test_visible_group_checks_for_duplicate_outside_previous_click_location(self):
        runner=self.runner()
        runner.confirm_target=Mock(return_value=(10,10))
        runner.probe=Mock(return_value=dict(found=False,status='ambiguous'))
        image=dict(self.first,repeat_while_visible=True)
        self.assertEqual(runner.presence(image,dict(box=(3,3,14,14)))['status'],'ambiguous')
        runner.confirm_target.assert_not_called()

    def test_group_retries_black_frames_for_silhouette_template_without_advancing(self):
        template=Image.new('RGB',(180,80),'black')
        font=ImageFont.truetype('arialbd.ttf',60)
        ImageDraw.Draw(template).text((90,40),'4',font=font,anchor='mm',fill='white')
        self.project['images']['target']['data']=core.encode_image(template)
        self.first['repeat_while_visible']=True
        frame=Image.new('RGB',(400,180),'black')
        visible=frame.copy()
        visible.paste(template,(90,35))
        capture=Mock(side_effect=[frame,frame,visible])
        runner=core.Runner(self.project,self.emit,capture,self.output)
        runner.sleep=Mock()
        self.assertIsNotNone(runner.templates['target'].silhouette)
        found=runner.verify_disappearance(runner.top_steps[0],{})
        self.assertTrue(found['found'])
        self.assertEqual(capture.call_count,3)
        self.emit.assert_any_call('waiting',(self.first['id'],0,'capture_error','화면을 읽을 수 없습니다'))

    def test_second_image_click_uses_fresh_location(self):
        runner=self.runner()
        runner.output=None
        runner.input=Mock()
        runner.sleep=Mock()
        runner.locate_click=Mock(side_effect=[((10,10),dict(box=(3,3,14,14))),
                                             ((35,36),dict(box=(28,29,14,14)))])
        action=dict(core.step('click'),clicks=2)
        runner.click_detected_image(self.first,{},action)
        self.assertEqual([call.args[:2] for call in runner.input.click_at.call_args_list],
                         [(10,10),(35,36)])

    def test_stop_after_confirmation_prevents_input(self):
        runner=self.runner()
        runner.output=None
        runner.input=Mock()
        def covered(*_):
            runner.cancel.set()
            return False
        runner.editor_at=covered
        with self.assertRaises(core.Halt):
            runner.send('configured_click',10,10,'left',1,.1)
        runner.input.click_at.assert_not_called()

    def test_pointer_interference_retries_only_the_unsent_click(self):
        self.project['workflow_repeats']=0
        runner=self.runner()
        runner.output=None
        runner.input=Mock()
        runner.sleep=Mock()
        runner.input.click_at.side_effect=[None,core.PointerMoved('cursor changed'),None]
        runner.locate_click=Mock(side_effect=[((10,10),dict(box=(3,3,14,14))),
                                             ((20,20),dict(box=(13,13,14,14))),
                                             ((35,36),dict(box=(28,29,14,14)))])
        runner.click_detected_image(self.first,{},dict(core.step('click'),clicks=2))
        self.assertEqual([call.args[:2] for call in runner.input.click_at.call_args_list],
                         [(10,10),(20,20),(35,36)])

    def test_waiting_click_reacquires_without_replaying_prior_action(self):
        click=dict(core.step('click'),source=self.first['id'],configured_target=True)
        self.first.update(wait_forever=True,children=[self.first['children'][0],click])
        result=dict(found=True,box=(4,4,12,12),point=(10,10))
        runner=self.runner()
        runner.wait_image=Mock(return_value=result)
        runner.confirm_target=Mock(side_effect=[None,core.CaptureError('temporary'),(10,10)])
        runner.run()
        self.assertEqual([call.args[0] for call in self.output.call_args_list],
                         ['text','configured_click','text'])
        self.assertEqual(runner.wait_image.call_count,2)

    def test_image_disappears_before_repeat_click_and_next_step_runs(self):
        click=dict(core.step('click'),source=self.first['id'],configured_target=True)
        self.first.update(wait_forever=True,repeat_while_visible=True,children=[click])
        result=dict(found=True,box=(4,4,12,12),point=(10,10))
        runner=self.runner()
        runner.wait_image=Mock(return_value=result)
        runner.confirm_target=Mock(return_value=None)
        runner.probe=Mock(return_value=dict(found=False,status='not_found'))
        runner.run()
        self.assertEqual([call.args for call in self.output.call_args_list],[('text','C')])
        self.assertIn(('state','완료'),[c.args for c in self.emit.call_args_list])

    def test_temporary_uncertainty_keeps_continuous_workflow_running(self):
        self.project['workflow_repeats']=0
        self.first.update(wait_forever=True,repeat_while_visible=True)
        runner=self.runner()
        runner.sleep=Mock()
        uncertain=dict(found=False,status='ambiguous',reason='temporary')
        absent=dict(found=False,status='not_found')
        runner.probe=Mock(side_effect=[uncertain]*25+[absent,absent])
        def run_action(kind,text):
            if text=='C':
                runner.cancel.set()
        self.output.side_effect=run_action
        runner.run()
        self.assertEqual([call.args[1] for call in self.output.call_args_list],['A','B','C'])
        self.assertIn(('state','정지됨'),[c.args for c in self.emit.call_args_list])

    def test_disappearance_retries_stalled_candidate_search_with_larger_budget(self):
        runner = self.runner()
        runner.sleep = Mock()
        incomplete = dict(found=False, status='incomplete', reason='candidate limit')
        absent = dict(found=False, status='not_found')
        runner.probe = Mock(side_effect=[incomplete]*4+[absent,absent])
        self.assertIsNone(runner.verify_disappearance(self.first, {}))
        self.assertEqual([call.kwargs['budget'] for call in runner.probe.call_args_list],
                         [1, 2, 4, 8, 8, 1])

    def test_repeating_required_image_waits_past_timeout_and_once_settings(self):
        for continuous, group, mode in [(True,False,'wait'),(True,False,'once'),
                                         (False,True,'wait'),(False,True,'once'),
                                         (True,True,'wait')]:
            with self.subTest(continuous=continuous,group=group,mode=mode):
                self.project['workflow_repeats']=0 if continuous else 1
                self.first.update(timeout=.1,image_mode=mode,repeat_while_visible=group)
                frame=Image.new('RGB',(40,32),'gray')
                runner=core.Runner(self.project,Mock(),lambda _:frame,Mock())
                now=0.
                def advance(seconds):
                    now_tick[0]+=max(seconds,.05)
                    runner.check()
                now_tick=[now]
                runner.sleep=advance
                miss=dict(found=False,status='not_found',point=None,reason='missing')
                match=dict(found=True,status='found',point=(5,5))
                runner.probe=Mock(side_effect=[miss]*30+[core.CaptureError('offline'),match])
                with patch('core.time.monotonic',side_effect=lambda:now_tick[0]):
                    result=runner.wait_image(runner.top_steps[0])
                self.assertTrue(result['found'])
                self.assertGreater(now_tick[0],1.)

    def test_continuous_repeat_preserves_explicit_absent_branch(self):
        self.project['workflow_repeats']=0
        self.first.update(image_mode='once',otherwise=[dict(core.step('text'),text='absent')])
        runner=core.Runner(self.project,Mock(),lambda _:self.frame,Mock())
        runner.probe=Mock(return_value=dict(found=False,status='not_found',point=None))
        runner.output.side_effect=lambda *_:runner.cancel.set()
        runner.run()
        runner.output.assert_called_once_with('text','absent')

    def test_optional_popup_skips_absence_but_required_next_card_waits(self):
        self.first.update(image_mode='once',failure='skip',
                          children=[dict(core.step('text'),text='close')])
        required=dict(core.step('image'),image='target',timeout=.1,image_action='actions',
                      children=[dict(core.step('text'),text='start')])
        self.project.update(workflow_repeats=0,steps=[self.first,required])
        runner=core.Runner(self.project,self.emit,lambda _:self.frame,self.output)
        missing=dict(found=False,status='not_found',point=None,score=0.,reason='absent')
        found=dict(found=True,status='found',point=(5,5))
        runner.sleep=Mock()
        runner.probe=Mock(side_effect=[missing,missing,missing,found,found,found])
        def output(*_):
            if self.output.call_count==3:
                runner.cancel.set()
        self.output.side_effect=output
        runner.run()
        self.assertEqual([call.args for call in self.output.call_args_list],
                         [('text','start'),('text','close'),('text','start')])

    def test_delayed_next_image_preserves_order_over_twenty_cycles(self):
        second=dict(core.step('image'),image='target',image_action='actions',
                    children=[dict(core.step('text'),text='2')])
        self.first['children']=[dict(core.step('text'),text='1')]
        self.project.update(workflow_repeats=0,steps=[self.first,second])
        runner=core.Runner(self.project,self.emit,lambda _:self.frame,self.output)
        clock=0.
        available_at=0.
        outputs=[]
        expected_delays=[5,30,300]+[2]*17

        def probe(step,**_):
            if step['id']==second['id'] and clock<available_at:
                return dict(found=False,status='not_found',point=None,reason='missing')
            return dict(found=True,status='found',point=(5,5))

        def output(_,value):
            nonlocal available_at
            outputs.append(value)
            if value=='1':
                available_at=clock+expected_delays[(len(outputs)-1)//2]
            else:
                self.assertGreaterEqual(clock,available_at)
                if len(outputs)==40:
                    runner.cancel.set()

        def sleep(seconds):
            nonlocal clock
            if seconds:
                clock+=max(seconds,1.)

        runner.probe=probe
        runner.output=output
        runner.sleep=sleep
        with patch('core.time.monotonic',side_effect=lambda:clock):
            runner.run()
        self.assertEqual(outputs,list('12'*20))

    def test_stop_during_absence_capture_recovery_or_pause_prevents_later_click(self):
        for condition in ('not_found','capture_error','paused'):
            with self.subTest(condition=condition):
                self.project['workflow_repeats']=0
                runner=core.Runner(self.project,Mock(),lambda _:self.frame,Mock())

                def stop(*_):
                    runner.cancel.set()
                    return True

                def probe(*_,**__):
                    if condition=='capture_error':
                        raise core.CaptureError('temporarily unavailable')
                    return dict(found=False,status='not_found',point=None,reason='missing')

                runner.probe=Mock(side_effect=probe)
                if condition=='paused':
                    runner.paused.set()
                    runner.cancel.wait=Mock(side_effect=stop)
                else:
                    runner.sleep=Mock(side_effect=stop)
                runner.run()
                runner.output.assert_not_called()
                runner.emit.assert_any_call('state','정지됨')
