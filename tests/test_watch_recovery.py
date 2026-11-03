import contextlib
from datetime import datetime, timedelta
import fcntl
import multiprocessing
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import night_watch as nw


def race_arm(state, start, results):
    nw.STATE = Path(state)
    nw.TASK = nw.STATE / 'task.json'
    nw.LOG = nw.STATE / 'watch.log'
    def spawn(task):
        time.sleep(.15)
        task['pid'] = os.getpid()
        nw.save_task(task)
        with (nw.STATE / 'spawn-count').open('a') as out: out.write('one\n')
    start.wait()
    try:
        with patch.object(nw.keychain_store, 'load'), patch.object(nw.notify, 'configured', return_value=True), \
             patch.object(nw, 'emulator_running', return_value=True), patch.object(nw, 'booted', return_value=True), \
             patch.object(nw, 'adb'), patch.object(nw, 'spawn_watch', side_effect=spawn), \
             patch.object(nw.subprocess, 'run'):
            nw.arm_task('TEST01', '0.01', dry_run=True, now=True)
        results.put(True)
        time.sleep(.5)  # Winning fake worker remains alive through the competing check.
    except nw.Abort:
        results.put(False)


class RecoveryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        state = Path(self.tmp.name)
        self.stack = contextlib.ExitStack()
        for name, value in [('STATE', state), ('TASK', state / 'task.json'), ('LOG', state / 'watch.log')]:
            self.stack.enter_context(patch.object(nw, name, value))
        self.stack.enter_context(patch.object(nw, 'alert'))
        self.stack.enter_context(patch.object(nw, 'log'))
        self.stack.enter_context(patch.object(nw, 'emulator_running', return_value=True))
        self.stack.enter_context(patch.object(nw, 'booted', return_value=True))
        self.spawn = self.stack.enter_context(patch.object(nw, 'spawn_watch'))

    def tearDown(self):
        self.stack.close()
        self.tmp.cleanup()

    def task(self, **kwargs):
        data = dict(version=2, phase='armed', task_id='original', generation='original',
                    armed_at='2026-11-03T09:00:00', code='TEST01', amount='0.01', dry_run=True,
                    at=(datetime.now() + timedelta(minutes=20)).isoformat(),
                    fire_at=(datetime.now() + timedelta(minutes=20)).isoformat(),
                    patterns_sent=2, resumes=[], last_tick=(datetime.now() - timedelta(minutes=6)).isoformat())
        data.update(kwargs)
        nw.save_task(data)
        return data

    def refuses(self):
        before = nw.TASK.read_bytes()
        with self.assertRaises(nw.Abort): nw.resume_task('test')
        self.assertEqual(nw.TASK.read_bytes(), before)
        self.spawn.assert_not_called()

    def test_resume_keeps_authorized_parameters_and_pattern_budget(self):
        original = self.task(phase='aborted')
        resumed = nw.resume_task('test', by='agent:test')
        for key in ('task_id', 'code', 'amount', 'at', 'fire_at', 'dry_run', 'patterns_sent', 'armed_at'):
            self.assertEqual(resumed[key], original[key])
        self.assertNotEqual(resumed['generation'], original['generation'])
        self.assertEqual(resumed['phase'], 'armed')
        self.assertEqual(resumed['resumes'][0]['by'], 'agent:test')
        self.spawn.assert_called_once()

    def test_resume_denials(self):
        for kwargs in ({'version': None}, {'fired_at': 'already', 'phase': 'aborted'},
                       {'phase': 'done'}, {'patterns_sent': 3}, {'resumes': [{}, {}]},
                       {'fire_at': (datetime.now() + timedelta(minutes=2)).isoformat()}):
            self.task(**kwargs)
            self.refuses()
        self.task()
        with patch.object(nw, 'booted', return_value=False): self.refuses()

    def test_live_process_needs_stale_flag_and_tick(self):
        self.task(pid=123)
        with patch.object(nw, 'alive', return_value=True): self.refuses()
        self.task(pid=123, last_tick=datetime.now().isoformat())
        with patch.object(nw, 'alive', return_value=True), patch.object(nw, 'stop_watch') as stop:
            with self.assertRaises(nw.Abort): nw.resume_task('test', kill_stale=True)
        stop.assert_not_called()

    def test_stale_recovery_stops_verified_worker(self):
        task = self.task(pid=123)
        with patch.object(nw, 'alive', return_value=True), patch.object(nw, 'stop_watch') as stop:
            nw.resume_task('test', kill_stale=True)
        stop.assert_called_once()
        self.assertEqual(stop.call_args.args[0]["pid"], task["pid"])

    def test_lock_excludes_all_control_operations(self):
        self.task()
        before = nw.TASK.read_bytes()
        with (nw.STATE / 'task.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            for operation in (lambda: nw.resume_task('test'), nw.disarm_task,
                              lambda: nw.arm_task('TEST01', '0.01', now=True, dry_run=True)):
                with self.assertRaises(nw.Abort): operation()
                self.assertEqual(nw.TASK.read_bytes(), before)

    def test_old_generation_cannot_write_or_fire(self):
        task = self.task()
        nw.resume_task('test')
        before = nw.TASK.read_bytes()
        task['phase'] = 'firing'
        with self.assertRaises(nw.Abort): nw.persist(task)
        self.assertEqual(nw.TASK.read_bytes(), before)

    def test_submission_marker_and_budget_cannot_be_erased(self):
        task = self.task(fired_at="permanent", phase="done")
        task.pop("fired_at")
        with self.assertRaises(nw.Abort): nw.persist(task)
        task = self.task()
        task["patterns_sent"] = 1
        with self.assertRaises(nw.Abort): nw.persist(task)

    def test_disarmed_worker_cannot_write(self):
        task = self.task()
        nw.disarm_task()
        with self.assertRaises(nw.Abort): nw.persist(task)

    def test_legacy_status_and_disarm(self):
        self.task(version=None)
        self.assertTrue(nw.status_info()['legacy'])
        nw.disarm_task()
        self.assertEqual(nw.load_task()['phase'], 'disarmed')

    def test_manual_login_never_cold_starts_or_draws(self):
        task = self.task(patterns_sent=3)
        task = nw.resume_task('manual', after_manual_login=True)
        with patch.object(nw, 'ensure_emulator'), patch.object(nw, 'ensure_awake'), \
             patch.object(nw, 'tap_text', return_value=True), patch.object(nw, 'logged_in', return_value=True), \
             patch.object(nw, 'on_login_page', return_value=False), patch.object(nw, 'open_detail'), \
             patch.object(nw, 'cold_start') as cold, patch.object(nw.secure_input, 'login') as login:
            nw.prepare(task, [0], {})
        cold.assert_not_called(); login.assert_not_called()
        with patch.object(nw, 'ensure_emulator'), patch.object(nw, 'ensure_awake'), \
             patch.object(nw, 'tap_text', return_value=False), patch.object(nw, 'login_fresh') as fresh:
            with self.assertRaises(nw.Abort): nw.prepare(task, [0], {})
        fresh.assert_not_called()

    def test_fire_marker_survives_failure(self):
        import types
        task = self.task()
        fake = types.SimpleNamespace(run=lambda *a, **k: (_ for _ in ()).throw(RuntimeError('unknown')))
        with patch.dict(sys.modules, {'fast_buy_uia2': fake}): nw.fire(task, datetime.now())
        self.assertTrue(nw.load_task()['fired_at'])
        self.refuses()

    def test_two_processes_only_one_arm(self):
        ctx = multiprocessing.get_context('spawn')
        start, results = ctx.Event(), ctx.Queue()
        workers = [ctx.Process(target=race_arm, args=(self.tmp.name, start, results)) for _ in range(2)]
        try:
            for worker in workers: worker.start()
            start.set()
            self.assertEqual(sorted(results.get(timeout=10) for _ in workers), [False, True])
            for worker in workers:
                worker.join(10)
                self.assertEqual(worker.exitcode, 0)
            self.assertEqual((nw.STATE / 'spawn-count').read_text().splitlines(), ['one'])
        finally:
            for worker in workers:
                if worker.is_alive(): worker.terminate(); worker.join()


if __name__ == '__main__': unittest.main()
