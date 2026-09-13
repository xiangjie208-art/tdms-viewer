import os

import numpy as np
from nptdms import ChannelObject, TdmsWriter

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from tdms_fingerprint_viewer.cluster_panel import BatchClusterWorker
from tdms_fingerprint_viewer.main_window import MainWindow


def write_trace(path, unit='nA', channel='ai0', pulse=True):
    factor = 1 if unit == 'pA' else 1000
    values = np.full(1000, -2/factor)
    if pulse: values[500] = 30/factor
    with TdmsWriter(path) as writer:
        writer.write_segment([ChannelObject('Current', channel, values,
                             properties={'wf_increment': .001, 'unit_string': unit})])


def wait_until(app, predicate):
    for _ in range(500):
        app.processEvents()
        if predicate(): return
        QTest.qWait(10)
    assert predicate()


def test_batch_converts_each_unit_continues_errors_and_cancels(tmp_path):
    app = QApplication.instance() or QApplication([])
    paths = [tmp_path/f'sample_{i}.tdms' for i in range(5)]
    write_trace(paths[0], 'nA'); write_trace(paths[1], 'Volts'); write_trace(paths[2], 'pA')
    write_trace(paths[3], 'a.u.'); write_trace(paths[4], channel='other')
    parameters = {'amplitude':15, 'baseline':-2, 'baseline_auto':False,
                  'fwhm_ms':40, 'threshold':.1, 'input_unit':'pA'}
    worker = BatchClusterWorker(paths, 'Current/ai0', parameters)
    items = []; done = []
    worker.signals.item.connect(items.append); worker.signals.done.connect(done.append)
    worker.run()
    assert len(items) == 5 and done[0]['success'] == 3 and done[0]['failed'] == 2
    assert items[0]['result']['rows'] == items[1]['result']['rows'] == items[2]['result']['rows']
    assert items[1]['result']['parameters']['amplitude'] == .015
    assert items[2]['result']['parameters']['amplitude'] == 15
    worker.cancelled.set(); items.clear(); worker.run()
    assert not items and done[-1]['cancelled']
    partial = BatchClusterWorker(paths, 'Current/ai0', parameters)
    partial_items = []
    partial.signals.item.connect(lambda item: (partial_items.append(item), partial.cancelled.set()))
    partial.run()
    assert len(partial_items) == 1 and 'result' in partial_items[0]
    app.processEvents()


def test_batch_cache_follows_file_navigation_and_parameter_changes(tmp_path, monkeypatch):
    monkeypatch.setenv('TDMS_VIEWER_DATA_DIR', str(tmp_path/'state'))
    folder = tmp_path/'data'; folder.mkdir()
    write_trace(folder/'sample_1.tdms')
    write_trace(folder/'sample_2.tdms', 'Volts', pulse=False)
    app = QApplication.instance() or QApplication([])
    w = MainWindow(); panel = w.cluster_panel
    w.open_data_folder(folder)
    wait_until(app, lambda: w.current_channel is not None and not panel.loading)
    panel.start_batch()
    assert not panel.amplitude.isEnabled()
    assert not panel.min_peaks.isEnabled()
    wait_until(app, lambda: panel.batch_worker is None)
    assert len(panel.batch_cache) == 2
    assert panel.table.rowCount() == 1
    assert '[1 簇]' in panel.file_combo.itemText(0)
    assert '[0 簇]' in panel.file_combo.itemText(1)
    assert not w.session['regions']
    panel.next_file_button.click()
    wait_until(app, lambda: w.current_path.name == 'sample_2.tdms' and not panel.loading)
    assert panel.result is not None and panel.table.rowCount() == 0
    assert panel.amplitude.value() == 15 and panel.unit == 'Volts'
    panel.previous_file_button.click()
    wait_until(app, lambda: w.current_path.name == 'sample_1.tdms' and not panel.loading)
    assert panel.table.rowCount() == 1
    panel.threshold.setValue(.2)
    assert not panel.batch_cache and panel.result is None
    assert panel.file_combo.itemText(0) == 'sample_1.tdms'
    w.fft_timer.stop(); w.session_timer.stop(); w.session=None; w.close(); app.processEvents()
