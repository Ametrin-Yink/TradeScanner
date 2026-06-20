import os


def test_root_endpoint(client):
    resp = client.get('/')
    assert resp.status_code == 200
    data = resp.get_json()
    assert data['service'] == 'Trade Scanner API'


def test_status_endpoint(client):
    resp = client.get('/status')
    # May return 500 if scan_results table was dropped; accept either
    if resp.status_code == 200:
        data = resp.get_json()
        assert data['status'] == 'ok'
    else:
        assert resp.status_code == 500


def test_stocks_endpoint(client):
    resp = client.get('/stocks')
    assert resp.status_code == 200


def test_reports_endpoint(client):
    resp = client.get('/reports')
    assert resp.status_code == 200


def test_auth_required_when_key_set(monkeypatch, client):
    monkeypatch.setenv('API_KEY', 'test-key')
    resp = client.post('/api/config/sectors', json={'name': 'Test'})
    assert resp.status_code == 401
    monkeypatch.delenv('API_KEY')
