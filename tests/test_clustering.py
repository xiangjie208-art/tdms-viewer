import os
import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
from tdms_fingerprint_viewer.clustering import find_clusters
from tdms_fingerprint_viewer.core import ChannelInfo
from tdms_fingerprint_viewer.main_window import MainWindow
from tdms_fingerprint_viewer.session import normalize_session


def params(**overrides):
    return dict({"amplitude": 1., "fwhm_ms": 40., "threshold": .1,
                 "baseline_auto": False, "baseline": -2., "unit": "nA"}, **overrides)


def test_unit_height_isolated_event_and_original_samples():
    values = np.full(1000, -2.); values[500:503] = [0, 2, 0]
    original = values.copy()
    result = find_clusters(values, .001, params(), offset=100)
    assert result["peaks"].tolist() == [601]
    row = result["rows"][0]
    assert row["n_seeds"] == 1
    assert abs((row["end_index_exclusive"]-row["start_index"])-72.9) < 2
    np.testing.assert_array_equal(values, original)


def test_window_connects_peaks_and_edges_are_marked():
    values = np.full(1000, -2.); values[[0, 200, 250, 999]] = 3
    narrow = find_clusters(values, .001, params(fwhm_ms=10))
    wide = find_clusters(values, .001, params())
    assert len(narrow["rows"]) == 4
    assert len(wide["rows"]) == 3
    assert wide["rows"][0]["left_censored"]
    assert wide["rows"][-1]["right_censored"]
    assert sum(r["n_seeds"] for r in wide["rows"]) == 4


def test_minimum_peak_count_filters_completed_clusters():
    values = np.full(1000, -2.); values[[200, 250, 750]] = 3
    result = find_clusters(values, .001, params(min_peaks=2))
    assert len(result["rows"]) == 1
    assert result["rows"][0]["n_seeds"] == 2
    assert result["parameters"]["min_peaks"] == 2


def test_minimum_peak_count_defaults_to_one_for_existing_parameters():
    values = np.full(1000, -2.); values[500] = 3
    result = find_clusters(values, .001, params())
    assert len(result["rows"]) == 1
    assert result["parameters"]["min_peaks"] == 1


def test_empty_result_and_automatic_baseline():
    result = find_clusters(np.full(1000, -3.), .001, params(baseline_auto=True))
    assert result["baseline"] == -3
    assert result["rows"] == []


@pytest.mark.parametrize("values,dt,changes", [([0,np.nan],.001,{}), ([0,1],0,{}),
    ([0,1],.001,{"threshold": 1}), ([0,1],.001,{"fwhm_ms": .01}),
    ([0,1],.001,{"min_peaks": 0}), ([0,1],.001,{"min_peaks": 1.5})])
def test_invalid_inputs_are_rejected(values, dt, changes):
    with pytest.raises(ValueError): find_clusters(values, dt, params(**changes))


@pytest.mark.parametrize("unit", ["nA", "Volts"])
def test_preview_review_save_and_recompute(tmp_path, monkeypatch, unit):
    monkeypatch.setenv("TDMS_VIEWER_DATA_DIR", str(tmp_path/'state'))
    app = QApplication.instance() or QApplication([])
    w = MainWindow(); w.data_folder = tmp_path
    w.session = normalize_session(None, tmp_path)
    values = np.full(1000, -2.); values[[200, 250, 750]] = 3
    channel = ChannelInfo('Current', 'ai0', len(values), .001, unit)
    w.on_trace_loaded({"token":w.load_token,"path":tmp_path/'sample.tdms',"values":values,
                       "selected":channel,"channels":[channel]})
    panel = w.cluster_panel; panel.amplitude.setValue(1000)
    panel.start()
    for _ in range(200):
        app.processEvents()
        if not panel.workers: break
        QTest.qWait(10)
    assert not panel.workers
    assert panel.table.rowCount() == 2
    assert len(w.session['regions']) == 0
    panel.table.selectRow(0); app.processEvents()
    first = panel.result['rows'][0]
    assert w.current_indices == (first['start_index'], first['end_index_exclusive'])
    assert w.detail_view_box.viewRange()[0][0] < first['start_index'] * .001
    # Manual edits determine saved bounds, not the original cluster boundaries.
    w.on_detail_selection_finished(('time', .21, .27, -3, 4))
    panel.save()
    saved = w.session['regions'][0]
    assert saved['start_index'] == 210
    assert saved['end_index_exclusive'] == 270
    assert saved['cluster_detection']['parameters']['amplitude'] == 1
    assert saved['cluster_detection']['parameters']['native_to_pa_factor'] == 1000
    assert saved['cluster_detection']['parameters']['min_peaks'] == 1
    np.testing.assert_array_equal(w.current_values, values)
    panel.threshold.setValue(.2)
    assert panel.result is None and panel.table.rowCount() == 0
    assert w.session['regions'][0] == saved
    # Late results after parameter/file changes must not restore old candidates.
    panel.finished(None, (panel.token-1, {}))
    assert panel.result is None
    w.fft_timer.stop(); w.session_timer.stop(); w.session=None; w.close(); app.processEvents()


