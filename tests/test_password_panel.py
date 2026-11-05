import sys
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import patch
from contextlib import nullcontext
from tests.test_open_form import Clock

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
import fast_buy_uia2 as fu
import fast_buy as fb


def panel(enabled=False,keyboard=True,covered=False,done=True):
    nodes=['<node text="点击谈出密码键盘" focused="true" bounds="[30,100][290,130]"/>',
           f'<node text="确定" enabled="{str(enabled).lower()}" bounds="[100,{450 if covered else 200}][220,{490 if covered else 240}]"/>']
    if keyboard:
        for digit in range(10):
            x,y=10+(digit%3)*90,400+(digit//3)*40
            nodes.append(f'<node text="{digit}" class="android.widget.Button" enabled="true" clickable="true" bounds="[{x},{y}][{x+60},{y+30}]"/>')
        if done:nodes.append('<node text="完成" class="android.widget.Button" enabled="true" clickable="true" bounds="[220,360][300,390]"/>')
    return ET.fromstring('<hierarchy>'+''.join(nodes)+'</hierarchy>')


class PasswordPanelTest(unittest.TestCase):
    def run_input(self,screens,stable=None,settle=False,submit=True,pace=None):
        stable=stable if stable is not None else panel()
        keys=fu.raw_digit_buttons(stable)
        calls=[]
        clock=Clock()
        settle_mock = nullcontext() if settle else patch.object(fu, "wait_password_confirm", side_effect=lambda root,**kw: root)
        with settle_mock, patch.object(fu.time,"monotonic",side_effect=clock.monotonic), patch.object(fu,'wait_keypad_stable',return_value=(stable,keys)) as wait, \
             patch.object(fu,'dump',side_effect=screens), \
             patch.object(fu,'send_commands',side_effect=lambda c:calls.append(c)), \
             patch.object(fu.time,'sleep',side_effect=clock.sleep),patch.object(fu,'close_password_panel') as close:
            error=None
            try:fu.enter_password('111111',submit=submit,pace=pace)
            except fb.Stop as exc:error=exc
        return calls,wait,close,error

    def test_direct_confirm_without_done(self):
        calls,wait,close,error=self.run_input([panel(enabled=True)])
        self.assertIsNone(error);close.assert_not_called()
        self.assertEqual(calls[-1],['input tap 160 220'])
        self.assertEqual(len(calls),2)  # six digits and delay, then exactly one submit
        self.assertNotIn('input tap 260 375',[c for batch in calls for c in batch])

    def test_drill_types_but_never_taps_confirm(self):
        calls,_,close,error=self.run_input([panel(enabled=True)],submit=False)
        self.assertIsNone(error);close.assert_not_called()
        self.assertEqual(len(calls),1)  # the six digits only
        self.assertNotIn('input tap 160 220',[c for batch in calls for c in batch])

    def test_drill_uses_done_fallback_but_still_never_taps_confirm(self):
        calls,_,_,error=self.run_input([panel(),panel(enabled=True,keyboard=False)],submit=False)
        self.assertIsNone(error);self.assertEqual(calls[-1],['input tap 260 375'])
        self.assertNotIn('input tap 160 220',[c for batch in calls for c in batch])

    def test_done_not_required_to_exist(self):
        calls,_,_,error=self.run_input([panel(enabled=True,done=False)],panel(done=False))
        self.assertIsNone(error);self.assertEqual(calls[-1],['input tap 160 220'])

    def test_disabled_confirm_falls_back_to_done(self):
        calls,_,close,error=self.run_input([panel(),panel(enabled=True,keyboard=False)])
        self.assertIsNone(error);close.assert_not_called()
        self.assertEqual(calls[1],['input tap 260 375'])
        self.assertEqual(calls[-1],['input tap 160 220'])

    def test_enabled_but_covered_confirm_closes_keypad_first(self):
        calls,_,_,error=self.run_input([panel(enabled=True,covered=True),panel(enabled=True,keyboard=False)])
        self.assertIsNone(error);self.assertEqual(calls[1],['input tap 260 375'])

    def test_incomplete_input_retypes_once_without_duplicate_submit(self):
        calls,wait,_,error=self.run_input([panel(),panel(keyboard=False),panel(enabled=True)])
        self.assertIsNone(error);self.assertEqual(wait.call_count,2)
        self.assertEqual(sum(batch==['input tap 160 220'] for batch in calls),1)

    def test_incomplete_twice_closes_without_submit(self):
        calls,wait,close,error=self.run_input([panel(),panel(keyboard=False),panel(),panel(keyboard=False)])
        self.assertIsInstance(error,fb.Stop);close.assert_called_once();self.assertEqual(wait.call_count,2)
        self.assertNotIn(['input tap 160 220'],calls)

    def test_still_covered_after_done_never_submits(self):
        calls,_,close,error=self.run_input([panel(enabled=True,covered=True),panel(enabled=True,covered=True)])
        self.assertIsInstance(error,fb.Stop);close.assert_called_once()
        self.assertNotIn(['input tap 160 470'],calls)


    def test_delayed_enabled_state_does_not_click_done_or_retype(self):
        calls,wait,close,error=self.run_input([panel(),panel(),panel(enabled=True)],settle=True)
        self.assertIsNone(error);self.assertEqual(wait.call_count,1);close.assert_not_called()
        self.assertEqual(len(calls),2)
        self.assertEqual(calls[-1],['input tap 160 220'])

    def test_delayed_enabled_after_done_does_not_retype(self):
        calls,wait,close,error=self.run_input([panel(enabled=True,covered=True),panel(keyboard=False),panel(enabled=True,keyboard=False)],settle=True)
        self.assertIsNone(error);self.assertEqual(wait.call_count,1);close.assert_not_called()
        self.assertEqual(calls[1],['input tap 260 375'])
        self.assertEqual(calls[-1],['input tap 160 220'])

    def test_status_read_failure_never_retypes_or_submits(self):
        calls,wait,close,error=self.run_input([panel(),RuntimeError('read failed')],settle=True)
        self.assertIsInstance(error,fb.Stop);self.assertEqual(wait.call_count,1);close.assert_called_once()
        self.assertEqual(len(calls),1)

    def test_unstable_keypad_timeout_cannot_fall_back_to_last_coordinates(self):
        clock=Clock()
        index=[0]
        def moving():
            index[0]+=1;clock.sleep(.1)
            root=panel()
            digit=next(n for n in root.iter('node') if n.get('text')=='0')
            digit.set('bounds',f'[{10+2*index[0]},400][70,430]')
            return root
        with patch.object(fu.time,'monotonic',side_effect=clock.monotonic), \
             patch.object(fu.time,'sleep',side_effect=clock.sleep),patch.object(fu,'dump',side_effect=moving):
            with self.assertRaisesRegex(fb.Stop,'未稳定'):
                fu.wait_keypad_stable(timeout=.2)


    def test_persistently_disabled_state_wait_is_bounded(self):
        clock=Clock()
        with patch.object(fu.time,'monotonic',side_effect=clock.monotonic), \
             patch.object(fu.time,'sleep',side_effect=clock.sleep),patch.object(fu,'dump',return_value=panel()) as read:
            root=fu.wait_password_confirm(panel())
        self.assertFalse(fu.confirm_enabled(root))
        self.assertGreaterEqual(clock.now,.6)
        self.assertLess(clock.now,.65)
        self.assertGreater(read.call_count,1)


    def test_keypad_requires_focus_and_every_digit_actionable(self):
        root=panel()
        self.assertIsNotNone(fu.keypad_ready(root))
        root.find('node').set('focused','false')
        self.assertIsNone(fu.keypad_ready(root))
        for attribute in ('enabled','clickable'):
            root=panel()
            next(n for n in root.iter('node') if n.get('text')=='0').set(attribute,'false')
            self.assertIsNone(fu.keypad_ready(root))

    def test_duplicate_digit_controls_are_not_ready(self):
        root=panel();root.append(ET.fromstring('<node text="0" class="android.widget.Button" enabled="true" clickable="true" bounds="[1,1][10,10]"/>'))
        self.assertIsNone(fu.keypad_ready(root))

    def slow_dump(self,clock,cost=.1):
        def read():
            clock.sleep(cost);return panel()
        return read

    def test_keypad_needs_stability_duration_not_just_two_samples(self):
        clock=Clock()
        with patch.object(fu.time,'monotonic',side_effect=clock.monotonic), \
             patch.object(fu.time,'sleep',side_effect=clock.sleep) as sleep, \
             patch.object(fu,'dump',side_effect=self.slow_dump(clock,.01))as read:
            fu.wait_keypad_stable()
        self.assertGreaterEqual(clock.now,fu.KEYPAD_STABLE_SECONDS)
        self.assertGreaterEqual(read.call_count,fu.KEYPAD_STABLE_SAMPLES)
        self.assertEqual(sleep.call_count,0)  # no extra gap by default

    def test_keypad_with_100ms_dump_is_ready_on_the_third_sample(self):
        # 11-05: dump ~0.1 s + 40 ms sleep put the third sample at ~280 ms.
        clock=Clock()
        with patch.object(fu.time,'monotonic',side_effect=clock.monotonic), \
             patch.object(fu.time,'sleep',side_effect=clock.sleep), \
             patch.object(fu,'dump',side_effect=self.slow_dump(clock))as read:
            fu.wait_keypad_stable()
        self.assertEqual(read.call_count,3)
        self.assertAlmostEqual(clock.now,.3)

    def test_keypad_sample_count_and_gap_are_honoured(self):
        clock=Clock()
        with patch.object(fu.time,'monotonic',side_effect=clock.monotonic), \
             patch.object(fu.time,'sleep',side_effect=clock.sleep), \
             patch.object(fu,'dump',side_effect=self.slow_dump(clock))as read:
            fu.wait_keypad_stable(stable_seconds=0,samples_needed=5,gap=.04)
        self.assertEqual(read.call_count,5)
        self.assertAlmostEqual(clock.now,.5+.04*4)

    def test_keypad_motion_with_same_rounded_center_resets_stability(self):
        clock=Clock();index=[0]
        def moving():
            index[0]+=1;clock.sleep(.1);root=panel()
            digit=next(n for n in root.iter('node')if n.get('text')=='0')
            # Both rectangles have the same center, but the layout is moving.
            digit.set('bounds','[10,400][70,430]'if index[0]%2 else'[11,400][69,430]')
            return root
        with patch.object(fu.time,'monotonic',side_effect=clock.monotonic), \
             patch.object(fu.time,'sleep',side_effect=clock.sleep),patch.object(fu,'dump',side_effect=moving):
            with self.assertRaises(fb.Stop):fu.wait_keypad_stable(timeout=.4)

    def test_repeated_digit_taps_have_explicit_spacing(self):
        keys=fu.raw_digit_buttons(panel())
        commands=fu.password_taps('111111',keys,.15)
        self.assertEqual(len([c for c in commands if c.startswith('input tap')]),6)
        self.assertEqual(commands.count('sleep 0.05'),5)
        self.assertEqual(commands[-1],'sleep 0.15')
        for i in range(0,10,2):
            self.assertTrue(commands[i].startswith('input tap'))
            self.assertEqual(commands[i+1],'sleep 0.05')

    def test_distinct_digits_use_the_short_gap(self):
        keys=fu.raw_digit_buttons(panel())
        commands=fu.password_taps('123456',keys,.15)
        self.assertEqual(commands.count('sleep 0.05'),0)
        self.assertEqual(commands.count('sleep 0.01'),5)
        self.assertEqual(commands[-1],'sleep 0.15')

    def test_only_repeated_digit_pairs_get_the_long_gap(self):
        keys=fu.raw_digit_buttons(panel())
        commands=fu.password_taps('112233',keys,.15)
        # 1-1, 2-2 and 3-3 repeat; 1-2 and 2-3 change.
        self.assertEqual(commands.count('sleep 0.05'),3)
        self.assertEqual(commands.count('sleep 0.01'),2)


class PasswordPaceTest(unittest.TestCase):
    """Every pause in the password flow is a saved setting, not a constant."""

    PACE = dict(password_page_timeout_s=7,keypad_timeout_ms=900,keypad_stable_ms=120,
                keypad_stable_samples=4,keypad_sample_gap_ms=30,
                password_same_digit_gap_ms=80,password_different_digit_gap_ms=20,
                password_confirm_gap_ms=250,password_confirm_timeout_ms=800,
                password_retry_gap_ms=40,password_done_gap_ms=60,
                password_close_wait_ms=300,result_first_wait_ms=1500,result_timeout_s=45)

    def test_saved_preferences_become_the_seconds_this_module_sleeps(self):
        pace=fu.password_pace(self.PACE)
        self.assertEqual(pace['page_timeout'],7)
        self.assertAlmostEqual(pace['keypad_timeout'],.9)
        self.assertAlmostEqual(pace['keypad_stable'],.12)
        self.assertEqual(pace['keypad_samples'],4)
        self.assertAlmostEqual(pace['keypad_gap'],.03)
        self.assertAlmostEqual(pace['same_gap'],.08)
        self.assertAlmostEqual(pace['different_gap'],.02)
        self.assertAlmostEqual(pace['confirm_gap'],.25)
        self.assertAlmostEqual(pace['confirm_timeout'],.8)
        self.assertAlmostEqual(pace['retry_gap'],.04)
        self.assertAlmostEqual(pace['done_gap'],.06)
        self.assertAlmostEqual(pace['close_wait'],.3)
        self.assertAlmostEqual(pace['result_wait'],1.5)
        self.assertEqual(pace['result_timeout'],45)

    def test_pace_with_no_arguments_reads_the_saved_file(self):
        with patch.object(fu.purchase_settings,'load',return_value=dict(fu.purchase_settings.DEFAULTS,**self.PACE)):
            pace=fu.password_pace()
        self.assertAlmostEqual(pace['same_gap'],.08)

    def test_gaps_come_from_the_caller_not_the_module_constants(self):
        keys=fu.raw_digit_buttons(panel())
        commands=fu.password_taps('112233',keys,.4,same_gap=.08,different_gap=.02)
        self.assertEqual(commands.count('sleep 0.08'),3)
        self.assertEqual(commands.count('sleep 0.02'),2)
        self.assertEqual(commands[-1],'sleep 0.4')

    def test_enter_password_passes_pace_to_keypad_and_confirm_waits(self):
        stable=panel();keys=fu.raw_digit_buttons(stable);calls=[]
        pace=dict(fu.DEFAULT_PACE,keypad_timeout=2.5,keypad_stable=1.5,confirm_timeout=1.1,
                  same_gap=.07,different_gap=.03)
        with patch.object(fu,'wait_keypad_stable',return_value=(stable,keys)) as wait, \
             patch.object(fu,'wait_password_confirm',side_effect=lambda root,**kw:root) as confirm, \
             patch.object(fu,'dump',return_value=panel(enabled=True)), \
             patch.object(fu,'send_commands',side_effect=lambda c:calls.append(c)), \
             patch.object(fu.time,'sleep'):
            fu.enter_password('111111',pace=pace)
        self.assertEqual(wait.call_args.kwargs,{'timeout':2.5,'stable_seconds':1.5,
                                                'samples_needed':3,'gap':0.0})
        self.assertEqual(confirm.call_args.kwargs,{'timeout':1.1})
        self.assertEqual(calls[0].count('sleep 0.07'),5)
        self.assertEqual(calls[-1],['input tap 160 220'])

    def test_explicit_confirm_wait_still_overrides_the_saved_gap(self):
        keys=fu.raw_digit_buttons(panel())
        commands=fu.password_taps('123456',keys,.33,same_gap=.08,different_gap=.02)
        self.assertEqual(commands[-1],'sleep 0.33')

    def test_defaults_are_valid_and_keep_the_measured_gaps(self):
        values=fu.purchase_settings.validate(fu.purchase_settings.DEFAULTS)
        self.assertEqual(values['password_same_digit_gap_ms'],50)
        self.assertEqual(values['password_different_digit_gap_ms'],10)
        self.assertEqual(values['keypad_stable_ms'],200)
        self.assertEqual(values['keypad_stable_samples'],fu.KEYPAD_STABLE_SAMPLES)
        self.assertEqual(values['keypad_sample_gap_ms']/1000,fu.KEYPAD_SAMPLE_GAP)
        self.assertEqual(values['keypad_stable_ms']/1000,fu.KEYPAD_STABLE_SECONDS)

    def test_impossible_keypad_stability_is_rejected_at_save_time(self):
        with self.assertRaisesRegex(RuntimeError,'键盘稳定时长必须小于'):
            fu.purchase_settings.validate(dict(fu.purchase_settings.DEFAULTS,keypad_stable_ms=1200))

    def test_out_of_range_gap_is_rejected_at_save_time(self):
        with self.assertRaisesRegex(RuntimeError,'password_same_digit_gap_ms'):
            fu.purchase_settings.validate(dict(fu.purchase_settings.DEFAULTS,password_same_digit_gap_ms=3001))
