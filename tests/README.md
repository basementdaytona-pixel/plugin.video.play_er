<!-- coderabbit-ai-generated:v1 -->

<!-- coderabbit-ai-generated-section:v1:5606fbcfb4a05c80985265831d1014ef2b3e9ae42996aaa945120ee12712e3a9 -->

# Playback and database regression tests

Run from the addon root with Python 3:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v
```

The suite uses the standard library and replaces Kodi modules and unrelated integrations with test doubles. SQLite tests use real temporary databases. It checks TMDBHelper resolver failures, bundled player coverage, existing Continue fallback and season rollover behavior, finite pool capacity, connection health failures and shutdown.

## Optional MariaDB integration

Install the addon's declared `mysql-connector-python==8.0.33` into a test virtual environment. Start a disposable local MySQL/MariaDB server with passwordless root on loopback, then run:

```sh
PLAY_ER_TEST_MYSQL_PORT=33077 PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v
```

<!-- coderabbit-ai-generated:v1 -->

<!-- coderabbit-ai-generated-section:v1:88907ced00f60dcdfc289f95d5e15603343fa20c95be54ec16aa3683a4e353d8 -->

Integration tests create unique temporary databases and a synthetic database user and remove them on completion. They exercise 48 persistent writes and reads with 12 workers and a three-connection pool, UTF-8 data, quoted credentials and database names, checkout accounting, and reconnection after the server kills an idle connection. Without the environment variable, the three integration tests are skipped. Verified with MariaDB 11.4.13 and the declared connector 8.0.33.

<!-- /coderabbit-ai-generated:v1 -->

## Playback behavior

Continue, Skip Credits and playlist progression retain their original behavior, including fallback to the next episode number when season metadata is unavailable. TMDBHelper playback rejects error responses rather than treating them as episode details.

Native playback still needs verification in Kodi 22 with TMDBHelper and Arctic Fuse 3. These tests cannot validate rendering, native playback callbacks or provider availability.

Upstream references checked during implementation: [TMDBHelper player contract](https://github.com/jurialmunkey/plugin.video.themoviedb.helper/wiki/Player-Function), [Kodi player API](https://github.com/xbmc/xbmc/blob/de50755d5fd347011f6816d3c5d72c5cdbd83f61/xbmc/interfaces/legacy/Player.h), [Kodi JSON-RPC schema](https://github.com/xbmc/xbmc/blob/de50755d5fd347011f6816d3c5d72c5cdbd83f61/xbmc/interfaces/json-rpc/schema/types.json).


<!-- /coderabbit-ai-generated:v1 -->