@pytest.mark.parametrize("unit,factor", [("A", 1e12), ("nA", 1000), ("pA", 1),
                                       ("V", 1000), ("Volts", 1000), ("volt", 1000)])
def test_pa_inputs_convert_to_native_and_restore_saved_values(tmp_path, monkeypatch, unit, factor):
    monkeypatch.setenv("TDMS_VIEWER_DATA_DIR", str(tmp_path/'state'))
    app = QApplication.instance() or QApplication([])
    w = MainWindow()
    w.current_channel = ChannelInfo('Current', 'ai0', 1000, .001, unit)
    w.settings['cluster_parameters'] = {unit: {'amplitude': 15/factor, 'baseline': -2/factor,
                                              'baseline_auto': False, 'min_peaks': 4}}
    panel = w.cluster_panel; panel.loaded()
    assert "已确认" not in panel.unit_label.text()
    assert "标定：1 V = 1000 pA" in panel.unit_label.text() if unit.lower() in ("v", "volt", "volts") else True
    assert panel.amplitude.value() == 15
    assert panel.baseline.value() == -2
    assert panel.parameters()['amplitude'] == pytest.approx(15/factor, abs=1e-25)
    assert panel.parameters()['baseline'] == pytest.approx(-2/factor, abs=1e-25)
    assert panel.min_peaks.value() == panel.parameters()['min_peaks'] == 4
    assert panel.run_button.isEnabled()
    assert panel.parameters()['native_to_pa_factor'] == factor
    w.current_channel = ChannelInfo('Current', 'ai0', 1000, .001, 'a.u.')
    panel.loaded()
    assert not panel.run_button.isEnabled()
    panel.amplitude.setValue(20)
    assert not panel.run_button.isEnabled()
    w.close(); app.processEvents()


def test_cluster_panel_switches_real_files_without_leaving_tab(tmp_path, monkeypatch):
    from nptdms import ChannelObject, TdmsWriter
    monkeypatch.setenv("TDMS_VIEWER_DATA_DIR", str(tmp_path/'state'))
    folder = tmp_path/'data'; folder.mkdir()
    for number in (1, 2, 10):
        values = np.zeros(1000); values[500] = number
        with TdmsWriter(folder/f'sample_{number}.tdms') as writer:
            writer.write_segment([ChannelObject('Current', 'ai0', values,
                                 properties={'wf_increment': .001, 'unit_string': 'nA'})])
    app = QApplication.instance() or QApplication([])
    w = MainWindow(); panel = w.cluster_panel
    assert not panel.file_combo.isEnabled()
    assert not panel.next_file_button.isEnabled()
    w.controls.setCurrentIndex(2)

    def wait_loaded(name):
        for _ in range(300):
            app.processEvents()
            if w.current_path and w.current_path.name == name and not panel.loading: break
            QTest.qWait(10)
        assert w.current_path.name == name
        assert not panel.loading
        assert w.controls.currentIndex() == 2

    w.open_data_folder(folder); wait_loaded('sample_1.tdms')
    assert panel.file_position_label.text() == '1 / 3'
    assert not panel.previous_file_button.isEnabled()
    panel.start()
    for _ in range(300):
        app.processEvents()
        if not panel.workers: break
        QTest.qWait(10)
    assert panel.result is not None
    before_token = panel.token
    panel.next_file_button.click(); wait_loaded('sample_2.tdms')
    assert panel.token > before_token and panel.result is None
    assert panel.file_combo.currentIndex() == w.file_list.currentRow() == 1
    assert panel.file_position_label.text() == '2 / 3'
    panel.file_combo.setCurrentIndex(2); panel.file_combo.activated.emit(2)
    wait_loaded('sample_10.tdms')
    assert not panel.next_file_button.isEnabled()
    panel.previous_file_button.click(); wait_loaded('sample_2.tdms')
    w.file_list.setCurrentRow(0); wait_loaded('sample_1.tdms')
    assert panel.file_combo.currentIndex() == 0
    assert panel.amplitude.value() == 15
    w.fft_timer.stop(); w.session_timer.stop(); w.session=None; w.close(); app.processEvents()
