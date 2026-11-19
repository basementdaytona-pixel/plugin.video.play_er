<!-- coderabbit-ai-generated:v1 -->

# Playback and database regression tests

Run from the addon root with Python 3:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v
```

The suite uses the standard library and replaces Kodi modules and unrelated integrations with test doubles. SQLite tests use real temporary databases. It checks TMDBHelper resolver failures, bundled player coverage, episode numbering (including specials and season gaps), background playlist ownership, finite pool capacity, connection health failures and shutdown.

## Optional MariaDB integration

Install the addon's declared `mysql-connector-python==8.0.33` into a test virtual environment. Start a disposable local MySQL/MariaDB server with passwordless root on loopback, then run:

```sh
PLAY_ER_TEST_MYSQL_PORT=33077 PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v
```

Integration tests create a unique `play_er_test_*` database and remove it on completion. They exercise 48 persistent writes and reads with 12 workers and a three-connection pool, UTF-8 data, checkout accounting, and reconnection after the server kills an idle connection. Without the environment variable, these two integration tests are skipped. Verified with MariaDB 11.4.13 and the declared connector 8.0.33.

## Playback behavior

TMDBHelper smart play, Continue, background queues and Skip Credits now share the next-episode lookup. It uses TMDB episode numbers instead of list length and checks subsequent seasons listed by TMDB. If metadata is unavailable, automatic progression stops without guessing an episode. Background playlist builders check the active episode and stream before appending results.

Native playback still needs verification in Kodi 22 with TMDBHelper and Arctic Fuse 3. These tests cannot validate rendering, native playback callbacks or provider availability.

Upstream references checked during implementation: [TMDBHelper player contract](https://github.com/jurialmunkey/plugin.video.themoviedb.helper/wiki/Player-Function), [Kodi player API](https://github.com/xbmc/xbmc/blob/de50755d5fd347011f6816d3c5d72c5cdbd83f61/xbmc/interfaces/legacy/Player.h), [Kodi JSON-RPC schema](https://github.com/xbmc/xbmc/blob/de50755d5fd347011f6816d3c5d72c5cdbd83f61/xbmc/interfaces/json-rpc/schema/types.json).
