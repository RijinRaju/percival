import fakeredis

from percival_server.connections import Connections, ConnectionSettings, mask_url
from percival_server.crypto import SecretBox


def test_mask_url_hides_only_the_password():
    assert mask_url("redis://:pw@host:6379/0") == "redis://:****@host:6379/0"
    assert mask_url("amqp://user:pw@rabbit:5672//") == "amqp://user:****@rabbit:5672//"
    assert mask_url("redis://host:6379/0") == "redis://host:6379/0"


def test_save_then_load_round_trip(app):
    server = fakeredis.FakeServer()
    conns = Connections(
        SecretBox("k" * 40), lambda url, d: fakeredis.FakeRedis(server=server, decode_responses=d)
    )
    settings = ConnectionSettings(broker_url="amqp://u:p@rabbit//", redis_url="redis://r:6379/1")
    with app.state.sessionmaker() as db:
        conns.save(db, settings)
        db.commit()

    fresh = Connections(SecretBox("k" * 40))
    with app.state.sessionmaker() as db:
        assert fresh.load(db) == settings
    assert fresh.keys.events == "percival:events"
    assert conns.celery().conf.redbeat_key_prefix == "redbeat:"
