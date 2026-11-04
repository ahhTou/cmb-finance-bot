import sys
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
import fast_buy_uia2 as fu
import fast_buy as fb


def panel(enabled=False,keyboard=True,covered=False,done=True):
    nodes=['<node text="点击谈出密码键盘" bounds="[30,100][290,130]"/>',
           f'<node text="确定" enabled="{str(enabled).lower()}" bounds="[100,{450 if covered else 200}][220,{490 if covered else 240}]"/>']
    if keyboard:
        for digit in range(10):
            x,y=10+(digit%3)*90,400+(digit//3)*40
            nodes.append(f'<node text="{digit}" class="android.widget.Button" bounds="[{x},{y}][{x+60},{y+30}]"/>')
        if done:nodes.append('<node text="完成" class="android.widget.Button" bounds="[220,360][300,390]"/>')
    return ET.fromstring('<hierarchy>'+''.join(nodes)+'</hierarchy>')


class PasswordPanelTest(unittest.TestCase):
    def run_input(self,screens,stable=None):
        stable=stable if stable is not None else panel()
        keys=fu.raw_digit_buttons(stable)
        calls=[]
        with patch.object(fu,'wait_keypad_stable',return_value=(stable,keys)) as wait, \
             patch.object(fu,'dump',side_effect=screens), \
             patch.object(fu,'send_commands',side_effect=lambda c:calls.append(c)), \
             patch.object(fu.time,'sleep'),patch.object(fu,'close_password_panel') as close:
            error=None
            try:fu.enter_password('111111')
            except fb.Stop as exc:error=exc
        return calls,wait,close,error

    def test_direct_confirm_without_done(self):
        calls,wait,close,error=self.run_input([panel(enabled=True)])
        self.assertIsNone(error);close.assert_not_called()
        self.assertEqual(calls[-1],['input tap 160 220'])
        self.assertEqual(len(calls),2)  # six digits and delay, then exactly one submit
        self.assertNotIn('input tap 260 375',[c for batch in calls for c in batch])

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
