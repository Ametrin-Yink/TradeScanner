from core.tag_manager import TagManager


def test_get_tags(seeded_db):
    manager = TagManager()
    tags = manager.get_tags(seeded_db)
    assert len(tags) == 3
    names = [t['name'] for t in tags]
    assert 'AI_Infra' in names
    assert 'Semiconductors' in names
    assert 'Software' in names


def test_get_tag_stocks(seeded_db):
    manager = TagManager()
    stocks = manager.get_tag_stocks('Software', seeded_db)
    assert len(stocks) == 3
    symbols = {s['symbol'] for s in stocks}
    assert symbols == {'AAPL', 'MSFT', 'PLTR'}


def test_add_and_remove_tag(seeded_db):
    manager = TagManager()
    manager.add_tag('NewSector', 'NEW', seeded_db)
    tags = manager.get_tags(seeded_db)
    assert any(t['name'] == 'NewSector' for t in tags)
    manager.remove_tag('NewSector', seeded_db)
    tags = manager.get_tags(seeded_db)
    assert not any(t['name'] == 'NewSector' for t in tags)


def test_add_stock_to_tag(seeded_db):
    manager = TagManager()
    manager.add_stock_to_tag('TSLA', 'Semiconductors', seeded_db)
    stocks = manager.get_tag_stocks('Semiconductors', seeded_db)
    symbols = {s['symbol'] for s in stocks}
    assert 'TSLA' in symbols


def test_remove_stock_from_tag(seeded_db):
    manager = TagManager()
    manager.remove_stock_from_tag('NVDA', 'Semiconductors', seeded_db)
    stocks = manager.get_tag_stocks('Semiconductors', seeded_db)
    assert len(stocks) == 0


def test_search_deduplicates(seeded_db):
    manager = TagManager()
    results = manager.search_stocks('NVDA', seeded_db)
    assert len(results) == 1
    assert results[0]['symbol'] == 'NVDA'
    assert 'Semiconductors' in results[0]['tags']
    assert 'AI_Infra' in results[0]['tags']


def test_get_unassigned(seeded_db):
    manager = TagManager()
    stocks = manager.get_unassigned_stocks(seeded_db)
    symbols = {s['symbol'] for s in stocks}
    assert 'TSLA' in symbols
    assert 'NVDA' not in symbols


def test_get_pipeline_stocks(seeded_db):
    manager = TagManager()
    all_stocks = manager.get_pipeline_stocks(None, seeded_db)
    assert len(all_stocks) == 4


def test_tag_daily_change(seeded_db):
    manager = TagManager()
    change = manager.get_tag_daily_change('Software', seeded_db)
    assert change is not None
    assert abs(change - 2.92) < 0.01  # avg of AAPL 2.63%, MSFT 2.44%, PLTR 3.70%
