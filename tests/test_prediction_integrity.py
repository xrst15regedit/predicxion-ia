from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP_SOURCE = (ROOT / "app.py").read_text(encoding="utf-8")
ETL_SOURCE = (ROOT / "etl_3am_worker.py").read_text(encoding="utf-8")


def test_predictions_require_verified_inputs_and_provenance():
    assert 'match_data.get("prediction_status") != "VERIFIED"' in APP_SOURCE
    assert 'source.get("provider")' in APP_SOURCE
    assert 'source.get("fetched_at")' in APP_SOURCE


def test_no_synthetic_prediction_fallbacks_are_shipped():
    assert 'generar_calendario_completo_mes' not in APP_SOURCE
    assert '"local": "Real Madrid"' not in APP_SOURCE
    assert '"Arsenal vs Chelsea"' not in APP_SOURCE
    assert 'cal_destacados' not in APP_SOURCE


def test_firebase_credentials_are_external_to_the_repository():
    assert '"firebase_key.json"' not in APP_SOURCE
    assert '"firebase_key.json"' not in ETL_SOURCE
    assert 'FIREBASE_CREDENTIALS_PATH' in ETL_SOURCE
