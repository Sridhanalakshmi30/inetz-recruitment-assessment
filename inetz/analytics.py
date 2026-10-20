"""Execution against a separately configured, SELECT-only MySQL exercise account."""
import os
import re
from functools import lru_cache
from urllib.parse import urlparse

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.exc import SQLAlchemyError


@lru_cache(maxsize=1)
def practice_engine():
    url = os.getenv('ANALYTICS_DATABASE_URL', '')
    if not url:
        raise HTTPException(503, 'The MySQL practice database has not been connected. Ask the administrator to complete analytics setup.')
    if not url.startswith('mysql+pymysql://'):
        raise HTTPException(503, 'The practice connection must use MySQL.')
    return create_engine(url, pool_pre_ping=True, pool_size=3, max_overflow=0,
                         pool_timeout=5, connect_args={'connect_timeout': 5, 'read_timeout': 5, 'write_timeout': 5})


def verify_practice_account(conn):
    # Refuse broad grants even if somebody accidentally configures the recruitment account.
    database = conn.exec_driver_sql('SELECT DATABASE()').scalar()
    if database != 'inetz_analytics_practice':
        raise HTTPException(503, 'Use the dedicated inetz_analytics_practice database.')
    allowed = {f'`{database}`.*', *(f'`{database}`.`{table}`' for table in ('teams', 'employees', 'orders'))}
    for row in conn.exec_driver_sql('SHOW GRANTS'):
        grant = row[0]
        match = re.match(r'GRANT (.+?) ON (.+?) TO ', grant)
        if not match or 'WITH GRANT OPTION' in grant:
            raise HTTPException(503, 'The practice account must have SELECT-only privileges and no roles.')
        privileges, scope = match.groups()
        if (privileges, scope) == ('USAGE', '*.*'):
            continue
        if privileges != 'SELECT' or scope not in allowed:
            raise HTTPException(503, 'The practice account must only read the exercise tables.')


def run_query(source):
    query = source.strip().rstrip(';').strip()
    if not re.match(r'^(SELECT|WITH)\b', query, re.I) or any(x in query for x in (';', '--', '/*', '#', '@')):
        raise HTTPException(422, 'Enter one SELECT query or a WITH query ending in SELECT; comments and session variables are not supported.')
    if re.search(r'\b(INTO|OUTFILE|DUMPFILE|SLEEP|BENCHMARK|GET_LOCK|RELEASE_LOCK|LOAD_FILE|FOR\s+UPDATE)\b', query, re.I):
        raise HTTPException(422, 'Use a read-only query without file operations, locks, or delay functions.')
    try:
        with practice_engine().connect() as conn:
            verify_practice_account(conn)
            conn.exec_driver_sql('SET SESSION MAX_EXECUTION_TIME=2000')
            conn.commit()
            conn.exec_driver_sql('START TRANSACTION READ ONLY')
            try:
                result = conn.execution_options(no_parameters=True).exec_driver_sql(query)
                if not result.returns_rows:
                    raise HTTPException(422, 'The query must return rows.')
                columns = list(result.keys())
                rows = result.fetchmany(201)
                return {'columns': columns, 'rows': [list(r) for r in rows[:200]], 'truncated': len(rows) > 200}
            finally:
                conn.rollback()
    except SQLAlchemyError as error:
        code = getattr(getattr(error, 'orig', None), 'args', [None])[0]
        messages = {1064: 'SQL syntax error. Check your query.', 1146: 'Table not found. Use the exercise tables shown beside the editor.',
                    1054: 'Unknown column. Check the table schema.', 1142: 'Only the exercise tables may be queried.',
                    3024: 'Query exceeded the two-second execution limit.'}
        raise HTTPException(422 if code in messages else 503, messages.get(code, 'The MySQL practice connection is unavailable. Ask the administrator to check its configuration.')) from None


def powerbi_embed_url():
    value = os.getenv('POWERBI_EMBED_URL', '').strip()
    parsed = urlparse(value)
    if parsed.scheme == 'https' and parsed.netloc == 'app.powerbi.com' and parsed.path == '/reportEmbed':
        return value
    return None
